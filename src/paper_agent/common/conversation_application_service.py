from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any, Optional

from .conversation_service import ConversationService
from .events import EventPublisher
from .models.conversation import (
    ConversationMessage,
    ConversationSession,
    PendingAction,
)
from .models import AgentEvent
from .models.paper_candidate import PaperCandidate, PaperCandidateSet
from .models.research_spec import ResearchSpec
from .models.task_state import TaskState
from .response_composer import ComposedResponse, ResponseComposer
from .persistence import ConversationStore
from .persistence import EventStore
from ..orchestrator import Orchestrator


class ConversationApplicationService(ConversationService):
    """Application-layer coordinator for conversation and task execution."""

    _TERMINAL_SESSION_STATUSES = {"cancelled", "completed", "failed", "closed"}
    _CHINESE_DIGITS = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    _CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}

    def __init__(
        self,
        store: ConversationStore,
        registry,
        *,
        llm_router=None,
        orchestrator: Optional[Orchestrator] = None,
        event_publisher: Optional[EventPublisher] = None,
        normalize_queries: bool = True,
    ):
        super().__init__(
            store,
            registry,
            llm_router=llm_router,
            normalize_queries=normalize_queries,
        )
        self.orchestrator = orchestrator or Orchestrator()
        self.event_publisher = event_publisher or EventPublisher(
            EventStore(store.base_dir)
        )
        self.response_composer = ResponseComposer()
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_states: dict[str, TaskState] = {}

    def compose_event_response(self, event: AgentEvent) -> ComposedResponse:
        """Compose a safe user response without changing application state."""
        return self.response_composer.compose(event)

    def list_events(
        self,
        session_id: str,
        *,
        task_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> list[AgentEvent]:
        self._require_session(session_id)
        return self.event_publisher.store.list(
            session_id=session_id,
            task_id=task_id,
            correlation_id=correlation_id,
        )

    async def handle_message(self, session_id: str, content: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        correlation_id = uuid.uuid4().hex
        if not isinstance(content, str) or not content.strip():
            raise ValueError("conversation message content must not be empty")
        if session.status in self._TERMINAL_SESSION_STATUSES:
            return self._response(
                session,
                reply="该会话已经结束，无法继续处理消息。",
                status=session.status,
                error="session_is_terminal",
            )

        user_message = ConversationMessage(
            session_id=session_id,
            role="user",
            content=content,
            task_id=session.active_task_id,
        )
        self.store.append_message(session_id, user_message)
        session = self._require_session(session_id)
        session = self._refresh_candidate_context(session)
        selected = self._select_candidate(session, content)
        if selected is not None:
            updated_context = session.context.model_copy(
                update={"selected_paper": selected}
            )
            self.store.update_context(session_id, updated_context)
            reply = f"已选择论文：{selected.get('title') or selected.get('arxiv_id', '指定论文')}。"
            self._append_reply(
                session_id,
                reply,
                correlation_id=correlation_id,
            )
            self._publish_event(
                "intent_detected",
                session,
                correlation_id,
                payload={"intent": "paper_select", "matched": True},
            )
            self.store.update_status(session_id, "active")
            return self._response(
                self._require_session(session_id),
                reply=reply,
                status="active",
                selected_paper=selected,
            )

        session = self._require_session(session_id)
        projection = self.context_projector.project(
            session,
            self.store.list_messages(session_id),
        )
        decision = await self.router.route(
            user_message,
            session.context,
            projection,
        )
        decision_data = decision.model_dump(mode="json")
        self._publish_event(
            "intent_detected",
            session,
            correlation_id,
            payload={
                "intent": decision.intent,
                "capability_name": decision.capability_name,
                "matched": decision.matched,
            },
        )

        if not decision.matched:
            reply = decision.clarification_question or "暂时无法理解这个请求。"
            self._append_reply(
                session_id,
                reply,
                metadata={"decision": decision_data},
                correlation_id=correlation_id,
            )
            self.store.update_status(session_id, "waiting_user_input")
            return self._response(
                self._require_session(session_id),
                reply=reply,
                status="waiting_user_input",
                decision=decision_data,
            )

        try:
            capability = self.registry.resolve(decision.capability_name)
        except (KeyError, RuntimeError) as exc:
            return self._capability_failure(
                session_id,
                decision_data,
                str(exc),
                correlation_id,
            )
        explicit_paper = self._explicit_paper_from_decision(decision_data)
        if (
            decision.capability_name == "process_selected_paper"
            and explicit_paper is not None
        ):
            authorization = self.security_policy.authorize(
                decision,
                confirmed=True,
            )
            if not authorization.allowed:
                reply = f"该操作未被允许执行：{authorization.reason}"
                self._append_reply(
                    session_id,
                    reply,
                    metadata={
                        "decision": decision_data,
                        "security": authorization.model_dump(mode="json"),
                    },
                    correlation_id=correlation_id,
                )
                return self._response(
                    self._require_session(session_id),
                    reply=reply,
                    status="blocked",
                    decision=decision_data,
                    security=authorization.model_dump(mode="json"),
                )
            return await self._start_processing_task(
                session_id,
                explicit_paper,
                decision_data=decision_data,
                action_id=None,
                confirmation_token=None,
                correlation_id=correlation_id,
            )

        authorization = self.security_policy.authorize(decision)
        if not authorization.allowed and authorization.requires_confirmation:
            pending = PendingAction(
                capability_name=decision.capability_name,
                arguments=decision.arguments,
                selected_paper=session.context.selected_paper,
            )
            updated_context = session.context.model_copy(
                update={
                    "current_intent": decision.intent,
                    "pending_action": pending,
                }
            )
            self.store.update_context(session_id, updated_context)
            self.store.update_status(session_id, "waiting_confirmation")
            reply = "该操作将启动完整论文处理流程，请确认后继续。"
            self._append_reply(
                session_id,
                reply,
                metadata={
                    "decision": decision_data,
                    "confirmation_token": pending.confirmation_token,
                },
                correlation_id=correlation_id,
            )
            return self._response(
                self._require_session(session_id),
                reply=reply,
                status="waiting_confirmation",
                decision=decision_data,
                confirmation_token=pending.confirmation_token,
            )

        if not authorization.allowed:
            reply = f"该操作未被允许执行：{authorization.reason}"
            self._append_reply(
                session_id,
                reply,
                metadata={
                    "decision": decision_data,
                    "security": authorization.model_dump(mode="json"),
                },
                correlation_id=correlation_id,
            )
            return self._response(
                self._require_session(session_id),
                reply=reply,
                status="blocked",
                decision=decision_data,
                security=authorization.model_dump(mode="json"),
            )

        try:
            result = await capability.adapter.execute(
                self._execution_context(session),
                decision.arguments,
            )
        except Exception as exc:
            return self._capability_failure(
                session_id,
                decision_data,
                f"{type(exc).__name__}: {exc}",
                correlation_id,
            )
        result_data = result.model_dump(mode="json")
        if result.success and decision.capability_name == "paper_search":
            return self._persist_search_result(
                session_id,
                session,
                decision_data,
                result_data,
                correlation_id,
            )

        reply = (
            "操作已完成。"
            if result.success
            else f"操作失败：{result.error}"
        )
        self._append_reply(
            session_id,
            reply,
            artifact_refs=result.artifact_refs,
            metadata={"decision": decision_data, "result": result_data},
            correlation_id=correlation_id,
        )
        return self._response(
            self._require_session(session_id),
            reply=reply,
            status="active" if result.success else "failed",
            decision=decision_data,
            result=result_data,
        )

    async def confirm(
        self,
        session_id: str,
        confirmation_token: str,
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        pending = session.context.pending_action
        if (
            pending is None
            and session.active_task_id
            and session.context.last_confirmation_token == confirmation_token
        ):
            return await self.refresh_status(session_id)
        if pending is None or pending.confirmation_token != confirmation_token:
            raise ValueError("confirmation token is invalid or expired")
        if pending.capability_name != "process_selected_paper":
            raise ValueError(
                f"unsupported pending capability: {pending.capability_name}"
            )
        if session.active_task_id:
            return self.get_status(session_id)
        if not pending.selected_paper:
            raise ValueError("confirmation requires a selected paper")

        return await self._start_processing_task(
            session_id,
            dict(pending.selected_paper),
            decision_data=None,
            action_id=pending.action_id,
            confirmation_token=confirmation_token,
                correlation_id=uuid.uuid4().hex,
        )

    async def _start_processing_task(
        self,
        session_id: str,
        selected_paper: dict[str, Any],
        *,
        decision_data: Optional[dict[str, Any]],
        action_id: Optional[str],
        confirmation_token: Optional[str],
        correlation_id: str,
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        research_spec = ResearchSpec(
            user_query=selected_paper.get("title") or "Process selected paper",
            target_paper_url=selected_paper.get("url"),
            target_paper_arxiv_id=(
                selected_paper.get("arxiv_id")
                or selected_paper.get("id")
            ),
        )
        task_state = await self.orchestrator.create_task(
            user_query=research_spec.user_query,
            research_spec=research_spec,
            session_id=session_id,
        )
        task_state.lifecycle_status = "running"
        task_state.metadata["correlation_id"] = correlation_id
        task_state.metadata["paper_processing_selected_candidate"] = selected_paper
        task_state.metadata["paper_candidates"] = [selected_paper]
        if action_id is not None:
            task_state.metadata["pending_action_id"] = action_id
        if decision_data is not None:
            task_state.metadata["application_decision"] = decision_data
        await self.orchestrator.persistence.save_checkpoint(task_state)
        self._publish_event(
            "workflow_started",
            session,
            correlation_id,
            task_id=task_state.id,
            payload={"workflow_name": "paper_processing"},
        )

        cleared_context = session.context.model_copy(
            update={
                "pending_action": None,
                "selected_paper": selected_paper,
                "active_task_id": task_state.id,
                "last_confirmation_token": confirmation_token,
                "last_confirmed_task_id": (
                    task_state.id if confirmation_token is not None else None
                ),
            }
        )
        self.store.update_context(session_id, cleared_context)
        self.store.bind_task(session_id, task_state.id)
        self.store.update_status(session_id, "running")
        self._task_states[task_state.id] = task_state
        execution = asyncio.create_task(self.orchestrator.run(task_state))
        self._running_tasks[task_state.id] = execution
        execution.add_done_callback(
            lambda completed: self._on_task_done(session_id, task_state, completed)
        )
        return self._response(
            self._require_session(session_id),
            task_id=task_state.id,
            status="running",
            reply=(
                "已确认，开始处理论文。"
                if confirmation_token is not None
                else "已识别指定论文，开始处理论文。"
            ),
        )

    @staticmethod
    def _explicit_paper_from_decision(
        decision_data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        arguments = decision_data.get("arguments") or {}
        arxiv_id = arguments.get("arxiv_id")
        url = arguments.get("url")
        pdf_url = arguments.get("pdf_url")
        if not any((arxiv_id, url, pdf_url)):
            return None
        selected: dict[str, Any] = {}
        if isinstance(arxiv_id, str) and arxiv_id.strip():
            selected["arxiv_id"] = arxiv_id.strip()
        if isinstance(url, str) and url.strip():
            selected["url"] = url.strip()
        if isinstance(pdf_url, str) and pdf_url.strip():
            selected["pdf_url"] = pdf_url.strip()
        return selected or None

    async def pause(self, session_id: str) -> dict[str, Any]:
        session, task_state = await self._bound_task(session_id)
        if session.status != "running":
            raise ValueError(f"task cannot be paused from status {session.status}")
        live_task = self._task_states.get(task_state.id, task_state)
        live_task.control_request = "pause"
        await self.orchestrator.persistence.save_checkpoint(live_task)
        self.store.update_status(session_id, "paused")
        self._publish_event(
            "task_paused",
            session,
            uuid.uuid4().hex,
            task_id=task_state.id,
            payload={},
        )
        return self._response(
            self._require_session(session_id),
            task_id=task_state.id,
            status="paused",
            reply="已请求暂停任务，将在当前安全点生效。",
        )

    async def resume(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        if session.status != "paused":
            raise ValueError(f"task cannot be resumed from status {session.status}")
        _, task_state = await self._bound_task(session_id)
        checkpoint = self.orchestrator.persistence.get_latest_checkpoint(task_state.id)
        if checkpoint is None:
            raise FileNotFoundError(f"No checkpoint found for task {task_state.id}")
        restored = await self.orchestrator.create_task(
            user_query="",
            resume_from_checkpoint=str(checkpoint),
            session_id=session_id,
        )
        if restored.session_id not in (None, session_id):
            raise ValueError("restored task is bound to a different session")
        restored.session_id = session_id
        restored.control_request = None
        restored.lifecycle_status = "running"
        await self.orchestrator.persistence.save_checkpoint(restored)
        self.store.update_status(session_id, "running")
        self._publish_event(
            "task_resumed",
            session,
            uuid.uuid4().hex,
            task_id=restored.id,
            payload={},
        )
        self._task_states[restored.id] = restored
        execution = asyncio.create_task(self.orchestrator.run(restored))
        self._running_tasks[restored.id] = execution
        execution.add_done_callback(
            lambda completed: self._on_task_done(session_id, restored, completed)
        )
        return self._response(
            self._require_session(session_id),
            task_id=restored.id,
            status="running",
            reply="已恢复任务。",
        )

    async def cancel(self, session_id: str) -> dict[str, Any]:
        session, task_state = await self._bound_task(session_id)
        if session.status not in {"running", "paused"}:
            raise ValueError(f"task cannot be cancelled from status {session.status}")
        live_task = self._task_states.get(task_state.id, task_state)
        live_task.control_request = "cancel"
        live_task.lifecycle_status = "cancelled"
        await self.orchestrator.persistence.save_checkpoint(live_task)
        self.store.update_status(session_id, "cancelled")
        self._publish_event(
            "task_cancelled",
            session,
            uuid.uuid4().hex,
            task_id=task_state.id,
            payload={},
        )
        return self._response(
            self._require_session(session_id),
            task_id=task_state.id,
            status="cancelled",
            reply="任务已取消。",
        )

    def get_status(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        response = self._response(
            session,
            status=session.status,
            task_id=session.active_task_id,
        )
        if session.active_task_id:
            checkpoint = self.orchestrator.persistence.get_latest_checkpoint(
                session.active_task_id
            )
            if checkpoint is not None:
                response["checkpoint"] = str(checkpoint)
        return response

    async def refresh_status(self, session_id: str) -> dict[str, Any]:
        """Reconcile a persisted task lifecycle state into its Session."""
        session = self._require_session(session_id)
        if not session.active_task_id or session.status in self._TERMINAL_SESSION_STATUSES:
            return self.get_status(session_id)

        checkpoint = self.orchestrator.persistence.get_latest_checkpoint(
            session.active_task_id
        )
        if checkpoint is None:
            return self.get_status(session_id)
        task_state = await self.orchestrator.persistence.load_checkpoint(str(checkpoint))
        if task_state.id != session.active_task_id:
            raise ValueError("session active task does not match checkpoint")
        if task_state.session_id not in (None, session_id):
            raise ValueError("session and task are not bound to each other")

        status_by_lifecycle = {
            "pending": "active",
            "running": "running",
            "paused": "paused",
            "cancelled": "cancelled",
            "completed": "completed",
            "failed": "failed",
        }
        target_status = status_by_lifecycle[task_state.lifecycle_status]
        if target_status != session.status:
            self.store.update_status(session_id, target_status)
        return self.get_status(session_id)

    def _require_session(self, session_id: str) -> ConversationSession:
        session = self.store.load_session(session_id)
        if session is None:
            raise FileNotFoundError(
                f"Conversation session does not exist: {session_id}"
            )
        return session

    async def _bound_task(
        self,
        session_id: str,
    ) -> tuple[ConversationSession, TaskState]:
        session = self._require_session(session_id)
        if not session.active_task_id:
            raise ValueError("conversation session has no active task")
        checkpoint = self.orchestrator.persistence.get_latest_checkpoint(
            session.active_task_id
        )
        if checkpoint is None:
            raise FileNotFoundError(
                f"Task checkpoint not found: {session.active_task_id}"
            )
        task_state = await self.orchestrator.persistence.load_checkpoint(str(checkpoint))
        if task_state.session_id != session_id:
            raise ValueError("session and task are not bound to each other")
        if task_state.id != session.active_task_id:
            raise ValueError("session active task does not match checkpoint")
        return session, task_state

    def _execution_context(self, session: ConversationSession):
        from .capabilities import ExecutionContext

        return ExecutionContext(
            session_id=session.session_id,
            task_id=session.active_task_id,
            selected_paper=session.context.selected_paper,
            artifact_refs=[],
        )

    def _persist_search_result(
        self,
        session_id: str,
        session: ConversationSession,
        decision_data: dict[str, Any],
        result_data: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        result_payload = result_data.get("data") or {}
        candidates = result_payload.get("candidates", [])
        candidate_set = PaperCandidateSet(
            research_spec_id=session.active_task_id or session_id,
            session_id=session_id,
            query_used=result_payload.get("query") or "",
            candidates=[PaperCandidate.model_validate(item) for item in candidates],
            total_results=len(candidates),
        )
        candidate_path = self.store.save_paper_candidate_set(candidate_set)
        result_data["data"] = result_payload
        result_payload["candidate_set_id"] = candidate_set.id
        result_payload["session_id"] = session_id
        result_payload["queried_at"] = candidate_set.queried_at.isoformat()
        context = session.context.model_copy(
            update={
                "current_intent": decision_data.get("intent"),
                "candidate_papers": candidates,
                "candidate_set_id": candidate_set.id,
                "candidate_queried_at": candidate_set.queried_at,
            }
        )
        self.store.update_context(session_id, context)
        self._publish_event(
            "candidate_found",
            session,
            correlation_id,
            payload={
                "candidate_set_id": candidate_set.id,
                "query_used": candidate_set.query_used,
                "queried_at": candidate_set.queried_at.isoformat(),
                "candidates": candidates,
                "total": len(candidates),
            },
        )
        reply = (
            f"已找到 {len(candidates)} 篇候选论文，请选择一篇并确认。"
            f"（session_id={session_id}, candidate_set_id={candidate_set.id}, "
            f"queried_at={candidate_set.queried_at.isoformat()}）"
        )
        self._append_reply(
            session_id,
            reply,
            artifact_refs=[
                candidate_path.relative_to(self.store.base_dir).as_posix()
            ],
            metadata={"decision": decision_data, "result": result_data},
            correlation_id=correlation_id,
        )
        self.store.update_status(session_id, "waiting_confirmation")
        return self._response(
            self._require_session(session_id),
            reply=reply,
            status="waiting_confirmation",
            decision=decision_data,
            result=result_data,
        )

    @staticmethod
    def _select_candidate(
        session: ConversationSession,
        content: str,
    ) -> Optional[dict[str, Any]]:
        if not session.context.candidate_papers:
            return None
        text = content.strip()
        candidate_number = ConversationApplicationService._parse_candidate_number(text)
        if candidate_number is not None:
            index = candidate_number - 1
            if 0 <= index < len(session.context.candidate_papers):
                candidate = session.context.candidate_papers[index]
                return dict(candidate)

        lowered = text.casefold()
        for candidate in session.context.candidate_papers:
            for key in ("arxiv_id", "url", "title"):
                value = candidate.get(key)
                if isinstance(value, str) and value and value.casefold() in lowered:
                    return dict(candidate)
        return None

    def _refresh_candidate_context(
        self,
        session: ConversationSession,
    ) -> ConversationSession:
        """Reconcile candidate context with its session-owned persisted set."""
        candidate_set_id = session.context.candidate_set_id
        if not candidate_set_id:
            return session
        candidate_set = self.store.load_paper_candidate_set_for_session(
            candidate_set_id,
            session.session_id,
        )
        if candidate_set is None:
            return session
        if (
            session.context.candidate_queried_at != candidate_set.queried_at
            or session.context.candidate_papers != [
                candidate.model_dump(mode="json")
                for candidate in candidate_set.candidates
            ]
        ):
            session = self.store.update_context(
                session.session_id,
                session.context.model_copy(
                    update={
                        "candidate_papers": [
                            candidate.model_dump(mode="json")
                            for candidate in candidate_set.candidates
                        ],
                        "candidate_queried_at": candidate_set.queried_at,
                    }
                ),
            )
        return session

    @classmethod
    def _parse_candidate_number(cls, text: str) -> Optional[int]:
        """Parse a candidate ordinal such as ``2`` or ``第二篇``.

        The full-match boundary is intentional: a Chinese number embedded in
        a normal sentence must not be mistaken for a candidate selection.
        """
        match = re.fullmatch(
            r"(?:第\s*)?((?:\d+)|[零〇一二两三四五六七八九十百千万]+)"
            r"(?:\s*篇)?",
            text.strip(),
        )
        if not match:
            return None

        value = match.group(1)
        if value.isdigit():
            return int(value)

        total = 0
        section = 0
        number = 0
        for char in value:
            if char in cls._CHINESE_DIGITS:
                number = cls._CHINESE_DIGITS[char]
                continue
            unit = cls._CHINESE_UNITS[char]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
                number = 0
            else:
                if number == 0:
                    number = 1
                section += number * unit
                number = 0
        return total + section + number

    def _append_reply(
        self,
        session_id: str,
        content: str,
        *,
        artifact_refs: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        self.store.append_message(
            session_id,
            ConversationMessage(
                session_id=session_id,
                role="assistant",
                content=content,
                artifact_refs=artifact_refs or [],
                metadata=metadata or {},
            ),
        )
        if correlation_id is not None:
            session = self._require_session(session_id)
            self._publish_event(
                "response_ready",
                session,
                correlation_id,
                task_id=session.active_task_id,
                payload={
                    "status": "ready",
                    "message": content,
                    "artifact_refs": artifact_refs or [],
                },
            )

    def _capability_failure(
        self,
        session_id: str,
        decision_data: dict[str, Any],
        error: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        reply = f"能力执行失败：{error}"
        self._append_reply(
            session_id,
            reply,
            metadata={"decision": decision_data, "error": error},
            correlation_id=correlation_id,
        )
        return self._response(
            self._require_session(session_id),
            status="failed",
            reply=reply,
            decision=decision_data,
            error=error,
        )

    def _publish_event(
        self,
        event_type: str,
        session: ConversationSession,
        correlation_id: str,
        *,
        task_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        self.event_publisher.publish(
            AgentEvent(
                event_type=event_type,
                session_id=session.session_id,
                task_id=task_id,
                correlation_id=correlation_id,
                payload=payload or {},
            )
        )

    @staticmethod
    def _response(
        session: ConversationSession,
        *,
        status: str,
        reply: Optional[str] = None,
        task_id: Optional[str] = None,
        **extra: Any,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "session_id": session.session_id,
            "status": status,
        }
        if session.context.candidate_set_id:
            response["candidate_set_id"] = session.context.candidate_set_id
            response["queried_at"] = (
                session.context.candidate_queried_at.isoformat()
                if session.context.candidate_queried_at
                else None
            )
        if task_id is not None:
            response["task_id"] = task_id
        if reply is not None:
            response["reply"] = reply
        response.update(extra)
        return response

    def _on_task_done(
        self,
        session_id: str,
        task_state: TaskState,
        completed: asyncio.Task[None],
    ) -> None:
        self._running_tasks.pop(task_state.id, None)
        self._task_states.pop(task_state.id, None)
        try:
            completed.result()
        except Exception as exc:
            self.store.update_status(session_id, "failed")
            task_state.lifecycle_status = "failed"
            task_state.metadata["application_error"] = str(exc)
            return

        if task_state.lifecycle_status == "paused":
            status = "paused"
        elif task_state.lifecycle_status == "cancelled":
            status = "cancelled"
        elif task_state.lifecycle_status == "completed":
            status = "completed"
        else:
            status = "failed"
        self.store.update_status(session_id, status)

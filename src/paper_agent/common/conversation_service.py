from __future__ import annotations

from typing import Any, Optional

from .capabilities import (
    CapabilityRegistry,
    ExecutionContext,
    HybridIntentRouter,
    CapabilityExecutionSecurityPolicy,
    CapabilityCatalog,
    IntentContextProjector,
)
from .capabilities.router import DeterministicIntentRouter
from .capabilities.hybrid_router import LLMDecisionRouter
from .models.conversation import ConversationMessage
from .models.paper_candidate import PaperCandidate, PaperCandidateSet
from .persistence import ConversationStore


class ConversationService:
    """Minimal chat application service for routing paper-search requests."""

    def __init__(
        self,
        store: ConversationStore,
        registry: CapabilityRegistry,
        *,
        llm_router: Optional[LLMDecisionRouter] = None,
    ):
        self.store = store
        self.registry = registry
        self.security_policy = CapabilityExecutionSecurityPolicy(
            CapabilityCatalog.from_registry(registry)
        )
        self.deterministic_router = DeterministicIntentRouter(registry)
        self.router = (
            HybridIntentRouter(self.deterministic_router, llm_router)
            if llm_router is not None
            else self.deterministic_router
        )
        self.context_projector = IntentContextProjector()

    async def handle_message(self, session_id: str, content: str) -> dict[str, Any]:
        user_message = ConversationMessage(
            session_id=session_id,
            role="user",
            content=content,
        )
        self.store.append_message(session_id, user_message)
        session = self.store.load_session(session_id)
        if session is None:
            raise FileNotFoundError(f"Conversation session does not exist: {session_id}")

        if isinstance(self.router, HybridIntentRouter):
            projection = self.context_projector.project(
                session,
                self.store.list_messages(session_id),
            )
            decision = await self.router.route(
                user_message,
                session.context,
                projection,
            )
        else:
            decision = self.router.route(user_message, session.context)
        if not decision.matched:
            reply = decision.clarification_question or "暂时无法理解这个请求。"
            self.store.append_message(
                session_id,
                ConversationMessage(
                    session_id=session_id,
                    role="assistant",
                    content=reply,
                    metadata={"decision": decision.model_dump()},
                ),
            )
            return {
                "session_id": session_id,
                "status": "waiting_user_input",
                "reply": reply,
                "decision": decision.model_dump(),
            }

        capability = self.registry.resolve(decision.capability_name)
        authorization = self.security_policy.authorize(decision)
        if not authorization.allowed:
            if authorization.requires_confirmation:
                reply = "该操作将启动完整论文处理流程，请确认后继续。"
                status = "waiting_confirmation"
            else:
                reply = f"该操作未被允许执行：{authorization.reason}"
                status = "blocked"
            self.store.append_message(
                session_id,
                ConversationMessage(
                    session_id=session_id,
                    role="assistant",
                    content=reply,
                    metadata={
                        "decision": decision.model_dump(),
                        "security": authorization.model_dump(),
                    },
                ),
            )
            return {
                "session_id": session_id,
                "status": status,
                "reply": reply,
                "decision": decision.model_dump(),
                "security": authorization.model_dump(),
            }
        result = await capability.adapter.execute(
            ExecutionContext(
                session_id=session_id,
                task_id=session.active_task_id,
                selected_paper=session.context.selected_paper,
                artifact_refs=[],
            ),
            decision.arguments,
        )
        if result.success:
            candidate_count = len((result.data or {}).get("candidates", []))
            try:
                candidate_set = PaperCandidateSet(
                    research_spec_id=session.active_task_id or session_id,
                    query_used=(result.data or {}).get("query") or "",
                    candidates=[
                        PaperCandidate.model_validate(candidate)
                        for candidate in (result.data or {}).get("candidates", [])
                    ],
                    total_results=candidate_count,
                )
                candidate_path = self.store.save_paper_candidate_set(candidate_set)
            except Exception as exc:
                result = result.failed(f"Failed to persist paper candidate set: {exc}")
                reply = f"论文检索结果持久化失败：{result.error}"
                status = result.status
            else:
                candidate_ref = candidate_path.relative_to(self.store.base_dir).as_posix()
                result.data["candidate_set_id"] = candidate_set.id
                reply = f"已找到 {candidate_count} 篇候选论文，请告诉我想选择哪一篇。"
                status = "waiting_confirmation"
        else:
            reply = f"论文检索失败：{result.error}"
            status = result.status

        artifact_refs = [candidate_ref] if result.success else []
        self.store.append_message(
            session_id,
            ConversationMessage(
                session_id=session_id,
                role="assistant",
                content=reply,
                artifact_refs=artifact_refs + result.artifact_refs,
                metadata={"decision": decision.model_dump(), "result": result.model_dump()},
            ),
        )
        self.store.update_context(
            session_id,
            session.context.model_copy(
                update={
                    "current_intent": decision.intent,
                    "candidate_papers": (result.data or {}).get("candidates", [])
                    if result.success
                    else session.context.candidate_papers,
                    "candidate_set_id": candidate_set.id if result.success else session.context.candidate_set_id,
                }
            ),
        )
        return {
            "session_id": session_id,
            "status": status,
            "reply": reply,
            "decision": decision.model_dump(),
            "result": result.model_dump(),
        }

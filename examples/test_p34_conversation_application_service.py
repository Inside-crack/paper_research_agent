"""P34 ConversationApplicationService focused tests."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.capabilities import (
    CapabilityRegistry,
    PaperProcessingWorkflowAdapter,
    PaperSearchAdapter,
)
from paper_agent.cli import _handle_chat_command
from paper_agent.common.conversation_application_service import (
    ConversationApplicationService,
)
from paper_agent.common.models import PaperCandidateSet, TaskPhase, TaskState
from paper_agent.common.persistence import ConversationStore, StatePersistence
from paper_agent.common.tools import ToolResult


class FakeToolRegistry:
    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        assert tool_name == "arxiv_search"
        return ToolResult.ok(
            data={
                "query": kwargs["query"],
                "total_found": 2,
                "results": [
                    {
                        "arxiv_id": "2401.00001v1",
                        "title": "First Paper",
                        "authors": ["A"],
                        "abstract": "First.",
                        "url": "https://arxiv.org/abs/2401.00001v1",
                        "pdf_url": "https://arxiv.org/pdf/2401.00001v1",
                        "published_date": "2024-01-01",
                        "version": "1",
                        "source": "arxiv",
                    },
                    {
                        "arxiv_id": "2401.00002v1",
                        "title": "Second Paper",
                        "authors": ["B"],
                        "abstract": "Second.",
                        "url": "https://arxiv.org/abs/2401.00002v1",
                        "pdf_url": "https://arxiv.org/pdf/2401.00002v1",
                        "published_date": "2024-01-02",
                        "version": "1",
                        "source": "arxiv",
                    },
                ],
            }
        )


class FakeOrchestrator:
    def __init__(self, base_dir: Path):
        self.persistence = StatePersistence(base_dir)

    async def create_task(self, **kwargs: Any) -> TaskState:
        if kwargs.get("resume_from_checkpoint"):
            return await self.persistence.load_checkpoint(
                kwargs["resume_from_checkpoint"]
            )
        research_spec = kwargs["research_spec"]
        state = TaskState(
            research_spec_id=research_spec.id,
            session_id=kwargs.get("session_id"),
            artifact_dir=str(self.persistence.base_dir / "artifacts"),
        )
        await self.persistence.save_checkpoint(state)
        return state

    async def run(self, state: TaskState) -> None:
        if state.control_request == "pause":
            state.lifecycle_status = "paused"
            await self.persistence.save_checkpoint(state)
            return
        if state.control_request == "cancel":
            state.lifecycle_status = "cancelled"
            await self.persistence.save_checkpoint(state)
            return
        state.lifecycle_status = "completed"
        state.current_phase = TaskPhase.COMPLETED
        await self.persistence.save_checkpoint(state)


def make_service(tmpdir: str):
    base_dir = Path(tmpdir)
    store = ConversationStore(base_dir / "conversations")
    tools = FakeToolRegistry()
    registry = CapabilityRegistry()
    registry.register(PaperSearchAdapter(tools))  # type: ignore[arg-type]
    registry.register(
        PaperProcessingWorkflowAdapter(),
        execution_kind="workflow",
        confirmation_required=True,
        allowed_intents=["process_selected_paper"],
    )
    service = ConversationApplicationService(
        store,
        registry,
        orchestrator=FakeOrchestrator(base_dir / "tasks"),
    )
    return store, store.create_session(), service


def test_search_select_confirm_and_run_updates_session_state():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store, session, service = make_service(tmpdir)

            search = await service.handle_message(session.session_id, "检索 agents")
            assert search["status"] == "waiting_confirmation"
            assert len(store.load_session(session.session_id).context.candidate_papers) == 2

            selected = await service.handle_message(session.session_id, "2")
            assert selected["status"] == "active"
            assert selected["selected_paper"]["arxiv_id"] == "2401.00002v1"

            pending = await service.handle_message(
                session.session_id,
                "处理这篇论文",
            )
            assert pending["status"] == "waiting_confirmation"
            assert pending["confirmation_token"]

            started = await service.confirm(
                session.session_id,
                pending["confirmation_token"],
            )
            assert started["status"] == "running"
            assert started["task_id"]
            duplicate = await service.confirm(
                session.session_id,
                pending["confirmation_token"],
            )
            assert duplicate["task_id"] == started["task_id"]

            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert store.load_session(session.session_id).status == "completed"

    asyncio.run(scenario())


def test_candidate_selection_accepts_chinese_ordinals():
    with tempfile.TemporaryDirectory() as tmpdir:
        _, session, service = make_service(tmpdir)
        session.context.candidate_papers = [
            {"arxiv_id": "2401.00001v1", "title": "First Paper"},
            {"arxiv_id": "2401.00002v1", "title": "Second Paper"},
            {"arxiv_id": "2401.00003v1", "title": "Third Paper"},
        ]

        assert service._select_candidate(session, "第二篇")["arxiv_id"] == "2401.00002v1"
        assert service._select_candidate(session, "第 三 篇")["arxiv_id"] == "2401.00003v1"
        assert service._select_candidate(session, "二")["arxiv_id"] == "2401.00002v1"
        assert service._select_candidate(session, "2")["arxiv_id"] == "2401.00002v1"


def test_candidate_selection_rejects_embedded_or_out_of_range_ordinals():
    with tempfile.TemporaryDirectory() as tmpdir:
        _, session, service = make_service(tmpdir)
        session.context.candidate_papers = [
            {"arxiv_id": "2401.00001v1", "title": "First Paper"},
            {"arxiv_id": "2401.00002v1", "title": "Second Paper"},
        ]

        assert service._select_candidate(session, "我选第二篇") is None
        assert service._select_candidate(session, "第三篇") is None
        assert service._select_candidate(session, "第十篇") is None


def test_invalid_confirmation_and_cross_session_control_are_rejected():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store, session, service = make_service(tmpdir)
            other = store.create_session()

            with pytest.raises(ValueError, match="invalid or expired"):
                await service.confirm(session.session_id, "invalid")

            with pytest.raises(ValueError, match="no active task"):
                await service.cancel(other.session_id)

    asyncio.run(scenario())


def test_candidate_set_is_rejected_when_bound_to_another_session():
    with tempfile.TemporaryDirectory() as tmpdir:
        store, session, _ = make_service(tmpdir)
        other = store.create_session()
        candidate_set = PaperCandidateSet(
            research_spec_id="research",
            session_id=other.session_id,
            candidates=[],
        )
        store.save_paper_candidate_set(candidate_set)

        with pytest.raises(ValueError, match="does not belong"):
            store.load_paper_candidate_set_for_session(
                candidate_set.id,
                session.session_id,
            )


def test_legacy_task_checkpoint_defaults_new_lifecycle_fields():
    state = TaskState.model_validate(
        {
            "id": "legacy-task",
            "research_spec_id": "legacy-spec",
        }
    )
    assert state.session_id is None
    assert state.lifecycle_status == "pending"
    assert state.control_request is None


def test_session_status_transitions_reject_illegal_changes_and_support_slash_status():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store, session, service = make_service(tmpdir)
            store.update_status(session.session_id, "running")
            with pytest.raises(ValueError, match="Invalid conversation status transition"):
                store.update_status(session.session_id, "waiting_user_input")

            response = await _handle_chat_command(
                service,
                session.session_id,
                "/status",
            )
            assert response["status"] == "running"
            assert await _handle_chat_command(service, session.session_id, "status") is None

    asyncio.run(scenario())


def test_explicit_arxiv_url_starts_processing_without_confirmation():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store, session, service = make_service(tmpdir)
            response = await service.handle_message(
                session.session_id,
                "处理这篇论文 https://arxiv.org/abs/2401.00099v2",
            )

            assert response["status"] == "running"
            assert "confirmation_token" not in response
            saved = store.load_session(session.session_id)
            assert saved.context.pending_action is None
            assert saved.context.selected_paper["arxiv_id"] == "2401.00099v2"
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert store.load_session(session.session_id).status == "completed"

    asyncio.run(scenario())


def test_application_service_publishes_correlated_events():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store, session, service = make_service(tmpdir)
            await service.handle_message(session.session_id, "检索 agents")

            events = service.event_publisher.store.list(
                session_id=session.session_id
            )
            event_types = [event.event_type.value for event in events]
            assert "intent_detected" in event_types
            assert "candidate_found" in event_types
            assert "response_ready" in event_types
            assert all(event.session_id == session.session_id for event in events)
            assert all(event.correlation_id for event in events)
            assert any(event.task_id is None for event in events)

    asyncio.run(scenario())


def test_refresh_status_reconciles_persisted_task_after_process_restart():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store, session, service = make_service(tmpdir)
            state = TaskState(
                session_id=session.session_id,
                research_spec_id="recovered-spec",
                lifecycle_status="completed",
            )
            await service.orchestrator.persistence.save_checkpoint(state)
            store.bind_task(session.session_id, state.id)
            store.update_status(session.session_id, "running")

            response = await service.refresh_status(session.session_id)
            assert response["status"] == "completed"
            assert store.load_session(session.session_id).status == "completed"

    asyncio.run(scenario())


def test_pause_before_runner_safe_point_and_resume_are_persisted():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store, session, service = make_service(tmpdir)
            selected = {
                "arxiv_id": "2401.00001v1",
                "title": "Selected",
                "url": "https://arxiv.org/abs/2401.00001v1",
            }
            store.update_context(
                session.session_id,
                store.load_session(session.session_id).context.model_copy(
                    update={"selected_paper": selected}
                ),
            )
            pending = await service.handle_message(session.session_id, "处理这篇论文")
            started = await service.confirm(
                session.session_id,
                pending["confirmation_token"],
            )

            paused = await service.pause(session.session_id)
            assert paused["status"] == "paused"
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert store.load_session(session.session_id).status == "paused"

            resumed = await service.resume(session.session_id)
            assert resumed["status"] == "running"
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert store.load_session(session.session_id).status == "completed"
            assert started["task_id"] == resumed["task_id"]

    asyncio.run(scenario())

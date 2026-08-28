from __future__ import annotations

import asyncio
from pathlib import Path

from paper_agent.common.capabilities import CapabilityRegistry
from paper_agent.common.conversation_application_service import (
    ConversationApplicationService,
)
from paper_agent.common.models import ConversationMessage, TaskPhase, TaskState
from paper_agent.common.persistence import ConversationStore, MemoryStore
from paper_agent.orchestrator.orchestrator import Orchestrator


def _service(tmp_path: Path) -> tuple[ConversationStore, ConversationApplicationService]:
    store = ConversationStore(tmp_path / "conversations")
    memory_store = MemoryStore(tmp_path / "memory")
    service = ConversationApplicationService(
        store,
        registry=CapabilityRegistry(),
        orchestrator=object(),  # Hook methods are optional for test isolation.
        memory_store=memory_store,
    )
    return store, service


def test_application_hook_captures_only_explicit_persistent_preference(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path)
    session = store.create_session(user_id="user-a")

    persistent = ConversationMessage(
        session_id=session.session_id,
        role="user",
        content="以后默认使用中文回答",
    )
    transient = ConversationMessage(
        session_id=session.session_id,
        role="user",
        content="这次只看第二篇论文",
    )

    service._capture_user_message_memory(session, persistent)
    service._capture_user_message_memory(session, transient)

    candidates = service.memory_store.list_candidates(owner_user_id="user-a")
    assert len(candidates) == 1
    assert candidates[0].source_message_id == persistent.message_id


def test_application_task_hook_captures_validated_completion(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path)
    session = store.create_session(user_id="user-a")
    state = TaskState(
        research_spec_id="spec-1",
        session_id=session.session_id,
        lifecycle_status="completed",
        current_phase=TaskPhase.COMPLETED,
        metadata={"user_query": "研究场景文本检测"},
        phase_summaries=[{"artifact_ids": ["paper_summary.json"]}],
    )

    asyncio.run(service._capture_task_memory(state))

    candidates = service.memory_store.list_candidates(owner_user_id="user-a")
    assert len(candidates) == 1
    assert candidates[0].source_task_id == state.id
    assert candidates[0].source_artifact_ids == ["paper_summary.json"]


def test_orchestrator_memory_hook_failure_is_best_effort() -> None:
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator._task_memory_hooks = []
    calls: list[str] = []

    async def failing_hook(_state: TaskState) -> None:
        calls.append("called")
        raise RuntimeError("memory backend unavailable")

    orchestrator.on_task_memory(failing_hook)
    asyncio.run(
        orchestrator._run_task_memory_hooks(
            TaskState(research_spec_id="spec-1"),
        )
    )
    assert calls == ["called"]

"""P36 cross-process task recovery tests."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models import TaskState  # noqa: E402
from paper_agent.common.persistence import ConversationStore, StatePersistence  # noqa: E402
from paper_agent.common.task_recovery import TaskLeaseStore, TaskRecoveryManager  # noqa: E402


class FakeOrchestrator:
    def __init__(self, persistence: StatePersistence):
        self.persistence = persistence
        self.run_ids: list[str] = []

    async def create_task(self, **kwargs):
        return await self.persistence.load_checkpoint(kwargs["resume_from_checkpoint"])

    async def run(self, state):
        self.run_ids.append(state.id)
        state.lifecycle_status = "completed"
        await self.persistence.save_checkpoint(state)


def make_recoverable(tmp_path: Path):
    persistence = StatePersistence(tmp_path / "tasks")
    conversations = ConversationStore(tmp_path / "conversations")
    session = conversations.create_session(user_id="anonymous")
    state = TaskState(
        session_id=session.session_id,
        research_spec_id="spec-1",
        lifecycle_status="running",
    )
    state_path = tmp_path / "tasks" / state.id / "task_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(state.model_dump(mode="json")), encoding="utf-8")
    conversations.bind_task(session.session_id, state.id)
    conversations.update_status(session.session_id, "running")
    return persistence, conversations, session, state


def test_recovery_claims_and_runs_persisted_task(tmp_path: Path):
    async def scenario():
        persistence, conversations, session, state = make_recoverable(tmp_path)
        orchestrator = FakeOrchestrator(persistence)
        manager = TaskRecoveryManager(
            persistence=persistence,
            conversations=conversations,
            orchestrator=orchestrator,
        )
        started = await manager.recover_once()
        assert started == [state.id]
        await manager.handles[state.id]
        assert orchestrator.run_ids == [state.id]
        assert not (tmp_path / "tasks" / state.id / "task.lease.json").exists()

    asyncio.run(scenario())


def test_two_workers_cannot_claim_same_task(tmp_path: Path):
    persistence, conversations, _session, state = make_recoverable(tmp_path)
    leases_a = TaskLeaseStore(persistence.base_dir)
    leases_b = TaskLeaseStore(persistence.base_dir)
    assert leases_a.claim(state.id, "worker-a") is True
    assert leases_b.claim(state.id, "worker-b") is False
    leases_a.release(state.id, "worker-a")


def test_paused_or_unbound_task_is_not_auto_recovered(tmp_path: Path):
    async def scenario():
        persistence, conversations, session, state = make_recoverable(tmp_path)
        conversations.update_status(session.session_id, "paused")
        orchestrator = FakeOrchestrator(persistence)
        manager = TaskRecoveryManager(
            persistence=persistence,
            conversations=conversations,
            orchestrator=orchestrator,
        )
        assert await manager.recover_once() == []
        assert orchestrator.run_ids == []

    asyncio.run(scenario())

from __future__ import annotations

import asyncio
from pathlib import Path

from paper_agent.common.memory import MemoryExtractor, MemoryPipeline
from paper_agent.common.models.memory import (
    MemoryCandidateStatus,
    MemoryJobStatus,
)
from paper_agent.common.persistence import MemoryStore


def _candidate():
    return MemoryExtractor().from_confirmation(
        content="用户确认使用论文 A 作为研究目标",
        owner_user_id="user-a",
        session_id="session-1",
        task_id="task-1",
        message_id="message-1",
    )


def test_pipeline_promotes_candidate_and_writes_checkpoint(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    pipeline = MemoryPipeline(
        store,
        auto_start=False,
        retry_base_delay_seconds=0,
    )
    candidate = _candidate()
    assert candidate is not None

    job = pipeline.enqueue(candidate)
    asyncio.run(pipeline.drain())

    completed = pipeline.list_jobs(status=MemoryJobStatus.COMPLETED)
    assert [item.job_id for item in completed] == [job.job_id]
    assert store.list_memories(owner_user_id="user-a")[0].content == candidate.content
    accepted = store.get_candidate(candidate.candidate_id, owner_user_id="user-a")
    assert accepted is not None
    assert accepted.status == MemoryCandidateStatus.ACCEPTED.value
    assert pipeline.load_checkpoint()["last_status"] == MemoryJobStatus.COMPLETED.value


class FlakyMemoryStore(MemoryStore):
    def __init__(self, base_dir: Path, failures: int):
        self.failures = failures
        super().__init__(base_dir)

    def save_memory(self, memory, **kwargs):
        if self.failures:
            self.failures -= 1
            raise OSError("temporary memory backend failure")
        return super().save_memory(memory, **kwargs)


def test_pipeline_retries_with_exponential_backoff(tmp_path: Path) -> None:
    store = FlakyMemoryStore(tmp_path / "memory", failures=1)
    pipeline = MemoryPipeline(
        store,
        auto_start=False,
        max_attempts=3,
        retry_base_delay_seconds=0,
    )
    candidate = _candidate()
    assert candidate is not None
    pipeline.enqueue(candidate)

    asyncio.run(pipeline.drain())

    job = pipeline.list_jobs()[0]
    assert job.status == MemoryJobStatus.COMPLETED.value
    assert job.attempt_count == 2


def test_pipeline_moves_permanently_failing_job_to_dead_letter(tmp_path: Path) -> None:
    store = FlakyMemoryStore(tmp_path / "memory", failures=10)
    pipeline = MemoryPipeline(
        store,
        auto_start=False,
        max_attempts=2,
        retry_base_delay_seconds=0,
    )
    candidate = _candidate()
    assert candidate is not None
    pipeline.enqueue(candidate)

    asyncio.run(pipeline.drain())

    job = pipeline.list_jobs()[0]
    assert job.status == MemoryJobStatus.DEAD_LETTER.value
    assert job.attempt_count == 2
    failed = store.get_candidate(candidate.candidate_id, owner_user_id="user-a")
    assert failed is not None
    assert failed.status == MemoryCandidateStatus.FAILED.value
    assert failed.rejection_reason


def test_pipeline_recovers_running_job_after_restart(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    first = MemoryPipeline(store, auto_start=False)
    candidate = _candidate()
    assert candidate is not None
    job = first.enqueue(candidate)
    jobs = first._load_jobs()
    first._save_jobs(
        [
            item.model_copy(update={"status": MemoryJobStatus.RUNNING})
            if item.job_id == job.job_id
            else item
            for item in jobs
        ]
    )

    restarted = MemoryPipeline(store, auto_start=False)

    recovered = restarted.list_jobs()[0]
    assert recovered.status == MemoryJobStatus.PENDING.value
    assert "recovered" in (recovered.last_error or "")

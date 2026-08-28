from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..logging import get_logger
from ..models.memory import (
    MemoryCandidate,
    MemoryCandidateStatus,
    MemoryJob,
    MemoryJobStatus,
)
from ..persistence.manifest import atomic_write_json
from ..persistence.memory_store import MemoryStore
from .consolidator import MemoryConsolidator

logger = get_logger(__name__)

_PIPELINE_VERSION = 1
_JOBS_FILENAME = "memory_jobs.json"
_CHECKPOINT_FILENAME = "memory_pipeline_checkpoint.json"


class MemoryPipeline:
    """Durable, single-process queue for asynchronous memory consolidation."""

    def __init__(
        self,
        memory_store: MemoryStore,
        *,
        base_dir: Optional[Path] = None,
        max_attempts: int = 3,
        retry_base_delay_seconds: float = 0.5,
        auto_start: bool = True,
        consolidator: Optional[MemoryConsolidator] = None,
    ):
        if not isinstance(memory_store, MemoryStore):
            raise TypeError("memory_store must be a MemoryStore")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds must not be negative")

        self.memory_store = memory_store
        self.base_dir = Path(base_dir) if base_dir is not None else memory_store.base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.max_attempts = max_attempts
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.auto_start = auto_start
        self.consolidator = consolidator or MemoryConsolidator(memory_store)
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._recover_interrupted_jobs()

    @property
    def jobs_path(self) -> Path:
        return self.base_dir / _JOBS_FILENAME

    @property
    def checkpoint_path(self) -> Path:
        return self.base_dir / _CHECKPOINT_FILENAME

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

    def _load_jobs(self) -> list[MemoryJob]:
        if not self.jobs_path.exists():
            return []
        try:
            with self.jobs_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Corrupt memory jobs file: {self.jobs_path}") from exc
        if not isinstance(data, dict) or data.get("version") != _PIPELINE_VERSION:
            raise ValueError(f"Unsupported memory jobs format: {self.jobs_path}")
        records = data.get("jobs")
        if not isinstance(records, list):
            raise ValueError(f"Invalid memory jobs in: {self.jobs_path}")
        try:
            return [MemoryJob.model_validate(record) for record in records]
        except Exception as exc:
            raise ValueError(f"Invalid memory job in: {self.jobs_path}") from exc

    def _save_jobs(self, jobs: list[MemoryJob]) -> None:
        atomic_write_json(
            self.jobs_path,
            {
                "version": _PIPELINE_VERSION,
                "updated_at": self._now().isoformat(),
                "jobs": [job.model_dump(mode="json") for job in jobs],
            },
        )

    def _write_checkpoint(self, job: MemoryJob) -> None:
        atomic_write_json(
            self.checkpoint_path,
            {
                "version": _PIPELINE_VERSION,
                "updated_at": self._now().isoformat(),
                "last_job_id": job.job_id,
                "last_candidate_id": job.candidate_id,
                "last_status": job.status,
                "last_attempt_count": job.attempt_count,
            },
        )

    def load_checkpoint(self) -> Optional[dict]:
        if not self.checkpoint_path.exists():
            return None
        try:
            with self.checkpoint_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Corrupt memory pipeline checkpoint: {self.checkpoint_path}") from exc
        if not isinstance(data, dict) or data.get("version") != _PIPELINE_VERSION:
            raise ValueError(f"Unsupported memory pipeline checkpoint: {self.checkpoint_path}")
        return data

    def _recover_interrupted_jobs(self) -> None:
        try:
            jobs = self._load_jobs()
        except ValueError as exc:
            logger.warning(
                "Memory pipeline queue unavailable; preserving main flow",
                error=str(exc),
            )
            return
        recovered: list[MemoryJob] = []
        changed = False
        for job in jobs:
            if job.status != MemoryJobStatus.RUNNING.value:
                recovered.append(job)
                continue
            recovered.append(
                job.model_copy(
                    update={
                        "status": MemoryJobStatus.PENDING,
                        "next_attempt_at": None,
                        "updated_at": self._now(),
                        "last_error": "worker interrupted; recovered on startup",
                    }
                )
            )
            changed = True
        if changed:
            self._save_jobs(recovered)

    def list_jobs(self, *, status: Optional[MemoryJobStatus] = None) -> list[MemoryJob]:
        jobs = self._load_jobs()
        if status is None:
            return jobs
        return [job for job in jobs if job.status == status.value]

    def enqueue(self, candidate: MemoryCandidate) -> MemoryJob:
        if not isinstance(candidate, MemoryCandidate):
            raise TypeError("candidate must be a MemoryCandidate")
        saved_candidate = self.memory_store.save_candidate(candidate)
        jobs = self._load_jobs()
        for job in jobs:
            if job.idempotency_key == saved_candidate.idempotency_key:
                self._schedule_worker()
                return job

        job = MemoryJob(
            candidate_id=saved_candidate.candidate_id,
            idempotency_key=saved_candidate.idempotency_key,
            owner_user_id=saved_candidate.owner_user_id,
            max_attempts=self.max_attempts,
        )
        self._save_jobs([*jobs, job])
        self._schedule_worker()
        return job

    def try_enqueue(self, candidate: MemoryCandidate) -> Optional[MemoryJob]:
        try:
            return self.enqueue(candidate)
        except Exception as exc:
            logger.warning("Memory pipeline enqueue degraded", error=str(exc))
            return None

    def _schedule_worker(self) -> None:
        if not self.auto_start or self._worker_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._worker_task = loop.create_task(self._worker_loop())

    async def drain(self) -> None:
        """Process ready and retryable jobs until the queue is idle."""
        if self._worker_task is not None and self._worker_task is not asyncio.current_task():
            await self._worker_task
            return
        await self._worker_loop()

    async def wait_until_idle(self) -> None:
        if self._worker_task is not None:
            await self._worker_task

    async def shutdown(self) -> None:
        """Wait for the current worker; queued jobs remain persisted."""
        await self.wait_until_idle()

    async def _worker_loop(self) -> None:
        try:
            while True:
                job = self._next_ready_job()
                if job is not None:
                    await self._process_job(job)
                    continue
                delay = self._next_retry_delay()
                if delay is None:
                    return
                await asyncio.sleep(delay)
        finally:
            if self._worker_task is asyncio.current_task():
                self._worker_task = None

    def _next_ready_job(self) -> Optional[MemoryJob]:
        now = self._now()
        for job in self._load_jobs():
            if job.status != MemoryJobStatus.PENDING.value:
                continue
            if job.next_attempt_at is not None and job.next_attempt_at > now:
                continue
            return job
        return None

    def _next_retry_delay(self) -> Optional[float]:
        now = self._now()
        future_times = [
            job.next_attempt_at
            for job in self._load_jobs()
            if job.status == MemoryJobStatus.PENDING.value
            and job.next_attempt_at is not None
            and job.next_attempt_at > now
        ]
        if not future_times:
            return None
        return max(0.0, min((next_time - now).total_seconds() for next_time in future_times))

    async def _process_job(self, job: MemoryJob) -> None:
        jobs = self._load_jobs()
        current = next((item for item in jobs if item.job_id == job.job_id), None)
        if current is None or current.status != MemoryJobStatus.PENDING.value:
            return

        running = current.model_copy(
            update={
                "status": MemoryJobStatus.RUNNING,
                "attempt_count": current.attempt_count + 1,
                "updated_at": self._now(),
                "last_error": None,
            }
        )
        self._replace_job(jobs, running)
        try:
            await self._consolidate(running)
        except Exception as exc:
            await self._handle_failure(running, exc)
        else:
            completed = running.model_copy(
                update={
                    "status": MemoryJobStatus.COMPLETED,
                    "updated_at": self._now(),
                    "completed_at": self._now(),
                }
            )
            self._replace_job(self._load_jobs(), completed)
            self._write_checkpoint(completed)

    async def _consolidate(self, job: MemoryJob) -> None:
        candidate = self.memory_store.get_candidate(
            job.candidate_id,
            owner_user_id=job.owner_user_id,
        )
        if candidate is None:
            raise KeyError(f"Memory candidate not found: {job.candidate_id}")
        if candidate.status == MemoryCandidateStatus.ACCEPTED.value and candidate.memory_id:
            return

        self.consolidator.consolidate(candidate)

    async def _handle_failure(self, job: MemoryJob, error: Exception) -> None:
        message = str(error)[:1000] or type(error).__name__
        if job.attempt_count >= job.max_attempts:
            failed = job.model_copy(
                update={
                    "status": MemoryJobStatus.DEAD_LETTER,
                    "updated_at": self._now(),
                    "last_error": message,
                }
            )
            try:
                candidate = self.memory_store.get_candidate(
                    job.candidate_id,
                    owner_user_id=job.owner_user_id,
                )
                if candidate is not None:
                    self.memory_store.update_candidate(
                        candidate.model_copy(
                            update={
                                "status": MemoryCandidateStatus.FAILED,
                                "rejection_reason": message,
                            }
                        ),
                        owner_user_id=job.owner_user_id,
                    )
            except Exception as candidate_error:
                logger.warning("Failed to mark memory candidate as failed", error=str(candidate_error))
            logger.warning("Memory job moved to dead letter", job_id=job.job_id, error=message)
        else:
            delay = self.retry_base_delay_seconds * (2 ** (job.attempt_count - 1))
            failed = job.model_copy(
                update={
                    "status": MemoryJobStatus.PENDING,
                    "next_attempt_at": self._now() + timedelta(seconds=delay),
                    "updated_at": self._now(),
                    "last_error": message,
                }
            )
        self._replace_job(self._load_jobs(), failed)
        self._write_checkpoint(failed)

    def _replace_job(self, jobs: list[MemoryJob], replacement: MemoryJob) -> None:
        updated = [
            replacement if job.job_id == replacement.job_id else job
            for job in jobs
        ]
        self._save_jobs(updated)

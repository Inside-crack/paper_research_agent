from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .logging import get_logger
from .models.task_state import TaskState
from .persistence import ConversationStore, StatePersistence

logger = get_logger(__name__)


class TaskLeaseStore:
    """File leases that prevent two workers from recovering one task."""

    def __init__(self, base_dir: Path, *, ttl_seconds: int = 300):
        self.base_dir = Path(base_dir)
        self.ttl_seconds = ttl_seconds

    def _path(self, task_id: str) -> Path:
        return self.base_dir / task_id / "task.lease.json"

    def claim(self, task_id: str, owner_id: str) -> bool:
        path = self._path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        payload = {
            "owner_id": owner_id,
            "task_id": task_id,
            "expires_at": now + self.ttl_seconds,
        }
        for _ in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(payload, file)
                    file.flush()
                    os.fsync(file.fileno())
                return True
            except FileExistsError:
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (FileNotFoundError, json.JSONDecodeError, OSError):
                    existing = {}
                if float(existing.get("expires_at", 0)) > now:
                    return existing.get("owner_id") == owner_id
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
        return False

    def release(self, task_id: str, owner_id: str) -> None:
        path = self._path(task_id)
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if existing.get("owner_id") == owner_id:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


class TaskRecoveryManager:
    """Recover persisted running tasks after a worker/process restart."""

    def __init__(
        self,
        *,
        persistence: StatePersistence,
        conversations: ConversationStore,
        orchestrator,
        lease_store: Optional[TaskLeaseStore] = None,
        owner_id: Optional[str] = None,
        on_started: Optional[Callable[[TaskState, asyncio.Task], None]] = None,
        on_finished: Optional[Callable[[TaskState, asyncio.Task], None]] = None,
    ):
        self.persistence = persistence
        self.conversations = conversations
        self.orchestrator = orchestrator
        self.owner_id = owner_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
        self.leases = lease_store or TaskLeaseStore(persistence.base_dir)
        self.on_started = on_started
        self.on_finished = on_finished
        self.handles: dict[str, asyncio.Task] = {}

    def _candidate_states(self) -> list[TaskState]:
        candidates: list[TaskState] = []
        if not self.persistence.base_dir.exists():
            return candidates
        for task_dir in self.persistence.base_dir.iterdir():
            state_path = task_dir / "task_state.json"
            if not task_dir.is_dir() or not state_path.exists():
                continue
            try:
                state = TaskState.model_validate(
                    json.loads(state_path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Skipping invalid recovery checkpoint", path=str(state_path), error=str(exc))
                continue
            if state.lifecycle_status not in {"pending", "running"}:
                continue
            candidates.append(state)
        return candidates

    def _is_recoverable(self, state: TaskState) -> bool:
        if not state.session_id:
            return False
        session = self.conversations.load_session(state.session_id)
        return bool(
            session
            and session.active_task_id == state.id
            and session.status == "running"
        )

    async def recover_once(self) -> list[str]:
        started: list[str] = []
        for state in self._candidate_states():
            if state.id in self.handles or not self._is_recoverable(state):
                continue
            if not self.leases.claim(state.id, self.owner_id):
                continue
            try:
                restored = await self.orchestrator.create_task(
                    user_query="",
                    resume_from_checkpoint=str(
                        self.persistence.get_latest_checkpoint(state.id)
                    ),
                    session_id=state.session_id,
                )
                restored.session_id = state.session_id
                restored.control_request = None
                restored.lifecycle_status = "running"
                await self.persistence.save_checkpoint(restored)
                execution = asyncio.create_task(self._run_one(restored))
                self.handles[restored.id] = execution
                if self.on_started:
                    self.on_started(restored, execution)
                started.append(restored.id)
            except Exception:
                self.leases.release(state.id, self.owner_id)
                logger.exception("Failed to recover task", task_id=state.id)
        return started

    async def _run_one(self, state: TaskState) -> None:
        current = asyncio.current_task()
        try:
            await self.orchestrator.run(state)
        finally:
            self.handles.pop(state.id, None)
            self.leases.release(state.id, self.owner_id)
            if self.on_finished and current is not None:
                self.on_finished(state, current)

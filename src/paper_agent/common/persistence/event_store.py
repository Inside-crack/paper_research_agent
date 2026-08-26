from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from ..models import AgentEvent
from ..event_security import EventSecurityFilter

_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EVENTS_FILENAME = "events.jsonl"


class EventStore:
    """Append-only JSONL store for correlated agent events."""

    def __init__(
        self,
        base_dir: Path,
        *,
        security_filter: Optional[EventSecurityFilter] = None,
    ):
        self.base_dir = Path(base_dir)
        self.security_filter = security_filter or EventSecurityFilter()
        if self.base_dir.is_symlink():
            raise ValueError(f"Event store base directory must not be a symlink: {self.base_dir}")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_task_id(task_id: str) -> None:
        if task_id == "_conversation":
            return
        if not isinstance(task_id, str) or not _TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError(f"Invalid event task_id: {task_id!r}")

    def _event_path(self, task_id: str | None) -> Path:
        storage_key = task_id or "_conversation"
        self._validate_task_id(storage_key)
        task_dir = self.base_dir / storage_key
        logs_dir = task_dir / "logs"
        if task_dir.is_symlink() or logs_dir.is_symlink():
            raise ValueError(f"Event persistence path must not be a symlink: {storage_key!r}")
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / _EVENTS_FILENAME
        if path.is_symlink():
            raise ValueError(f"Event persistence file must not be a symlink: {path}")
        return path

    def append(self, event: AgentEvent) -> Path:
        if not isinstance(event, AgentEvent):
            raise TypeError("event must be an AgentEvent")
        safe_event = self.security_filter.sanitize_event(event)
        path = self._event_path(safe_event.task_id)
        payload = safe_event.model_dump(mode="json")
        try:
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")
                file.flush()
                os.fsync(file.fileno())
        except OSError as exc:
            raise OSError(f"Failed to append agent event: {path}") from exc
        return path

    def list(
        self,
        *,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> list[AgentEvent]:
        for value, name in (
            (session_id, "session_id"),
            (task_id, "task_id"),
            (correlation_id, "correlation_id"),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} filter must not be empty")
        if task_id is not None:
            paths = [self._event_path(task_id)]
        else:
            paths = sorted(self.base_dir.glob(f"*/logs/{_EVENTS_FILENAME}"))

        events: list[AgentEvent] = []
        for path in paths:
            self._validate_event_path(path)
            task_dir = path.parent.parent
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if not line.strip():
                    continue
                try:
                    event = AgentEvent.model_validate(json.loads(line))
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ValueError(
                        f"Corrupt agent event at {path}:{line_number}"
                    ) from exc
                expected_task_id = (
                    None if task_dir.name == "_conversation" else task_dir.name
                )
                if event.task_id != expected_task_id:
                    raise ValueError(
                        f"Agent event task_id mismatch at {path}:{line_number}"
                    )
                if session_id is not None and event.session_id != session_id:
                    continue
                if correlation_id is not None and event.correlation_id != correlation_id:
                    continue
                events.append(event)
        return sorted(events, key=lambda event: (event.timestamp, event.event_id))

    @staticmethod
    def _validate_event_path(path: Path) -> None:
        if path.is_symlink():
            raise ValueError(f"Event persistence file must not be a symlink: {path}")

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..logging import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


class TaskJsonLogger:
    def __init__(self, task_dir: Path, task_id: str):
        self.task_dir = task_dir
        self.task_id = task_id
        self.log_dir = task_dir / "logs"
        self.log_path = self.log_dir / "run.jsonl"
        self._fh = None
        self._ensure_open()

    def _ensure_open(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.log_path, "a", encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to open task jsonl log for {self.task_id}: {e}")
            self._fh = None

    def _write(self, event: str, **fields: Any) -> None:
        if self._fh is None:
            return
        entry = {"ts": _now_iso(), "event": event}
        entry.update({k: v for k, v in fields.items() if v is not None})
        try:
            self._fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
        except Exception as e:
            logger.error(f"Failed to write jsonl event for {self.task_id}: {e}")

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None

    def phase_started(self, phase: str, revision: int = 0) -> None:
        self._write("phase_started", phase=phase, revision=revision)

    def phase_completed(self, phase: str, verdict: str, score: Optional[float] = None,
                        duration_ms: int = 0, revision: int = 0) -> None:
        self._write("phase_completed", phase=phase, verdict=verdict, score=score,
                    duration_ms=duration_ms, revision=revision)

    def step_executed(self, step_id: str, tool: str, success: bool,
                      duration_ms: int = 0, artifact: Optional[str] = None,
                      error: Optional[str] = None) -> None:
        self._write("step_executed", step_id=step_id, tool=tool, success=success,
                    duration_ms=duration_ms, artifact=artifact, error=error[:200] if error else None)

    def revision_triggered(self, phase: str, revision: int, reason: str = "") -> None:
        self._write("revision_triggered", phase=phase, revision=revision, reason=reason[:200] if reason else None)

    def checkpoint_saved(self, checkpoint_name: str) -> None:
        self._write("checkpoint_saved", checkpoint=checkpoint_name)

    def error_dumped(self, error_type: str, error_file: str, message: str = "") -> None:
        self._write("error_dumped", error_type=error_type, error_file=error_file,
                    message=message[:300] if message else None)

    def warning(self, message: str, **extra: Any) -> None:
        self._write("warning", message=message[:300], **extra)

    def error(self, message: str, **extra: Any) -> None:
        self._write("error", message=message[:500], **extra)

    def cleanup(self, deleted_checkpoints: list[str]) -> None:
        if deleted_checkpoints:
            self._write("cleanup", deleted_checkpoints=deleted_checkpoints, count=len(deleted_checkpoints))

    def task_completed(self, final_status: str, total_duration_ms: int = 0,
                       total_phases: int = 0, total_errors: int = 0, total_revisions: int = 0) -> None:
        self._write("task_completed", status=final_status, total_duration_ms=total_duration_ms,
                    total_phases=total_phases, total_errors=total_errors, total_revisions=total_revisions)
        self.close()

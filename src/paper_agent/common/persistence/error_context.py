from __future__ import annotations

import json
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..logging import get_logger
from .manifest import atomic_write_json
from .naming import artifact_filename, phase_short

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


class StepSnapshot(BaseModel):
    step_id: str
    tool_name: str
    success: bool
    duration_ms: int = 0
    artifact_id: Optional[str] = None
    error: Optional[str] = None
    arguments_snapshot: dict[str, Any] = Field(default_factory=dict)


class ErrorContext(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str
    phase: str
    revision: int = 0
    error_type: str
    error_message: str
    traceback: Optional[str] = None
    timestamp: str = Field(default_factory=_now_iso)

    failed_step: Optional[str] = None
    failed_tool: Optional[str] = None

    execution_plan: Optional[dict[str, Any]] = None
    step_snapshots: list[StepSnapshot] = Field(default_factory=list)

    messages_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    eval_result: Optional[dict[str, Any]] = None
    research_output: Optional[dict[str, Any]] = None

    recovery_hint: Optional[str] = None


class PhaseCompletionRecord(BaseModel):
    task_id: str
    phase: str
    revision: int = 0
    verdict: str
    score: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: str = Field(default_factory=_now_iso)
    duration_ms: int = 0
    steps_total: int = 0
    steps_succeeded: int = 0
    steps_failed: int = 0
    total_errors: int = 0
    artifacts: list[str] = Field(default_factory=list)


def build_error_filename(phase, error_type: str, revision: int = 0) -> str:
    short = phase_short(phase)
    if error_type in ("blocked", "exception", "fatal"):
        if revision > 0:
            return f"{short}_error_r{revision}_fatal.json"
        return f"{short}_fatal_error.json"
    if error_type == "revise":
        return artifact_filename(phase, "error", revision=revision) if revision > 0 else f"{short}_error.json"
    return artifact_filename(phase, "error", revision=revision) if revision > 0 else f"{short}_error.json"


def build_completion_filename(phase) -> str:
    return artifact_filename(phase, "completion")


def build_step_snapshots_from_plan(plan) -> list[StepSnapshot]:
    from ..models.execution_plan import ExecutionPlan
    snapshots: list[StepSnapshot] = []
    if not plan:
        return snapshots
    if hasattr(plan, "steps"):
        steps = plan.steps
    elif isinstance(plan, dict):
        steps = plan.get("steps", [])
    else:
        return snapshots
    for s in steps:
        if hasattr(s, "step_id"):
            snapshots.append(StepSnapshot(
                step_id=s.step_id,
                tool_name=s.tool_name,
                success=bool(getattr(s, "success", False)),
                duration_ms=getattr(s, "duration_ms", 0) or 0,
                artifact_id=getattr(s, "artifact_id", None),
                error=getattr(s, "error", None),
                arguments_snapshot=getattr(s, "arguments", {}) or {},
            ))
        elif isinstance(s, dict):
            snapshots.append(StepSnapshot(
                step_id=s.get("step_id", ""),
                tool_name=s.get("tool_name", ""),
                success=bool(s.get("success", False)),
                duration_ms=s.get("duration_ms", 0) or 0,
                artifact_id=s.get("artifact_id"),
                error=s.get("error"),
                arguments_snapshot=s.get("arguments", {}) or {},
            ))
    return snapshots


def snapshot_messages(messages) -> list[dict[str, Any]]:
    result = []
    if not messages:
        return result
    for m in messages:
        if hasattr(m, "model_dump"):
            try:
                result.append(m.model_dump(exclude_none=False))
                continue
            except Exception:
                pass
        if hasattr(m, "dict"):
            try:
                result.append(m.dict())
                continue
            except Exception:
                pass
        if isinstance(m, dict):
            result.append(dict(m))
    return result


def snapshot_model(obj) -> Optional[dict[str, Any]]:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(exclude_none=False, default=str)
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    if isinstance(obj, dict):
        return dict(obj)
    return None


def _safe_json_dumps(obj) -> dict:
    try:
        data = obj.model_dump(exclude_none=False)
        return json.loads(json.dumps(data, default=str, ensure_ascii=False))
    except Exception:
        return json.loads(json.dumps(obj, default=str, ensure_ascii=False))


def write_error_context(task_dir: Path, ctx: ErrorContext) -> Optional[Path]:
    fname = build_error_filename(ctx.phase, ctx.error_type, ctx.revision)
    path = task_dir / fname
    try:
        atomic_write_json(path, _safe_json_dumps(ctx))
        logger.info(f"Error context dumped to {path.name}", error_type=ctx.error_type, phase=ctx.phase)
    except Exception as e:
        logger.error(f"Failed to write error context to {path}: {e}", exc_info=True)
        return None
    return path


def write_completion_record(task_dir: Path, rec: PhaseCompletionRecord) -> Optional[Path]:
    fname = build_completion_filename(rec.phase)
    path = task_dir / fname
    try:
        atomic_write_json(path, _safe_json_dumps(rec))
    except Exception as e:
        logger.error(f"Failed to write completion record to {path}: {e}", exc_info=True)
        return None
    return path


def format_traceback(exc: Optional[BaseException] = None) -> Optional[str]:
    if exc is None:
        return None
    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        try:
            return traceback.format_exc()
        except Exception:
            return str(exc)

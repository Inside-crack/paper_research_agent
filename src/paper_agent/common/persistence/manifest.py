from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..config import get_settings
from ..logging import get_logger
from ..models.base import TaskPhase
from ..models.task_state import PAPER_PROCESSING_SUBSTEPS
from .naming import phase_short, artifact_filename, parse_artifact_filename

logger = get_logger(__name__)

MANIFEST_VERSION = 1
INDEX_VERSION = 1
TASKS_INDEX_FILENAME = "tasks_index.json"
MANIFEST_FILENAME = "manifest.json"


class StepSummary(BaseModel):
    tool: str
    status: str = "pending"
    artifact: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0


class PhaseArtifacts(BaseModel):
    spec: Optional[str] = None
    plan: Optional[str] = None
    eval: Optional[str] = None
    summary: Optional[str] = None
    output: Optional[str] = None


class PaperProcessingStepEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "not_started"
    revision_count: int = 0
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


def _default_paper_processing_steps() -> dict[str, PaperProcessingStepEntry]:
    return {name: PaperProcessingStepEntry() for name in PAPER_PROCESSING_SUBSTEPS}


class PhaseEntry(BaseModel):
    status: str = "not_started"
    score: Optional[float] = None
    verdict: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    revisions: int = 0
    artifacts: PhaseArtifacts = Field(default_factory=PhaseArtifacts)
    steps: dict[str, StepSummary] = Field(default_factory=dict)
    paper_processing_steps: dict[str, PaperProcessingStepEntry] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class FileEntry(BaseModel):
    name: str
    type: str
    phase: Optional[str] = None
    step_id: Optional[str] = None
    size_bytes: int = 0


class TaskManifest(BaseModel):
    task_id: str
    topic: str = ""
    status: str = "running"
    current_phase: str = TaskPhase.TASK_INITIALIZATION.value
    current_revision: int = 0
    created_at: str
    updated_at: str
    phases: dict[str, PhaseEntry] = Field(default_factory=dict)
    files: list[FileEntry] = Field(default_factory=list)
    total_errors: int = 0
    total_revisions: int = 0
    version: int = MANIFEST_VERSION


class TaskIndexEntry(BaseModel):
    task_id: str
    topic: str = ""
    status: str = "running"
    current_phase: str = ""
    latest_score: Optional[float] = None
    total_errors: int = 0
    total_revisions: int = 0
    created_at: str = ""
    updated_at: str = ""
    manifest_path: str = ""


class TasksIndex(BaseModel):
    updated_at: str
    version: int = INDEX_VERSION
    tasks: list[TaskIndexEntry] = Field(default_factory=list)


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _init_phases() -> dict[str, PhaseEntry]:
    phases = {p.value: PhaseEntry() for p in TaskPhase if p.value not in ("completed", "failed")}
    phases[TaskPhase.PAPER_PARSING.value].paper_processing_steps = _default_paper_processing_steps()
    return phases


def create_empty_manifest(task_id: str, topic: str = "") -> TaskManifest:
    now = _now_iso()
    topic_short = topic[:100] if topic else ""
    m = TaskManifest(
        task_id=task_id,
        topic=topic_short,
        status="running",
        current_phase=TaskPhase.TASK_INITIALIZATION.value,
        created_at=now,
        updated_at=now,
        phases=_init_phases(),
    )
    m.phases[TaskPhase.TASK_INITIALIZATION.value].status = "running"
    m.phases[TaskPhase.TASK_INITIALIZATION.value].started_at = now
    m.phases[TaskPhase.TASK_INITIALIZATION.value].artifacts.spec = "research_spec.json"
    return m


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise


def load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load JSON from {path}: {e}")
        return None


def manifest_to_dict(m: TaskManifest) -> dict:
    return json.loads(m.model_dump_json(exclude_none=False))


def dict_to_manifest(d: dict) -> Optional[TaskManifest]:
    try:
        manifest = TaskManifest.model_validate(d)
        phases = d.get("phases", {})
        paper_phase = phases.get(TaskPhase.PAPER_PARSING.value) if isinstance(phases, dict) else None
        if isinstance(paper_phase, dict) and "paper_processing_steps" in paper_phase:
            manifest.phases[TaskPhase.PAPER_PARSING.value].paper_processing_steps = (
                validate_paper_processing_steps(paper_phase["paper_processing_steps"])
            )
        return manifest
    except Exception as e:
        logger.warning(f"Failed to parse manifest: {e}")
        return None


def validate_paper_processing_steps(
    steps: Any,
) -> dict[str, PaperProcessingStepEntry]:
    if not isinstance(steps, dict):
        raise ValueError("Invalid paper_processing_steps: expected a dict")

    restored: dict[str, PaperProcessingStepEntry] = {}
    for name, step_data in steps.items():
        if name not in PAPER_PROCESSING_SUBSTEPS:
            allowed = ", ".join(PAPER_PROCESSING_SUBSTEPS)
            raise ValueError(
                f"Unknown paper processing substep {name!r}; expected one of: {allowed}"
            )
        if isinstance(step_data, PaperProcessingStepEntry):
            restored[name] = step_data
            continue
        if not isinstance(step_data, dict):
            raise ValueError(f"Invalid paper processing step {name!r}: expected a dict")
        try:
            restored[name] = PaperProcessingStepEntry.model_validate(step_data)
        except Exception as exc:
            raise ValueError(f"Invalid paper processing step {name!r}: {exc}") from exc
    return restored


def dict_to_manifest_strict(d: Any, source: Optional[Path] = None) -> TaskManifest:
    location = f": {source}" if source is not None else ""
    if not isinstance(d, dict):
        raise ValueError(f"Invalid Manifest JSON structure{location}")
    try:
        manifest = TaskManifest.model_validate(d)
    except Exception as exc:
        raise ValueError(f"Invalid Manifest structure{location}: {exc}") from exc

    paper_phase = manifest.phases.get(TaskPhase.PAPER_PARSING.value)
    if paper_phase is not None:
        paper_phase.paper_processing_steps = validate_paper_processing_steps(
            paper_phase.paper_processing_steps
        )
    return manifest


def load_manifest_strict(path: Path) -> Optional[TaskManifest]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return dict_to_manifest_strict(json.load(f), source=path)


def dict_to_index(d: dict) -> Optional[TasksIndex]:
    try:
        return TasksIndex(**d)
    except Exception as e:
        logger.warning(f"Failed to parse tasks index: {e}")
        return None


def manifest_to_index_entry(m: TaskManifest) -> TaskIndexEntry:
    score = None
    for phase_name, pe in m.phases.items():
        if pe.score is not None:
            score = pe.score
    topic_short = m.topic[:80] if m.topic else ""
    return TaskIndexEntry(
        task_id=m.task_id,
        topic=topic_short,
        status=m.status,
        current_phase=m.current_phase,
        latest_score=score,
        total_errors=m.total_errors,
        total_revisions=m.total_revisions,
        created_at=m.created_at,
        updated_at=m.updated_at,
        manifest_path=f"{m.task_id}/{MANIFEST_FILENAME}",
    )


def scan_artifacts_for_files(task_dir: Path) -> list[FileEntry]:
    files = []
    if not task_dir.exists():
        return files
    for p in sorted(task_dir.rglob("*.json")):
        if p.name in (MANIFEST_FILENAME, TASKS_INDEX_FILENAME):
            continue
        if p.name.startswith("checkpoint_"):
            continue
        if "checkpoints" in p.relative_to(task_dir).parts:
            continue
        if "evaluations" in p.relative_to(task_dir).parts:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        rel = p.relative_to(task_dir).as_posix()
        parsed = parse_artifact_filename(p.name)
        if parsed and not parsed.get("is_fixed"):
            files.append(FileEntry(
                name=rel,
                type=parsed["type"],
                phase=parsed.get("phase"),
                step_id=parsed.get("step_id"),
                size_bytes=size,
            ))
        elif p.name == "research_spec.json":
            files.append(FileEntry(name=rel, type="spec", phase="task_initialization", size_bytes=size))
        elif p.name == "task_state.json":
            files.append(FileEntry(name=rel, type="state", size_bytes=size))
        else:
            files.append(FileEntry(name=rel, type="unknown", size_bytes=size))
    return files


def rebuild_manifest_from_state(task_dir: Path, task_id: str, state_data: dict) -> TaskManifest:
    if not isinstance(state_data, dict):
        raise ValueError("Invalid task state JSON: expected a dict")

    topic = ""
    spec = state_data.get("metadata", {}).get("research_spec", {})
    if spec:
        topic = spec.get("user_query", "") or spec.get("topic", "") or spec.get("research_topic", "") or spec.get("query", "")
    m = create_empty_manifest(task_id, topic)

    current_phase = state_data.get("current_phase", TaskPhase.TASK_INITIALIZATION.value)
    if current_phase in ("completed", "failed"):
        m.status = current_phase
        current_phase = state_data.get("metadata", {}).get("last_phase", TaskPhase.RESULT_REPORTING.value)
    m.current_phase = current_phase

    if state_data.get("started_at"):
        m.created_at = state_data["started_at"]

    phase_summaries = state_data.get("metadata", {}).get("phase_summaries", [])
    for card in phase_summaries:
        pname = card.get("phase", "")
        if pname in m.phases:
            m.phases[pname].status = card.get("verdict", "passed")
            m.phases[pname].score = card.get("score")
            m.phases[pname].verdict = card.get("verdict")
            m.phases[pname].summary = artifact_filename(pname, "summary") if pname else None

    if "paper_processing_steps" in state_data:
        m.phases[TaskPhase.PAPER_PARSING.value].paper_processing_steps = (
            validate_paper_processing_steps(state_data["paper_processing_steps"])
        )

    m.files = scan_artifacts_for_files(task_dir)

    m.updated_at = _now_iso()
    return m

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel

from ..config import get_settings
from ..logging import get_logger
from ..models.base import EvaluationVerdict, TaskPhase
from ..models.evaluation_result import EvaluationResult
from ..models.execution_plan import ExecutionPlan
from ..models.research_spec import ResearchSpec
from ..models.paper_artifact import PaperArtifact
from ..models.task_state import (
    PAPER_PROCESSING_SUBSTEPS,
    PaperProcessingStepState,
    TaskState,
    default_paper_processing_steps,
)
from .error_context import (
    ErrorContext,
    PhaseCompletionRecord,
    StepSnapshot,
    build_step_snapshots_from_plan,
    format_traceback,
    snapshot_messages,
    snapshot_model,
    write_completion_record,
    write_error_context,
)
from .manifest import (
    MANIFEST_FILENAME,
    TASKS_INDEX_FILENAME,
    TaskManifest,
    TasksIndex,
    TaskIndexEntry,
    PhaseEntry,
    PaperProcessingStepEntry,
    StepSummary,
    FileEntry,
    atomic_write_json,
    create_empty_manifest,
    dict_to_index,
    dict_to_manifest,
    load_json,
    manifest_to_dict,
    manifest_to_index_entry,
    rebuild_manifest_from_state,
    load_manifest_strict,
    validate_paper_processing_steps,
    _now_iso,
)
from .naming import artifact_filename, phase_short

logger = get_logger(__name__)


class StatePersistence:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir if base_dir is not None else get_settings().artifact_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_task_dir(self, task_id: str) -> Path:
        task_dir = self.base_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def _get_manifest_path(self, task_id: str) -> Path:
        return self._get_task_dir(task_id) / MANIFEST_FILENAME

    def _get_index_path(self) -> Path:
        return self.base_dir / TASKS_INDEX_FILENAME

    def _serialize_model(self, model: BaseModel) -> dict[str, Any]:
        return model.model_dump(mode="json")

    def _save_json(self, path: Path, data: Any) -> None:
        atomic_write_json(path, data)

    def _save_bytes_atomically(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp_path, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

    def _load_json(self, path: Path) -> Any:
        return load_json(path)

    def _load_json_strict(self, path: Path) -> Any:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _restore_file(self, path: Path, content: Optional[bytes]) -> None:
        if content is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        self._save_bytes_atomically(path, content)

    async def save_research_spec(self, spec: ResearchSpec) -> Path:
        task_dir = self._get_task_dir(spec.id)
        path = task_dir / "research_spec.json"
        self._save_json(path, self._serialize_model(spec))
        logger.debug(f"Saved ResearchSpec to {path}")
        return path

    async def create_task_manifest(self, spec: ResearchSpec) -> TaskManifest:
        topic = spec.user_query or ""
        m = create_empty_manifest(spec.id, topic)
        self._save_json(self._get_manifest_path(spec.id), manifest_to_dict(m))
        await self.update_tasks_index(spec.id)
        return m

    def load_manifest(self, task_id: str) -> Optional[TaskManifest]:
        path = self._get_manifest_path(task_id)
        data = load_json(path)
        m = dict_to_manifest(data) if data else None
        if m is None and (self._get_task_dir(task_id) / "task_state.json").exists():
            state_data = load_json(self._get_task_dir(task_id) / "task_state.json")
            if state_data:
                m = rebuild_manifest_from_state(self._get_task_dir(task_id), task_id, state_data)
                self._save_json(path, manifest_to_dict(m))
        return m

    def _update_manifest(self, task_id: str, updater: Callable[[TaskManifest], None]) -> TaskManifest:
        path = self._get_manifest_path(task_id)
        m = load_manifest_strict(path)
        if m is None:
            state_path = self._get_task_dir(task_id) / "task_state.json"
            state_data = self._load_json_strict(state_path)
            if state_path.exists() and not isinstance(state_data, dict):
                raise ValueError(f"Invalid task state JSON: {state_path}")
            topic = ""
            if state_data:
                spec = state_data.get("metadata", {}).get("research_spec", {})
                topic = spec.get("topic", "") or spec.get("query", "")
            m = create_empty_manifest(task_id, topic)
            if state_data:
                m = rebuild_manifest_from_state(self._get_task_dir(task_id), task_id, state_data)

        updater(m)
        m.updated_at = _now_iso()
        self._save_json(path, manifest_to_dict(m))
        return m

    @staticmethod
    def _validate_paper_processing_substep(substep: str) -> None:
        if substep not in PAPER_PROCESSING_SUBSTEPS:
            allowed = ", ".join(PAPER_PROCESSING_SUBSTEPS)
            raise ValueError(f"Unknown paper processing substep {substep!r}; expected one of: {allowed}")

    @classmethod
    def _validate_paper_processing_step_names(cls, steps: Any) -> None:
        if not isinstance(steps, dict):
            raise ValueError("Invalid paper_processing_steps: expected a dict")
        for name in steps:
            cls._validate_paper_processing_substep(name)

    def load_paper_processing_steps(self, task_id: str) -> dict[str, PaperProcessingStepState]:
        """Load persisted paper substep state, falling back to the Manifest."""
        task_dir = self._get_task_dir(task_id)
        state_path = task_dir / "task_state.json"
        manifest = load_manifest_strict(task_dir / MANIFEST_FILENAME)
        if state_path.exists():
            state_data = self._load_json_strict(state_path)
            if not isinstance(state_data, dict):
                raise ValueError(f"Invalid task state JSON: {state_path}")
            state = TaskState(**state_data)
            self._validate_paper_processing_step_names(state.paper_processing_steps)
            return state.paper_processing_steps

        if manifest is None:
            return default_paper_processing_steps()

        entries = manifest.phases.get(TaskPhase.PAPER_PARSING.value)
        if entries is None:
            return default_paper_processing_steps()
        entries.paper_processing_steps = validate_paper_processing_steps(
            entries.paper_processing_steps
        )
        return {
            name: PaperProcessingStepState.model_validate(entry.model_dump(mode="json"))
            for name, entry in entries.paper_processing_steps.items()
        }

    def _build_minimal_task_state(
        self,
        task_id: str,
        task_dir: Path,
        manifest: Optional[TaskManifest],
    ) -> TaskState:
        research_spec_id = task_id
        metadata: dict[str, Any] = {}
        spec_path = task_dir / "research_spec.json"
        if spec_path.exists():
            spec_data = self._load_json_strict(spec_path)
            if not isinstance(spec_data, dict):
                raise ValueError(f"Invalid research spec JSON: {spec_path}")
            metadata["research_spec"] = spec_data
            research_spec_id = spec_data.get("id") or task_id
        elif manifest is not None and manifest.topic:
            metadata["research_spec"] = {"user_query": manifest.topic}

        paper_processing_steps = default_paper_processing_steps()
        if manifest is not None:
            phase = manifest.phases.get(TaskPhase.PAPER_PARSING.value)
            if phase is not None:
                entries = validate_paper_processing_steps(phase.paper_processing_steps)
                for name, entry in entries.items():
                    paper_processing_steps[name] = PaperProcessingStepState.model_validate(
                        entry.model_dump(mode="json")
                    )

        return TaskState(
            id=task_id,
            research_spec_id=research_spec_id,
            current_phase=TaskPhase.PAPER_PARSING,
            paper_processing_steps=paper_processing_steps,
            metadata=metadata,
            artifact_dir=str(task_dir),
        )

    async def update_paper_processing_step(
        self,
        task_id: str,
        substep: str,
        step_state: PaperProcessingStepState,
    ) -> PaperProcessingStepState:
        """Persist one PAPER_PARSING substep in state and its Manifest entry."""
        self._validate_paper_processing_substep(substep)
        if not isinstance(step_state, PaperProcessingStepState):
            raise TypeError("step_state must be a PaperProcessingStepState")

        task_dir = self._get_task_dir(task_id)
        state_path = task_dir / "task_state.json"
        previous_state = state_path.read_bytes() if state_path.exists() else None
        manifest_path = task_dir / MANIFEST_FILENAME
        previous_manifest = manifest_path.read_bytes() if manifest_path.exists() else None
        try:
            manifest = load_manifest_strict(manifest_path)
            if previous_state is not None:
                state_data = self._load_json_strict(state_path)
                if not isinstance(state_data, dict):
                    raise ValueError(f"Invalid task state JSON: {state_path}")
                state = TaskState(**state_data)
                self._validate_paper_processing_step_names(state.paper_processing_steps)
            else:
                state = self._build_minimal_task_state(task_id, task_dir, manifest)
            state.current_phase = TaskPhase.PAPER_PARSING
            state.paper_processing_steps[substep] = step_state
            self._save_json(state_path, self._serialize_model(state))

            def _upd(m: TaskManifest):
                phase_name = TaskPhase.PAPER_PARSING.value
                if phase_name not in m.phases:
                    m.phases[phase_name] = PhaseEntry()
                m.phases[phase_name].paper_processing_steps[substep] = PaperProcessingStepEntry(
                    **step_state.model_dump(mode="json")
                )
                m.current_phase = phase_name

            self._update_manifest(task_id, _upd)
            await self.update_tasks_index(task_id, strict=True)
            return step_state
        except Exception as original_error:
            rollback_errors = []
            for path, content in (
                (state_path, previous_state),
                (manifest_path, previous_manifest),
            ):
                try:
                    self._restore_file(path, content)
                except Exception as rollback_error:
                    rollback_errors.append((path, rollback_error))
                    logger.error(f"Failed to roll back {path}: {rollback_error}")
            try:
                rollback_index = self._rebuild_tasks_index_without_creating_manifests()
                self._save_json(
                    self._get_index_path(),
                    rollback_index.model_dump(mode="json"),
                )
            except Exception as rollback_error:
                rollback_errors.append((self._get_index_path(), rollback_error))
                logger.error(
                    f"Failed to rebuild tasks index during rollback: {rollback_error}"
                )
            if rollback_errors:
                details = "; ".join(
                    f"{path}: {rollback_error}" for path, rollback_error in rollback_errors
                )
                raise RuntimeError(
                    f"Persistence operation failed with original error {original_error!r}; "
                    f"rollback failure(s): {details}"
                ) from original_error
            raise

    def _add_file_entry(self, m: TaskManifest, name: str, file_type: str,
                        phase: Optional[str] = None, step_id: Optional[str] = None) -> None:
        fpath = self._get_task_dir(m.task_id) / name
        try:
            size = fpath.stat().st_size if fpath.exists() else 0
        except OSError:
            size = 0
        for fe in m.files:
            if fe.name == name:
                fe.size_bytes = size
                fe.type = file_type
                fe.phase = phase or fe.phase
                fe.step_id = step_id or fe.step_id
                return
        m.files.append(FileEntry(name=name, type=file_type, phase=phase, step_id=step_id, size_bytes=size))

    async def save_phase_plan(self, task_id: str, phase: TaskPhase, plan: ExecutionPlan) -> Path:
        task_dir = self._get_task_dir(task_id)
        fname = artifact_filename(phase, "plan")
        path = task_dir / fname
        self._save_json(path, self._serialize_model(plan))

        def _upd(m: TaskManifest):
            pshort = phase.value
            if pshort not in m.phases:
                m.phases[pshort] = PhaseEntry()
            m.phases[pshort].artifacts.plan = fname
            m.phases[pshort].status = "running"
            if not m.phases[pshort].started_at:
                m.phases[pshort].started_at = _now_iso()
            m.current_phase = pshort
            self._add_file_entry(m, fname, "plan", pshort)

        self._update_manifest(task_id, _upd)
        await self.update_tasks_index(task_id)
        return path

    async def save_phase_summary(self, task_id: str, phase: TaskPhase, summary_card: dict) -> Path:
        task_dir = self._get_task_dir(task_id)
        fname = artifact_filename(phase, "summary")
        path = task_dir / fname
        self._save_json(path, summary_card)

        def _upd(m: TaskManifest):
            pshort = phase.value
            if pshort not in m.phases:
                m.phases[pshort] = PhaseEntry()
            m.phases[pshort].artifacts.summary = fname
            self._add_file_entry(m, fname, "summary", pshort)

        self._update_manifest(task_id, _upd)
        await self.update_tasks_index(task_id)
        return path

    async def save_phase_output(self, task_id: str, phase: TaskPhase, output: dict) -> Path:
        task_dir = self._get_task_dir(task_id)
        fname = artifact_filename(phase, "output")
        path = task_dir / fname
        self._save_json(path, output)

        def _upd(m: TaskManifest):
            pshort = phase.value
            if pshort not in m.phases:
                m.phases[pshort] = PhaseEntry()
            m.phases[pshort].artifacts.output = fname
            self._add_file_entry(m, fname, "output", pshort)

        self._update_manifest(task_id, _upd)
        await self.update_tasks_index(task_id)
        return path

    async def save_paper_artifact(
        self,
        task_id: str,
        artifact: PaperArtifact,
        pdf_bytes: bytes,
        pdf_relative_path: str,
    ) -> tuple[Path, Path]:
        """Persist a validated paper PDF and its structured metadata together."""
        pdf_path = self._get_task_dir(task_id) / pdf_relative_path
        artifact_path = pdf_path.with_suffix(".json")
        written_paths: list[Path] = []

        try:
            self._save_bytes_atomically(pdf_path, pdf_bytes)
            written_paths.append(pdf_path)
            self._save_json(artifact_path, self._serialize_model(artifact))
            written_paths.append(artifact_path)

            def _upd(m: TaskManifest):
                phase_name = TaskPhase.PAPER_PARSING.value
                if phase_name not in m.phases:
                    m.phases[phase_name] = PhaseEntry()
                m.phases[phase_name].artifacts.output = artifact_path.relative_to(
                    self._get_task_dir(task_id)
                ).as_posix()
                self._add_file_entry(
                    m,
                    pdf_path.relative_to(self._get_task_dir(task_id)).as_posix(),
                    "paper_pdf",
                    phase_name,
                )
                self._add_file_entry(
                    m,
                    artifact_path.relative_to(self._get_task_dir(task_id)).as_posix(),
                    "paper_artifact",
                    phase_name,
                )

            self._update_manifest(task_id, _upd)
            await self.update_tasks_index(task_id)
            return pdf_path, artifact_path
        except Exception:
            for path in written_paths:
                try:
                    path.unlink()
                except OSError:
                    pass
            raise

    async def update_paper_artifact(
        self,
        task_id: str,
        artifact_path: str,
        artifact: PaperArtifact,
    ) -> Path:
        relative_path = Path(artifact_path)
        task_dir = self._get_task_dir(task_id)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Invalid paper artifact path: {artifact_path}")

        path = task_dir / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Paper artifact not found: {artifact_path}")

        previous_content = path.read_bytes()
        try:
            self._save_json(path, self._serialize_model(artifact))

            def _upd(m: TaskManifest):
                phase_name = TaskPhase.PAPER_PARSING.value
                if phase_name not in m.phases:
                    m.phases[phase_name] = PhaseEntry()
                m.phases[phase_name].artifacts.output = relative_path.as_posix()
                self._add_file_entry(m, relative_path.as_posix(), "paper_artifact", phase_name)

            self._update_manifest(task_id, _upd)
            await self.update_tasks_index(task_id)
            return path
        except Exception:
            self._save_bytes_atomically(path, previous_content)
            raise

    async def save_phase_eval(self, task_id: str, phase: TaskPhase, verdict: EvaluationVerdict,
                               eval_result: EvaluationResult) -> Path:
        task_dir = self._get_task_dir(task_id)
        eval_dir = task_dir / "evaluations"
        eval_dir.mkdir(exist_ok=True)
        eval_fname = f"eval_{phase.value}_{eval_result.id}.json"
        eval_path = eval_dir / eval_fname
        self._save_json(eval_path, self._serialize_model(eval_result))

        fname = artifact_filename(phase, "eval")
        manifest_ref = f"evaluations/{eval_fname}"

        def _upd(m: TaskManifest):
            pshort = phase.value
            if pshort not in m.phases:
                m.phases[pshort] = PhaseEntry()
            m.phases[pshort].artifacts.eval = manifest_ref
            m.phases[pshort].verdict = verdict.value
            m.phases[pshort].score = eval_result.score
            self._add_file_entry(m, manifest_ref, "eval", pshort)

        self._update_manifest(task_id, _upd)
        await self.update_tasks_index(task_id)
        return eval_path

    async def update_step_in_manifest(
        self, task_id: str, phase: TaskPhase, step_id: str, tool: str,
        success: bool, artifact_name: Optional[str], error_msg: Optional[str],
        duration_ms: int, revision: int = 0,
    ) -> None:
        def _upd(m: TaskManifest):
            pshort = phase.value
            if pshort not in m.phases:
                m.phases[pshort] = PhaseEntry()
            pe = m.phases[pshort]
            pe.steps[step_id] = StepSummary(
                tool=tool,
                status="success" if success else "failed",
                artifact=artifact_name,
                error=(error_msg[:200] if error_msg else None),
                duration_ms=duration_ms,
            )
            if artifact_name:
                file_type = "result" if success else "error"
                self._add_file_entry(m, artifact_name, file_type, pshort, step_id)
            if not success and error_msg:
                err_entry = {
                    "step_id": step_id, "tool": tool, "error": error_msg[:200],
                    "revision": revision, "artifact": artifact_name,
                }
                pe.errors.append(err_entry)
                m.total_errors += 1
            m.current_revision = max(m.current_revision, revision)
            m.total_revisions = max(m.total_revisions, revision)

        self._update_manifest(task_id, _upd)
        await self.update_tasks_index(task_id)

    async def record_revision(self, task_id: str, phase: TaskPhase, revision: int) -> None:
        def _upd(m: TaskManifest):
            pshort = phase.value
            if pshort not in m.phases:
                m.phases[pshort] = PhaseEntry()
            m.phases[pshort].revisions = max(m.phases[pshort].revisions, revision)
            m.current_revision = revision
            m.total_revisions = max(m.total_revisions, revision)

        self._update_manifest(task_id, _upd)

    async def mark_phase_started(self, task_id: str, phase: TaskPhase) -> None:
        def _upd(m: TaskManifest):
            pshort = phase.value
            if pshort not in m.phases:
                m.phases[pshort] = PhaseEntry()
            m.phases[pshort].status = "running"
            if not m.phases[pshort].started_at:
                m.phases[pshort].started_at = _now_iso()
            m.current_phase = pshort

        self._update_manifest(task_id, _upd)
        await self.update_tasks_index(task_id)

    async def mark_phase_completed(self, task_id: str, phase: TaskPhase, verdict: EvaluationVerdict,
                                    score: Optional[float] = None) -> None:
        def _upd(m: TaskManifest):
            pshort = phase.value
            if pshort not in m.phases:
                m.phases[pshort] = PhaseEntry()
            m.phases[pshort].status = verdict.value
            m.phases[pshort].verdict = verdict.value
            m.phases[pshort].ended_at = _now_iso()
            if score is not None:
                m.phases[pshort].score = score

        self._update_manifest(task_id, _upd)
        await self.update_tasks_index(task_id)

    async def mark_task_completed(self, task_id: str, final_status: str) -> None:
        def _upd(m: TaskManifest):
            m.status = final_status
            m.updated_at = _now_iso()

        self._update_manifest(task_id, _upd)
        await self.update_tasks_index(task_id)

    async def rebuild_manifest_if_missing(self, task_id: str) -> Optional[TaskManifest]:
        path = self._get_manifest_path(task_id)
        if path.exists():
            return self.load_manifest(task_id)
        state_path = self._get_task_dir(task_id) / "task_state.json"
        state_data = load_json(state_path)
        if not state_data:
            return None
        m = rebuild_manifest_from_state(self._get_task_dir(task_id), task_id, state_data)
        self._save_json(path, manifest_to_dict(m))
        await self.update_tasks_index(task_id)
        return m

    async def update_tasks_index(self, task_id: Optional[str] = None, *, strict: bool = False) -> None:
        try:
            self._do_update_tasks_index(task_id)
        except Exception as e:
            if strict:
                raise
            logger.warning(f"Failed to update tasks index: {e} (non-critical)")

    def _do_update_tasks_index(self, task_id: Optional[str]) -> None:
        index_path = self._get_index_path()
        existing = load_json(index_path)
        idx = dict_to_index(existing) if existing else None
        if idx is None:
            if existing is not None:
                corrupt = index_path.with_suffix(".json.corrupt")
                try:
                    shutil.copy2(index_path, corrupt)
                    logger.warning(f"Corrupt tasks_index.json backed up to {corrupt}")
                except Exception:
                    pass
            idx = self._rebuild_tasks_index()
            self._save_json(index_path, idx.model_dump(mode="json"))
            return

        if task_id:
            m = self.load_manifest(task_id)
            if m is None:
                idx.tasks = [t for t in idx.tasks if t.task_id != task_id]
            else:
                entry = manifest_to_index_entry(m)
                found = False
                for i, t in enumerate(idx.tasks):
                    if t.task_id == task_id:
                        idx.tasks[i] = entry
                        found = True
                        break
                if not found:
                    idx.tasks.append(entry)
        else:
            idx = self._rebuild_tasks_index()

        idx.updated_at = _now_iso()
        idx.tasks.sort(key=lambda t: t.updated_at or "", reverse=True)
        self._save_json(index_path, idx.model_dump(mode="json"))

    def _rebuild_tasks_index(self) -> TasksIndex:
        tasks = []
        if self.base_dir.exists():
            for child in sorted(self.base_dir.iterdir()):
                if not child.is_dir():
                    continue
                tid = child.name
                try:
                    m = self.load_manifest(tid)
                    if m:
                        tasks.append(manifest_to_index_entry(m))
                except Exception as e:
                    logger.warning(f"Skipping task {tid} during index rebuild: {e}")
        tasks.sort(key=lambda t: t.updated_at or "", reverse=True)
        return TasksIndex(updated_at=_now_iso(), tasks=tasks)

    def _rebuild_tasks_index_without_creating_manifests(self) -> TasksIndex:
        tasks = []
        if self.base_dir.exists():
            for child in sorted(self.base_dir.iterdir()):
                if not child.is_dir():
                    continue
                manifest_path = child / MANIFEST_FILENAME
                if not manifest_path.exists():
                    continue
                try:
                    manifest = load_manifest_strict(manifest_path)
                    if manifest is not None:
                        tasks.append(manifest_to_index_entry(manifest))
                except Exception as e:
                    logger.warning(
                        f"Skipping task {child.name} during rollback index rebuild: {e}"
                    )
        tasks.sort(key=lambda t: t.updated_at or "", reverse=True)
        return TasksIndex(updated_at=_now_iso(), tasks=tasks)

    def list_tasks(self) -> list[dict]:
        idx_path = self._get_index_path()
        data = load_json(idx_path)
        idx = dict_to_index(data) if data else None
        if idx is None:
            idx = self._rebuild_tasks_index()
            try:
                self._save_json(idx_path, idx.model_dump(mode="json"))
            except Exception as e:
                logger.warning(f"Could not save rebuilt index: {e}")
        return [t.model_dump(mode="json") for t in idx.tasks]

    async def save_checkpoint(self, state: TaskState) -> Path:
        task_dir = self._get_task_dir(state.id)
        checkpoint_dir = task_dir / "checkpoints"
        checkpoint_dir.mkdir(exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        checkpoint_path = checkpoint_dir / f"checkpoint_{timestamp}.json"
        latest_path = task_dir / "task_state.json"

        data = self._serialize_model(state)
        data["checkpoint_at"] = timestamp

        self._save_json(checkpoint_path, data)
        self._save_json(latest_path, data)

        state.checkpoint_path = str(latest_path)
        logger.debug(f"Saved checkpoint to {checkpoint_path}")
        return latest_path

    async def load_checkpoint(self, checkpoint_path: str) -> TaskState:
        path = Path(checkpoint_path)
        if not path.is_absolute():
            path = self.base_dir / path
        data = self._load_json(path)
        if not data:
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        state = TaskState(**data)
        logger.info(f"Loaded checkpoint from {checkpoint_path}, phase: {state.current_phase}")
        return state

    async def save_evaluation_result(self, result: EvaluationResult) -> Path:
        task_dir = self._get_task_dir(result.task_state_id)
        eval_dir = task_dir / "evaluations"
        eval_dir.mkdir(exist_ok=True)

        path = eval_dir / f"eval_{result.phase.value}_{result.id}.json"
        self._save_json(path, self._serialize_model(result))
        return path

    def get_latest_checkpoint(self, task_id: str) -> Optional[Path]:
        task_dir = self._get_task_dir(task_id)
        latest = task_dir / "task_state.json"
        return latest if latest.exists() else None

    def list_checkpoints(self, task_id: str) -> list[Path]:
        task_dir = self._get_task_dir(task_id)
        checkpoint_dir = task_dir / "checkpoints"
        if not checkpoint_dir.exists():
            return []
        return sorted(checkpoint_dir.glob("checkpoint_*.json"), reverse=True)

    def trim_checkpoints(self, task_id: str, keep: int = 5) -> list[str]:
        task_dir = self._get_task_dir(task_id)
        checkpoint_dir = task_dir / "checkpoints"
        if not checkpoint_dir.exists():
            return []
        checkpoints = sorted(
            checkpoint_dir.glob("checkpoint_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        old = checkpoints[keep:]
        deleted = []
        for p in old:
            try:
                p.unlink()
                deleted.append(p.name)
            except OSError as e:
                logger.warning(f"Failed to delete old checkpoint {p.name}: {e}")
        if deleted:
            logger.info(f"Trimmed {len(deleted)} old checkpoints for task {task_id}, kept {keep}")
        return deleted

    async def save_completion_record(
        self, task_id: str, phase: TaskPhase, verdict: EvaluationVerdict,
        score: Optional[float] = None, duration_ms: int = 0,
        plan: Optional[ExecutionPlan] = None, started_at: Optional[str] = None,
        revision: int = 0,
    ) -> Optional[Path]:
        try:
            task_dir = self._get_task_dir(task_id)
            if not (task_dir / MANIFEST_FILENAME).exists():
                logger.warning(f"save_completion_record: task {task_id} manifest not found, skipping")
                return None
            steps_total = 0
            steps_succeeded = 0
            steps_failed = 0
            artifacts: list[str] = []
            if plan and hasattr(plan, "steps"):
                steps_total = len(plan.steps)
                for s in plan.steps:
                    if getattr(s, "executed", False) or getattr(s, "success", False):
                        if getattr(s, "success", False):
                            steps_succeeded += 1
                        else:
                            steps_failed += 1
                    if getattr(s, "artifact_id", None):
                        artifacts.append(s.artifact_id)
            m = self.load_manifest(task_id)
            total_errors = m.total_errors if m else 0
            rec = PhaseCompletionRecord(
                task_id=task_id,
                phase=phase.value,
                revision=revision,
                verdict=verdict.value if hasattr(verdict, "value") else str(verdict),
                score=score,
                started_at=started_at,
                duration_ms=duration_ms,
                steps_total=steps_total,
                steps_succeeded=steps_succeeded,
                steps_failed=steps_failed,
                total_errors=total_errors,
                artifacts=artifacts,
            )
            path = write_completion_record(task_dir, rec)

            def _upd(m: TaskManifest):
                pshort = phase.value
                if pshort not in m.phases:
                    m.phases[pshort] = PhaseEntry()
                m.phases[pshort].artifacts.output = path.name
                self._add_file_entry(m, path.name, "completion", pshort)
            self._update_manifest(task_id, _upd)
            return path
        except Exception as e:
            logger.error(f"Failed to save completion record for {task_id}/{phase.value}: {e}", exc_info=True)
            return None

    async def dump_error_context(
        self, task_id: str, phase: TaskPhase, error_type: str,
        error_message: str, exc: Optional[BaseException] = None,
        plan: Optional[ExecutionPlan] = None,
        eval_result: Optional[EvaluationResult] = None,
        research_output: Optional[dict] = None,
        messages: Optional[list] = None,
        failed_step: Optional[str] = None,
        failed_tool: Optional[str] = None,
        revision: int = 0,
        recovery_hint: Optional[str] = None,
    ) -> Optional[Path]:
        try:
            task_dir = self._get_task_dir(task_id)
            if not (task_dir / MANIFEST_FILENAME).exists():
                logger.warning(f"dump_error_context: task {task_id} manifest not found, skipping")
                return None
            ctx = ErrorContext(
                task_id=task_id,
                phase=phase.value,
                revision=revision,
                error_type=error_type,
                error_message=error_message[:1000] if error_message else "",
                traceback=format_traceback(exc),
                failed_step=failed_step,
                failed_tool=failed_tool,
                execution_plan=snapshot_model(plan),
                step_snapshots=build_step_snapshots_from_plan(plan),
                messages_snapshot=snapshot_messages(messages) if messages else [],
                eval_result=snapshot_model(eval_result),
                research_output=snapshot_model(research_output) if research_output else None,
                recovery_hint=recovery_hint,
            )
            path = write_error_context(task_dir, ctx)

            def _upd(m: TaskManifest):
                pshort = phase.value
                if pshort not in m.phases:
                    m.phases[pshort] = PhaseEntry()
                err_entry = {
                    "error_id": ctx.id,
                    "error_type": error_type,
                    "message": error_message[:200] if error_message else "",
                    "file": path.name,
                    "revision": revision,
                    "timestamp": ctx.timestamp,
                }
                m.phases[pshort].errors.append(err_entry)
                m.total_errors += 1
                self._add_file_entry(m, path.name, "error", pshort)
            self._update_manifest(task_id, _upd)
            await self.update_tasks_index(task_id)
            return path
        except Exception as e:
            logger.error(f"Failed to dump error context for {task_id}/{phase.value}: {e}", exc_info=True)
            return None

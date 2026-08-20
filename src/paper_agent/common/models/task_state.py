from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import (
    BaseModelWithId,
    Budget,
    EvaluationVerdict,
    TaskPhase,
    TraceEntry,
)


PAPER_PROCESSING_SUBSTEPS = ("download", "parse", "glossary", "translate", "summary")


class PaperProcessingStepState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "not_started"
    revision_count: int = 0
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


def default_paper_processing_steps() -> dict[str, PaperProcessingStepState]:
    return {name: PaperProcessingStepState() for name in PAPER_PROCESSING_SUBSTEPS}


class StageStatus(BaseModel):
    phase: TaskPhase
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    verdict: Optional[EvaluationVerdict] = None
    revision_count: int = 0
    artifact_ids: list[str] = Field(default_factory=list)
    evaluation_result_ids: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class TaskState(BaseModelWithId):
    research_spec_id: str
    current_phase: TaskPhase = TaskPhase.TASK_INITIALIZATION
    previous_phase: Optional[TaskPhase] = None

    stages: dict[TaskPhase, StageStatus] = Field(default_factory=dict)
    paper_processing_steps: dict[str, PaperProcessingStepState] = Field(
        default_factory=default_paper_processing_steps
    )
    budget: Budget = Field(default_factory=Budget)

    paper_candidate_set_id: Optional[str] = None
    paper_artifact_id: Optional[str] = None
    reproduction_spec_id: Optional[str] = None
    experiment_run_ids: list[str] = Field(default_factory=list)
    evaluation_result_ids: list[str] = Field(default_factory=list)
    final_report_id: Optional[str] = None

    trace: list[TraceEntry] = Field(default_factory=list)
    checkpoint_path: Optional[str] = None

    total_revisions: int = 0
    max_revisions: int = 1
    human_intervention_required: bool = False

    workspace_dir: str = ""
    artifact_dir: str = ""

    metadata: dict[str, Any] = Field(default_factory=dict)
    phase_summaries: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("paper_processing_steps", mode="before")
    @classmethod
    def validate_paper_processing_steps(cls, steps: Any) -> Any:
        if not isinstance(steps, dict):
            raise ValueError("Invalid paper_processing_steps: expected a dict")

        allowed = ", ".join(PAPER_PROCESSING_SUBSTEPS)
        for name, step_data in steps.items():
            if name not in PAPER_PROCESSING_SUBSTEPS:
                raise ValueError(
                    f"Unknown paper processing substep {name!r}; expected one of: {allowed}"
                )
            if isinstance(step_data, PaperProcessingStepState):
                continue
            if not isinstance(step_data, dict):
                raise ValueError(f"Invalid paper processing step {name!r}: expected a dict")
            try:
                PaperProcessingStepState.model_validate(step_data)
            except Exception as exc:
                raise ValueError(f"Invalid paper processing step {name!r}: {exc}") from exc
        return steps

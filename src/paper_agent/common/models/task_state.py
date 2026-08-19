from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .base import (
    BaseModelWithId,
    Budget,
    EvaluationVerdict,
    TaskPhase,
    TraceEntry,
)


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

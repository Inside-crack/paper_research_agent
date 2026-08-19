from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .base import BaseModelWithId, EvaluationVerdict, SeverityLevel, TaskPhase


class EvaluationIssue(BaseModel):
    issue_id: str = Field(default="")
    issue_type: str
    severity: SeverityLevel
    location: str = ""
    description: str
    evidence: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    suggestion: str = ""


class Correction(BaseModel):
    target_issue_id: str
    instruction: str
    scope: str = "local"
    max_attempts: int = 1


class EvaluationResult(BaseModelWithId):
    task_state_id: str
    phase: TaskPhase
    verdict: EvaluationVerdict = EvaluationVerdict.REVISE

    score: float = 0.0
    issues: list[EvaluationIssue] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)

    evidence_summary: str = ""
    deterministic_checks_passed: int = 0
    deterministic_checks_failed: int = 0
    model_evaluation_notes: str = ""

    reviewer_model: str = ""
    review_duration_ms: int = 0
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)

    revision_count: int = 0
    requires_human_intervention: bool = False
    human_intervention_reason: Optional[str] = None

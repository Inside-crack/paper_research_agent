from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .base import BaseModelWithId, ReproductionLevel


class ResultComparison(BaseModel):
    metric_name: str
    paper_value: str
    reproduced_value: str
    difference: str
    difference_percent: Optional[float] = None
    within_tolerance: bool = False
    notes: str = ""


class DifferenceAnalysis(BaseModel):
    category: str
    description: str
    evidence: str = ""
    is_speculative: bool = False
    confidence: float = 0.0


class FinalReport(BaseModelWithId):
    research_spec_id: str
    paper_artifact_id: str
    reproduction_spec_id: str
    experiment_run_ids: list[str] = Field(default_factory=list)

    reproduction_level: ReproductionLevel = ReproductionLevel.NOT_REPRODUCIBLE
    reproduction_success: bool = False

    result_comparisons: list[ResultComparison] = Field(default_factory=list)
    difference_analyses: list[DifferenceAnalysis] = Field(default_factory=list)

    environment_summary: dict[str, str] = Field(default_factory=dict)
    code_version: str = ""
    dataset_used: str = ""

    limitations: list[str] = Field(default_factory=list)
    future_work: list[str] = Field(default_factory=list)
    conclusion: str = ""

    artifact_locations: dict[str, str] = Field(default_factory=dict)
    trace_refs: list[str] = Field(default_factory=list)

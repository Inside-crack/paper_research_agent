from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .base import BaseModelWithId


DEFAULT_COMPARISON_DIMENSIONS = [
    "研究问题",
    "核心方法",
    "训练策略",
    "数据集与评价指标",
    "实验结果",
    "优点与局限",
]


def normalize_arxiv_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().rstrip("/")
    if "/abs/" in normalized:
        normalized = normalized.rsplit("/abs/", 1)[-1]
    if "/pdf/" in normalized:
        normalized = normalized.rsplit("/pdf/", 1)[-1].removesuffix(".pdf")
    if normalized.casefold().startswith("arxiv:"):
        normalized = normalized[6:]
    if "?" in normalized:
        normalized = normalized.split("?", 1)[0]
    if "v" in normalized:
        base, version = normalized.rsplit("v", 1)
        if version.isdigit():
            return base
    return normalized


class PaperReference(BaseModel):
    arxiv_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    local_artifact_path: Optional[str] = None
    local_pdf_path: Optional[str] = None

    @model_validator(mode="after")
    def require_reference(self) -> "PaperReference":
        if not any(
            value
            for value in (
                self.arxiv_id,
                self.url,
                self.title,
                self.local_artifact_path,
                self.local_pdf_path,
            )
        ):
            raise ValueError("paper reference must contain an id, URL, title, or local path")
        return self

    @property
    def identity(self) -> str:
        return normalize_arxiv_id(self.arxiv_id or self.url or "")


class PaperConflict(BaseModel):
    paper_id: str
    field: str
    values: dict[str, str] = Field(default_factory=dict)
    severity: Literal["info", "warning", "blocking"] = "warning"
    resolution: str
    selected_source: Optional[str] = None


class ComparisonSpec(BaseModelWithId):
    user_query: str
    paper_refs: list[PaperReference] = Field(min_length=2, max_length=5)
    comparison_dimensions: list[str] = Field(
        default_factory=lambda: list(DEFAULT_COMPARISON_DIMENSIONS)
    )
    domain: Optional[str] = None
    translation_language: str = "zh-CN"

    @field_validator("comparison_dimensions")
    @classmethod
    def validate_dimensions(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if not cleaned:
            return list(DEFAULT_COMPARISON_DIMENSIONS)
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def reject_duplicate_papers(self) -> "ComparisonSpec":
        identities = [ref.identity for ref in self.paper_refs]
        known = [identity for identity in identities if identity]
        if len(known) != len(set(known)):
            raise ValueError("comparison paper references must be unique")
        return self


class ComparisonPaperFacts(BaseModel):
    paper_id: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    version: Optional[str] = None
    source: str = "unknown"
    reuse_level: str = "none"
    reused_from_task_id: Optional[str] = None
    available_stages: list[str] = Field(default_factory=list)
    artifact_path: Optional[str] = None
    pdf_path: Optional[str] = None
    problem_definition: str = "unknown"
    methodology_summary: str = "unknown"
    training_strategy: str = "unknown"
    datasets_and_metrics: str = "unknown"
    reported_results: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    conflicts: list[PaperConflict] = Field(default_factory=list)


class ComparisonMatrixRow(BaseModel):
    dimension: str
    values: dict[str, str] = Field(default_factory=dict)


class PaperComparisonArtifact(BaseModelWithId):
    comparison_spec_id: str
    papers: list[ComparisonPaperFacts] = Field(min_length=2)
    dimensions: list[str] = Field(default_factory=list)
    comparison_matrix: list[ComparisonMatrixRow] = Field(default_factory=list)
    commonalities: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    conclusion: str = ""
    missing_information: list[str] = Field(default_factory=list)
    conflicts: list[PaperConflict] = Field(default_factory=list)
    exported_artifacts: dict[str, str] = Field(default_factory=dict)

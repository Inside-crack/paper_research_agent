from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from .base import BaseModelWithId, PaperType


class PaperCandidate(BaseModelWithId):
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""

    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    url: str
    pdf_url: Optional[str] = None
    source: str = "arxiv"

    published_date: Optional[str] = None
    version: Optional[str] = None

    paper_type: PaperType = PaperType.UNKNOWN
    relevance_score: float = 0.0
    reproducibility_score: float = 0.0
    recency_score: float = 0.0
    code_available: Optional[bool] = None
    code_url: Optional[str] = None
    code_evidence_sources: list[str] = Field(default_factory=list)
    license: Optional[str] = None
    data_available: Optional[bool] = None
    data_evidence_source: Optional[str] = None
    feasibility_score: float = 0.0

    selection_rationale: str = ""
    citations: Optional[int] = None
    venue: Optional[str] = None

    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_retrieval_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)

        if "code_available" not in normalized and "code_available_hint" in normalized:
            normalized["code_available"] = normalized["code_available_hint"]
        if not normalized.get("code_url") and normalized.get("code_url_hint"):
            normalized["code_url"] = normalized["code_url_hint"]
        if "paper_type" not in normalized and "type" in normalized:
            normalized["paper_type"] = normalized["type"]
        if "published_date" not in normalized and normalized.get("year"):
            normalized["published_date"] = f"{normalized['year']}-01-01"

        return normalized


class PaperCandidateSet(BaseModelWithId):
    research_spec_id: str
    session_id: Optional[str] = None
    query_used: str = ""
    queried_at: datetime = Field(default_factory=datetime.utcnow)
    candidates: list[PaperCandidate] = Field(default_factory=list)
    total_results: int = 0
    deduplication_notes: str = ""
    filtering_criteria: dict[str, str] = Field(default_factory=dict)
    selected_candidate_id: Optional[str] = None
    user_confirmed: bool = False


class PaperRetrievalArtifact(BaseModel):
    """Canonical, validated output of the paper retrieval phase."""

    target_paper: PaperCandidate
    target_paper_verified: bool
    candidates: list[PaperCandidate] = Field(default_factory=list)
    top_recommendations: list[str] = Field(default_factory=list)
    search_queries_used: list[str] = Field(default_factory=list)
    ranking_rationale: str = Field(default="", max_length=1000)
    total_found: int = Field(default=0, ge=0)
    candidate_set_id: str = "paper_candidates"

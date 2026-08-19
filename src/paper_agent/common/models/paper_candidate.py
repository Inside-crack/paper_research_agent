from __future__ import annotations

from typing import Optional

from pydantic import Field

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
    code_available: bool = False
    code_url: Optional[str] = None
    data_available: bool = False
    feasibility_score: float = 0.0

    selection_rationale: str = ""
    citations: Optional[int] = None
    venue: Optional[str] = None

    tags: list[str] = Field(default_factory=list)


class PaperCandidateSet(BaseModelWithId):
    research_spec_id: str
    query_used: str = ""
    candidates: list[PaperCandidate] = Field(default_factory=list)
    total_results: int = 0
    deduplication_notes: str = ""
    filtering_criteria: dict[str, str] = Field(default_factory=dict)
    selected_candidate_id: Optional[str] = None
    user_confirmed: bool = False

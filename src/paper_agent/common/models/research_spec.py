from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .base import BaseModelWithId, Budget


class ResearchSpec(BaseModelWithId):
    user_query: str
    task_type: str = Field(default="topic_research", description="topic_research | paper_analysis | reproduction")

    target_paper_url: Optional[str] = None
    target_paper_arxiv_id: Optional[str] = None

    domain: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    year_range: Optional[tuple[int, int]] = None
    paper_types: list[str] = Field(default_factory=list)

    translation_required: bool = True
    translation_language: str = "zh-CN"

    reproduction_target: Optional[str] = Field(
        default=None,
        description="demo | trend_verification | partial_main_results | full_main | ablation",
    )
    compute_constraints: dict[str, str] = Field(default_factory=dict)
    budget: Budget = Field(default_factory=Budget)

    user_constraints: dict[str, str] = Field(default_factory=dict)
    notes: Optional[str] = None


class PaperRetrievalInput(BaseModel):
    """Structured contract consumed by the paper retrieval phase."""

    target_paper_arxiv_id: Optional[str] = None
    target_paper_url: Optional[str] = None
    related_categories: list[str] = Field(
        default_factory=lambda: ["cs.CV", "cs.AI", "cs.LG"]
    )
    max_related_results: int = Field(default=15, gt=0)

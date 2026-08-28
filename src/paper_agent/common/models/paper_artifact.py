from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .base import BaseModelWithId


class TermEntry(BaseModel):
    source_term: str
    target_term: str
    context: str = ""
    confidence: float = 1.0


class PaperSection(BaseModel):
    section_id: str
    title: str
    level: int
    original_text: str = ""
    translated_text: str = ""
    summary: str = ""
    has_formulas: bool = False
    has_tables: bool = False
    has_figures: bool = False
    references: list[str] = Field(default_factory=list)


class PaperArtifact(BaseModelWithId):
    research_spec_id: str
    candidate_id: str

    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    published_date: Optional[str] = None
    version: Optional[str] = None
    abstract: str = ""

    pdf_path: Optional[str] = None
    pdf_source: str = ""

    sections: list[PaperSection] = Field(default_factory=list)
    glossary: list[TermEntry] = Field(default_factory=list)

    research_questions: list[str] = Field(default_factory=list)
    methodology_summary: str = ""
    contributions: list[str] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    summary_evidence: dict[str, list[str]] = Field(default_factory=dict)

    full_text_original: str = ""
    full_text_translated: str = ""

    parsing_errors: list[str] = Field(default_factory=list)

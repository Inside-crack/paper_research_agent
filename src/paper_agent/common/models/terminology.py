from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TerminologyTranslation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1, max_length=200)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    usage: str = Field(default="", max_length=500)
    is_preferred: bool = False


class TerminologyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_id: str
    source_term: str = Field(min_length=1, max_length=200)
    target_terms: list[TerminologyTranslation] = Field(min_length=1, max_length=10)
    domain: list[str] = Field(default_factory=list, max_length=10)
    context: str = Field(default="", max_length=1000)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    source: Literal["seed_dictionary", "llm", "human", "corpus"] = "llm"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: Literal["pending", "verified", "rejected", "deprecated"] = "pending"
    usage_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _new_id() -> str:
    return uuid4().hex


def _now_utc() -> datetime:
    return datetime.utcnow()


class MemoryType(str, Enum):
    PERSONA = "persona"
    INSTRUCTION = "instruction"
    EPISODIC = "episodic"
    RESEARCH_FACT = "research_fact"
    FAILURE_LESSON = "failure_lesson"


class MemoryScope(str, Enum):
    USER = "user"
    RESEARCH_TOPIC = "research_topic"
    AGENT = "agent"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DELETED = "deleted"


class MemoryCandidateStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class MemorySourceKind(str, Enum):
    USER_MESSAGE = "user_message"
    USER_CONFIRMATION = "user_confirmation"
    TOOL_FACT = "tool_fact"
    TASK_RESULT = "task_result"
    FAILURE_DIAGNOSIS = "failure_diagnosis"
    AGENT_INFERENCE = "agent_inference"


class MemoryDecision(str, Enum):
    STORE = "store"
    SKIP = "skip"
    UPDATE = "update"
    MERGE = "merge"


class MemoryJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class MemoryJob(BaseModel):
    """Durable queue entry for asynchronous candidate consolidation."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    job_id: str = Field(default_factory=_new_id)
    candidate_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    owner_user_id: str = Field(min_length=1)
    status: MemoryJobStatus = MemoryJobStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=20)
    next_attempt_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
    completed_at: Optional[datetime] = None

    @field_validator("candidate_id", "idempotency_key", "owner_user_id")
    @classmethod
    def job_identifiers_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("memory job identifiers must not be blank")
        return value


class MemoryRecallQuery(BaseModel):
    """Bounded and owner-scoped query for long-term memory recall."""

    model_config = ConfigDict(extra="forbid")

    owner_user_id: str = Field(min_length=1)
    text: str = Field(default="", max_length=10000)
    scope: Optional[MemoryScope] = None
    memory_types: list[MemoryType] = Field(default_factory=list)
    topic_key: Optional[str] = None
    limit: int = Field(default=5, ge=1, le=100)
    max_chars: int = Field(default=6000, ge=100, le=50000)
    max_memory_chars: int = Field(default=1200, ge=100, le=10000)

    @field_validator("owner_user_id", "topic_key", mode="before")
    @classmethod
    def recall_identifiers_must_not_be_blank(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("memory recall identifiers must not be blank")
        return value.strip()

    @field_validator("text", mode="before")
    @classmethod
    def normalize_recall_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("memory recall text must be a string")
        return value.strip()


class MemoryRecallItem(BaseModel):
    """Safe, ranked memory representation returned by the recall service."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    memory_id: str
    content: str
    memory_type: MemoryType
    scope: MemoryScope
    confidence: float = Field(ge=0.0, le=1.0)
    priority: int = Field(ge=-1, le=100)
    source_task_id: Optional[str] = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    relevance_score: float = Field(ge=0.0)
    updated_at: datetime


class RecallResult(BaseModel):
    """Non-throwing result contract for memory recall."""

    model_config = ConfigDict(extra="forbid")

    query_text: str = ""
    memories: list[MemoryRecallItem] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0)
    truncated: bool = False
    degraded: bool = False
    error: Optional[str] = None
    elapsed_ms: int = Field(default=0, ge=0)


class ConsolidationResult(BaseModel):
    """Auditable outcome of candidate deduplication and consolidation."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    candidate_id: str
    decision: MemoryDecision
    memory_id: Optional[str] = None
    matched_memory_ids: list[str] = Field(default_factory=list)
    superseded_memory_ids: list[str] = Field(default_factory=list)
    conflict_memory_ids: list[str] = Field(default_factory=list)
    merged: bool = False
    reason: str = ""


class MemoryItem(BaseModel):
    """A durable, cross-task memory item with traceable provenance."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    memory_id: str = Field(default_factory=_new_id)
    idempotency_key: Optional[str] = None
    content: str = Field(min_length=1)
    memory_type: MemoryType
    scope: MemoryScope = MemoryScope.USER
    scope_key: Optional[str] = None
    owner_user_id: str = Field(min_length=1)
    priority: int = Field(default=50, ge=-1, le=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: MemoryStatus = MemoryStatus.ACTIVE

    source_kind: MemorySourceKind
    source_session_id: Optional[str] = None
    source_task_id: Optional[str] = None
    source_message_id: Optional[str] = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    source_timestamps: list[datetime] = Field(default_factory=list)
    extractor_version: Optional[str] = None
    rationale: Optional[str] = None
    supersedes_memory_ids: list[str] = Field(default_factory=list)
    conflict_memory_ids: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
    expires_at: Optional[datetime] = None
    version: int = Field(default=1, ge=1)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("memory content must not be blank")
        return value

    @field_validator("owner_user_id", "scope_key", mode="before")
    @classmethod
    def identifiers_must_not_be_blank(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("memory identifiers must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def require_source_reference(self) -> "MemoryItem":
        if not (
            self.source_session_id
            or self.source_task_id
            or self.source_message_id
            or self.source_artifact_ids
        ):
            raise ValueError("memory must include at least one source reference")
        return self


class MemoryCandidate(BaseModel):
    """A traceable intermediate record before a candidate becomes durable memory."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    candidate_id: str = Field(default_factory=_new_id)
    idempotency_key: str = Field(min_length=1)
    content: str = Field(min_length=1)
    memory_type: MemoryType
    scope: MemoryScope = MemoryScope.USER
    scope_key: Optional[str] = None
    owner_user_id: str = Field(min_length=1)
    source_kind: MemorySourceKind
    source_session_id: Optional[str] = None
    source_task_id: Optional[str] = None
    source_message_id: Optional[str] = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    source_timestamps: list[datetime] = Field(default_factory=list)
    priority: int = Field(default=50, ge=-1, le=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: MemoryCandidateStatus = MemoryCandidateStatus.PENDING
    decision: Optional[MemoryDecision] = None
    memory_id: Optional[str] = None
    conflict_memory_ids: list[str] = Field(default_factory=list)
    rejection_reason: Optional[str] = None
    extractor_version: Optional[str] = None
    rationale: Optional[str] = None
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("memory candidate content must not be blank")
        return value

    @field_validator("idempotency_key", "owner_user_id", "scope_key", mode="before")
    @classmethod
    def identifiers_must_not_be_blank(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("memory candidate identifiers must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def require_source_reference(self) -> "MemoryCandidate":
        if not (
            self.source_session_id
            or self.source_task_id
            or self.source_message_id
            or self.source_artifact_ids
        ):
            raise ValueError("memory candidate must include at least one source reference")
        return self

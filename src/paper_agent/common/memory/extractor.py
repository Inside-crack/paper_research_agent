from __future__ import annotations

import hashlib
import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.memory import (
    MemoryCandidate,
    MemoryScope,
    MemorySourceKind,
    MemoryType,
)

_EXTRACTOR_VERSION = "f03-deterministic-v1"
_MAX_CANDIDATE_LENGTH = 2000
_ONE_TIME_MARKERS = (
    "这次",
    "本次",
    "今天",
    "现在",
    "this time",
    "today",
    "for this task",
)


class MemoryExtractionRequest(BaseModel):
    """Structured, explicit input to the conservative memory extractor."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=_MAX_CANDIDATE_LENGTH)
    owner_user_id: str = Field(min_length=1)
    memory_type: MemoryType
    source_kind: MemorySourceKind
    scope: MemoryScope = MemoryScope.USER
    scope_key: Optional[str] = None
    source_session_id: Optional[str] = None
    source_task_id: Optional[str] = None
    source_message_id: Optional[str] = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    confirmed: bool = False
    validated: bool = False
    reusable: bool = False
    stable: bool = False
    idempotency_key: Optional[str] = None
    priority: int = Field(default=50, ge=-1, le=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: Optional[str] = None

    @field_validator("content", "owner_user_id", "scope_key", mode="before")
    @classmethod
    def strip_and_reject_blank(cls, value: object) -> object:
        if value is None:
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("memory extraction fields must not be blank")
        return value.strip()


class MemoryExtractor:
    """Build traceable candidates only from explicitly eligible inputs.

    This class deliberately does not infer durable memories from arbitrary
    prose. A future LLM extractor may populate MemoryExtractionRequest, but
    the eligibility and provenance checks remain deterministic here.
    """

    version = _EXTRACTOR_VERSION

    def extract(self, request: MemoryExtractionRequest) -> Optional[MemoryCandidate]:
        if not isinstance(request, MemoryExtractionRequest):
            raise TypeError("request must be a MemoryExtractionRequest")
        if not self._is_eligible(request):
            return None

        return MemoryCandidate(
            idempotency_key=request.idempotency_key or self._idempotency_key(request),
            content=request.content,
            memory_type=request.memory_type,
            scope=request.scope,
            scope_key=request.scope_key,
            owner_user_id=request.owner_user_id,
            source_kind=request.source_kind,
            source_session_id=request.source_session_id,
            source_task_id=request.source_task_id,
            source_message_id=request.source_message_id,
            source_artifact_ids=request.source_artifact_ids,
            priority=request.priority,
            confidence=request.confidence,
            extractor_version=self.version,
            rationale=request.rationale,
        )

    def from_user_message(
        self,
        *,
        content: str,
        owner_user_id: str,
        session_id: str,
        message_id: str,
        memory_type: MemoryType = MemoryType.INSTRUCTION,
        stable: bool = False,
        rationale: Optional[str] = None,
    ) -> Optional[MemoryCandidate]:
        return self.extract(
            MemoryExtractionRequest(
                content=content,
                owner_user_id=owner_user_id,
                memory_type=memory_type,
                source_kind=MemorySourceKind.USER_MESSAGE,
                source_session_id=session_id,
                source_message_id=message_id,
                stable=stable,
                rationale=rationale,
            )
        )

    def from_confirmation(
        self,
        *,
        content: str,
        owner_user_id: str,
        session_id: str,
        task_id: str,
        message_id: Optional[str] = None,
        memory_type: MemoryType = MemoryType.RESEARCH_FACT,
        rationale: Optional[str] = None,
    ) -> Optional[MemoryCandidate]:
        return self.extract(
            MemoryExtractionRequest(
                content=content,
                owner_user_id=owner_user_id,
                memory_type=memory_type,
                source_kind=MemorySourceKind.USER_CONFIRMATION,
                source_session_id=session_id,
                source_task_id=task_id,
                source_message_id=message_id,
                confirmed=True,
                stable=True,
                rationale=rationale,
            )
        )

    def from_validated_task_result(
        self,
        *,
        content: str,
        owner_user_id: str,
        task_id: str,
        artifact_ids: list[str],
        memory_type: MemoryType = MemoryType.RESEARCH_FACT,
        rationale: Optional[str] = None,
    ) -> Optional[MemoryCandidate]:
        return self.extract(
            MemoryExtractionRequest(
                content=content,
                owner_user_id=owner_user_id,
                memory_type=memory_type,
                source_kind=MemorySourceKind.TASK_RESULT,
                source_task_id=task_id,
                source_artifact_ids=artifact_ids,
                validated=True,
                stable=True,
                rationale=rationale,
            )
        )

    def from_failure_diagnosis(
        self,
        *,
        content: str,
        owner_user_id: str,
        task_id: str,
        artifact_ids: list[str],
        rationale: Optional[str] = None,
    ) -> Optional[MemoryCandidate]:
        return self.extract(
            MemoryExtractionRequest(
                content=content,
                owner_user_id=owner_user_id,
                memory_type=MemoryType.FAILURE_LESSON,
                source_kind=MemorySourceKind.FAILURE_DIAGNOSIS,
                source_task_id=task_id,
                source_artifact_ids=artifact_ids,
                validated=True,
                reusable=True,
                stable=True,
                rationale=rationale,
            )
        )

    @classmethod
    def _is_eligible(cls, request: MemoryExtractionRequest) -> bool:
        if request.source_kind == MemorySourceKind.AGENT_INFERENCE and not request.confirmed:
            return False
        if not request.stable or cls._looks_one_time(request.content):
            return False
        if request.source_kind == MemorySourceKind.USER_CONFIRMATION and not request.confirmed:
            return False
        if request.source_kind in {
            MemorySourceKind.TASK_RESULT,
            MemorySourceKind.TOOL_FACT,
            MemorySourceKind.FAILURE_DIAGNOSIS,
        } and not request.validated:
            return False
        if request.source_kind == MemorySourceKind.FAILURE_DIAGNOSIS and not request.reusable:
            return False
        if not cls._has_source_reference(request):
            return False
        return True

    @staticmethod
    def _has_source_reference(request: MemoryExtractionRequest) -> bool:
        return bool(
            request.source_message_id
            or request.source_task_id
            or request.source_artifact_ids
            or request.source_session_id
        )

    @staticmethod
    def _looks_one_time(content: str) -> bool:
        normalized = re.sub(r"\s+", " ", content.strip().lower())
        return any(marker in normalized for marker in _ONE_TIME_MARKERS)

    @staticmethod
    def _idempotency_key(request: MemoryExtractionRequest) -> str:
        source = "|".join(
            [
                request.owner_user_id,
                request.source_kind.value,
                request.source_session_id or "",
                request.source_task_id or "",
                request.source_message_id or "",
                ",".join(sorted(request.source_artifact_ids)),
                request.content,
            ]
        )
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return f"{_EXTRACTOR_VERSION}:{digest}"

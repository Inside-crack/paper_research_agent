from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class AgentEventType(str, enum.Enum):
    """Stable event names shared by the application, CLI, and future API."""

    INTENT_DETECTED = "intent_detected"
    CANDIDATE_FOUND = "candidate_found"
    WORKFLOW_STARTED = "workflow_started"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    ARTIFACT_CREATED = "artifact_created"
    EVALUATION_COMPLETED = "evaluation_completed"
    TASK_PAUSED = "task_paused"
    TASK_RESUMED = "task_resumed"
    TASK_CANCELLED = "task_cancelled"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    RESPONSE_READY = "response_ready"


class AgentEvent(BaseModel):
    """Serializable, correlated event emitted during an agent interaction."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_type: AgentEventType
    session_id: str
    task_id: Optional[str] = None
    correlation_id: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def validate_payload(
        cls,
        value: dict[str, Any],
        info: ValidationInfo,
    ) -> dict[str, Any]:
        event_type = info.data.get("event_type")
        if event_type is None:
            return value
        from .event_payloads import EVENT_PAYLOAD_MODELS

        payload_model = EVENT_PAYLOAD_MODELS[event_type]
        return payload_model.model_validate(value).model_dump(mode="json")

    @field_validator("session_id", "correlation_id")
    @classmethod
    def validate_correlation_field(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("event correlation fields must not be empty")
        return value

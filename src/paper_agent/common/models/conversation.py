from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ConversationMessageRole = Literal["user", "assistant", "system", "tool"]
ConversationSessionStatus = Literal[
    "active",
    "closed",
    "waiting_user_input",
    "waiting_confirmation",
    "running",
    "paused",
    "cancelled",
    "completed",
    "failed",
]

SESSION_STATUS_TRANSITIONS: dict[
    ConversationSessionStatus,
    frozenset[ConversationSessionStatus],
] = {
    "active": frozenset({"active", "waiting_user_input", "waiting_confirmation", "running", "failed", "closed"}),
    "waiting_user_input": frozenset({"waiting_user_input", "active", "waiting_confirmation", "failed", "closed"}),
    "waiting_confirmation": frozenset({"waiting_confirmation", "active", "running", "failed", "closed"}),
    "running": frozenset({"running", "paused", "cancelled", "completed", "failed"}),
    "paused": frozenset({"paused", "running", "cancelled", "completed", "failed", "closed"}),
    "cancelled": frozenset({"cancelled"}),
    "completed": frozenset({"completed"}),
    "failed": frozenset({"failed", "active"}),
    "closed": frozenset({"closed"}),
}


def _new_id() -> str:
    return uuid.uuid4().hex


def _now_utc() -> datetime:
    return datetime.utcnow()


class ConversationMessage(BaseModel):
    """A persisted message belonging to one conversation session."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    message_id: str = Field(default_factory=_new_id, alias="id")
    session_id: str = ""
    role: ConversationMessageRole = "user"
    content: str = ""
    created_at: datetime = Field(default_factory=_now_utc)
    task_id: Optional[str] = None
    artifact_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def id(self) -> str:
        """Compatibility accessor matching the project's other ID models."""
        return self.message_id


class PendingAction(BaseModel):
    """A persisted action waiting for explicit user confirmation."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(default_factory=_new_id)
    capability_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    selected_paper: Optional[dict[str, Any]] = None
    confirmation_token: str = Field(default_factory=_new_id)
    created_at: datetime = Field(default_factory=_now_utc)


class ConversationContext(BaseModel):
    """Recoverable context used to resume a conversation."""

    model_config = ConfigDict(extra="forbid")

    current_intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    candidate_papers: list[dict[str, Any]] = Field(default_factory=list)
    candidate_set_id: Optional[str] = None
    candidate_queried_at: Optional[datetime] = None
    selected_paper: Optional[dict[str, Any]] = None
    selected_sections: list[str] = Field(default_factory=list)
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    active_task_id: Optional[str] = None
    pending_action: Optional[PendingAction] = None
    last_confirmation_token: Optional[str] = None
    last_confirmed_task_id: Optional[str] = None
    summary: Optional[str] = None


class ConversationSession(BaseModel):
    """Conversation metadata and the context needed for recovery."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    session_id: str = Field(default_factory=_new_id, alias="id")
    status: ConversationSessionStatus = "active"
    user_id: Optional[str] = None
    active_task_id: Optional[str] = None
    context: ConversationContext = Field(default_factory=ConversationContext)
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
    message_count: int = Field(default=0, ge=0)

    @property
    def id(self) -> str:
        """Compatibility accessor matching the project's other ID models."""
        return self.session_id

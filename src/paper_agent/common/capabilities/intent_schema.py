from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
)


IntentExecutionKind = Literal["tool", "workflow"]
IntentSource = Literal["deterministic", "llm", "fallback"]
ContextReferenceType = Literal[
    "candidate_index",
    "selected_paper",
    "artifact_ref",
    "selected_section",
    "task_id",
]


class ContextReference(BaseModel):
    """A typed reference into validated conversation context."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    type: ContextReferenceType
    value: Union[StrictStr, StrictInt]

    @model_validator(mode="after")
    def validate_value(self) -> "ContextReference":
        if isinstance(self.value, str) and not self.value.strip():
            raise ValueError("context reference value must not be empty")
        if isinstance(self.value, bool):
            raise ValueError("context reference value must not be boolean")
        return self


class IntentDecision(BaseModel):
    """唯一的、可序列化的意图路由决策契约."""

    model_config = ConfigDict(extra="forbid")

    matched: bool
    intent: Optional[str] = None
    capability_name: Optional[str] = None
    execution_kind: IntentExecutionKind = "tool"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    arguments: dict[str, Any] = Field(default_factory=dict)
    references: list[ContextReference] = Field(default_factory=list)
    missing_arguments: list[str] = Field(default_factory=list)
    clarification_question: Optional[str] = None
    reason: Optional[str] = None
    source: IntentSource = "deterministic"

    @model_validator(mode="after")
    def validate_decision_state(self) -> "IntentDecision":
        if self.matched and not self.intent:
            raise ValueError("matched decision requires intent")
        if self.matched and not self.capability_name:
            raise ValueError("matched decision requires capability_name")
        if self.matched and self.missing_arguments:
            raise ValueError(
                "matched decision cannot contain missing_arguments"
            )
        return self

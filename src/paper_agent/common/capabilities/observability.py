from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .intent_schema import IntentDecision


class RoutingDecisionEvent(BaseModel):
    """Structured, non-sensitive event for one routing decision."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    source: str
    matched: bool
    intent: Optional[str] = None
    capability_name: Optional[str] = None
    execution_kind: str = "tool"
    confidence: float = 0.0
    reason: Optional[str] = None
    missing_arguments: list[str] = Field(default_factory=list)
    validation_result: str = "not_executed"
    needs_clarification: bool = False
    duration_ms: int = 0

    @classmethod
    def from_decision(
        cls,
        decision: IntentDecision,
        *,
        session_id: Optional[str] = None,
        message_id: Optional[str] = None,
        validation_result: str = "not_executed",
        duration_ms: int = 0,
    ) -> "RoutingDecisionEvent":
        return cls(
            source=decision.source,
            session_id=session_id,
            message_id=message_id,
            matched=decision.matched,
            intent=decision.intent,
            capability_name=decision.capability_name,
            execution_kind=decision.execution_kind,
            confidence=decision.confidence,
            reason=decision.reason,
            missing_arguments=list(decision.missing_arguments),
            validation_result=validation_result,
            needs_clarification=not decision.matched,
            duration_ms=max(0, duration_ms),
        )


class RoutingObserver(Protocol):
    def record(self, event: RoutingDecisionEvent) -> None:
        ...


class InMemoryRoutingObserver:
    """Small observer for tests, local diagnostics, and evaluation reports."""

    def __init__(self):
        self.events: list[RoutingDecisionEvent] = []

    def record(self, event: RoutingDecisionEvent) -> None:
        if not isinstance(event, RoutingDecisionEvent):
            raise TypeError("event must be a RoutingDecisionEvent")
        self.events.append(event)

    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.events),
            "matched": sum(event.matched for event in self.events),
            "clarifications": sum(
                event.needs_clarification for event in self.events
            ),
            "deterministic": sum(
                event.source == "deterministic" for event in self.events
            ),
            "llm": sum(event.source == "llm" for event in self.events),
            "fallback": sum(event.source == "fallback" for event in self.events),
        }


class RoutingObserverFailure(Exception):
    """Reserved for observer implementations that cannot persist an event."""

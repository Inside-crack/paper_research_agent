from __future__ import annotations

import json
import os
from pathlib import Path
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
    task_id: Optional[str] = None
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
        task_id: Optional[str] = None,
        message_id: Optional[str] = None,
        validation_result: str = "not_executed",
        duration_ms: int = 0,
    ) -> "RoutingDecisionEvent":
        return cls(
            source=decision.source,
            session_id=session_id,
            task_id=task_id,
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


class PersistentRoutingObserver:
    """Append-only, reloadable JSONL observer for sanitized routing events."""

    def __init__(self, base_dir: Path):
        self.routing_dir = Path(base_dir) / "routing"
        self.events_path = self.routing_dir / "decisions.jsonl"
        if self.routing_dir.is_symlink() or self.events_path.is_symlink():
            raise ValueError("Routing persistence paths must not be symlinks")
        self.routing_dir.mkdir(parents=True, exist_ok=True)

    def record(self, event: RoutingDecisionEvent) -> None:
        if not isinstance(event, RoutingDecisionEvent):
            raise TypeError("event must be a RoutingDecisionEvent")
        self.routing_dir.mkdir(parents=True, exist_ok=True)
        if self.events_path.is_symlink():
            raise ValueError("Routing event file must not be a symlink")
        payload = event.model_dump(mode="json")
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
            file.flush()
            os.fsync(file.fileno())

    def list_events(self) -> list[RoutingDecisionEvent]:
        if not self.events_path.exists():
            return []
        if self.events_path.is_symlink():
            raise ValueError("Routing event file must not be a symlink")
        events: list[RoutingDecisionEvent] = []
        try:
            with self.events_path.open("r", encoding="utf-8") as file:
                for line_number, line in enumerate(file, start=1):
                    if not line.strip():
                        continue
                    try:
                        events.append(
                            RoutingDecisionEvent.model_validate(json.loads(line))
                        )
                    except (json.JSONDecodeError, ValueError) as exc:
                        raise ValueError(
                            f"Corrupt routing event at {self.events_path}:{line_number}"
                        ) from exc
        except OSError as exc:
            raise OSError(f"Failed to read routing events: {self.events_path}") from exc
        return events

    def summary(self) -> dict[str, int]:
        events = self.list_events()
        return {
            "total": len(events),
            "matched": sum(event.matched for event in events),
            "clarifications": sum(event.needs_clarification for event in events),
            "deterministic": sum(event.source == "deterministic" for event in events),
            "llm": sum(event.source == "llm" for event in events),
            "fallback": sum(event.source == "fallback" for event in events),
        }


class RoutingObserverFailure(Exception):
    """Reserved for observer implementations that cannot persist an event."""

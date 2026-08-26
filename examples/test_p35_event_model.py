"""P35-1 AgentEvent model tests."""

from __future__ import annotations

import json
import sys
from datetime import timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models import AgentEvent, AgentEventType  # noqa: E402


def test_agent_event_round_trips_to_shared_json_shape():
    event = AgentEvent(
        event_type=AgentEventType.STEP_COMPLETED,
        session_id="session-35",
        task_id="task-35",
        correlation_id="request-35",
        payload={
            "phase": "paper_parsing",
            "step_id": "parse",
            "success": True,
            "artifact_refs": ["papers/paper.json"],
        },
    )

    serialized = event.model_dump(mode="json")
    assert serialized["event_type"] == "step_completed"
    assert serialized["session_id"] == "session-35"
    assert serialized["task_id"] == "task-35"
    assert serialized["correlation_id"] == "request-35"
    assert serialized["payload"]["artifact_refs"] == ["papers/paper.json"]
    assert event.timestamp.tzinfo == timezone.utc

    restored = AgentEvent.model_validate_json(json.dumps(serialized))
    assert restored == event


def test_agent_event_rejects_missing_correlation_and_unknown_fields():
    with pytest.raises(ValueError, match="event correlation fields"):
        AgentEvent(
            event_type="task_failed",
                session_id="",
                task_id="task-35",
            correlation_id="request-35",
        )

    with pytest.raises(ValueError):
        AgentEvent(
            event_type="unknown_event",
            session_id="session-35",
            task_id="task-35",
            correlation_id="request-35",
        )

    with pytest.raises(ValueError):
        AgentEvent.model_validate(
            {
                "event_type": "task_failed",
                "session_id": "session-35",
                "task_id": "task-35",
                "correlation_id": "request-35",
                "unexpected": True,
            }
        )


def test_agent_event_validates_payload_by_event_type():
    event = AgentEvent(
        event_type="step_started",
        session_id="session-35",
        task_id="task-35",
        correlation_id="request-35",
        payload={
            "phase": "paper_parsing",
            "step_id": "parse",
            "step_index": 1,
            "total_steps": 5,
        },
    )
    assert event.payload["step_id"] == "parse"

    with pytest.raises(ValueError):
        AgentEvent(
            event_type="step_started",
            session_id="session-35",
            task_id="task-35",
            correlation_id="request-35",
            payload={"phase": "paper_parsing", "step_id": "parse"},
        )

    with pytest.raises(ValueError):
        AgentEvent(
            event_type="artifact_created",
            session_id="session-35",
            task_id="task-35",
            correlation_id="request-35",
            payload={"artifact_refs": []},
        )

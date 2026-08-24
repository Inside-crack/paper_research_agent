import json
from pathlib import Path

import pytest

from paper_agent.common.capabilities import (
    InMemoryRoutingObserver,
    PersistentRoutingObserver,
    RoutingDecisionEvent,
)
from paper_agent.common.capabilities.intent_schema import IntentDecision


def event() -> RoutingDecisionEvent:
    return RoutingDecisionEvent.from_decision(
        IntentDecision(
            matched=True,
            intent="parse_paper",
            capability_name="paper_parse",
            arguments={"artifact_path": "papers/private.json"},
            confidence=0.91,
            source="deterministic",
            reason="explicit parse command",
        ),
        session_id="session-1",
        task_id="task-1",
        message_id="message-1",
        duration_ms=4,
    )


def test_persistent_observer_reloads_sanitized_event(tmp_path: Path):
    observer = PersistentRoutingObserver(tmp_path)
    observer.record(event())

    path = tmp_path / "routing" / "decisions.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["session_id"] == "session-1"
    assert payload["task_id"] == "task-1"
    assert "arguments" not in payload
    assert "private.json" not in path.read_text(encoding="utf-8")

    reloaded = PersistentRoutingObserver(tmp_path)
    events = reloaded.list_events()
    assert len(events) == 1
    assert events[0].capability_name == "paper_parse"
    assert reloaded.summary()["matched"] == 1


def test_persistent_observer_rejects_corrupt_event(tmp_path: Path):
    observer = PersistentRoutingObserver(tmp_path)
    observer.events_path.write_text('{"event_id":"ok"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupt routing event"):
        observer.list_events()


def test_in_memory_observer_remains_non_persistent():
    observer = InMemoryRoutingObserver()
    observer.record(event())
    assert observer.events

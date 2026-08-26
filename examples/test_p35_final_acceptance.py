"""P35-10 final acceptance checks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.events import EventPublisher  # noqa: E402
from paper_agent.common.models import AgentEvent  # noqa: E402
from paper_agent.common.persistence import EventStore  # noqa: E402
from paper_agent.common.response_composer import ResponseComposer  # noqa: E402


def event(event_type: str, *, task_id: str | None = "task-35") -> AgentEvent:
    payload = {}
    if event_type == "step_started":
        payload = {
            "phase": "paper_parsing",
            "step_id": "parse",
            "step_index": 0,
            "total_steps": 1,
        }
    elif event_type == "step_completed":
        payload = {
            "phase": "paper_parsing",
            "step_id": "parse",
            "success": True,
        }
    elif event_type == "artifact_created":
        payload = {"artifact_refs": ["papers/result.json"]}
    elif event_type == "workflow_started":
        payload = {"workflow_name": "paper_processing"}
    elif event_type == "response_ready":
        payload = {"status": "completed", "message": "完成"}
    return AgentEvent(
        event_type=event_type,
        session_id="session-35",
        task_id=task_id,
        correlation_id="request-35",
        payload=payload,
    )


def test_final_event_sequence_is_persisted_and_queryable(tmp_path: Path):
    publisher = EventPublisher(EventStore(tmp_path))
    sequence = [
        event("intent_detected", task_id=None),
        event("workflow_started"),
        event("step_started"),
        event("step_completed"),
        event("artifact_created"),
        event("task_completed"),
    ]
    for item in sequence:
        publisher.publish(item)

    store = EventStore(tmp_path)
    assert [item.event_type.value for item in store.list(session_id="session-35")] == [
        item.event_type.value for item in sequence
    ]
    assert len(store.list(task_id="task-35")) == 5
    assert len(store.list(correlation_id="request-35")) == 6


def test_persistence_failure_blocks_subscriber_notification():
    class FailingStore:
        def append(self, _event):
            raise OSError("disk full")

    received = []

    class Subscriber:
        def on_event(self, item):
            received.append(item)

    publisher = EventPublisher(FailingStore())  # type: ignore[arg-type]
    publisher.subscribe(Subscriber())
    with pytest.raises(OSError, match="disk full"):
        publisher.publish(event("task_completed"))
    assert received == []


def test_composer_covers_terminal_states_without_sensitive_output():
    composer = ResponseComposer()
    expected = {
        "task_paused": "paused",
        "task_cancelled": "cancelled",
        "task_completed": "completed",
        "task_failed": "failed",
    }
    for event_type, status in expected.items():
        item = event(event_type)
        if event_type == "task_failed":
            item = item.model_copy(
                update={"payload": {"reason": "token=secret /private/error.log"}}
            )
        response = composer.compose(item)
        assert response.status == status
        assert "secret" not in response.message
        assert "/private" not in response.message

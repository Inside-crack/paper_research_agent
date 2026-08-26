"""P35-3 EventPublisher tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.events import (  # noqa: E402
    EventPublisher,
    InMemoryEventSubscriber,
)
from paper_agent.common.models import AgentEvent  # noqa: E402
from paper_agent.common.persistence import EventStore  # noqa: E402


def event() -> AgentEvent:
    return AgentEvent(
        event_type="task_completed",
        session_id="session-35",
        task_id="task-35",
        correlation_id="request-35",
    )


def test_publisher_persists_before_notifying_subscribers(tmp_path: Path):
    publisher = EventPublisher(EventStore(tmp_path))
    subscriber = InMemoryEventSubscriber()
    publisher.subscribe(subscriber)

    publisher.publish(event())

    assert subscriber.events[0].event_id
    assert len(EventStore(tmp_path).list(task_id="task-35")) == 1


def test_publisher_does_not_duplicate_subscription_and_can_unsubscribe(
    tmp_path: Path,
):
    publisher = EventPublisher(EventStore(tmp_path))
    subscriber = InMemoryEventSubscriber()
    publisher.subscribe(subscriber)
    publisher.subscribe(subscriber)
    publisher.publish(event())
    assert len(subscriber.events) == 1

    publisher.unsubscribe(subscriber)
    publisher.publish(event())
    assert len(subscriber.events) == 1


def test_failing_subscriber_does_not_hide_persisted_event(tmp_path: Path):
    class FailingSubscriber:
        def on_event(self, _event):
            raise RuntimeError("subscriber unavailable")

    publisher = EventPublisher(EventStore(tmp_path))
    publisher.subscribe(FailingSubscriber())
    publisher.publish(event())

    assert len(EventStore(tmp_path).list(task_id="task-35")) == 1


def test_publisher_rejects_invalid_subscriber_and_event(tmp_path: Path):
    publisher = EventPublisher(EventStore(tmp_path))
    with pytest.raises(TypeError, match="subscriber"):
        publisher.subscribe(object())
    with pytest.raises(TypeError, match="AgentEvent"):
        publisher.publish({"event_type": "task_completed"})  # type: ignore[arg-type]

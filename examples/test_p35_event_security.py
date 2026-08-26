"""P35-9 event security tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.events import EventPublisher  # noqa: E402
from paper_agent.common.models import AgentEvent  # noqa: E402
from paper_agent.common.persistence import EventStore  # noqa: E402


def unsafe_event() -> AgentEvent:
    return AgentEvent(
        event_type="task_failed",
        session_id="session-35",
        task_id="task-35",
        correlation_id="request-35",
        payload={
            "reason": (
                "api_key=top-secret bearer hidden-token "
                "/Users/bytedance/workspace/private/error.log"
            ),
        },
    )


def test_event_store_persists_only_sanitized_payload(tmp_path: Path):
    store = EventStore(tmp_path)
    store.append(unsafe_event())
    line = (tmp_path / "task-35" / "logs" / "events.jsonl").read_text()
    persisted = json.loads(line)
    payload = persisted["payload"]
    assert "top-secret" not in line
    assert "hidden-token" not in line
    assert "/Users/bytedance" not in line
    assert payload["reason"].count("[REDACTED]") == 2


def test_publisher_sends_sanitized_event_to_subscriber(tmp_path: Path):
    received: list[AgentEvent] = []

    class Subscriber:
        def on_event(self, event: AgentEvent) -> None:
            received.append(event)

    publisher = EventPublisher(EventStore(tmp_path))
    publisher.subscribe(Subscriber())
    publisher.publish(unsafe_event())

    assert len(received) == 1
    serialized = json.dumps(received[0].model_dump(mode="json"))
    assert "top-secret" not in serialized
    assert "private research prompt" not in serialized
    assert "[PATH]" in serialized

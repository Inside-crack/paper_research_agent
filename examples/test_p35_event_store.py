"""P35-4 EventStore persistence tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models import AgentEvent  # noqa: E402
from paper_agent.common.persistence import EventStore  # noqa: E402


def make_event(
    *,
    task_id: str = "task-35",
    session_id: str = "session-35",
    correlation_id: str = "request-35",
    event_type: str = "task_completed",
) -> AgentEvent:
    return AgentEvent(
        event_type=event_type,
        session_id=session_id,
        task_id=task_id,
        correlation_id=correlation_id,
        payload={},
    )


def test_event_store_appends_and_filters_correlated_events(tmp_path: Path):
    store = EventStore(tmp_path)
    store.append(make_event(event_type="task_completed"))
    store.append(make_event(event_type="task_completed", correlation_id="request-36"))
    store.append(make_event(task_id="task-other", session_id="session-other"))

    assert len(store.list(task_id="task-35")) == 2
    assert len(store.list(session_id="session-35")) == 2
    assert len(store.list(correlation_id="request-36")) == 1
    assert store.list(task_id="task-35")[1].event_type.value == "task_completed"

    events_path = tmp_path / "task-35" / "logs" / "events.jsonl"
    payload = json.loads(events_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["task_id"] == "task-35"
    assert payload["correlation_id"] == "request-35"


def test_event_store_rejects_corrupt_or_mismatched_events(tmp_path: Path):
    store = EventStore(tmp_path)
    path = tmp_path / "task-35" / "logs" / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupt agent event"):
        store.list(task_id="task-35")

    path.write_text(
        json.dumps(make_event(task_id="different").model_dump(mode="json")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="task_id mismatch"):
        store.list(task_id="task-35")


def test_event_store_validates_filters_and_event_types(tmp_path: Path):
    store = EventStore(tmp_path)
    with pytest.raises(ValueError, match="session_id filter"):
        store.list(session_id="")
    with pytest.raises(TypeError, match="AgentEvent"):
        store.append({"event_type": "task_completed"})  # type: ignore[arg-type]

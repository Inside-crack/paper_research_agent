"""P35-8 ResponseComposer tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models import AgentEvent  # noqa: E402
from paper_agent.common.response_composer import ResponseComposer  # noqa: E402


def make_event(event_type: str, payload=None, task_id="task-35"):
    return AgentEvent(
        event_type=event_type,
        session_id="session-35",
        task_id=task_id,
        correlation_id="request-35",
        payload=payload or {},
    )


def test_composer_maps_progress_and_terminal_events():
    composer = ResponseComposer()
    started = composer.compose(
        make_event(
            "step_started",
            {"phase": "parse", "step_id": "parse", "step_index": 0, "total_steps": 3},
        )
    )
    assert started.status == "progress"
    assert "parse" in started.message
    assert "pause" in started.next_actions

    completed = composer.compose(make_event("task_completed"))
    assert completed.status == "completed"
    assert completed.next_actions == ["view_artifact"]

    paused = composer.compose(make_event("task_paused"))
    assert paused.status == "paused"
    assert paused.next_actions == ["resume", "cancel"]


def test_composer_handles_waiting_and_failure_events():
    composer = ResponseComposer()
    waiting = composer.compose(
        make_event(
            "candidate_found",
            {"candidate_set_id": "set-1", "candidates": [], "total": 2},
            task_id=None,
        )
    )
    assert waiting.status == "waiting_confirmation"
    assert "confirm" in waiting.next_actions

    failed = composer.compose(
        make_event(
            "task_failed",
            {"reason": "api_key=secret-value /Users/bytedance/private/error.log"},
        )
    )
    assert failed.status == "failed"
    assert "secret-value" not in failed.message
    assert "/Users/bytedance" not in failed.message
    assert failed.next_actions == ["retry", "status"]


def test_composer_filters_unsafe_artifact_references():
    response = ResponseComposer().compose(
        make_event(
            "artifact_created",
            {
                "artifact_refs": [
                    "papers/result.json",
                    "/Users/bytedance/workspace/secret.json",
                    "../outside.json",
                    r"C:\private\secret.json",
                ],
                "artifact_type": "result",
            }
        )
    )
    assert response.artifact_refs == ["papers/result.json"]


def test_composer_rejects_unknown_event_and_invalid_input():
    composer = ResponseComposer()
    with pytest.raises(ValueError, match="Unsupported"):
        composer._compose_content("unknown", {})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AgentEvent"):
        composer.compose({"event_type": "task_completed"})  # type: ignore[arg-type]

"""P35-7 realtime subscriber and history query tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.events import CliProgressSubscriber  # noqa: E402
from paper_agent.common.models import AgentEvent  # noqa: E402


def test_cli_progress_subscriber_renders_safe_json_and_filters_session():
    output: list[str] = []
    subscriber = CliProgressSubscriber(session_id="session-35", output=output.append)
    subscriber.on_event(
        AgentEvent(
            event_type="task_failed",
            session_id="session-other",
            task_id="task-35",
            correlation_id="request-35",
            payload={"reason": "api_key=hidden"},
        )
    )
    assert output == []

    subscriber.on_event(
        AgentEvent(
            event_type="task_completed",
            session_id="session-35",
            task_id="task-35",
            correlation_id="request-35",
        )
    )
    assert len(output) == 1
    assert '"type": "progress"' in output[0]
    assert "completed" in output[0]

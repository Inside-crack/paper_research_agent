"""P36 multi-turn conversation and persisted recovery acceptance tests."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from paper_agent.api import create_app  # noqa: E402
from test_p34_conversation_application_service import make_service  # noqa: E402


def test_http_multiturn_search_select_confirm_and_reload():
    with tempfile.TemporaryDirectory() as tmpdir:
        store, session, service = make_service(tmpdir)
        client = TestClient(create_app(service=service, store=store))
        headers = {"X-Principal-ID": "anonymous"}

        created = client.post("/sessions", headers=headers, json={})
        assert created.status_code == 201
        session_id = created.json()["session_id"]

        search = client.post(
            f"/sessions/{session_id}/messages",
            headers=headers,
            json={"content": "检索 agents", "request_id": "turn-1"},
        )
        assert search.json()["status"] == "waiting_confirmation"

        selected = client.post(
            f"/sessions/{session_id}/messages",
            headers=headers,
            json={"content": "2", "request_id": "turn-2"},
        )
        assert selected.json()["status"] == "active"
        assert selected.json()["selected_paper"]["arxiv_id"] == "2401.00002v1"

        pending = client.post(
            f"/sessions/{session_id}/messages",
            headers=headers,
            json={"content": "处理这篇论文", "request_id": "turn-3"},
        )
        token = pending.json()["confirmation_token"]
        assert pending.json()["status"] == "waiting_confirmation"

        started = client.post(
            f"/sessions/{session_id}/actions",
            headers=headers,
            json={
                "action": "confirm",
                "confirmation_token": token,
                "request_id": "turn-4",
            },
        )
        assert started.json()["status"] == "running"
        task_id = started.json()["task_id"]

        reloaded_store = type(store)(store.base_dir)
        reloaded = reloaded_store.load_session(session_id)
        assert reloaded is not None
        assert reloaded.active_task_id == task_id
        assert reloaded.context.selected_paper["arxiv_id"] == "2401.00002v1"
        assert reloaded.message_count >= 6

        status_response = client.get(
            f"/sessions/{session_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        assert status_response.json()["active_task_id"] == task_id


def test_http_control_request_is_idempotent_after_replay():
    with tempfile.TemporaryDirectory() as tmpdir:
        store, session, service = make_service(tmpdir)
        client = TestClient(create_app(service=service, store=store))
        store.bind_task(session.session_id, "task-unknown")
        store.update_status(session.session_id, "running")

        first = client.post(
            f"/sessions/{session.session_id}/actions",
            headers={"X-Principal-ID": "anonymous"},
            json={"action": "cancel", "request_id": "cancel-1"},
        )
        second = client.post(
            f"/sessions/{session.session_id}/actions",
            headers={"X-Principal-ID": "anonymous"},
            json={"action": "cancel", "request_id": "cancel-1"},
        )
        # The fake orchestrator cannot load an artificial checkpoint, so both
        # calls are expected to return the same stable error shape.
        assert first.status_code == second.status_code
        assert first.json() == second.json()

"""P36 Session and Message API tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from paper_agent.api import _sse_event, create_app  # noqa: E402
from paper_agent.common.models.conversation import ConversationMessage  # noqa: E402
from paper_agent.common.persistence import ConversationStore  # noqa: E402


class FakeConversationService:
    def __init__(self, store: ConversationStore):
        self.store = store
        self.calls: list[tuple[str, str]] = []

    async def handle_message(self, session_id: str, content: str):
        self.calls.append((session_id, content))
        self.store.append_message(
            session_id,
            ConversationMessage(
                session_id=session_id,
                role="user",
                content=content,
            ),
        )
        self.store.append_message(
            session_id,
            ConversationMessage(
                session_id=session_id,
                role="assistant",
                content=f"需要补充：{content}",
            ),
        )
        self.store.update_status(session_id, "waiting_user_input")
        return {
            "session_id": session_id,
            "status": "waiting_user_input",
            "reply": f"需要补充：{content}",
        }

    async def refresh_status(self, session_id: str):
        return {"session_id": session_id, "status": self.store.load_session(session_id).status}

    async def pause(self, session_id: str):
        return {"session_id": session_id, "status": "paused"}

    async def resume(self, session_id: str):
        return {"session_id": session_id, "status": "running"}

    async def cancel(self, session_id: str):
        return {"session_id": session_id, "status": "cancelled"}

    async def confirm(self, session_id: str, _token: str):
        return {"session_id": session_id, "status": "running"}


def test_session_message_and_idempotency_flow(tmp_path: Path):
    store = ConversationStore(tmp_path)
    service = FakeConversationService(store)
    client = TestClient(create_app(service=service, store=store))

    created = client.post("/sessions", headers={"X-Principal-ID": "user-1"}, json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    first = client.post(
        f"/sessions/{session_id}/messages",
        headers={"X-Principal-ID": "user-1"},
        json={"content": "找论文", "request_id": "req-1"},
    )
    duplicate = client.post(
        f"/sessions/{session_id}/messages",
        headers={"X-Principal-ID": "user-1"},
        json={"content": "找论文", "request_id": "req-1"},
    )
    assert first.status_code == 200
    assert duplicate.json() == first.json()
    assert len(service.calls) == 1

    reused = client.post(
        f"/sessions/{session_id}/messages",
        headers={"X-Principal-ID": "user-1"},
        json={"content": "另一条消息", "request_id": "req-1"},
    )
    assert reused.status_code == 409
    assert reused.json()["error"] == "request_id_reused"

    session = client.get(
        f"/sessions/{session_id}",
        headers={"X-Principal-ID": "user-1"},
    )
    assert session.status_code == 200
    assert session.json()["message_count"] == 2


def test_session_isolation_hides_other_principal(tmp_path: Path):
    store = ConversationStore(tmp_path)
    service = FakeConversationService(store)
    client = TestClient(create_app(service=service, store=store))
    response = client.post(
        "/sessions",
        headers={"X-Principal-ID": "owner"},
        json={},
    )
    session_id = response.json()["session_id"]

    forbidden = client.get(
        f"/sessions/{session_id}",
        headers={"X-Principal-ID": "other"},
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["detail"] == "session_not_found"


def test_missing_session_returns_stable_error(tmp_path: Path):
    store = ConversationStore(tmp_path)
    service = FakeConversationService(store)
    client = TestClient(create_app(service=service, store=store))
    response = client.post(
        "/sessions/missing/messages",
        headers={"X-Principal-ID": "user-1"},
        json={"content": "hello", "request_id": "req-1"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "session_not_found"


def test_sse_event_uses_p35_json_contract():
    item = {
        "event_id": "evt-1",
        "event_type": "task_completed",
        "session_id": "session-35",
        "task_id": "task-35",
        "correlation_id": "req-35",
        "payload": {},
    }

    class Event:
        event_id = item["event_id"]

        def model_dump(self, mode):
            assert mode == "json"
            return item

    rendered = _sse_event(Event())
    assert rendered.startswith("id: evt-1\n")
    assert "event: agent_event\n" in rendered
    assert '"event_type": "task_completed"' in rendered

"""P36 final SSE and recovery acceptance tests."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from paper_agent.api import create_app  # noqa: E402
from paper_agent.common.models import AgentEvent  # noqa: E402
from test_p34_conversation_application_service import make_service  # noqa: E402


class FakeRequest:
    def __init__(self):
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


def event(event_id: str, event_type: str = "task_completed") -> AgentEvent:
    return AgentEvent(
        event_id=event_id,
        event_type=event_type,
        session_id="session-sse",
        task_id="task-sse",
        correlation_id="request-sse",
        payload={},
    )


def sse_route(app):
    return next(route for route in app.routes if route.path == "/sessions/{session_id}/events")


def test_sse_replays_history_resumes_after_last_event_and_streams_live_event():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store, session, service = make_service(tmpdir)
            session = store.create_session(user_id="anonymous")
            first = event("evt-1")
            second = event("evt-2")
            first = first.model_copy(update={"session_id": session.session_id})
            second = second.model_copy(update={"session_id": session.session_id})
            service.event_publisher.publish(first)
            service.event_publisher.publish(second)
            app = create_app(service=service, store=store)
            route = sse_route(app)

            request = FakeRequest()
            response = await route.endpoint(
                session_id=session.session_id,
                request=request,
                task_id=None,
                last_event_id="evt-1",
                x_principal_id="anonymous",
            )
            stream = response.body_iterator
            replayed = await stream.__anext__()
            assert "id: evt-2" in replayed
            assert "evt-1" not in replayed

            live = event("evt-3").model_copy(update={"session_id": session.session_id})
            service.event_publisher.publish(live)
            rendered = await stream.__anext__()
            assert "id: evt-3" in rendered
            assert "event: agent_event" in rendered

            request.disconnected = True
            try:
                await stream.__anext__()
            except StopAsyncIteration:
                pass
            else:
                raise AssertionError("SSE stream did not close after disconnect")
            assert len(service.event_publisher._subscribers) == 0

    asyncio.run(scenario())


def test_sse_rejects_cross_session_subscription():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store, _session, service = make_service(tmpdir)
            other = store.create_session(user_id="other")
            app = create_app(service=service, store=store)
            route = sse_route(app)
            request = FakeRequest()
            try:
                await route.endpoint(
                    session_id=other.session_id,
                    request=request,
                    task_id=None,
                    last_event_id=None,
                    x_principal_id="anonymous",
                )
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 404
            else:
                raise AssertionError("cross-principal SSE subscription was accepted")

    asyncio.run(scenario())

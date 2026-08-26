from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .common.capabilities import (
    CapabilityCatalog,
    CapabilityRegistry,
    LLMIntentDecisionRouter,
    LLMIntentRouterProvider,
    register_default_capabilities,
)
from .common.config import get_settings
from .common.conversation_application_service import ConversationApplicationService
from .common.llm import create_llm
from .common.models.conversation import ConversationSession
from .common.persistence import (
    ConversationStore,
    RequestIdempotencyStore,
)
from .common.task_recovery import TaskRecoveryManager
from .tools import get_default_registry


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=256)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    request_id: str = Field(min_length=1, max_length=256)
    confirmation_token: Optional[str] = None


def _default_service(store: ConversationStore) -> ConversationApplicationService:
    registry = CapabilityRegistry()
    register_default_capabilities(registry, get_default_registry())
    router = LLMIntentDecisionRouter(
        LLMIntentRouterProvider(create_llm()),
        CapabilityCatalog.from_registry(registry),
    )
    return ConversationApplicationService(store, registry, llm_router=router)


def create_app(
    *,
    service: Optional[ConversationApplicationService] = None,
    store: Optional[ConversationStore] = None,
    idempotency_store: Optional[RequestIdempotencyStore] = None,
    title: str = "Paper Research Agent API",
) -> FastAPI:
    """Create the HTTP gateway with injectable application dependencies."""

    if service is None:
        settings = get_settings()
        store = store or ConversationStore(settings.artifact_dir)
        service = _default_service(store)
    else:
        store = store or service.store
    idempotency = idempotency_store or RequestIdempotencyStore(store.base_dir)
    request_locks: dict[tuple[str, str], asyncio.Lock] = {}
    app = FastAPI(title=title, version="0.1.0")
    app.state.conversation_service = service
    app.state.conversation_store = store

    def on_recovery_started(task_state, execution):
        service._task_states[task_state.id] = task_state
        service._running_tasks[task_state.id] = execution

    def on_recovery_finished(task_state, execution):
        if task_state.session_id:
            service._on_task_done(task_state.session_id, task_state, execution)

    recovery = None
    if hasattr(service, "orchestrator"):
        recovery = TaskRecoveryManager(
            persistence=service.orchestrator.persistence,
            conversations=store,
            orchestrator=service.orchestrator,
            on_started=on_recovery_started,
            on_finished=on_recovery_finished,
        )
    app.state.task_recovery = recovery

    async def recover_persisted_tasks():
        if recovery is not None:
            await recovery.recover_once()
    app.add_event_handler("startup", recover_persisted_tasks)

    def principal_from_header(value: Optional[str]) -> str:
        return value.strip() if value and value.strip() else "anonymous"

    def require_owned_session(
        session_id: str,
        principal_id: str,
    ) -> ConversationSession:
        session = store.load_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session_not_found")
        if session.user_id not in (None, principal_id):
            raise HTTPException(status_code=404, detail="session_not_found")
        return session

    def get_lock(session_id: str, request_id: str) -> asyncio.Lock:
        key = (session_id, request_id)
        return request_locks.setdefault(key, asyncio.Lock())

    def error_response(
        error_code: str,
        message: str,
        *,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {"error": error_code, "message": message}
        if request_id:
            response["request_id"] = request_id
        if correlation_id:
            response["correlation_id"] = correlation_id
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError):
        return _json_error(error_response("invalid_request", str(exc)), 400)

    @app.post("/sessions", status_code=status.HTTP_201_CREATED)
    async def create_session(
        _body: CreateSessionRequest,
        x_principal_id: Optional[str] = Header(default=None),
    ):
        principal_id = principal_from_header(x_principal_id)
        session = store.create_session(user_id=principal_id)
        return _session_response(session)

    @app.get("/sessions/{session_id}")
    async def get_session(
        session_id: str,
        x_principal_id: Optional[str] = Header(default=None),
    ):
        session = require_owned_session(
            session_id,
            principal_from_header(x_principal_id),
        )
        return _session_response(session, messages=store.list_messages(session_id))

    @app.post("/sessions/{session_id}/messages")
    async def post_message(
        session_id: str,
        body: MessageRequest,
        x_principal_id: Optional[str] = Header(default=None),
    ):
        principal_id = principal_from_header(x_principal_id)
        require_owned_session(session_id, principal_id)
        fingerprint = idempotency.fingerprint(body.content)
        async with get_lock(session_id, body.request_id):
            previous = idempotency.get(session_id, body.request_id)
            if previous is not None:
                if previous["fingerprint"] != fingerprint:
                    return _json_error(
                        error_response(
                            "request_id_reused",
                            "request_id 已用于其他请求。",
                            request_id=body.request_id,
                        ),
                        409,
                    )
                return _replay_response(previous)
            try:
                response = await service.handle_message(session_id, body.content)
            except FileNotFoundError:
                response = error_response(
                    "session_not_found",
                    "Conversation session not found.",
                    request_id=body.request_id,
                )
                idempotency.save(
                    session_id,
                    body.request_id,
                    fingerprint=fingerprint,
                    response=response,
                    http_status=404,
                )
                return _json_error(response, 404)
            except ValueError as exc:
                response = error_response(
                    "invalid_state_transition",
                    str(exc),
                    request_id=body.request_id,
                )
                idempotency.save(
                    session_id,
                    body.request_id,
                    fingerprint=fingerprint,
                    response=response,
                    http_status=409,
                )
                return _json_error(response, 409)
            idempotency.save(
                session_id,
                body.request_id,
                fingerprint=fingerprint,
                response=response,
            )
            return response

    @app.post("/sessions/{session_id}/actions")
    async def post_action(
        session_id: str,
        body: ActionRequest,
        x_principal_id: Optional[str] = Header(default=None),
    ):
        require_owned_session(session_id, principal_from_header(x_principal_id))
        if body.action not in {"confirm", "pause", "resume", "cancel", "status"}:
            return _json_error(
                error_response("invalid_action", "不支持的会话操作。", request_id=body.request_id),
                400,
            )
        content = body.action
        if body.action == "confirm":
            if not body.confirmation_token:
                return _json_error(
                    error_response("invalid_request", "confirmation_token is required.", request_id=body.request_id),
                    400,
                )
            content = body.confirmation_token
        fingerprint = idempotency.fingerprint(f"{body.action}:{content}")
        async with get_lock(session_id, body.request_id):
            previous = idempotency.get(session_id, body.request_id)
            if previous is not None:
                if previous["fingerprint"] != fingerprint:
                    return _json_error(
                        error_response("request_id_reused", "request_id 已用于其他请求。", request_id=body.request_id),
                        409,
                    )
                return _replay_response(previous)
            try:
                if body.action == "confirm":
                    response = await service.confirm(session_id, content)
                elif body.action == "status":
                    response = await service.refresh_status(session_id)
                else:
                    response = await getattr(service, body.action)(session_id)
            except FileNotFoundError:
                response = error_response(
                    "session_not_found",
                    "Conversation session not found.",
                    request_id=body.request_id,
                )
                idempotency.save(
                    session_id,
                    body.request_id,
                    fingerprint=fingerprint,
                    response=response,
                    http_status=404,
                )
                return _json_error(response, 404)
            except ValueError as exc:
                response = error_response(
                    "invalid_state_transition",
                    str(exc),
                    request_id=body.request_id,
                )
                idempotency.save(
                    session_id,
                    body.request_id,
                    fingerprint=fingerprint,
                    response=response,
                    http_status=409,
                )
                return _json_error(response, 409)
            idempotency.save(session_id, body.request_id, fingerprint=fingerprint, response=response)
            return response

    @app.get("/sessions/{session_id}/events")
    async def session_events(
        session_id: str,
        request: Request,
        task_id: Optional[str] = None,
        last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
        x_principal_id: Optional[str] = Header(default=None),
    ):
        require_owned_session(session_id, principal_from_header(x_principal_id))
        if task_id is not None:
            events = service.list_events(session_id, task_id=task_id)
        else:
            events = service.list_events(session_id)
        publisher = service.event_publisher
        queue: asyncio.Queue[Any] = asyncio.Queue()
        start_index = 0
        if last_event_id:
            for index, item in enumerate(events):
                if item.event_id == last_event_id:
                    start_index = index + 1
                    break

        class Subscriber:
            def on_event(self, event):
                if event.session_id != session_id:
                    return
                if task_id is not None and event.task_id != task_id:
                    return
                queue.put_nowait(event)

        subscriber = Subscriber()

        async def stream() -> AsyncIterator[str]:
            publisher.subscribe(subscriber)
            try:
                for item in events[start_index:]:
                    yield _sse_event(item)
                while not await request.is_disconnected():
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    yield _sse_event(item)
            finally:
                publisher.unsubscribe(subscriber)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _session_response(
    session: ConversationSession,
    *,
    messages: Optional[list[Any]] = None,
) -> dict[str, Any]:
    response = session.model_dump(mode="json")
    response["candidate_set_id"] = session.context.candidate_set_id
    response["queried_at"] = (
        session.context.candidate_queried_at.isoformat()
        if session.context.candidate_queried_at
        else None
    )
    if messages is not None:
        response["messages"] = [message.model_dump(mode="json") for message in messages]
    return response


def _json_error(payload: dict[str, Any], status_code: int):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content=payload)


def _replay_response(record: dict[str, Any]):
    status_code = int(record.get("http_status", 200))
    if status_code == 200:
        return record["response"]
    return _json_error(record["response"], status_code)


def _sse_event(event: Any) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
    )
    return f"id: {event.event_id}\nevent: agent_event\ndata: {payload}\n\n"

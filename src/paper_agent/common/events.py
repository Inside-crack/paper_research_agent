from __future__ import annotations

from typing import Protocol
import json
from typing import Callable, Optional

from .logging import get_logger
from .event_security import EventSecurityFilter
from .models import AgentEvent
from .persistence import EventStore
from .response_composer import ResponseComposer

logger = get_logger(__name__)


class EventSubscriber(Protocol):
    def on_event(self, event: AgentEvent) -> None:
        ...


class InMemoryEventSubscriber:
    """Reload-free subscriber useful for CLI adapters and tests."""

    def __init__(self):
        self.events: list[AgentEvent] = []

    def on_event(self, event: AgentEvent) -> None:
        if not isinstance(event, AgentEvent):
            raise TypeError("event must be an AgentEvent")
        self.events.append(event)


class CliProgressSubscriber:
    """Render correlated events as JSON progress records for the CLI."""

    def __init__(
        self,
        *,
        session_id: Optional[str] = None,
        output: Optional[Callable[[str], None]] = None,
        composer: Optional[ResponseComposer] = None,
    ):
        self.session_id = session_id
        self.output = output or print
        self.composer = composer or ResponseComposer()

    def on_event(self, event: AgentEvent) -> None:
        if self.session_id is not None and event.session_id != self.session_id:
            return
        response = self.composer.compose(event)
        self.output(
            json.dumps(
                {
                    "type": "progress",
                    **response.model_dump(mode="json"),
                },
                ensure_ascii=False,
            )
        )


class EventPublisher:
    """Persist events before notifying best-effort realtime subscribers."""

    def __init__(
        self,
        store: EventStore,
        *,
        security_filter: Optional[EventSecurityFilter] = None,
    ):
        self.store = store
        self.security_filter = security_filter or EventSecurityFilter()
        self._subscribers: list[EventSubscriber] = []

    def subscribe(self, subscriber: EventSubscriber) -> None:
        if not hasattr(subscriber, "on_event"):
            raise TypeError("subscriber must define on_event")
        if subscriber not in self._subscribers:
            self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: EventSubscriber) -> None:
        try:
            self._subscribers.remove(subscriber)
        except ValueError:
            return

    def publish(self, event: AgentEvent) -> None:
        if not isinstance(event, AgentEvent):
            raise TypeError("event must be an AgentEvent")
        safe_event = self.security_filter.sanitize_event(event)
        self.store.append(safe_event)
        for subscriber in tuple(self._subscribers):
            try:
                subscriber.on_event(safe_event)
            except Exception as exc:
                logger.warning(
                    "Event subscriber failed",
                    event_id=safe_event.event_id,
                    error=str(exc),
                )

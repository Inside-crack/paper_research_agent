from __future__ import annotations

import re
from typing import Any

from .models import AgentEvent


class EventSecurityFilter:
    """Remove credentials, prompts, and host paths from event payloads."""

    _SECRET_KEY_PATTERN = re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|auth(?:orization)?|password|"
        r"secret|credential|private[_-]?key)"
    )
    _SECRET_VALUE_PATTERN = re.compile(
        r"(?i)\b(?:bearer\s+|sk-[a-z0-9_-]{8,}|"
        r"api[_-]?key\s*[:=]\s*|access[_-]?token\s*[:=]\s*|"
        r"token\s*[:=]\s*|secret\s*[:=]\s*)\S+"
    )
    _UNIX_PATH_PATTERN = re.compile(
        r"(?<![\w:])/(?:Users|home|root|private|tmp|var|opt|etc)/\S+"
    )
    _WINDOWS_PATH_PATTERN = re.compile(r"(?i)\b[A-Z]:\\\S+")
    _TRACEBACK_PATTERN = re.compile(r"(?m)^\s*Traceback \(most recent call last\):.*")

    def sanitize_event(self, event: AgentEvent) -> AgentEvent:
        if not isinstance(event, AgentEvent):
            raise TypeError("event must be an AgentEvent")
        return event.model_copy(
            deep=True,
            update={"payload": self.sanitize_payload(event.payload)},
        )

    def sanitize_payload(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            return {
                str(key): (
                    "[REDACTED]"
                    if self._SECRET_KEY_PATTERN.search(str(key))
                    else self.sanitize_payload(value)
                )
                for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self.sanitize_payload(value) for value in payload]
        if isinstance(payload, tuple):
            return [self.sanitize_payload(value) for value in payload]
        if isinstance(payload, str):
            value = self._SECRET_VALUE_PATTERN.sub("[REDACTED]", payload)
            value = self._UNIX_PATH_PATTERN.sub("[PATH]", value)
            value = self._WINDOWS_PATH_PATTERN.sub("[PATH]", value)
            return self._TRACEBACK_PATTERN.sub("[TRACEBACK REDACTED]", value)
        return payload

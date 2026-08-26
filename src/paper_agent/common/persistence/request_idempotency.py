from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Optional

from .manifest import atomic_write_json


class RequestIdempotencyStore:
    """Durable per-session request replay records for the single-process API."""

    def __init__(self, base_dir: Path):
        self.path = Path(base_dir) / "conversation_request_idempotency.json"
        self._lock = threading.RLock()

    @staticmethod
    def fingerprint(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _read(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("Invalid request idempotency store")
        return data

    def get(
        self,
        session_id: str,
        request_id: str,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._read().get(session_id, {}).get(request_id)

    def save(
        self,
        session_id: str,
        request_id: str,
        *,
        fingerprint: str,
        response: dict[str, Any],
        http_status: int = 200,
    ) -> None:
        with self._lock:
            data = self._read()
            data.setdefault(session_id, {})[request_id] = {
                "fingerprint": fingerprint,
                "response": response,
                "http_status": http_status,
            }
            atomic_write_json(self.path, data)

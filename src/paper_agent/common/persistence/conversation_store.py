from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..models.conversation import (
    ConversationContext,
    ConversationMessage,
    ConversationSession,
    ConversationSessionStatus,
    SESSION_STATUS_TRANSITIONS,
)
from ..models.paper_candidate import PaperCandidateSet
from .manifest import atomic_write_json

_SESSION_DIRNAME = "sessions"
_SESSION_FILENAME = "session.json"
_MESSAGES_FILENAME = "messages.json"
_PAPER_CANDIDATES_DIRNAME = "paper_candidates"
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ConversationStore:
    """Atomic JSON persistence for conversation sessions and their messages."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.sessions_dir = self.base_dir / _SESSION_DIRNAME
        if self.sessions_dir.is_symlink():
            raise ValueError(
                f"Conversation sessions directory must not be a symlink: {self.sessions_dir}"
            )
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.paper_candidates_dir = self.base_dir / _PAPER_CANDIDATES_DIRNAME
        if self.paper_candidates_dir.is_symlink():
            raise ValueError(
                f"Paper candidate directory must not be a symlink: {self.paper_candidates_dir}"
            )
        self.paper_candidates_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError(f"Invalid conversation session_id: {session_id!r}")
        if "/" in session_id or "\\" in session_id or session_id in {".", ".."}:
            raise ValueError(f"Invalid conversation session_id: {session_id!r}")

    def _session_dir(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        sessions_root = self.sessions_dir.resolve()
        session_dir = self.sessions_dir / session_id
        resolved = session_dir.resolve()
        try:
            resolved.relative_to(sessions_root)
        except ValueError as exc:
            raise ValueError(f"Conversation session path escapes sessions directory: {session_id!r}") from exc
        if session_dir.is_symlink():
            raise ValueError(f"Conversation session path must not be a symlink: {session_id!r}")
        return session_dir

    def _session_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / _SESSION_FILENAME

    def _messages_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / _MESSAGES_FILENAME

    @staticmethod
    def _reject_symlink(path: Path) -> None:
        if path.is_symlink():
            raise ValueError(f"Conversation persistence path must not be a symlink: {path}")

    @classmethod
    def _snapshot_bytes(cls, path: Path) -> Optional[bytes]:
        cls._reject_symlink(path)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    @classmethod
    def _ensure_snapshot_unchanged(cls, path: Path, snapshot: Optional[bytes]) -> None:
        if cls._snapshot_bytes(path) != snapshot:
            raise RuntimeError(
                f"Conversation persistence file changed during append: {path}"
            )

    @classmethod
    def _restore_bytes(cls, path: Path, snapshot: Optional[bytes]) -> None:
        """Restore a previous file snapshot without exposing a partial file."""
        cls._reject_symlink(path)
        if snapshot is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.restore-",
        )
        os.close(fd)
        try:
            with open(temporary_path, "wb") as file:
                file.write(snapshot)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
        except Exception:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
            raise

    @classmethod
    def _read_json(cls, path: Path, *, missing_ok: bool) -> Any:
        cls._reject_symlink(path)
        if not path.exists():
            if missing_ok:
                return None
            raise FileNotFoundError(f"Conversation persistence file does not exist: {path}")
        try:
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt conversation JSON: {path}") from exc
        except OSError as exc:
            raise OSError(f"Failed to read conversation JSON: {path}") from exc

    @staticmethod
    def _validate_session_data(data: Any, path: Path) -> ConversationSession:
        if not isinstance(data, dict):
            raise ValueError(f"Invalid conversation session JSON structure: {path}")
        try:
            session = ConversationSession.model_validate(data)
        except Exception as exc:
            raise ValueError(f"Invalid conversation session data: {path}: {exc}") from exc
        if session.session_id != path.parent.name:
            raise ValueError(
                f"Conversation session_id mismatch: file directory {path.parent.name!r}, "
                f"payload {session.session_id!r}"
            )
        return session

    @staticmethod
    def _validate_message_data(data: Any, path: Path) -> ConversationMessage:
        if not isinstance(data, dict):
            raise ValueError(f"Invalid conversation message JSON structure: {path}")
        try:
            return ConversationMessage.model_validate(data)
        except Exception as exc:
            raise ValueError(f"Invalid conversation message data: {path}: {exc}") from exc

    def _require_session(self, session_id: str) -> ConversationSession:
        session = self.load_session(session_id)
        if session is None:
            raise FileNotFoundError(f"Conversation session does not exist: {session_id!r}")
        return session

    def _load_messages(self, session_id: str) -> list[ConversationMessage]:
        path = self._messages_path(session_id)
        data = self._read_json(path, missing_ok=True)
        if data is None:
            return []
        if not isinstance(data, list):
            raise ValueError(f"Invalid conversation messages JSON structure: {path}")

        messages = [self._validate_message_data(item, path) for item in data]
        for message in messages:
            if message.session_id != session_id:
                raise ValueError(
                    f"Conversation message.session_id mismatch: expected {session_id!r}, "
                    f"got {message.session_id!r}"
                )
        return messages

    def create_session(self, user_id: Optional[str] = None) -> ConversationSession:
        session = ConversationSession(user_id=user_id)
        self.save_session(session)
        return session

    def load_session(self, session_id: str) -> Optional[ConversationSession]:
        path = self._session_path(session_id)
        data = self._read_json(path, missing_ok=True)
        if data is None:
            return None
        return self._validate_session_data(data, path)

    def save_session(self, session: ConversationSession) -> Path:
        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        session_dir = self._session_dir(session.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / _SESSION_FILENAME
        self._reject_symlink(path)
        atomic_write_json(path, session.model_dump(mode="json"))
        return path

    def append_message(
        self,
        session_id: str,
        message: ConversationMessage,
    ) -> ConversationMessage:
        session = self._require_session(session_id)
        if not isinstance(message, ConversationMessage):
            try:
                message = ConversationMessage.model_validate(message)
            except Exception as exc:
                raise ValueError(f"Invalid conversation message: {exc}") from exc
        if message.session_id != session_id:
            raise ValueError(
                f"Conversation message.session_id mismatch: expected {session_id!r}, "
                f"got {message.session_id!r}"
            )

        messages_path = self._messages_path(session_id)
        session_path = self._session_path(session_id)
        messages_snapshot = self._snapshot_bytes(messages_path)
        session_snapshot = self._snapshot_bytes(session_path)
        messages = self._load_messages(session_id)
        messages.append(message)
        try:
            self._ensure_snapshot_unchanged(messages_path, messages_snapshot)
            atomic_write_json(
                messages_path,
                [item.model_dump(mode="json") for item in messages],
            )

            session.message_count = len(messages)
            session.updated_at = datetime.utcnow()
            self._ensure_snapshot_unchanged(session_path, session_snapshot)
            self.save_session(session)
        except Exception as original_error:
            rollback_errors = []
            for path, snapshot in (
                (messages_path, messages_snapshot),
                (session_path, session_snapshot),
            ):
                try:
                    self._restore_bytes(path, snapshot)
                except Exception as rollback_error:
                    rollback_errors.append(f"{path}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError(
                    f"Conversation append failed with {original_error}; "
                    f"rollback failed with {'; '.join(rollback_errors)}"
                ) from original_error
            raise
        return message

    def list_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> list[ConversationMessage]:
        self._require_session(session_id)
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
            raise ValueError("message limit must be an integer or None")
        if limit is not None and limit < 0:
            raise ValueError("message limit must be non-negative")

        messages = self._load_messages(session_id)
        if limit is None:
            return messages
        if limit == 0:
            return []
        return messages[-limit:]

    def update_context(
        self,
        session_id: str,
        context: ConversationContext,
    ) -> ConversationSession:
        session = self._require_session(session_id)
        if not isinstance(context, ConversationContext):
            try:
                context = ConversationContext.model_validate(context)
            except Exception as exc:
                raise ValueError(f"Invalid conversation context: {exc}") from exc
        session.context = context
        session.active_task_id = context.active_task_id
        session.updated_at = datetime.utcnow()
        self.save_session(session)
        return session

    def bind_task(
        self,
        session_id: str,
        task_id: Optional[str],
    ) -> ConversationSession:
        session = self._require_session(session_id)
        session.active_task_id = task_id
        session.context.active_task_id = task_id
        session.updated_at = datetime.utcnow()
        self.save_session(session)
        return session

    def update_status(
        self,
        session_id: str,
        status: ConversationSessionStatus,
    ) -> ConversationSession:
        """Persist a conversation lifecycle status change."""
        session = self._require_session(session_id)
        if status not in SESSION_STATUS_TRANSITIONS[session.status]:
            raise ValueError(
                f"Invalid conversation status transition: "
                f"{session.status} -> {status}"
            )
        session.status = status
        session.updated_at = datetime.utcnow()
        self.save_session(session)
        return session

    def save_paper_candidate_set(self, candidate_set: PaperCandidateSet) -> Path:
        """Persist a chat/search candidate set as a dedicated atomic artifact."""
        if not isinstance(candidate_set, PaperCandidateSet):
            raise TypeError("candidate_set must be a PaperCandidateSet")
        path = self.paper_candidates_dir / f"{candidate_set.id}.json"
        atomic_write_json(path, candidate_set.model_dump(mode="json"))
        return path

    def load_paper_candidate_set(self, candidate_set_id: str) -> Optional[PaperCandidateSet]:
        if (
            not isinstance(candidate_set_id, str)
            or not candidate_set_id
            or "/" in candidate_set_id
            or "\\" in candidate_set_id
            or candidate_set_id in {".", ".."}
        ):
            raise ValueError(f"Invalid paper candidate set id: {candidate_set_id!r}")
        path = self.paper_candidates_dir / f"{candidate_set_id}.json"
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            candidate_set = PaperCandidateSet.model_validate(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt paper candidate set JSON: {path}") from exc
        except Exception as exc:
            raise ValueError(f"Invalid paper candidate set: {path}") from exc
        if candidate_set.id != candidate_set_id:
            raise ValueError(
                f"Paper candidate set id mismatch: expected {candidate_set_id!r}, "
                f"got {candidate_set.id!r}"
            )
        return candidate_set

    def load_paper_candidate_set_for_session(
        self,
        candidate_set_id: str,
        session_id: str,
    ) -> Optional[PaperCandidateSet]:
        """Load a candidate set only when it is explicitly owned by a session."""
        candidate_set = self.load_paper_candidate_set(candidate_set_id)
        if candidate_set is None:
            return None
        if candidate_set.session_id != session_id:
            raise ValueError(
                "paper candidate set does not belong to conversation session"
            )
        return candidate_set

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import get_settings
from ..logging import get_logger
from ..models.memory import (
    MemoryCandidate,
    MemoryCandidateStatus,
    MemoryDecision,
    MemoryItem,
    MemoryScope,
    MemoryStatus,
)
from .manifest import atomic_write_json

_STORE_VERSION = 1
_MEMORIES_FILENAME = "memories.json"
_CANDIDATES_FILENAME = "memory_candidates.json"
_INDEX_FILENAME = "memory_index.json"

logger = get_logger(__name__)


class MemoryStore:
    """Atomic JSON persistence for cross-task memories and memory candidates.

    Long-term memory is intentionally stored outside task artifact directories.
    The store keeps source references, while the original conversation and task
    data remain owned by ConversationStore and StatePersistence.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir is not None else get_settings().memory_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if self.base_dir.is_symlink():
            raise ValueError(f"Memory directory must not be a symlink: {self.base_dir}")
        self._ensure_index()

    @property
    def memories_path(self) -> Path:
        return self.base_dir / _MEMORIES_FILENAME

    @property
    def candidates_path(self) -> Path:
        return self.base_dir / _CANDIDATES_FILENAME

    @property
    def index_path(self) -> Path:
        return self.base_dir / _INDEX_FILENAME

    @staticmethod
    def _validate_path(path: Path) -> None:
        if path.is_symlink():
            raise ValueError(f"Memory persistence path must not be a symlink: {path}")

    @classmethod
    def _load_records(cls, path: Path, model_type: type[MemoryItem] | type[MemoryCandidate]) -> list:
        cls._validate_path(path)
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt memory persistence file: {path}") from exc
        except OSError as exc:
            raise OSError(f"Failed to read memory persistence file: {path}") from exc

        if not isinstance(data, dict) or data.get("version") != _STORE_VERSION:
            raise ValueError(f"Unsupported memory persistence format: {path}")
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError(f"Invalid memory records in: {path}")
        try:
            return [model_type.model_validate(record) for record in records]
        except Exception as exc:
            raise ValueError(f"Invalid memory record in: {path}") from exc

    @classmethod
    def _save_records(cls, path: Path, records: list) -> None:
        cls._validate_path(path)
        payload = {
            "version": _STORE_VERSION,
            "updated_at": datetime.utcnow().isoformat(),
            "records": [record.model_dump(mode="json") for record in records],
        }
        atomic_write_json(path, payload)

    def _write_index(
        self,
        *,
        memories: Optional[list[MemoryItem]] = None,
        candidates: Optional[list[MemoryCandidate]] = None,
    ) -> None:
        if memories is None:
            memories = self._load_records(self.memories_path, MemoryItem)
        if candidates is None:
            candidates = self._load_records(self.candidates_path, MemoryCandidate)
        atomic_write_json(
            self.index_path,
            {
                "version": _STORE_VERSION,
                "updated_at": datetime.utcnow().isoformat(),
                "memory_ids": [item.memory_id for item in memories],
                "candidate_ids": [item.candidate_id for item in candidates],
                "memory_count": len(memories),
                "candidate_count": len(candidates),
            },
        )

    def _ensure_index(self) -> None:
        """Create or rebuild the lightweight index from canonical JSON records."""
        try:
            self._validate_path(self.index_path)
            index_is_valid = False
            if self.index_path.exists():
                try:
                    with self.index_path.open("r", encoding="utf-8") as file:
                        data = json.load(file)
                    index_is_valid = (
                        isinstance(data, dict)
                        and data.get("version") == _STORE_VERSION
                        and isinstance(data.get("memory_ids"), list)
                        and isinstance(data.get("candidate_ids"), list)
                    )
                except (OSError, json.JSONDecodeError):
                    index_is_valid = False
            if index_is_valid:
                return
            self.rebuild_index()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Failed to rebuild memory index; canonical records remain available: %s", exc)

    def rebuild_index(self) -> Path:
        """Rebuild the derived index from the canonical memory and candidate files."""
        memories = self._load_records(self.memories_path, MemoryItem)
        candidates = self._load_records(self.candidates_path, MemoryCandidate)
        self._write_index(memories=memories, candidates=candidates)
        return self.index_path

    def load_index(self) -> dict:
        self._validate_path(self.index_path)
        if not self.index_path.exists():
            self.rebuild_index()
        try:
            with self.index_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Corrupt memory index: {self.index_path}") from exc
        if not isinstance(data, dict) or data.get("version") != _STORE_VERSION:
            raise ValueError(f"Unsupported memory index format: {self.index_path}")
        return data

    def try_save_memory(
        self,
        memory: MemoryItem,
        *,
        idempotency_key: Optional[str] = None,
    ) -> Optional[MemoryItem]:
        """Best-effort write for enhancement paths; never raises to the caller."""
        try:
            return self.save_memory(memory, idempotency_key=idempotency_key)
        except Exception as exc:
            logger.warning("Memory write degraded: %s", exc)
            return None

    def try_save_candidate(self, candidate: MemoryCandidate) -> Optional[MemoryCandidate]:
        """Best-effort candidate write for enhancement paths; never raises to the caller."""
        try:
            return self.save_candidate(candidate)
        except Exception as exc:
            logger.warning("Memory candidate write degraded: %s", exc)
            return None

    def save_memory(
        self,
        memory: MemoryItem,
        *,
        idempotency_key: Optional[str] = None,
    ) -> MemoryItem:
        if not isinstance(memory, MemoryItem):
            raise TypeError("memory must be a MemoryItem")
        key = idempotency_key or memory.idempotency_key
        if key is not None and not key.strip():
            raise ValueError("idempotency_key must not be blank")
        if key and memory.idempotency_key != key:
            memory = memory.model_copy(update={"idempotency_key": key})

        records = self._load_records(self.memories_path, MemoryItem)
        if key:
            for existing in records:
                if existing.idempotency_key == key:
                    return existing
        if any(existing.memory_id == memory.memory_id for existing in records):
            raise ValueError(f"Memory already exists: {memory.memory_id}")
        self._save_records(self.memories_path, [*records, memory])
        self._write_index(memories=[*records, memory])
        return memory

    def get_memory(self, memory_id: str, *, owner_user_id: Optional[str] = None) -> Optional[MemoryItem]:
        for memory in self._load_records(self.memories_path, MemoryItem):
            if memory.memory_id != memory_id:
                continue
            if owner_user_id is not None and memory.owner_user_id != owner_user_id:
                return None
            return memory
        return None

    def list_memories(
        self,
        *,
        owner_user_id: str,
        scope: Optional[MemoryScope] = None,
        status: Optional[MemoryStatus] = MemoryStatus.ACTIVE,
        memory_type: Optional[str] = None,
    ) -> list[MemoryItem]:
        if not owner_user_id or not owner_user_id.strip():
            raise ValueError("owner_user_id must not be blank")
        records = self._load_records(self.memories_path, MemoryItem)
        return [
            memory
            for memory in records
            if memory.owner_user_id == owner_user_id
            and (scope is None or memory.scope == scope.value)
            and (status is None or memory.status == status.value)
            and (memory_type is None or memory.memory_type == memory_type)
        ]

    def update_memory(self, memory: MemoryItem, *, owner_user_id: str) -> MemoryItem:
        if not isinstance(memory, MemoryItem):
            raise TypeError("memory must be a MemoryItem")
        records = self._load_records(self.memories_path, MemoryItem)
        for index, existing in enumerate(records):
            if existing.memory_id != memory.memory_id:
                continue
            if existing.owner_user_id != owner_user_id:
                raise PermissionError(f"Memory does not belong to owner: {memory.memory_id}")
            updated = memory.model_copy(
                update={
                    "updated_at": datetime.utcnow(),
                    "version": existing.version + 1,
                }
            )
            records[index] = updated
            self._save_records(self.memories_path, records)
            self._write_index(memories=records)
            return updated
        raise KeyError(f"Memory not found: {memory.memory_id}")

    def delete_memory(self, memory_id: str, *, owner_user_id: str) -> MemoryItem:
        memory = self.get_memory(memory_id, owner_user_id=owner_user_id)
        if memory is None:
            raise KeyError(f"Memory not found: {memory_id}")
        return self.update_memory(
            memory.model_copy(update={"status": MemoryStatus.DELETED}),
            owner_user_id=owner_user_id,
        )

    def save_candidate(self, candidate: MemoryCandidate) -> MemoryCandidate:
        if not isinstance(candidate, MemoryCandidate):
            raise TypeError("candidate must be a MemoryCandidate")
        records = self._load_records(self.candidates_path, MemoryCandidate)
        for existing in records:
            if existing.idempotency_key == candidate.idempotency_key:
                return existing
        self._save_records(self.candidates_path, [*records, candidate])
        self._write_index(candidates=[*records, candidate])
        return candidate

    def get_candidate(
        self,
        candidate_id: str,
        *,
        owner_user_id: Optional[str] = None,
    ) -> Optional[MemoryCandidate]:
        for candidate in self._load_records(self.candidates_path, MemoryCandidate):
            if candidate.candidate_id != candidate_id:
                continue
            if owner_user_id is not None and candidate.owner_user_id != owner_user_id:
                return None
            return candidate
        return None

    def list_candidates(
        self,
        *,
        owner_user_id: str,
        status: Optional[MemoryCandidateStatus] = None,
    ) -> list[MemoryCandidate]:
        if not owner_user_id or not owner_user_id.strip():
            raise ValueError("owner_user_id must not be blank")
        records = self._load_records(self.candidates_path, MemoryCandidate)
        return [
            candidate
            for candidate in records
            if candidate.owner_user_id == owner_user_id
            and (status is None or candidate.status == status.value)
        ]

    def update_candidate(
        self,
        candidate: MemoryCandidate,
        *,
        owner_user_id: str,
    ) -> MemoryCandidate:
        if not isinstance(candidate, MemoryCandidate):
            raise TypeError("candidate must be a MemoryCandidate")
        records = self._load_records(self.candidates_path, MemoryCandidate)
        for index, existing in enumerate(records):
            if existing.candidate_id != candidate.candidate_id:
                continue
            if existing.owner_user_id != owner_user_id:
                raise PermissionError(
                    f"Candidate does not belong to owner: {candidate.candidate_id}"
                )
            updated = candidate.model_copy(update={"updated_at": datetime.utcnow()})
            records[index] = updated
            self._save_records(self.candidates_path, records)
            self._write_index(candidates=records)
            return updated
        raise KeyError(f"Memory candidate not found: {candidate.candidate_id}")

    def set_candidate_status(
        self,
        candidate_id: str,
        *,
        owner_user_id: str,
        status: MemoryCandidateStatus,
        decision: Optional[MemoryDecision] = None,
        memory_id: Optional[str] = None,
        rejection_reason: Optional[str] = None,
    ) -> MemoryCandidate:
        candidate = self.get_candidate(candidate_id, owner_user_id=owner_user_id)
        if candidate is None:
            raise KeyError(f"Memory candidate not found: {candidate_id}")
        return self.update_candidate(
            candidate.model_copy(
                update={
                    "status": status,
                    "decision": decision,
                    "memory_id": memory_id,
                    "rejection_reason": rejection_reason,
                }
            ),
            owner_user_id=owner_user_id,
        )

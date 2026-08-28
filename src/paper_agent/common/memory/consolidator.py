from __future__ import annotations

import re
from typing import Optional

from ..logging import get_logger
from ..models.memory import (
    ConsolidationResult,
    MemoryCandidate,
    MemoryCandidateStatus,
    MemoryDecision,
    MemoryItem,
    MemoryScope,
)
from ..persistence.memory_store import MemoryStore

logger = get_logger(__name__)

_TERM_PATTERN = re.compile(r"[a-z0-9][a-z0-9_./:+-]*|[\u4e00-\u9fff]+", re.IGNORECASE)
_CONFLICT_MARKERS = (
    "更正",
    "纠正",
    "改为",
    "改成",
    "不再",
    "不使用",
    "错误",
    "其实",
    "纠错",
    "correction",
    "instead",
    "no longer",
    "wrong",
    "replace",
)


class MemoryConsolidator:
    """Deterministic L1 deduplication and conflict consolidation.

    The policy is intentionally conservative. It provides a stable baseline
    for F05; an LLM may later improve candidate classification, but it must
    return one of the same decisions and cannot bypass these persistence
    methods.
    """

    def __init__(
        self,
        store: MemoryStore,
        *,
        max_candidates: int = 20,
    ):
        if not isinstance(store, MemoryStore):
            raise TypeError("store must be a MemoryStore")
        if max_candidates < 1:
            raise ValueError("max_candidates must be at least 1")
        self.store = store
        self.max_candidates = max_candidates

    def consolidate(self, candidate: MemoryCandidate) -> ConsolidationResult:
        if not isinstance(candidate, MemoryCandidate):
            raise TypeError("candidate must be a MemoryCandidate")
        if (
            candidate.status == MemoryCandidateStatus.ACCEPTED.value
            and candidate.memory_id
        ):
            return ConsolidationResult(
                candidate_id=candidate.candidate_id,
                decision=MemoryDecision.STORE,
                memory_id=candidate.memory_id,
                reason="candidate was already consolidated",
            )
        if candidate.status not in (
            MemoryCandidateStatus.PENDING.value,
            MemoryCandidateStatus.PROCESSING.value,
        ):
            raise ValueError(
                f"candidate cannot be consolidated from status {candidate.status}"
            )

        active_memories = self._load_matching_memories(candidate)
        ranked = sorted(
            (
                (memory, self._similarity(candidate.content, memory.content))
                for memory in active_memories
            ),
            key=lambda item: (
                item[1],
                memory_priority(item[0]),
                item[0].updated_at,
            ),
            reverse=True,
        )
        best = ranked[0] if ranked else None

        if best is None or best[1] < 0.20:
            return self._store_new(candidate, reason="no sufficiently similar active memory")

        existing, similarity = best
        if self._normalize(candidate.content) == self._normalize(existing.content):
            return self._skip(candidate, existing)

        if self._is_conflict(candidate.content, existing.content, similarity):
            return self._store_conflict(candidate, existing, similarity)

        if similarity >= 0.65 or self._contains_facts(existing.content, candidate.content):
            return self._update(candidate, existing, similarity)

        return self._merge(candidate, existing, similarity)

    def _load_matching_memories(self, candidate: MemoryCandidate) -> list[MemoryItem]:
        memories = self.store.list_memories(
            owner_user_id=candidate.owner_user_id,
            scope=MemoryScope(candidate.scope),
        )
        return [
            memory
            for memory in memories
            if memory.status == "active"
            and memory.memory_type == candidate.memory_type
            and memory.scope_key == candidate.scope_key
        ][: self.max_candidates]

    def _store_new(self, candidate: MemoryCandidate, *, reason: str) -> ConsolidationResult:
        memory = self._memory_from_candidate(candidate)
        saved = self.store.save_memory(memory)
        self._mark_candidate(
            candidate,
            decision=MemoryDecision.STORE,
            memory_id=saved.memory_id,
        )
        return ConsolidationResult(
            candidate_id=candidate.candidate_id,
            decision=MemoryDecision.STORE,
            memory_id=saved.memory_id,
            reason=reason,
        )

    def _skip(
        self,
        candidate: MemoryCandidate,
        existing: MemoryItem,
    ) -> ConsolidationResult:
        self._mark_candidate(
            candidate,
            decision=MemoryDecision.SKIP,
            memory_id=existing.memory_id,
        )
        return ConsolidationResult(
            candidate_id=candidate.candidate_id,
            decision=MemoryDecision.SKIP,
            memory_id=existing.memory_id,
            matched_memory_ids=[existing.memory_id],
            reason="equivalent active memory already exists",
        )

    def _update(
        self,
        candidate: MemoryCandidate,
        existing: MemoryItem,
        similarity: float,
    ) -> ConsolidationResult:
        updated_candidate = candidate.model_copy(
            update={
                "source_session_id": candidate.source_session_id or existing.source_session_id,
                "source_task_id": candidate.source_task_id or existing.source_task_id,
                "source_artifact_ids": self._unique(
                    [*existing.source_artifact_ids, *candidate.source_artifact_ids]
                ),
                "source_timestamps": [
                    *existing.source_timestamps,
                    *candidate.source_timestamps,
                    existing.updated_at,
                ],
                "priority": max(candidate.priority, existing.priority),
                "confidence": max(candidate.confidence, existing.confidence),
            }
        )
        memory = self._memory_from_candidate(
            updated_candidate,
            supersedes_memory_ids=[existing.memory_id],
        )
        saved = self.store.save_memory(memory)
        self.store.update_memory(
            existing.model_copy(
                update={
                    "status": "superseded",
                    "supersedes_memory_ids": [saved.memory_id],
                }
            ),
            owner_user_id=existing.owner_user_id,
        )
        self._mark_candidate(
            candidate,
            decision=MemoryDecision.UPDATE,
            memory_id=saved.memory_id,
        )
        return ConsolidationResult(
            candidate_id=candidate.candidate_id,
            decision=MemoryDecision.UPDATE,
            memory_id=saved.memory_id,
            matched_memory_ids=[existing.memory_id],
            superseded_memory_ids=[existing.memory_id],
            reason=f"new memory supersedes similar memory (similarity={similarity:.3f})",
        )

    def _merge(
        self,
        candidate: MemoryCandidate,
        existing: MemoryItem,
        similarity: float,
    ) -> ConsolidationResult:
        merged_content = self._merge_content(existing.content, candidate.content)
        merged_candidate = candidate.model_copy(
            update={
                "content": merged_content,
                "source_session_id": candidate.source_session_id or existing.source_session_id,
                "source_task_id": candidate.source_task_id or existing.source_task_id,
                "source_artifact_ids": self._unique(
                    [*existing.source_artifact_ids, *candidate.source_artifact_ids]
                ),
                "source_timestamps": [
                    *existing.source_timestamps,
                    *candidate.source_timestamps,
                    existing.updated_at,
                ],
                "priority": max(candidate.priority, existing.priority),
                "confidence": max(candidate.confidence, existing.confidence),
            }
        )
        memory = self._memory_from_candidate(
            merged_candidate,
            supersedes_memory_ids=[existing.memory_id],
        )
        saved = self.store.save_memory(memory)
        self.store.update_memory(
            existing.model_copy(
                update={
                    "status": "superseded",
                    "supersedes_memory_ids": [saved.memory_id],
                }
            ),
            owner_user_id=existing.owner_user_id,
        )
        self._mark_candidate(
            candidate,
            decision=MemoryDecision.MERGE,
            memory_id=saved.memory_id,
        )
        return ConsolidationResult(
            candidate_id=candidate.candidate_id,
            decision=MemoryDecision.MERGE,
            memory_id=saved.memory_id,
            matched_memory_ids=[existing.memory_id],
            superseded_memory_ids=[existing.memory_id],
            merged=True,
            reason=f"complementary memories merged (similarity={similarity:.3f})",
        )

    def _store_conflict(
        self,
        candidate: MemoryCandidate,
        existing: MemoryItem,
        similarity: float,
    ) -> ConsolidationResult:
        memory = self._memory_from_candidate(
            candidate,
            conflict_memory_ids=[existing.memory_id],
        )
        saved = self.store.save_memory(memory)
        self._mark_candidate(
            candidate,
            decision=MemoryDecision.STORE,
            memory_id=saved.memory_id,
            conflict_memory_ids=[existing.memory_id],
        )
        return ConsolidationResult(
            candidate_id=candidate.candidate_id,
            decision=MemoryDecision.STORE,
            memory_id=saved.memory_id,
            matched_memory_ids=[existing.memory_id],
            conflict_memory_ids=[existing.memory_id],
            reason=f"possible conflict preserved as a new version (similarity={similarity:.3f})",
        )

    def _mark_candidate(
        self,
        candidate: MemoryCandidate,
        *,
        decision: MemoryDecision,
        memory_id: str,
        conflict_memory_ids: Optional[list[str]] = None,
    ) -> None:
        self.store.update_candidate(
            candidate.model_copy(
                update={
                    "status": MemoryCandidateStatus.ACCEPTED,
                    "decision": decision,
                    "memory_id": memory_id,
                    "conflict_memory_ids": conflict_memory_ids or [],
                }
            ),
            owner_user_id=candidate.owner_user_id,
        )

    @staticmethod
    def _memory_from_candidate(
        candidate: MemoryCandidate,
        *,
        supersedes_memory_ids: Optional[list[str]] = None,
        conflict_memory_ids: Optional[list[str]] = None,
    ) -> MemoryItem:
        return MemoryItem(
            idempotency_key=candidate.idempotency_key,
            content=candidate.content,
            memory_type=candidate.memory_type,
            scope=candidate.scope,
            scope_key=candidate.scope_key,
            owner_user_id=candidate.owner_user_id,
            priority=candidate.priority,
            confidence=candidate.confidence,
            source_kind=candidate.source_kind,
            source_session_id=candidate.source_session_id,
            source_task_id=candidate.source_task_id,
            source_message_id=candidate.source_message_id,
            source_artifact_ids=candidate.source_artifact_ids,
            source_timestamps=candidate.source_timestamps,
            extractor_version=candidate.extractor_version,
            rationale=candidate.rationale,
            supersedes_memory_ids=supersedes_memory_ids or [],
            conflict_memory_ids=conflict_memory_ids or [],
        )

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        left_terms = cls._terms(left)
        right_terms = cls._terms(right)
        if not left_terms or not right_terms:
            return 0.0
        return len(left_terms & right_terms) / len(left_terms | right_terms)

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", "", value.strip().lower())

    @classmethod
    def _contains_facts(cls, old: str, new: str) -> bool:
        old_normalized = cls._normalize(old)
        new_normalized = cls._normalize(new)
        return old_normalized in new_normalized and old_normalized != new_normalized

    @classmethod
    def _is_conflict(cls, new: str, old: str, similarity: float) -> bool:
        if similarity < 0.20:
            return False
        combined = f"{new} {old}".lower()
        return any(marker in combined for marker in _CONFLICT_MARKERS)

    @classmethod
    def _merge_content(cls, old: str, new: str) -> str:
        if cls._normalize(new) in cls._normalize(old):
            return old
        return f"{old}；{new}"

    @classmethod
    def _terms(cls, value: str) -> set[str]:
        terms: set[str] = set()
        for raw in _TERM_PATTERN.findall(value.lower()):
            if any("\u4e00" <= char <= "\u9fff" for char in raw):
                terms.add(raw)
                if len(raw) > 1:
                    terms.update(raw[index : index + 2] for index in range(len(raw) - 1))
            else:
                terms.add(raw)
        return {term for term in terms if term.strip()}

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))


def memory_priority(memory: MemoryItem) -> int:
    return max(0, memory.priority)

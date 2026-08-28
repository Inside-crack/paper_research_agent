from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Iterable

from ..logging import get_logger
from ..models.memory import (
    MemoryItem,
    MemoryRecallItem,
    MemoryRecallQuery,
    MemoryScope,
    RecallResult,
)
from ..persistence.memory_store import MemoryStore

logger = get_logger(__name__)

_TERM_PATTERN = re.compile(r"[a-z0-9][a-z0-9_./:+-]*|[\u4e00-\u9fff]+", re.IGNORECASE)


class MemoryRecallService:
    """Owner-scoped deterministic memory recall with hard budgets."""

    def __init__(self, store: MemoryStore):
        if not isinstance(store, MemoryStore):
            raise TypeError("store must be a MemoryStore")
        self.store = store

    def search(self, query: MemoryRecallQuery) -> RecallResult:
        if not isinstance(query, MemoryRecallQuery):
            raise TypeError("query must be a MemoryRecallQuery")
        started = time.monotonic()
        try:
            memories = self.store.list_memories(
                owner_user_id=query.owner_user_id,
                scope=query.scope,
            )
            filtered = [
                memory
                for memory in memories
                if self._matches_scope(memory, query)
                and self._is_not_expired(memory)
                and self._matches_type(memory, query)
            ]
            terms = self._terms(query.text)
            ranked = self._rank(filtered, terms)
            candidate_count = len(ranked)
            selected, truncated = self._apply_budget(
                ranked,
                limit=query.limit,
                max_chars=query.max_chars,
                max_memory_chars=query.max_memory_chars,
            )
            return RecallResult(
                query_text=query.text,
                memories=selected,
                candidate_count=candidate_count,
                truncated=truncated,
                elapsed_ms=self._elapsed_ms(started),
            )
        except Exception as exc:
            logger.warning(
                "Memory recall degraded",
                owner_user_id=query.owner_user_id,
                error=str(exc),
            )
            return RecallResult(
                query_text=query.text,
                degraded=True,
                error=str(exc)[:500],
                elapsed_ms=self._elapsed_ms(started),
            )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    @staticmethod
    def _is_not_expired(memory: MemoryItem) -> bool:
        return memory.expires_at is None or memory.expires_at > datetime.utcnow()

    @staticmethod
    def _matches_type(memory: MemoryItem, query: MemoryRecallQuery) -> bool:
        if not query.memory_types:
            return True
        allowed = {memory_type.value for memory_type in query.memory_types}
        return memory.memory_type in allowed

    @staticmethod
    def _matches_scope(memory: MemoryItem, query: MemoryRecallQuery) -> bool:
        if query.scope is not None and memory.scope != query.scope.value:
            return False
        if query.topic_key is not None:
            return (
                memory.scope != MemoryScope.RESEARCH_TOPIC.value
                or memory.scope_key == query.topic_key
            )
        return True

    @classmethod
    def _rank(
        cls,
        memories: Iterable[MemoryItem],
        query_terms: set[str],
    ) -> list[tuple[MemoryItem, float]]:
        if not query_terms:
            return []
        ranked: list[tuple[MemoryItem, float]] = []
        now = datetime.utcnow()
        for memory in memories:
            memory_terms = cls._terms(memory.content)
            matched = query_terms.intersection(memory_terms)
            if not matched:
                continue
            lexical_match = len(matched) / len(query_terms)
            priority_score = max(0, memory.priority) / 100
            age_days = max(0.0, (now - memory.updated_at).total_seconds() / 86400)
            recency_score = 1 / (1 + age_days / 30)
            score = (
                lexical_match * 0.55
                + priority_score * 0.20
                + memory.confidence * 0.15
                + recency_score * 0.10
            )
            ranked.append((memory, score))
        ranked.sort(
            key=lambda item: (
                item[1],
                max(0, item[0].priority),
                item[0].updated_at,
                item[0].memory_id,
            ),
            reverse=True,
        )
        return ranked

    @classmethod
    def _apply_budget(
        cls,
        ranked: list[tuple[MemoryItem, float]],
        *,
        limit: int,
        max_chars: int,
        max_memory_chars: int,
    ) -> tuple[list[MemoryRecallItem], bool]:
        selected: list[MemoryRecallItem] = []
        used_chars = 0
        truncated = len(ranked) > limit
        for memory, score in ranked[:limit]:
            content = memory.content
            if len(content) > max_memory_chars:
                content = cls._truncate(content, max_memory_chars)
                truncated = True
            if used_chars + len(content) > max_chars:
                remaining = max_chars - used_chars
                if remaining < 100:
                    truncated = True
                    break
                content = cls._truncate(content, remaining)
                truncated = True
            selected.append(
                MemoryRecallItem(
                    memory_id=memory.memory_id,
                    content=content,
                    memory_type=memory.memory_type,
                    scope=memory.scope,
                    confidence=memory.confidence,
                    priority=memory.priority,
                    source_task_id=memory.source_task_id,
                    source_artifact_ids=memory.source_artifact_ids,
                    relevance_score=round(score, 6),
                    updated_at=memory.updated_at,
                )
            )
            used_chars += len(content)
        return selected, truncated

    @classmethod
    def _terms(cls, value: str) -> set[str]:
        terms: set[str] = set()
        for raw in _TERM_PATTERN.findall(value.lower()):
            if any("\u4e00" <= char <= "\u9fff" for char in raw):
                if len(raw) == 1:
                    terms.add(raw)
                else:
                    terms.add(raw)
                    terms.update(raw[index : index + 2] for index in range(len(raw) - 1))
            else:
                terms.add(raw)
        return {term for term in terms if term.strip()}

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        suffix = "... [truncated]"
        if len(value) <= limit:
            return value
        return value[: max(0, limit - len(suffix))] + suffix

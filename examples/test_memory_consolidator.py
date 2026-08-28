from __future__ import annotations

from pathlib import Path

from paper_agent.common.memory import (
    MemoryConsolidator,
    MemoryExtractionRequest,
    MemoryExtractor,
)
from paper_agent.common.models.memory import (
    MemoryCandidateStatus,
    MemoryDecision,
    MemoryItem,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
)
from paper_agent.common.persistence import MemoryStore


def _candidate(content: str, *, key: str):
    return MemoryExtractor().extract(
        MemoryExtractionRequest(
            content=content,
            owner_user_id="user-a",
            memory_type=MemoryType.INSTRUCTION,
            source_kind=MemorySourceKind.USER_CONFIRMATION,
            source_session_id="session-1",
            source_task_id="task-1",
            confirmed=True,
            stable=True,
            idempotency_key=key,
        )
    )


def _seed(store: MemoryStore, content: str) -> MemoryItem:
    memory = MemoryItem(
        content=content,
        memory_type=MemoryType.INSTRUCTION,
        scope=MemoryScope.USER,
        owner_user_id="user-a",
        source_kind=MemorySourceKind.USER_CONFIRMATION,
        source_task_id="old-task",
    )
    return store.save_memory(memory)


def test_consolidator_skips_exact_duplicate(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    existing = _seed(store, "用户偏好使用中文回答")
    candidate = _candidate("用户偏好使用中文回答", key="skip-1")
    assert candidate is not None
    store.save_candidate(candidate)

    result = MemoryConsolidator(store).consolidate(candidate)

    assert result.decision == MemoryDecision.SKIP.value
    assert result.memory_id == existing.memory_id
    saved_candidate = store.get_candidate(candidate.candidate_id, owner_user_id="user-a")
    assert saved_candidate is not None
    assert saved_candidate.status == MemoryCandidateStatus.ACCEPTED.value
    assert len(store.list_memories(owner_user_id="user-a")) == 1


def test_consolidator_updates_more_specific_fact_and_supersedes_old(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory")
    existing = _seed(store, "用户偏好使用中文回答")
    candidate = _candidate(
        "用户偏好使用中文回答论文问题并要求给出实验依据",
        key="update-1",
    )
    assert candidate is not None
    store.save_candidate(candidate)

    result = MemoryConsolidator(store).consolidate(candidate)

    assert result.decision == MemoryDecision.UPDATE.value
    assert result.superseded_memory_ids == [existing.memory_id]
    memories = store.list_memories(owner_user_id="user-a", status=None)
    assert any(memory.status == MemoryStatus.SUPERSEDED.value for memory in memories)
    assert any("实验依据" in memory.content for memory in memories)


def test_consolidator_merges_complementary_facts(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    existing = _seed(store, "用户关注场景文本检测方法")
    candidate = _candidate(
        "用户关注场景文本检测数据集",
        key="merge-1",
    )
    assert candidate is not None
    store.save_candidate(candidate)

    result = MemoryConsolidator(store).consolidate(candidate)

    assert result.decision == MemoryDecision.MERGE.value
    assert result.merged is True
    merged = store.get_memory(result.memory_id, owner_user_id="user-a")
    assert merged is not None
    assert "方法" in merged.content
    assert "数据集" in merged.content
    assert existing.memory_id in merged.supersedes_memory_ids


def test_consolidator_preserves_possible_conflict(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    existing = _seed(store, "用户偏好使用中文回答")
    candidate = _candidate(
        "用户更正为默认使用英文回答",
        key="conflict-1",
    )
    assert candidate is not None
    store.save_candidate(candidate)

    result = MemoryConsolidator(store).consolidate(candidate)

    assert result.decision == MemoryDecision.STORE.value
    assert result.conflict_memory_ids == [existing.memory_id]
    assert len(store.list_memories(owner_user_id="user-a")) == 2
    conflict = store.get_memory(result.memory_id, owner_user_id="user-a")
    assert conflict is not None
    assert conflict.conflict_memory_ids == [existing.memory_id]

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from paper_agent.common.memory import MemoryExtractor
from paper_agent.common.models.memory import (
    MemoryCandidate,
    MemoryCandidateStatus,
    MemoryItem,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
)
from paper_agent.common.persistence import MemoryStore


def _memory(*, owner_user_id: str = "user-a", key: Optional[str] = None) -> MemoryItem:
    return MemoryItem(
        content="用户偏好使用中文回答",
        memory_type=MemoryType.PERSONA,
        scope=MemoryScope.USER,
        owner_user_id=owner_user_id,
        source_kind=MemorySourceKind.USER_MESSAGE,
        source_session_id="session-1",
        source_task_id="task-1",
        source_message_id="message-1",
        idempotency_key=key,
    )


def test_memory_model_requires_traceable_owner_and_content() -> None:
    memory = _memory()
    assert memory.owner_user_id == "user-a"
    assert memory.source_task_id == "task-1"

    with pytest.raises(ValueError):
        _memory(owner_user_id=" ")

    with pytest.raises(ValueError):
        MemoryItem(
            content=" ",
            memory_type=MemoryType.PERSONA,
            owner_user_id="user-a",
            source_kind=MemorySourceKind.USER_MESSAGE,
        )


def test_memory_store_roundtrip_and_idempotency(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    memory = _memory(key="task-1:message-1")

    saved = store.save_memory(memory)
    duplicate = store.save_memory(_memory(key="task-1:message-1"))

    assert duplicate.memory_id == saved.memory_id
    assert len(store.list_memories(owner_user_id="user-a")) == 1
    assert (tmp_path / "memory" / "memories.json").exists()

    reloaded = MemoryStore(tmp_path / "memory").get_memory(saved.memory_id, owner_user_id="user-a")
    assert reloaded is not None
    assert reloaded.content == "用户偏好使用中文回答"


def test_memory_store_enforces_owner_isolation_and_soft_delete(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    memory = store.save_memory(_memory(owner_user_id="user-a"))

    assert store.get_memory(memory.memory_id, owner_user_id="user-b") is None
    assert store.list_memories(owner_user_id="user-b") == []
    with pytest.raises(KeyError):
        store.delete_memory(memory.memory_id, owner_user_id="user-b")

    deleted = store.delete_memory(memory.memory_id, owner_user_id="user-a")
    assert deleted.status == MemoryStatus.DELETED.value
    assert store.list_memories(owner_user_id="user-a") == []
    assert store.list_memories(owner_user_id="user-a", status=None)[0].status == MemoryStatus.DELETED.value


def test_candidate_store_roundtrip_status_and_idempotency(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    candidate = MemoryCandidate(
        idempotency_key="task-1:message-1",
        content="用户要求后续报告提供可复现实验步骤",
        memory_type=MemoryType.INSTRUCTION,
        owner_user_id="user-a",
        source_kind=MemorySourceKind.USER_CONFIRMATION,
        source_task_id="task-1",
    )

    saved = store.save_candidate(candidate)
    duplicate = store.save_candidate(candidate.model_copy(update={"candidate_id": "another-id"}))
    assert duplicate.candidate_id == saved.candidate_id

    accepted = store.set_candidate_status(
        saved.candidate_id,
        owner_user_id="user-a",
        status=MemoryCandidateStatus.ACCEPTED,
    )
    assert accepted.status == MemoryCandidateStatus.ACCEPTED.value
    assert store.list_candidates(
        owner_user_id="user-a",
        status=MemoryCandidateStatus.ACCEPTED,
    ) == [accepted]


def test_memory_store_rejects_corrupt_persistence(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.memories_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupt memory persistence file"):
        store.list_memories(owner_user_id="user-a")


def test_memory_index_is_rebuilt_from_canonical_records(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    memory = store.save_memory(_memory())
    store.index_path.write_text("{not-json", encoding="utf-8")

    rebuilt = MemoryStore(tmp_path / "memory")
    index = rebuilt.load_index()
    assert index["memory_ids"] == [memory.memory_id]
    assert index["memory_count"] == 1


def test_memory_store_best_effort_write_degrades_on_corrupt_records(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.memories_path.write_text("{not-json", encoding="utf-8")

    assert store.try_save_memory(_memory()) is None


def test_memory_extractor_requires_explicit_stability_and_source() -> None:
    extractor = MemoryExtractor()

    assert extractor.from_user_message(
        content="用户偏好使用中文回答",
        owner_user_id="user-a",
        session_id="session-1",
        message_id="message-1",
    ) is None

    candidate = extractor.from_user_message(
        content="用户偏好使用中文回答",
        owner_user_id="user-a",
        session_id="session-1",
        message_id="message-1",
        stable=True,
    )
    assert candidate is not None
    assert candidate.extractor_version == "f03-deterministic-v1"
    assert candidate.source_message_id == "message-1"


def test_memory_extractor_filters_one_time_and_unvalidated_inputs() -> None:
    extractor = MemoryExtractor()

    assert extractor.from_confirmation(
        content="这次只比较两篇论文",
        owner_user_id="user-a",
        session_id="session-1",
        task_id="task-1",
    ) is None
    assert extractor.from_validated_task_result(
        content="论文 A 的官方代码无法复现",
        owner_user_id="user-a",
        task_id="task-1",
        artifact_ids=[],
    ) is not None

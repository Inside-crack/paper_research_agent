from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from paper_agent.common.capabilities import IntentContextProjector
from paper_agent.common.memory import MemoryRecallService
from paper_agent.common.models.conversation import ConversationMessage, ConversationSession
from paper_agent.common.models.memory import (
    MemoryItem,
    MemoryRecallQuery,
    MemoryScope,
    MemorySourceKind,
    MemoryType,
)
from paper_agent.common.persistence import MemoryStore


def _memory(
    *,
    owner_user_id: str,
    content: str,
    priority: int = 50,
    expires_at: datetime | None = None,
) -> MemoryItem:
    return MemoryItem(
        content=content,
        memory_type=MemoryType.PERSONA,
        scope=MemoryScope.USER,
        owner_user_id=owner_user_id,
        priority=priority,
        source_kind=MemorySourceKind.USER_MESSAGE,
        source_message_id=f"message-{content[:4]}",
        expires_at=expires_at,
    )


def test_recall_ranks_related_memories_and_enforces_owner_scope(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.save_memory(
        _memory(
            owner_user_id="user-a",
            content="用户偏好使用中文回答论文问题",
            priority=80,
        )
    )
    store.save_memory(
        _memory(
            owner_user_id="user-a",
            content="用户关注场景文本检测数据集",
            priority=40,
        )
    )
    store.save_memory(
        _memory(
            owner_user_id="user-b",
            content="用户偏好使用中文回答论文问题",
            priority=100,
        )
    )

    result = MemoryRecallService(store).search(
        MemoryRecallQuery(owner_user_id="user-a", text="中文论文回答")
    )

    assert result.degraded is False
    assert result.candidate_count == 1
    assert len(result.memories) == 1
    assert result.memories[0].content == "用户偏好使用中文回答论文问题"


def test_recall_filters_expired_memories_and_applies_budget(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.save_memory(
        _memory(
            owner_user_id="user-a",
            content="用户偏好使用中文回答并要求给出详细实验步骤",
            expires_at=datetime.utcnow() - timedelta(seconds=1),
        )
    )
    store.save_memory(
        _memory(
            owner_user_id="user-a",
            content="用户偏好使用中文回答并要求给出可复现细节。" * 20,
        )
    )

    result = MemoryRecallService(store).search(
        MemoryRecallQuery(
            owner_user_id="user-a",
            text="中文回答",
            max_chars=100,
            max_memory_chars=100,
        )
    )

    assert result.candidate_count == 1
    assert result.truncated is True
    assert len(result.memories[0].content) <= 100


def test_recall_returns_degraded_empty_result_on_backend_failure(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.memories_path.write_text("{not-json", encoding="utf-8")

    result = MemoryRecallService(store).search(
        MemoryRecallQuery(owner_user_id="user-a", text="中文")
    )

    assert result.degraded is True
    assert result.memories == []
    assert result.error


def test_context_projector_injects_bounded_recall_items(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.save_memory(
        _memory(
            owner_user_id="user-a",
            content="用户偏好使用中文回答论文问题",
        )
    )
    session = ConversationSession(user_id="user-a")
    message = ConversationMessage(
        session_id=session.session_id,
        role="user",
        content="中文回答",
    )
    result = MemoryRecallService(store).search(
        MemoryRecallQuery(owner_user_id="user-a", text=message.content)
    )

    projection = IntentContextProjector().project(
        session,
        [message],
        memories=result.memories,
        memory_recall_degraded=result.degraded,
        memory_recall_truncated=result.truncated,
    )

    assert len(projection.relevant_memories) == 1
    assert projection.relevant_memories[0].content == "用户偏好使用中文回答论文问题"
    assert projection.memory_disclaimer
    assert not hasattr(projection.relevant_memories[0], "owner_user_id")

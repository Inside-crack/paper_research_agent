from __future__ import annotations

import asyncio
from datetime import datetime

from paper_agent.common.llm import MessageRole
from paper_agent.common.models.base import TaskPhase
from paper_agent.common.models.memory import MemoryRecallItem, RecallResult
from paper_agent.common.models.task_state import TaskState
from paper_agent.research_agent import ResearchAgent


def test_research_agent_injects_stable_and_dynamic_memory_after_phase_reset() -> None:
    state = TaskState(
        research_spec_id="spec-1",
        metadata={
            "research_spec": {"user_query": "研究场景文本检测"},
            "long_term_memory": [
                {
                    "memory_id": "m-stable",
                    "memory_type": "instruction",
                    "content": "用户偏好中文回答并要求给出证据。",
                    "source_task_id": "old-task-1",
                },
                {
                    "memory_id": "m-dynamic",
                    "memory_type": "research_fact",
                    "content": "历史任务曾分析过场景文本检测数据集。",
                    "source_task_id": "old-task-2",
                },
            ],
        },
    )
    agent = ResearchAgent(llm=object())

    asyncio.run(
        agent.start_new_phase(
            TaskPhase.PAPER_RETRIEVAL,
            state,
            [],
        )
    )

    memory_messages = [
        message
        for message in agent.message_history
        if message.metadata.get("msg_type", "").endswith("long_term_memory")
    ]
    assert len(memory_messages) == 2
    assert memory_messages[0].metadata["msg_type"] == "stable_long_term_memory"
    assert memory_messages[1].metadata["msg_type"] == "dynamic_long_term_memory"
    assert memory_messages[0].metadata["anchor"] is True
    assert memory_messages[1].metadata["anchor"] is False
    assert all(message.role == MessageRole.USER for message in memory_messages)
    assert all("不代表当前任务已完成" in message.content for message in memory_messages)


def test_research_agent_does_not_inject_memory_when_snapshot_is_invalid() -> None:
    state = TaskState(
        research_spec_id="spec-1",
        metadata={"long_term_memory": "invalid"},
    )
    agent = ResearchAgent(llm=object())

    asyncio.run(
        agent.start_new_phase(
            TaskPhase.PAPER_RETRIEVAL,
            state,
            [],
        )
    )

    assert not any(
        message.metadata.get("msg_type", "").endswith("long_term_memory")
        for message in agent.message_history
    )


def test_research_agent_refreshes_dynamic_memory_for_each_phase() -> None:
    class FakeRecallService:
        def __init__(self) -> None:
            self.queries = []

        def search(self, query):
            self.queries.append(query)
            return RecallResult(
                query_text=query.text,
                candidate_count=1,
                memories=[
                    MemoryRecallItem(
                        memory_id=f"dynamic-{len(self.queries)}",
                        content=f"阶段 {len(self.queries)} 的历史研究事实",
                        memory_type="research_fact",
                        scope="user",
                        confidence=1.0,
                        priority=50,
                        relevance_score=0.9,
                        updated_at=datetime.utcnow(),
                    )
                ],
            )

    recall = FakeRecallService()
    state = TaskState(
        research_spec_id="spec-1",
        metadata={
            "research_spec": {"user_query": "研究场景文本检测"},
            "long_term_memory_query": {
                "owner_user_id": "user-1",
                "text": "场景文本检测",
            },
            "long_term_memory": [
                {
                    "memory_id": "stable-1",
                    "memory_type": "instruction",
                    "content": "使用中文回答。",
                }
            ],
        },
    )
    agent = ResearchAgent(llm=object(), memory_recall_service=recall)

    async def run() -> None:
        await agent.start_new_phase(TaskPhase.PAPER_RETRIEVAL, state, [])
        first = state.metadata["long_term_memory"][1]["memory_id"]
        await agent.start_new_phase(
            TaskPhase.CODE_LOCATION,
            state,
            [{"phase": "paper_retrieval", "conclusion": "已完成论文检索"}],
        )
        second = state.metadata["long_term_memory"][1]["memory_id"]
        assert first != second

    asyncio.run(run())
    assert len(recall.queries) == 2
    assert recall.queries[0].text != recall.queries[1].text
    assert "当前阶段" in recall.queries[1].text

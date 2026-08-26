from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from paper_agent.common.capabilities import (
    CapabilityRegistry,
    PaperSearchAdapter,
)
from paper_agent.common.conversation_service import ConversationService
from paper_agent.common.persistence import ConversationStore
from paper_agent.common.tools import ToolResult


class FakeToolRegistry:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        self.calls.append((tool_name, kwargs))
        return ToolResult.ok(
            data={
                "query": kwargs["query"],
                "total_found": 1,
                "results": [
                    {
                        "arxiv_id": "2401.12345v1",
                        "title": "Agents in Research",
                        "authors": ["Author"],
                        "abstract": "A paper.",
                        "url": "https://arxiv.org/abs/2401.12345v1",
                        "pdf_url": "https://arxiv.org/pdf/2401.12345v1",
                        "published_date": "2024-01-01",
                        "version": "1",
                        "source": "arxiv",
                    }
                ],
            }
        )


def test_chat_message_routes_to_paper_search_and_persists_context():
    with tempfile.TemporaryDirectory() as temp_dir:
        store = ConversationStore(Path(temp_dir))
        session = store.create_session()
        tools = FakeToolRegistry()
        registry = CapabilityRegistry()
        registry.register(PaperSearchAdapter(tools))  # type: ignore[arg-type]
        service = ConversationService(store, registry)

        response = asyncio.run(
            service.handle_message(session.session_id, "检索多智能体协作论文，前 3 篇")
        )

        assert response["status"] == "waiting_confirmation"
        assert response["result"]["success"] is True
        assert len(response["result"]["data"]["candidates"]) == 1
        candidate_set_id = response["result"]["data"]["candidate_set_id"]
        assert response["result"]["data"]["session_id"] == session.session_id
        assert response["result"]["data"]["queried_at"]
        candidate_path = (
            Path(temp_dir) / "paper_candidates" / f"{candidate_set_id}.json"
        )
        assert candidate_path.exists()
        persisted_set = store.load_paper_candidate_set(candidate_set_id)
        assert persisted_set is not None
        assert persisted_set.session_id == session.session_id
        assert persisted_set.queried_at is not None
        assert persisted_set.query_used == "multi-agent collaboration"
        assert tools.calls == [
            (
                "arxiv_search",
                {
                    "query": "multi-agent collaboration",
                    "max_results": 3,
                    "categories": [],
                },
            )
        ]
        messages = store.list_messages(session.session_id)
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[-1].artifact_refs == [
            f"paper_candidates/{candidate_set_id}.json"
        ]
        restored = store.load_session(session.session_id)
        assert restored.context.current_intent == "paper_search"
        assert len(restored.context.candidate_papers) == 1
        assert restored.context.candidate_set_id == candidate_set_id
        assert restored.context.candidate_queried_at == persisted_set.queried_at


def test_unsupported_chat_message_returns_clarification_without_tool_call():
    with tempfile.TemporaryDirectory() as temp_dir:
        store = ConversationStore(Path(temp_dir))
        session = store.create_session()
        tools = FakeToolRegistry()
        registry = CapabilityRegistry()
        registry.register(PaperSearchAdapter(tools))  # type: ignore[arg-type]
        service = ConversationService(store, registry)

        response = asyncio.run(
            service.handle_message(session.session_id, "你好")
        )

        assert response["status"] == "waiting_user_input"
        assert response["decision"]["matched"] is False
        assert tools.calls == []
        assert len(store.list_messages(session.session_id)) == 2


def test_candidate_set_persistence_failure_is_not_reported_as_success():
    with tempfile.TemporaryDirectory() as temp_dir:
        store = ConversationStore(Path(temp_dir))
        session = store.create_session()
        tools = FakeToolRegistry()
        registry = CapabilityRegistry()
        registry.register(PaperSearchAdapter(tools))  # type: ignore[arg-type]
        service = ConversationService(store, registry)

        def fail_persistence(_candidate_set):
            raise OSError("disk full")

        store.save_paper_candidate_set = fail_persistence  # type: ignore[method-assign]
        response = asyncio.run(
            service.handle_message(session.session_id, "检索 agent memory")
        )

        assert response["status"] == "failed"
        assert response["result"]["success"] is False
        assert "disk full" in response["result"]["error"]


if __name__ == "__main__":
    test_chat_message_routes_to_paper_search_and_persists_context()
    test_unsupported_chat_message_returns_clarification_without_tool_call()
    test_candidate_set_persistence_failure_is_not_reported_as_success()
    print("3 passed")

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from paper_agent.common.capabilities import (
    CapabilityRegistry,
    IntentDecision,
    PaperSearchAdapter,
)
from paper_agent.common.conversation_service import ConversationService
from paper_agent.common.models.conversation import ConversationMessage
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


class FakeLLMRouter:
    def __init__(self):
        self.calls: list[tuple[ConversationMessage, Any]] = []

    async def route(self, message, projection):
        self.calls.append((message, projection))
        return IntentDecision(
            matched=False,
            source="fallback",
            reason="ambiguous test request",
            clarification_question="请说明要执行的论文操作。",
        )


def make_service(temp_dir: str, llm_router: FakeLLMRouter):
    store = ConversationStore(Path(temp_dir))
    tools = FakeToolRegistry()
    registry = CapabilityRegistry()
    registry.register(PaperSearchAdapter(tools))  # type: ignore[arg-type]
    return store, store.create_session(), tools, ConversationService(
        store,
        registry,
        llm_router=llm_router,
    )


def test_conversation_service_uses_deterministic_route_without_llm():
    with tempfile.TemporaryDirectory() as temp_dir:
        llm_router = FakeLLMRouter()
        store, session, tools, service = make_service(temp_dir, llm_router)

        response = asyncio.run(
            service.handle_message(session.session_id, "检索 multi-agent papers")
        )

        assert response["status"] == "waiting_confirmation"
        assert response["decision"]["source"] == "deterministic"
        assert llm_router.calls == []
        assert tools.calls


def test_conversation_service_projects_context_before_llm_route():
    with tempfile.TemporaryDirectory() as temp_dir:
        llm_router = FakeLLMRouter()
        store, session, tools, service = make_service(temp_dir, llm_router)

        response = asyncio.run(
            service.handle_message(session.session_id, "帮我继续处理刚才那篇")
        )

        assert response["status"] == "waiting_user_input"
        assert response["decision"]["source"] == "fallback"
        assert tools.calls == []
        assert len(llm_router.calls) == 1
        routed_message, projection = llm_router.calls[0]
        assert routed_message.content == "帮我继续处理刚才那篇"
        assert projection.session_status == "active"
        assert len(projection.recent_messages) == 1
        assert projection.recent_messages[0].content == routed_message.content
        assert len(store.list_messages(session.session_id)) == 2


if __name__ == "__main__":
    test_conversation_service_uses_deterministic_route_without_llm()
    test_conversation_service_projects_context_before_llm_route()
    print("2 passed")

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from paper_agent.common.capabilities import (
    CapabilityAdapter,
    CapabilityRegistry,
    CapabilityResult,
    ExecutionContext,
    HybridIntentRouter,
    IntentContextProjector,
    IntentDecision,
)
from paper_agent.common.capabilities.router import DeterministicIntentRouter
from paper_agent.common.models.conversation import ConversationContext, ConversationMessage, ConversationSession


class DummyAdapter(CapabilityAdapter):
    def __init__(self, name: str):
        super().__init__(tool_registry=None)  # type: ignore[arg-type]
        self.name = name

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        return CapabilityResult.succeeded(data=arguments)


class FakeLLMRouter:
    def __init__(self, decision: IntentDecision, error: Exception | None = None):
        self.decision = decision
        self.error = error
        self.calls: list[tuple[ConversationMessage, Any]] = []

    async def route(self, message, projection):
        self.calls.append((message, projection))
        if self.error:
            raise self.error
        return self.decision


def deterministic(*names: str) -> DeterministicIntentRouter:
    registry = CapabilityRegistry()
    for name in names:
        registry.register(DummyAdapter(name))
    return DeterministicIntentRouter(registry)


def projection_for(content: str):
    session = ConversationSession(session_id="session-1")
    message = ConversationMessage(
        session_id=session.session_id,
        role="user",
        content=content,
    )
    return message, IntentContextProjector().project(session, [message])


def llm_decision() -> IntentDecision:
    return IntentDecision(
        matched=True,
        intent="process_selected_paper",
        capability_name="paper_processing",
        execution_kind="workflow",
        confidence=0.9,
        source="llm",
    )


def test_explicit_deterministic_intent_has_priority_over_llm():
    provider = FakeLLMRouter(llm_decision())
    hybrid = HybridIntentRouter(
        deterministic("paper_search"),
        provider,
    )
    message, projection = projection_for("检索 multi-agent papers")

    decision = asyncio.run(
        hybrid.route(message, ConversationContext(), projection)
    )

    assert decision.intent == "paper_search"
    assert decision.source == "deterministic"
    assert provider.calls == []


def test_deterministic_missing_arguments_does_not_fall_through_to_llm():
    provider = FakeLLMRouter(llm_decision())
    hybrid = HybridIntentRouter(
        deterministic("paper_parse"),
        provider,
    )
    message, projection = projection_for("解析论文")

    decision = asyncio.run(
        hybrid.route(message, ConversationContext(), projection)
    )

    assert decision.matched is False
    assert decision.capability_name == "paper_parse"
    assert decision.missing_arguments == ["artifact_path"]
    assert provider.calls == []


def test_ambiguous_intent_is_delegated_to_llm():
    provider = FakeLLMRouter(llm_decision())
    hybrid = HybridIntentRouter(
        deterministic(
            "paper_search",
            "paper_download",
            "paper_parse",
            "paper_glossary",
            "paper_translate",
            "paper_summary",
        ),
        provider,
    )
    message, projection = projection_for("帮我继续处理刚才那篇")

    decision = asyncio.run(
        hybrid.route(message, ConversationContext(), projection)
    )

    assert decision == llm_decision()
    assert len(provider.calls) == 1


def test_ambiguous_intent_without_projection_is_not_executed():
    provider = FakeLLMRouter(llm_decision())
    hybrid = HybridIntentRouter(deterministic("paper_search"), provider)
    message, _ = projection_for("帮我继续处理刚才那篇")

    decision = asyncio.run(
        hybrid.route(message, ConversationContext(), projection=None)
    )

    assert decision.matched is False
    assert decision.source == "fallback"
    assert provider.calls == []


def test_unavailable_deterministic_capability_does_not_get_reinterpreted():
    provider = FakeLLMRouter(llm_decision())
    hybrid = HybridIntentRouter(deterministic(), provider)
    message, projection = projection_for("解析 papers/paper.json")

    decision = asyncio.run(
        hybrid.route(message, ConversationContext(), projection)
    )

    assert decision.matched is False
    assert decision.capability_name == "paper_parse"
    assert provider.calls == []


def test_llm_failure_is_not_silently_converted_to_success():
    provider = FakeLLMRouter(
        llm_decision(),
        error=RuntimeError("llm unavailable"),
    )
    hybrid = HybridIntentRouter(deterministic("paper_search"), provider)
    message, projection = projection_for("帮我处理刚才那篇")

    with pytest.raises(RuntimeError, match="llm unavailable"):
        asyncio.run(
            hybrid.route(message, ConversationContext(), projection)
        )


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

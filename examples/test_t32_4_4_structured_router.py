from __future__ import annotations

import asyncio
from typing import Any

import pytest

from paper_agent.common.capabilities import (
    CapabilityCatalog,
    CapabilityRegistry,
    IntentContextProjector,
    IntentRouterRequest,
    IntentRouterResponse,
    LLMIntentDecisionRouter,
    register_default_capabilities,
)
from paper_agent.common.models.conversation import (
    ConversationContext,
    ConversationMessage,
    ConversationSession,
)


class FakeProvider:
    def __init__(self, content: str = "{}", error: Exception | None = None):
        self.content = content
        self.error = error
        self.requests: list[IntentRouterRequest] = []

    async def decide(self, request: IntentRouterRequest) -> IntentRouterResponse:
        self.requests.append(request)
        if self.error:
            raise self.error
        return IntentRouterResponse(content=self.content)


def router(provider: FakeProvider) -> LLMIntentDecisionRouter:
    registry = register_default_capabilities(CapabilityRegistry(), object())
    return LLMIntentDecisionRouter(
        provider,
        CapabilityCatalog.from_registry(registry),
    )


def projection() -> tuple[ConversationMessage, Any]:
    session = ConversationSession(
        session_id="session-1",
        context=ConversationContext(
            candidate_papers=[
                {
                    "arxiv_id": "2412.05449v1",
                    "title": "A paper",
                }
            ],
            candidate_set_id="set-1",
        ),
    )
    message = ConversationMessage(
        session_id=session.session_id,
        role="user",
        content="下载刚才检索结果中的第一篇",
    )
    context = IntentContextProjector().project(session, [message])
    return message, context


def valid_content() -> str:
    return (
        "{"
        '"matched": true, '
        '"intent": "download_selected_paper", '
        '"capability_name": "paper_download", '
        '"execution_kind": "tool", '
        '"confidence": 0.94, '
        '"arguments": {}, '
        '"references": [{"type": "candidate_index", "value": 1}], '
        '"missing_arguments": [], '
        '"clarification_question": null, '
        '"reason": null'
        "}"
    )


def test_valid_json_becomes_llm_intent_decision():
    provider = FakeProvider(valid_content())
    llm_router = router(provider)
    message, context = projection()

    decision = asyncio.run(llm_router.route(message, context))

    assert decision.matched is True
    assert decision.intent == "download_selected_paper"
    assert decision.capability_name == "paper_download"
    assert decision.references[0].type == "candidate_index"
    assert decision.references[0].value == 1
    assert decision.source == "llm"


def test_router_builds_request_with_context_and_catalog():
    provider = FakeProvider(valid_content())
    llm_router = router(provider)
    message, context = projection()

    request = llm_router.build_request(message, context)

    assert len(request.messages) == 3
    assert "CAPABILITY_CATALOG" in request.messages[0].content
    assert "paper_download" in request.messages[0].content
    assert "CONVERSATION_CONTEXT" in request.messages[1].content
    assert "2412.05449v1" in request.messages[1].content
    assert request.messages[2].content == message.content
    assert request.response_format == {"type": "json_object"}


def test_invalid_json_returns_non_executable_fallback():
    provider = FakeProvider("not-json")
    llm_router = router(provider)
    message, context = projection()

    decision = asyncio.run(llm_router.route(message, context))

    assert decision.matched is False
    assert decision.source == "fallback"
    assert decision.capability_name is None
    assert decision.clarification_question


def test_json_array_returns_non_executable_fallback():
    provider = FakeProvider("[]")
    llm_router = router(provider)

    decision = llm_router.parse_response("[]")

    assert decision.matched is False
    assert decision.source == "fallback"
    assert decision.reason == "LLM decision must be a JSON object"


def test_invalid_intent_schema_returns_non_executable_fallback():
    provider = FakeProvider(
        '{"matched":true,"intent":"parse_paper",'
        '"capability_name":"paper_parse",'
        '"missing_arguments":["artifact_path"]}'
    )
    llm_router = router(provider)
    message, context = projection()

    decision = asyncio.run(llm_router.route(message, context))

    assert decision.matched is False
    assert decision.source == "fallback"
    assert "validation" in (decision.reason or "")


def test_router_controls_source_instead_of_trusting_model():
    content = valid_content().replace('"reason": null', '"reason": null, "source": "deterministic"')

    decision = router(FakeProvider(content)).parse_response(content)

    assert decision.source == "llm"


def test_non_user_message_does_not_call_provider():
    provider = FakeProvider(valid_content())
    llm_router = router(provider)
    session = ConversationSession(session_id="session-1")
    message = ConversationMessage(
        session_id=session.session_id,
        role="assistant",
        content="assistant message",
    )
    context = IntentContextProjector().project(session, [message])

    decision = asyncio.run(llm_router.route(message, context))

    assert decision.matched is False
    assert decision.source == "fallback"
    assert provider.requests == []


def test_provider_failure_is_propagated():
    provider = FakeProvider(error=RuntimeError("provider unavailable"))
    llm_router = router(provider)
    message, context = projection()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(llm_router.route(message, context))


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

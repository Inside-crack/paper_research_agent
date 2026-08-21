from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from paper_agent.common.capabilities import (
    IntentRouterProvider,
    IntentRouterRequest,
    IntentRouterResponse,
    LLMIntentRouterProvider,
)
from paper_agent.common.llm import LLMMessage, LLMResponse, MessageRole


class FakeLLM:
    def __init__(self, response: LLMResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def agenerate(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


def request() -> IntentRouterRequest:
    return IntentRouterRequest(
        messages=[
            LLMMessage(
                role=MessageRole.SYSTEM,
                content="Return a JSON intent decision.",
            ),
            LLMMessage(
                role=MessageRole.USER,
                content="Download the second paper.",
            ),
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=512,
        provider_options={"seed": 7},
    )


def test_request_requires_at_least_one_message():
    with pytest.raises(ValidationError):
        IntentRouterRequest(messages=[])


def test_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        IntentRouterRequest(
            messages=[
                LLMMessage(role=MessageRole.USER, content="hello")
            ],
            prompt="must-not-be-accepted",
        )


def test_fake_provider_satisfies_protocol_contract():
    class FakeProvider:
        async def decide(
            self,
            request: IntentRouterRequest,
        ) -> IntentRouterResponse:
            return IntentRouterResponse(content="{}")

    assert isinstance(FakeProvider(), IntentRouterProvider)


def test_llm_provider_forwards_request_and_preserves_raw_content():
    llm = FakeLLM(
        response=LLMResponse(
            content='{"intent":"download_selected_paper"}',
            model="deepseek-v4-flash",
            finish_reason="stop",
            input_tokens=120,
            output_tokens=18,
            duration_ms=42,
            raw_response={"id": "response-1"},
        )
    )
    provider = LLMIntentRouterProvider(llm)  # type: ignore[arg-type]

    result = asyncio.run(provider.decide(request()))

    assert result.content == '{"intent":"download_selected_paper"}'
    assert result.model == "deepseek-v4-flash"
    assert result.input_tokens == 120
    assert result.output_tokens == 18
    assert result.raw_response == {"id": "response-1"}
    assert llm.calls == [
        {
            "messages": request().messages,
            "temperature": 0.0,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
            "seed": 7,
        }
    ]


def test_provider_does_not_parse_model_content():
    content = "Explanation before JSON\n{\"intent\":\"parse_paper\"}"
    llm = FakeLLM(response=LLMResponse(content=content))
    provider = LLMIntentRouterProvider(llm)  # type: ignore[arg-type]

    result = asyncio.run(provider.decide(request()))

    assert result.content == content


def test_provider_preserves_llm_failure():
    error = RuntimeError("provider timeout")
    llm = FakeLLM(error=error)
    provider = LLMIntentRouterProvider(llm)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="provider timeout"):
        asyncio.run(provider.decide(request()))


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

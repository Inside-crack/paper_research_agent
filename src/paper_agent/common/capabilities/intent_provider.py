from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ..llm import BaseLLM, LLMMessage


class IntentRouterRequest(BaseModel):
    """Provider input prepared by the future Router orchestration layer."""

    model_config = ConfigDict(extra="forbid")

    messages: list[LLMMessage] = Field(min_length=1)
    response_format: dict[str, str] = Field(
        default_factory=lambda: {"type": "json_object"}
    )
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    provider_options: dict[str, Any] = Field(default_factory=dict)


class IntentRouterResponse(BaseModel):
    """Raw model output and transport metadata, before decision validation."""

    model_config = ConfigDict(extra="forbid")

    content: str
    model: str = ""
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    raw_response: Optional[dict[str, Any]] = None


@runtime_checkable
class IntentRouterProvider(Protocol):
    """Provider boundary for model-backed intent decisions."""

    async def decide(
        self,
        request: IntentRouterRequest,
    ) -> IntentRouterResponse:
        """Return raw model content without parsing or executing it."""


class LLMIntentRouterProvider:
    """Adapt the project's existing BaseLLM to the IntentRouterProvider contract."""

    def __init__(self, llm: BaseLLM):
        self.llm = llm

    async def decide(
        self,
        request: IntentRouterRequest,
    ) -> IntentRouterResponse:
        response = await self.llm.agenerate(
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format=request.response_format,
            **request.provider_options,
        )
        return IntentRouterResponse(
            content=response.content,
            model=response.model,
            finish_reason=response.finish_reason,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            duration_ms=response.duration_ms,
            raw_response=response.raw_response,
        )

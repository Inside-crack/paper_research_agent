from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from .base import BaseLLM, LLMMessage, LLMResponse, MessageRole


class OpenAILLM(BaseLLM):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str = "https://api.openai.com/v1",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout: int = 120,
        **kwargs: Any,
    ):
        super().__init__(model, temperature, max_tokens, timeout, **kwargs)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout)

    async def agenerate(
        self,
        messages: list[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        start_time = time.time()

        messages = self._prepare_messages(messages)

        openai_messages = [self._convert_message(msg) for msg in messages]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }

        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", self.model),
            finish_reason=choice.get("finish_reason", ""),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            duration_ms=self._track_duration(start_time),
            raw_response=data,
        )

    def _convert_message(self, message: LLMMessage) -> dict[str, Any]:
        msg_dict: dict[str, Any] = {
            "role": message.role.value,
            "content": message.content,
        }
        if message.name:
            msg_dict["name"] = message.name
        if message.tool_call_id:
            msg_dict["tool_call_id"] = message.tool_call_id
        return msg_dict

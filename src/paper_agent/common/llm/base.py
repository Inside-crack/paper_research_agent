from __future__ import annotations

import enum
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..logging import get_logger

logger = get_logger(__name__)

CONTEXT_WARNING_RATIO = 0.70
CONTEXT_COMPRESS_RATIO = 0.85
CONTEXT_CRITICAL_RATIO = 0.95
CONTEXT_TARGET_RATIO = 0.75
CHARS_PER_TOKEN_ESTIMATE = 4
DEFAULT_CONTEXT_WINDOW = 128000
RESERVED_OUTPUT_TOKENS = 4096


class MessageRole(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class LLMMessage(BaseModel):
    role: MessageRole
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_anchor(self) -> bool:
        return bool(self.metadata.get("anchor", False))

    @property
    def priority(self) -> int:
        return int(self.metadata.get("priority", 0))


class LLMResponse(BaseModel):
    content: str
    model: str = ""
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    raw_response: Optional[dict[str, Any]] = None


def estimate_tokens(messages: list[LLMMessage]) -> int:
    total = 0
    for m in messages:
        total += max(1, len(m.content) // CHARS_PER_TOKEN_ESTIMATE)
    return total


def compress_messages(
    messages: list[LLMMessage],
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    reserved_output: int = RESERVED_OUTPUT_TOKENS,
) -> tuple[list[LLMMessage], int]:
    effective_window = context_window - reserved_output
    current_tokens = estimate_tokens(messages)

    if current_tokens <= int(effective_window * CONTEXT_COMPRESS_RATIO):
        return messages, 0

    logger.warning(
        f"[context] Token budget pressure: ~{current_tokens} tokens / {effective_window} effective window "
        f"({current_tokens / effective_window:.0%}). Starting compression."
    )

    candidates = [
        (idx, msg) for idx, msg in enumerate(messages)
        if not msg.is_anchor and msg.role != MessageRole.SYSTEM
    ]
    candidates.sort(key=lambda x: (x[1].priority, x[0]))

    removed = 0
    remove_ids: set[int] = set()
    target = int(effective_window * CONTEXT_TARGET_RATIO)

    def _current_tokens() -> int:
        total = 0
        for i, m in enumerate(messages):
            if i in remove_ids:
                continue
            total += max(1, len(m.content) // CHARS_PER_TOKEN_ESTIMATE)
        return total

    for idx, msg in candidates:
        if _current_tokens() <= target:
            break
        if idx not in remove_ids:
            remove_ids.add(idx)
            removed += 1

    working = [m for i, m in enumerate(messages) if i not in remove_ids]
    final_tokens = estimate_tokens(working)

    if final_tokens > int(effective_window * CONTEXT_CRITICAL_RATIO):
        logger.error(
            f"[context] CRITICAL: After removing {removed} messages, still at {final_tokens} tokens "
            f"(>{CONTEXT_CRITICAL_RATIO:.0%}). Performing aggressive compression: keeping anchors + last 2 messages."
        )
        anchors = [m for m in working if m.is_anchor or m.role == MessageRole.SYSTEM]
        tail = working[-2:] if len(working) > 2 else []
        anchor_objs = {id(m) for m in anchors}
        tail = [m for m in tail if id(m) not in anchor_objs]
        working = anchors + tail
        removed = len(messages) - len(working)
        final_tokens = estimate_tokens(working)

    if removed > 0:
        notice = (
            f"[Context compressed: {removed} earlier non-critical messages removed to fit the context window "
            f"(kept {len(working)} messages, ~{final_tokens} tokens). "
            f"Use load_artifact to access previously persisted results if needed.]"
        )
        notice_msg = LLMMessage(role=MessageRole.SYSTEM, content=notice, metadata={"anchor": True, "priority": 100})
        working.append(notice_msg)
        logger.warning(f"[context] Compressed: removed {removed} messages, final ~{estimate_tokens(working)} tokens.")

    return working, removed


class BaseLLM(ABC):
    def __init__(
        self,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout: int = 120,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        **kwargs: Any,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.context_window = context_window
        self.config = kwargs

    def _prepare_messages(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        tokens = estimate_tokens(messages)
        effective_window = self.context_window - self.max_tokens
        ratio = tokens / effective_window if effective_window > 0 else 1.0

        if ratio >= CONTEXT_CRITICAL_RATIO:
            logger.error(f"[context] CRITICAL threshold reached: {tokens}/{effective_window} tokens ({ratio:.0%})")
        elif ratio >= CONTEXT_COMPRESS_RATIO:
            logger.warning(f"[context] COMPRESS threshold reached: {tokens}/{effective_window} tokens ({ratio:.0%})")
        elif ratio >= CONTEXT_WARNING_RATIO:
            logger.info(f"[context] WARNING: {tokens}/{effective_window} tokens ({ratio:.0%})")

        compressed, removed = compress_messages(messages, self.context_window, self.max_tokens)
        if removed > 0:
            logger.info(f"[context] Removed {removed} messages during compression.")
        return compressed

    @abstractmethod
    async def agenerate(
        self,
        messages: list[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        pass

    def generate(
        self,
        messages: list[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        import asyncio

        return asyncio.run(
            self.agenerate(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                **kwargs,
            )
        )

    def system_message(self, content: str, anchor: bool = True, priority: int = 100) -> LLMMessage:
        return LLMMessage(role=MessageRole.SYSTEM, content=content, metadata={"anchor": anchor, "priority": priority})

    def user_message(self, content: str, anchor: bool = False, priority: int = 50) -> LLMMessage:
        return LLMMessage(role=MessageRole.USER, content=content, metadata={"anchor": anchor, "priority": priority})

    def assistant_message(self, content: str, anchor: bool = False, priority: int = 50) -> LLMMessage:
        return LLMMessage(role=MessageRole.ASSISTANT, content=content, metadata={"anchor": anchor, "priority": priority})

    def _track_duration(self, start_time: float) -> int:
        return int((time.time() - start_time) * 1000)

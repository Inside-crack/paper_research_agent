from __future__ import annotations

from typing import Optional, Protocol

from ..models.conversation import ConversationContext, ConversationMessage
from .context_projection import IntentContextProjection
from .intent_schema import IntentDecision
from .router import DeterministicIntentRouter


class LLMDecisionRouter(Protocol):
    async def route(
        self,
        message: ConversationMessage,
        projection: IntentContextProjection,
    ) -> IntentDecision:
        ...


class HybridIntentRouter:
    """Prefer deterministic routing and delegate only unknown requests to LLM."""

    def __init__(
        self,
        deterministic_router: DeterministicIntentRouter,
        llm_router: Optional[LLMDecisionRouter] = None,
    ):
        self.deterministic_router = deterministic_router
        self.llm_router = llm_router

    async def route(
        self,
        message: ConversationMessage,
        context: ConversationContext,
        projection: Optional[IntentContextProjection] = None,
    ) -> IntentDecision:
        deterministic = self.deterministic_router.route(message, context)
        if self._deterministic_handled(deterministic):
            return deterministic

        if self.llm_router is None or projection is None:
            return self._fallback(
                "LLM routing requires a projected context and configured provider"
            )

        return await self.llm_router.route(message, projection)

    @staticmethod
    def _deterministic_handled(decision: IntentDecision) -> bool:
        # A recognized capability with missing parameters must go to clarification,
        # not to a second classifier that may invent the missing values.
        return bool(
            decision.capability_name
            or decision.matched
            or decision.source == "fallback"
        )

    @staticmethod
    def _fallback(reason: str) -> IntentDecision:
        return IntentDecision(
            matched=False,
            source="fallback",
            reason=reason,
            clarification_question="请补充需求，或明确说明要检索、下载、解析、翻译还是总结论文。",
        )

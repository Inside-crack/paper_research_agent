from __future__ import annotations

import time
from typing import Optional, Protocol

from ..models.conversation import ConversationContext, ConversationMessage
from .clarification import ClarificationPolicy
from .context_projection import IntentContextProjection
from .intent_schema import IntentDecision
from .observability import RoutingDecisionEvent, RoutingObserver
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
        clarification_policy: Optional[ClarificationPolicy] = None,
        observer: Optional[RoutingObserver] = None,
    ):
        self.deterministic_router = deterministic_router
        self.llm_router = llm_router
        self.clarification_policy = clarification_policy or ClarificationPolicy()
        self.observer = observer

    async def route(
        self,
        message: ConversationMessage,
        context: ConversationContext,
        projection: Optional[IntentContextProjection] = None,
    ) -> IntentDecision:
        started = time.monotonic()
        deterministic = self.deterministic_router.route(message, context)
        if self._deterministic_handled(deterministic):
            return self._finalize(deterministic, started, message)

        if self.llm_router is None or projection is None:
            return self._finalize(
                self._fallback(
                    "LLM routing requires a projected context and configured provider"
                ),
                started,
                message,
            )

        llm_decision = await self.llm_router.route(message, projection)
        return self._finalize(llm_decision, started, message)

    def _finalize(
        self,
        decision: IntentDecision,
        started: float,
        message: ConversationMessage,
    ) -> IntentDecision:
        resolved = self.clarification_policy.evaluate(decision).decision
        if self.observer is not None:
            event = RoutingDecisionEvent.from_decision(
                resolved,
                session_id=message.session_id,
                message_id=message.message_id,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            try:
                self.observer.record(event)
            except Exception:
                # Observability must never change routing or execution behavior.
                pass
        return resolved

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

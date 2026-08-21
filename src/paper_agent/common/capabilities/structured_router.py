from __future__ import annotations

import json
from typing import Optional

from pydantic import ValidationError

from ..llm import LLMMessage, MessageRole
from ..models.conversation import ConversationMessage
from .catalog import CapabilityCatalog
from .context_projection import IntentContextProjection
from .decision_validator import (
    CapabilityDecisionValidationError,
    CapabilityDecisionValidator,
)
from .intent_provider import (
    IntentRouterProvider,
    IntentRouterRequest,
)
from .intent_schema import IntentDecision
from .preconditions import IntentPreconditionResolver, IntentResolution


class LLMIntentDecisionRouter:
    """Generate schema-validated IntentDecision values through a Provider."""

    _SYSTEM_PROMPT = (
        "You are an intent router for a paper research agent. "
        "Return exactly one JSON object and no Markdown or explanation. "
        "Choose only a capability from CAPABILITY_CATALOG. "
        "Do not execute tools, invent capabilities, resolve files, or create tasks. "
        "Use references for conversation-context references such as candidate_index. "
        "If the request cannot be executed yet, set matched to false and list "
        "missing_arguments."
    )

    def __init__(
        self,
        provider: IntentRouterProvider,
        catalog: CapabilityCatalog,
        *,
        temperature: Optional[float] = 0.0,
        max_tokens: Optional[int] = 2048,
    ):
        self.provider = provider
        self.catalog = catalog
        self.decision_validator = CapabilityDecisionValidator(catalog)
        self.precondition_resolver = IntentPreconditionResolver(catalog)
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def route(
        self,
        message: ConversationMessage,
        projection: IntentContextProjection,
    ) -> IntentDecision:
        if not isinstance(message, ConversationMessage):
            raise TypeError("message must be a ConversationMessage")
        if not isinstance(projection, IntentContextProjection):
            raise TypeError("projection must be an IntentContextProjection")
        if message.role != "user":
            return self._fallback("Only user messages can be routed")

        request = self.build_request(message, projection)
        response = await self.provider.decide(request)
        return self.parse_response(response.content)

    def build_request(
        self,
        message: ConversationMessage,
        projection: IntentContextProjection,
    ) -> IntentRouterRequest:
        context_json = json.dumps(
            projection.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        catalog_json = json.dumps(
            self.catalog.as_prompt_schema(),
            ensure_ascii=False,
            sort_keys=True,
        )
        system_content = (
            f"{self._SYSTEM_PROMPT}\n\n"
            f"INTENT_DECISION_FIELDS:\n"
            f"{json.dumps(IntentDecision.model_json_schema(), ensure_ascii=False)}\n\n"
            f"CAPABILITY_CATALOG:\n{catalog_json}"
        )
        context_content = f"CONVERSATION_CONTEXT:\n{context_json}"
        return IntentRouterRequest(
            messages=[
                LLMMessage(role=MessageRole.SYSTEM, content=system_content),
                LLMMessage(role=MessageRole.SYSTEM, content=context_content),
                LLMMessage(role=MessageRole.USER, content=message.content),
            ],
            response_format={"type": "json_object"},
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    def parse_response(self, content: str) -> IntentDecision:
        if not isinstance(content, str) or not content.strip():
            return self._fallback("LLM returned an empty decision")

        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            return self._fallback("LLM returned invalid JSON")

        if not isinstance(payload, dict):
            return self._fallback("LLM decision must be a JSON object")

        # The source is controlled by this router, never by the model.
        payload = dict(payload)
        payload.pop("source", None)
        payload["source"] = "llm"
        try:
            decision = IntentDecision.model_validate(payload)
            return self.decision_validator.validate(decision)
        except (
            ValidationError,
            CapabilityDecisionValidationError,
        ):
            return self._fallback(
                "LLM decision failed Schema or Capability validation"
            )

    def resolve_decision(
        self,
        decision: IntentDecision,
        projection: IntentContextProjection,
    ) -> IntentResolution:
        """Resolve context references and prerequisites without executing anything."""
        return self.precondition_resolver.resolve(decision, projection)

    @staticmethod
    def _fallback(reason: str) -> IntentDecision:
        return IntentDecision(
            matched=False,
            confidence=0.0,
            source="fallback",
            reason=reason,
            clarification_question="我暂时无法确定要执行的操作，请换一种方式描述。",
        )

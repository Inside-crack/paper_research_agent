from __future__ import annotations

import inspect
from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..models.conversation import ConversationContext, ConversationMessage
from .intent_schema import IntentDecision


class RouterForEvaluation(Protocol):
    async def route(
        self,
        message: ConversationMessage,
        context: ConversationContext,
        projection: object = None,
    ) -> IntentDecision:
        ...


class RoutingEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    content: str
    expected_matched: bool
    expected_capability: Optional[str] = None
    expected_source: Optional[str] = None
    expected_clarification: Optional[bool] = None


class RoutingEvaluationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    passed: bool
    decision: IntentDecision
    failures: list[str] = Field(default_factory=list)


class RoutingEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    passed: int
    failed: int
    accuracy: float
    items: list[RoutingEvaluationItem]


async def evaluate_router(
    router: RouterForEvaluation,
    cases: list[RoutingEvaluationCase],
    *,
    context: Optional[ConversationContext] = None,
) -> RoutingEvaluationReport:
    items: list[RoutingEvaluationItem] = []
    shared_context = context or ConversationContext()
    for case in cases:
        message = ConversationMessage(
            session_id="evaluation",
            role="user",
            content=case.content,
        )
        route_parameters = inspect.signature(router.route).parameters
        if len(route_parameters) >= 3:
            routed = router.route(message, shared_context, None)
        else:
            routed = router.route(message, shared_context)
        decision = await routed if inspect.isawaitable(routed) else routed
        failures: list[str] = []
        if decision.matched != case.expected_matched:
            failures.append("matched")
        if (
            case.expected_capability is not None
            and decision.capability_name != case.expected_capability
        ):
            failures.append("capability_name")
        if case.expected_source is not None and decision.source != case.expected_source:
            failures.append("source")
        if (
            case.expected_clarification is not None
            and (not decision.matched) != case.expected_clarification
        ):
            failures.append("clarification")
        items.append(
            RoutingEvaluationItem(
                case_id=case.case_id,
                passed=not failures,
                decision=decision,
                failures=failures,
            )
        )
    total = len(items)
    passed = sum(item.passed for item in items)
    return RoutingEvaluationReport(
        total=total,
        passed=passed,
        failed=total - passed,
        accuracy=(passed / total) if total else 1.0,
        items=items,
    )

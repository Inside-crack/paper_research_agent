from __future__ import annotations

import asyncio
from typing import Any

from paper_agent.common.capabilities import (
    CapabilityAdapter,
    CapabilityCatalog,
    CapabilityExecutionSecurityPolicy,
    CapabilityRegistry,
    CapabilityResult,
    ExecutionContext,
    InMemoryRoutingObserver,
    IntentDecision,
    RoutingEvaluationCase,
    evaluate_router,
)
from paper_agent.common.capabilities.hybrid_router import HybridIntentRouter
from paper_agent.common.capabilities.router import DeterministicIntentRouter
from paper_agent.common.models.conversation import ConversationContext, ConversationMessage


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


def registry() -> CapabilityRegistry:
    result = CapabilityRegistry()
    result.register(
        DummyAdapter("paper_parse"),
        input_schema={
            "type": "object",
            "properties": {
                "artifact_path": {"type": "string", "minLength": 1},
            },
            "required": ["artifact_path"],
            "additionalProperties": False,
        },
        allowed_intents=["parse_paper"],
    )
    return result


def test_security_policy_allows_registered_schema_valid_decision():
    catalog = CapabilityCatalog.from_registry(registry())
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        arguments={"artifact_path": "papers/paper.json"},
        confidence=0.9,
    )

    result = CapabilityExecutionSecurityPolicy(catalog).authorize(decision)

    assert result.allowed is True


def test_security_policy_denies_unknown_capability():
    catalog = CapabilityCatalog.from_registry(registry())
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_download",
        arguments={"artifact_path": "papers/paper.json"},
        confidence=0.9,
    )

    result = CapabilityExecutionSecurityPolicy(catalog).authorize(decision)

    assert result.allowed is False
    assert result.reason


def test_security_policy_denies_schema_bypass():
    catalog = CapabilityCatalog.from_registry(registry())
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        arguments={
            "artifact_path": "papers/paper.json",
            "command": "rm -rf /",
        },
        confidence=0.9,
    )

    result = CapabilityExecutionSecurityPolicy(catalog).authorize(decision)

    assert result.allowed is False
    assert "Invalid arguments" in (result.reason or "")


def test_security_policy_denies_absolute_and_traversal_paths():
    catalog = CapabilityCatalog.from_registry(registry())
    policy = CapabilityExecutionSecurityPolicy(catalog)
    for path in ("/tmp/paper.json", "../paper.json", "papers/../../secret.json"):
        decision = IntentDecision(
            matched=True,
            intent="parse_paper",
            capability_name="paper_parse",
            arguments={"artifact_path": path},
            confidence=0.9,
        )
        result = policy.authorize(decision)
        assert result.allowed is False
        assert "safe path" in (result.reason or "")


def test_security_policy_requires_confirmation_for_workflow():
    result = CapabilityRegistry()
    result.register(
        DummyAdapter("process_selected_paper"),
        execution_kind="workflow",
        confirmation_required=True,
        allowed_intents=["process_selected_paper"],
    )
    decision = IntentDecision(
        matched=True,
        intent="process_selected_paper",
        capability_name="process_selected_paper",
        execution_kind="workflow",
        confidence=0.9,
    )

    policy = CapabilityExecutionSecurityPolicy(
        CapabilityCatalog.from_registry(result)
    )
    blocked = policy.authorize(decision)
    allowed = policy.authorize(decision, confirmed=True)

    assert blocked.requires_confirmation is True
    assert blocked.allowed is False
    assert allowed.allowed is True


def test_hybrid_router_records_decision_without_sensitive_arguments():
    observer = InMemoryRoutingObserver()
    router = DeterministicIntentRouter(registry())
    hybrid = HybridIntentRouter(router, observer=observer)
    message = ConversationMessage(role="user", content="你好")

    decision = asyncio.run(
        hybrid.route(message, ConversationContext())
    )

    assert decision.matched is False
    assert observer.summary()["total"] == 1
    assert observer.events[0].session_id == ""
    assert observer.events[0].message_id
    assert observer.events[0].missing_arguments == []
    assert "papers" not in observer.events[0].model_dump_json()


def test_evaluation_report_includes_negative_case_failures():
    router = DeterministicIntentRouter(registry())
    report = asyncio.run(
        evaluate_router(
            router,
            [
                RoutingEvaluationCase(
                    case_id="negative-unsupported",
                    content="你好",
                    expected_matched=False,
                    expected_clarification=True,
                ),
                RoutingEvaluationCase(
                    case_id="negative-wrong-expectation",
                    content="你好",
                    expected_matched=True,
                ),
            ],
        )
    )

    assert report.total == 2
    assert report.passed == 1
    assert report.failed == 1
    assert report.accuracy == 0.5
    assert report.items[1].failures == ["matched"]

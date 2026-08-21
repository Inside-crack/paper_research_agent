from __future__ import annotations

import pytest

from paper_agent.common.capabilities import (
    CapabilityCatalog,
    CapabilityDecisionValidationError,
    CapabilityDecisionValidator,
    CapabilityRegistry,
    IntentDecision,
    register_default_capabilities,
)


def validator() -> CapabilityDecisionValidator:
    registry = register_default_capabilities(CapabilityRegistry(), object())
    return CapabilityDecisionValidator(CapabilityCatalog.from_registry(registry))


def test_valid_decision_passes_catalog_and_input_schema_validation():
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        arguments={"artifact_path": "papers/paper.json"},
    )

    assert validator().validate(decision) == decision


def test_unmatched_decision_is_not_executability_validated():
    decision = IntentDecision(
        matched=False,
        intent="invented_intent",
        capability_name="invented_capability",
        missing_arguments=["something"],
    )

    assert validator().validate(decision) == decision


def test_unknown_capability_is_rejected():
    decision = IntentDecision(
        matched=True,
        intent="do_anything",
        capability_name="invented_capability",
    )

    with pytest.raises(CapabilityDecisionValidationError, match="not allowlisted"):
        validator().validate(decision)


def test_disallowed_intent_is_rejected():
    decision = IntentDecision(
        matched=True,
        intent="translate_paper",
        capability_name="paper_parse",
        arguments={"artifact_path": "papers/paper.json"},
    )

    with pytest.raises(CapabilityDecisionValidationError, match="not allowed"):
        validator().validate(decision)


def test_execution_kind_mismatch_is_rejected():
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        execution_kind="workflow",
        arguments={"artifact_path": "papers/paper.json"},
    )

    with pytest.raises(CapabilityDecisionValidationError, match="mismatch"):
        validator().validate(decision)


def test_missing_required_argument_is_rejected():
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        arguments={},
    )

    with pytest.raises(CapabilityDecisionValidationError, match="artifact_path"):
        validator().validate(decision)


def test_unknown_argument_is_rejected():
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        arguments={
            "artifact_path": "papers/paper.json",
            "arbitrary_command": "rm -rf /",
        },
    )

    with pytest.raises(CapabilityDecisionValidationError, match="arbitrary_command"):
        validator().validate(decision)


def test_invalid_argument_type_is_rejected():
    decision = IntentDecision(
        matched=True,
        intent="paper_search",
        capability_name="paper_search",
        arguments={"query": "agents", "max_results": "3"},
    )

    with pytest.raises(CapabilityDecisionValidationError, match="max_results"):
        validator().validate(decision)


def test_structured_router_turns_capability_validation_failure_into_fallback():
    from examples.test_t32_4_4_structured_router import FakeProvider, projection, router

    provider = FakeProvider(
        '{"matched":true,"intent":"parse_paper",'
        '"capability_name":"invented_capability","arguments":{}}'
    )
    llm_router = router(provider)
    message, context = projection()

    import asyncio

    decision = asyncio.run(llm_router.route(message, context))

    assert decision.matched is False
    assert decision.source == "fallback"
    assert "validation" in (decision.reason or "")


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

from __future__ import annotations

import pytest

from paper_agent.common.capabilities import (
    ClarificationPolicy,
    ClarificationPolicyConfig,
    IntentDecision,
)


def test_low_confidence_matched_decision_becomes_non_executable():
    result = ClarificationPolicy().evaluate(
        IntentDecision(
            matched=True,
            intent="download_paper",
            capability_name="paper_download",
            confidence=0.4,
        )
    )

    assert result.needs_clarification is True
    assert result.reason == "low_confidence"
    assert result.decision.matched is False
    assert result.decision.source == "fallback"
    assert result.question


def test_confidence_at_threshold_is_executable():
    policy = ClarificationPolicy(
        ClarificationPolicyConfig(low_confidence_threshold=0.7)
    )

    result = policy.evaluate(
        IntentDecision(
            matched=True,
            intent="parse_paper",
            capability_name="paper_parse",
            confidence=0.7,
        )
    )

    assert result.needs_clarification is False
    assert result.decision.matched is True


def test_missing_arguments_are_explained_without_invention():
    result = ClarificationPolicy().evaluate(
        IntentDecision(
            matched=False,
            intent="parse_paper",
            capability_name="paper_parse",
            missing_arguments=["artifact_path", "task_id"],
        )
    )

    assert result.reason == "missing_arguments"
    assert "论文产物" in result.question
    assert "当前任务" in result.question
    assert result.decision.matched is False


def test_capability_unavailable_has_bounded_question():
    result = ClarificationPolicy().evaluate(
        IntentDecision(
            matched=False,
            intent="parse_paper",
            capability_name="paper_parse",
            reason="Capability is disabled",
        )
    )

    assert result.reason == "capability_unavailable"
    assert "当前不可用" in result.question


def test_context_conflict_has_context_specific_question():
    result = ClarificationPolicy().evaluate(
        IntentDecision(
            matched=False,
            intent="download_paper",
            capability_name="paper_download",
            reason="context conflict: selected paper differs",
        )
    )

    assert result.reason == "context_conflict"
    assert "上下文" in result.question


def test_unknown_intent_preserves_existing_question():
    result = ClarificationPolicy().evaluate(
        IntentDecision(
            matched=False,
            clarification_question="请告诉我想做什么。",
        )
    )

    assert result.reason == "unknown_intent"
    assert result.question == "请告诉我想做什么。"


def test_matched_high_confidence_decision_is_unchanged():
    decision = IntentDecision(
        matched=True,
        intent="paper_search",
        capability_name="paper_search",
        confidence=0.99,
    )

    result = ClarificationPolicy().evaluate(decision)

    assert result.needs_clarification is False
    assert result.decision == decision


def test_policy_rejects_invalid_input_type():
    with pytest.raises(TypeError, match="IntentDecision"):
        ClarificationPolicy().evaluate({"matched": False})  # type: ignore[arg-type]


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

from __future__ import annotations

import pytest
from pydantic import ValidationError

from paper_agent.common.capabilities import ContextReference, IntentDecision


def test_matched_tool_decision_has_complete_serializable_shape():
    decision = IntentDecision(
        matched=True,
        intent="download_selected_paper",
        capability_name="paper_download",
        execution_kind="tool",
        confidence=0.94,
        arguments={"arxiv_id": "2412.05449v1"},
        references=[
            ContextReference(type="selected_paper", value="candidate-1")
        ],
        source="llm",
    )

    assert decision.model_dump() == {
        "matched": True,
        "intent": "download_selected_paper",
        "capability_name": "paper_download",
        "execution_kind": "tool",
        "confidence": 0.94,
        "arguments": {"arxiv_id": "2412.05449v1"},
        "references": [
            {"type": "selected_paper", "value": "candidate-1"}
        ],
        "missing_arguments": [],
        "clarification_question": None,
        "reason": None,
        "source": "llm",
    }


def test_unmatched_decision_can_report_missing_arguments():
    decision = IntentDecision(
        matched=False,
        intent="translate_paper",
        capability_name="paper_translate",
        confidence=0.82,
        arguments={"artifact_path": "papers/paper.json"},
        missing_arguments=["translations"],
        clarification_question="请提供各章节译文。",
        reason="Required capability arguments are missing",
        source="deterministic",
    )

    assert decision.matched is False
    assert decision.missing_arguments == ["translations"]


def test_workflow_decision_is_supported():
    decision = IntentDecision(
        matched=True,
        intent="process_selected_paper",
        capability_name="paper_processing",
        execution_kind="workflow",
        confidence=0.9,
        source="llm",
    )

    assert decision.execution_kind == "workflow"


def test_matched_decision_requires_intent_and_capability():
    with pytest.raises(ValidationError, match="requires intent"):
        IntentDecision(matched=True, capability_name="paper_parse")

    with pytest.raises(ValidationError, match="requires capability_name"):
        IntentDecision(matched=True, intent="parse_paper")


def test_matched_decision_cannot_have_missing_arguments():
    with pytest.raises(ValidationError, match="missing_arguments"):
        IntentDecision(
            matched=True,
            intent="parse_paper",
            capability_name="paper_parse",
            missing_arguments=["artifact_path"],
        )


def test_invalid_enum_and_confidence_are_rejected():
    with pytest.raises(ValidationError):
        IntentDecision(
            matched=False,
            execution_kind="command",
        )

    with pytest.raises(ValidationError):
        IntentDecision(
            matched=False,
            source="rule",
        )

    with pytest.raises(ValidationError):
        IntentDecision(
            matched=False,
            confidence=1.1,
        )


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError, match="extra_field"):
        IntentDecision(matched=False, extra_field="forbidden")


def test_context_reference_rejects_empty_and_boolean_values():
    with pytest.raises(ValidationError):
        ContextReference(type="artifact_ref", value="")

    with pytest.raises(ValidationError):
        ContextReference(type="candidate_index", value=True)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

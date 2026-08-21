from __future__ import annotations

import pytest

from paper_agent.common.capabilities import (
    CapabilityCatalog,
    CapabilityRegistry,
    ContextReference,
    IntentContextProjector,
    IntentDecision,
    IntentPreconditionResolver,
    register_default_capabilities,
)
from paper_agent.common.models.conversation import (
    ConversationContext,
    ConversationMessage,
    ConversationSession,
)


def make_projection(
    *,
    task_id: str | None = "task-1",
    artifacts: list[str] | None = None,
    selected_sections: list[str] | None = None,
):
    session = ConversationSession(
        session_id="session-1",
        active_task_id=task_id,
        context=ConversationContext(
            active_task_id=task_id,
            candidate_papers=[
                {
                    "id": "candidate-1",
                    "arxiv_id": "2412.05449v1",
                    "title": "Paper A",
                },
                {
                    "id": "candidate-2",
                    "arxiv_id": "2203.08975v2",
                    "title": "Paper B",
                },
            ],
            selected_sections=selected_sections or [],
        ),
    )
    message = ConversationMessage(
        session_id=session.session_id,
        role="tool",
        content="artifacts",
        artifact_refs=artifacts or [],
    )
    return IntentContextProjector().project(session, [message])


def resolver() -> IntentPreconditionResolver:
    registry = register_default_capabilities(CapabilityRegistry(), object())
    return IntentPreconditionResolver(CapabilityCatalog.from_registry(registry))


def test_candidate_index_is_resolved_to_selected_paper():
    decision = IntentDecision(
        matched=True,
        intent="download_selected_paper",
        capability_name="paper_download",
        references=[ContextReference(type="candidate_index", value=2)],
    )

    result = resolver().resolve(decision, make_projection())

    assert result.ready is True
    assert result.context_updates["selected_paper"]["arxiv_id"] == "2203.08975v2"
    assert result.decision.matched is True


def test_selected_paper_reference_resolves_by_arxiv_id():
    decision = IntentDecision(
        matched=True,
        intent="download_selected_paper",
        capability_name="paper_download",
        references=[
            ContextReference(type="selected_paper", value="2412.05449v1")
        ],
    )

    result = resolver().resolve(decision, make_projection())

    assert result.ready is True
    assert result.context_updates["selected_paper"]["id"] == "candidate-1"


def test_artifact_reference_is_normalized_to_artifact_path():
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        references=[
            ContextReference(type="artifact_ref", value="papers/paper.json")
        ],
    )

    result = resolver().resolve(
        decision,
        make_projection(artifacts=["papers/paper.json"]),
    )

    assert result.ready is True
    assert result.normalized_arguments == {
        "artifact_path": "papers/paper.json"
    }


def test_artifact_reference_not_in_context_is_blocked():
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        references=[
            ContextReference(type="artifact_ref", value="papers/unknown.json")
        ],
    )

    result = resolver().resolve(decision, make_projection())

    assert result.ready is False
    assert result.decision.matched is False
    assert "not present" in result.errors[0]


def test_task_bound_capability_requires_active_task():
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        arguments={"artifact_path": "papers/paper.json"},
    )

    result = resolver().resolve(decision, make_projection(task_id=None))

    assert result.ready is False
    assert "task_id" in result.missing_arguments


def test_paper_download_accepts_direct_arxiv_id_without_selected_paper():
    decision = IntentDecision(
        matched=True,
        intent="download_paper",
        capability_name="paper_download",
        arguments={"arxiv_id": "2412.05449v1"},
    )

    result = resolver().resolve(decision, make_projection())

    assert result.ready is True


def test_parse_requires_artifact_path():
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
    )

    result = resolver().resolve(decision, make_projection())

    assert result.ready is False
    assert "artifact_path" in result.missing_arguments


def test_unsafe_artifact_path_is_blocked():
    decision = IntentDecision(
        matched=True,
        intent="parse_paper",
        capability_name="paper_parse",
        arguments={"artifact_path": "../outside.json"},
    )

    result = resolver().resolve(decision, make_projection())

    assert result.ready is False
    assert "artifact_path" in result.missing_arguments


def test_selected_section_reference_is_returned_as_context_update():
    decision = IntentDecision(
        matched=True,
        intent="translate_paper",
        capability_name="paper_translate",
        arguments={
            "artifact_path": "papers/paper.json",
            "translations": [],
        },
        references=[
            ContextReference(type="selected_section", value="section_2")
        ],
    )

    result = resolver().resolve(
        decision,
        make_projection(selected_sections=["section_2"]),
    )

    assert result.ready is True
    assert result.context_updates["selected_sections"] == ["section_2"]


def test_non_matched_decision_is_returned_without_resolution():
    decision = IntentDecision(
        matched=False,
        missing_arguments=["artifact_path"],
    )

    result = resolver().resolve(decision, make_projection())

    assert result.ready is False
    assert result.decision == decision
    assert result.errors == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

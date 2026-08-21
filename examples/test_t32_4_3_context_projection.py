from __future__ import annotations

import pytest

from paper_agent.common.capabilities import (
    ContextProjectionConfig,
    IntentContextProjector,
)
from paper_agent.common.models.conversation import (
    ConversationContext,
    ConversationMessage,
    ConversationSession,
)


def make_session() -> ConversationSession:
    return ConversationSession(
        session_id="session-1",
        status="waiting_confirmation",
        active_task_id="task-1",
        context=ConversationContext(
            current_intent="paper_search",
            candidate_set_id="candidate-set-1",
            candidate_papers=[
                {
                    "id": "candidate-1",
                    "arxiv_id": "2412.05449v1",
                    "title": "A paper",
                    "authors": ["Author One"],
                    "abstract": "A useful abstract.",
                    "url": "https://arxiv.org/abs/2412.05449v1",
                    "pdf_url": "https://arxiv.org/pdf/2412.05449v1",
                    "internal_secret": "must-not-leak",
                },
                {
                    "id": "candidate-2",
                    "title": "Second paper",
                },
            ],
            selected_paper={
                "arxiv_id": "2412.05449v1",
                "title": "A paper",
                "absolute_path": "/tmp/private.pdf",
            },
            selected_sections=[" abstract ", "method", "method", ""],
            active_task_id="context-task-1",
        ),
    )


def test_projection_contains_bounded_read_only_context():
    session = make_session()
    messages = [
        ConversationMessage(
            session_id=session.session_id,
            role="user",
            content="first",
            metadata={"private": "must-not-leak"},
        ),
        ConversationMessage(
            session_id=session.session_id,
            role="assistant",
            content="second",
            artifact_refs=[
                "paper_candidates/set.json",
                "../escape.json",
                "/absolute/private.json",
                r"windows\\private.json",
            ],
        ),
    ]

    projection = IntentContextProjector().project(session, messages)

    assert projection.session_status == "waiting_confirmation"
    assert projection.current_intent == "paper_search"
    assert projection.active_task_id == "context-task-1"
    assert projection.candidate_set_id == "candidate-set-1"
    assert len(projection.candidate_papers) == 2
    assert "internal_secret" not in projection.candidate_papers[0]
    assert projection.selected_paper == {
        "arxiv_id": "2412.05449v1",
        "title": "A paper",
    }
    assert projection.selected_sections == ["abstract", "method"]
    assert projection.artifact_refs == ["paper_candidates/set.json"]
    assert projection.recent_messages[0].role == "user"
    assert not hasattr(projection.recent_messages[0], "metadata")


def test_projection_limits_messages_candidates_and_text():
    session = make_session()
    messages = [
        ConversationMessage(
            session_id=session.session_id,
            role="user",
            content=f"message-{index}-" + ("x" * 100),
        )
        for index in range(5)
    ]
    session.context.candidate_papers = [
        {
            "title": f"paper-{index}-" + ("y" * 100),
            "authors": [],
        }
        for index in range(5)
    ]

    projection = IntentContextProjector(
        ContextProjectionConfig(
            max_messages=2,
            max_message_chars=100,
            max_candidates=3,
            max_candidate_chars=100,
        )
    ).project(session, messages)

    assert len(projection.recent_messages) == 2
    assert projection.recent_messages[0].content.startswith("message-3-")
    assert len(projection.recent_messages[0].content) == 100
    assert len(projection.candidate_papers) == 3
    assert len(projection.candidate_papers[0]["title"]) == 100
    assert projection.recent_messages[-1].content.startswith("message-4-")


def test_projection_rejects_messages_from_another_session():
    session = make_session()
    messages = [
        ConversationMessage(
            session_id="other-session",
            role="user",
            content="cross-session data",
        )
    ]

    with pytest.raises(ValueError, match="does not match"):
        IntentContextProjector().project(session, messages)


def test_projection_rejects_invalid_inputs():
    session = make_session()
    message = ConversationMessage(session_id=session.session_id, content="hello")
    projector = IntentContextProjector()

    with pytest.raises(TypeError, match="session"):
        projector.project("not-a-session", [message])  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="sequence"):
        projector.project(session, None)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="ConversationMessage"):
        projector.project(session, ["not-a-message"])  # type: ignore[list-item]


def test_projection_does_not_require_artifact_files_to_exist():
    session = make_session()
    messages = [
        ConversationMessage(
            session_id=session.session_id,
            role="tool",
            content="artifact generated",
            artifact_refs=["not-yet-created/result.json"],
        )
    ]

    projection = IntentContextProjector().project(session, messages)

    assert projection.artifact_refs == ["not-yet-created/result.json"]


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

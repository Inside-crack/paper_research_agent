"""P31 会话、消息、上下文模型和 JSON Store 测试。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models import (  # noqa: E402
    ConversationContext,
    ConversationMessage,
    ConversationSession,
)
from paper_agent.common.persistence import ConversationStore  # noqa: E402
from paper_agent.common.persistence import conversation_store as conversation_store_module  # noqa: E402


def _store(tmpdir: str) -> ConversationStore:
    return ConversationStore(Path(tmpdir) / "artifacts")


def test_models_have_defaults_and_round_trip_serialization():
    context = ConversationContext()
    message = ConversationMessage(session_id="session-defaults")
    session = ConversationSession()

    assert context.candidate_papers == []
    assert context.selected_paper is None
    assert message.id == message.message_id
    assert message.role == "user"
    assert message.artifact_refs == []
    assert session.id == session.session_id
    assert session.status == "active"
    assert session.context == ConversationContext()
    assert session.message_count == 0

    restored_message = ConversationMessage.model_validate_json(message.model_dump_json())
    restored_session = ConversationSession.model_validate_json(session.model_dump_json())
    assert restored_message == message
    assert restored_session == session

    aliased = ConversationSession(id="session-alias")
    assert aliased.session_id == "session-alias"
    with pytest.raises(ValueError):
        ConversationContext.model_validate({"unexpected": True})


def test_create_and_restore_session():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)
        created = store.create_session(user_id="user-31")

        session_path = Path(tmpdir) / "artifacts" / "sessions" / created.session_id / "session.json"
        assert session_path.exists()
        restored = store.load_session(created.session_id)
        assert restored == created
        assert restored is not None
        assert restored.user_id == "user-31"
        assert json.loads(session_path.read_text(encoding="utf-8"))["session_id"] == created.session_id


def test_append_messages_preserves_order_and_returns_latest_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)
        session = store.create_session()
        messages = [
            ConversationMessage(session_id=session.session_id, role="user", content="first"),
            ConversationMessage(session_id=session.session_id, role="assistant", content="second"),
            ConversationMessage(session_id=session.session_id, role="tool", content="third"),
        ]

        for message in messages:
            assert store.append_message(session.session_id, message) == message

        restored = store.list_messages(session.session_id)
        assert [message.content for message in restored] == ["first", "second", "third"]
        assert [message.content for message in store.list_messages(session.session_id, limit=2)] == [
            "second",
            "third",
        ]
        assert store.list_messages(session.session_id, limit=0) == []
        assert store.load_session(session.session_id).message_count == 3


def test_append_message_rolls_back_messages_when_session_write_fails():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)
        session = store.create_session()
        first = ConversationMessage(session_id=session.session_id, content="first")
        store.append_message(session.session_id, first)

        messages_path = Path(tmpdir) / "artifacts" / "sessions" / session.session_id / "messages.json"
        session_path = messages_path.parent / "session.json"
        original_messages = messages_path.read_bytes()
        original_session = session_path.read_bytes()
        second = ConversationMessage(session_id=session.session_id, content="second")
        real_atomic_write_json = conversation_store_module.atomic_write_json
        session_write_error = OSError("session write failed")

        def fail_session_write(path, data):
            if path.name == "session.json":
                raise session_write_error
            return real_atomic_write_json(path, data)

        with patch.object(
            conversation_store_module,
            "atomic_write_json",
            side_effect=fail_session_write,
        ):
            with pytest.raises(OSError) as exc_info:
                store.append_message(session.session_id, second)

        assert exc_info.value is session_write_error
        assert messages_path.read_bytes() == original_messages
        assert session_path.read_bytes() == original_session
        assert [message.content for message in store.list_messages(session.session_id)] == ["first"]
        assert store.load_session(session.session_id).message_count == 1


def test_append_message_reports_original_and_rollback_failures():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)
        session = store.create_session()
        message = ConversationMessage(session_id=session.session_id, content="message")
        real_atomic_write_json = conversation_store_module.atomic_write_json
        session_write_error = OSError("session write failed")

        def fail_session_write(path, data):
            if path.name == "session.json":
                raise session_write_error
            return real_atomic_write_json(path, data)

        with patch.object(
            conversation_store_module,
            "atomic_write_json",
            side_effect=fail_session_write,
        ), patch.object(
            store,
            "_restore_bytes",
            side_effect=OSError("rollback failed"),
        ):
            with pytest.raises(RuntimeError, match="session write failed.*rollback failed") as exc_info:
                store.append_message(session.session_id, message)

        assert exc_info.value.__cause__ is session_write_error


def test_update_context_and_bind_or_unbind_task():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)
        session = store.create_session()
        store.bind_task(session.session_id, "old-task")
        context = ConversationContext(
            current_intent="paper_translation",
            intent_confidence=0.95,
            candidate_papers=[{"title": "A paper"}],
            selected_paper={"arxiv_id": "2401.00001"},
            selected_sections=["abstract", "method"],
            user_preferences={"language": "zh"},
            active_task_id="context-authoritative-task",
            summary="Selected a paper for translation.",
        )

        updated = store.update_context(session.session_id, context)
        assert updated.context == context
        assert updated.active_task_id == "context-authoritative-task"
        assert store.load_session(session.session_id).context == context
        assert store.load_session(session.session_id).active_task_id == "context-authoritative-task"

        bound = store.bind_task(session.session_id, "task-p31")
        assert bound.active_task_id == "task-p31"
        assert bound.context.active_task_id == "task-p31"
        unbound = store.bind_task(session.session_id, None)
        assert unbound.active_task_id is None
        assert unbound.context.active_task_id is None


def test_missing_session_is_explicit():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)

        assert store.load_session("missing-session") is None
        with pytest.raises(FileNotFoundError, match="does not exist"):
            store.list_messages("missing-session")
        with pytest.raises(FileNotFoundError, match="does not exist"):
            store.update_context("missing-session", ConversationContext())
        with pytest.raises(FileNotFoundError, match="does not exist"):
            store.bind_task("missing-session", "task-p31")


def test_corrupt_json_is_not_silently_ignored():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)
        session = store.create_session()
        session_path = Path(tmpdir) / "artifacts" / "sessions" / session.session_id / "session.json"
        session_path.write_text("{broken", encoding="utf-8")

        with pytest.raises(ValueError, match="Corrupt conversation JSON"):
            store.load_session(session.session_id)

        session_path.write_text(session.model_dump_json(), encoding="utf-8")
        messages_path = session_path.parent / "messages.json"
        messages_path.write_text("{broken", encoding="utf-8")
        with pytest.raises(ValueError, match="Corrupt conversation JSON"):
            store.list_messages(session.session_id)


def test_session_id_mismatch_is_rejected():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)
        session = store.create_session()
        wrong_message = ConversationMessage(session_id="another-session", content="wrong owner")

        with pytest.raises(ValueError, match="session_id mismatch"):
            store.append_message(session.session_id, wrong_message)

        messages_path = Path(tmpdir) / "artifacts" / "sessions" / session.session_id / "messages.json"
        messages_path.write_text(
            json.dumps(
                [
                    {
                        "message_id": "mismatch",
                        "session_id": "another-session",
                        "role": "user",
                        "content": "wrong owner",
                    }
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="session_id mismatch"):
            store.list_messages(session.session_id)


def test_session_path_traversal_is_rejected():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)
        for invalid_id in ("../escape", "nested/session", "/absolute", r"..\\escape"):
            with pytest.raises(ValueError, match="Invalid conversation session_id"):
                store.load_session(invalid_id)

        outside = Path(tmpdir) / "outside"
        outside.mkdir()
        link = Path(tmpdir) / "artifacts" / "sessions" / "safe"
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError, match="must not be a symlink|escapes"):
            store.load_session("safe")


def test_sessions_root_symlink_is_rejected():
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = Path(tmpdir) / "artifacts"
        artifacts_dir.mkdir()
        target_dir = Path(tmpdir) / "session-target"
        target_dir.mkdir()
        (artifacts_dir / "sessions").symlink_to(target_dir, target_is_directory=True)

        with pytest.raises(ValueError, match="sessions directory must not be a symlink"):
            ConversationStore(artifacts_dir)


def test_store_uses_atomic_json_writes():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir)
        real_atomic_write_json = conversation_store_module.atomic_write_json
        with patch.object(
            conversation_store_module,
            "atomic_write_json",
            side_effect=real_atomic_write_json,
        ) as atomic_write:
            session = store.create_session()
            store.append_message(
                session.session_id,
                ConversationMessage(session_id=session.session_id, content="atomic"),
            )

        written_paths = [call.args[0] for call in atomic_write.call_args_list]
        assert len(written_paths) == 3
        assert written_paths[0].name == "session.json"
        assert written_paths[1].name == "messages.json"
        assert written_paths[2].name == "session.json"
        assert all(path.exists() for path in written_paths)
        assert not list((Path(tmpdir) / "artifacts").rglob("*.tmp"))


def main():
    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()

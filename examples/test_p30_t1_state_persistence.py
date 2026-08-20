"""P30 T1 子步骤状态、TaskState 和 Manifest 持久化测试。"""

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models.base import TaskPhase
from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.models.task_state import (
    PAPER_PROCESSING_SUBSTEPS,
    PaperProcessingStepState,
    TaskState,
)
from paper_agent.common.persistence.manifest import (
    MANIFEST_FILENAME,
    TASKS_INDEX_FILENAME,
    create_empty_manifest,
    dict_to_manifest,
    rebuild_manifest_from_state,
)
from paper_agent.common.persistence.state_persistence import StatePersistence


def _make_persistence(tmpdir: str) -> StatePersistence:
    return StatePersistence(Path(tmpdir) / "artifacts")


def _make_spec(task_id: str) -> ResearchSpec:
    return ResearchSpec(
        id=task_id,
        user_query="P30 state persistence",
        task_type="topic_research",
        keywords=["paper"],
    )


def test_default_task_state_has_all_paper_processing_steps():
    state = TaskState(research_spec_id="task-p30-default")

    assert state.current_phase is TaskPhase.TASK_INITIALIZATION
    assert tuple(state.paper_processing_steps) == PAPER_PROCESSING_SUBSTEPS
    for step_name in PAPER_PROCESSING_SUBSTEPS:
        step = state.paper_processing_steps[step_name]
        assert step.status == "not_started"
        assert step.revision_count == 0
        assert step.input_artifacts == []
        assert step.output_artifacts == []
        assert step.error is None
        assert step.started_at is None
        assert step.completed_at is None


def test_paper_processing_step_serialization_round_trip():
    started_at = datetime(2026, 8, 19, 12, 0, 0)
    completed_at = datetime(2026, 8, 19, 12, 1, 0)
    step = PaperProcessingStepState(
        status="PASS",
        revision_count=1,
        input_artifacts=["papers/source.pdf"],
        output_artifacts=["papers/parsed.json"],
        error=None,
        started_at=started_at,
        completed_at=completed_at,
    )

    restored = PaperProcessingStepState.model_validate_json(step.model_dump_json())

    assert restored.status == "PASS"
    assert restored.revision_count == 1
    assert restored.input_artifacts == ["papers/source.pdf"]
    assert restored.output_artifacts == ["papers/parsed.json"]
    assert restored.started_at == started_at
    assert restored.completed_at == completed_at


def test_manifest_persists_paper_processing_step_state():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-manifest"
            await persistence.create_task_manifest(_make_spec(task_id))
            await persistence.save_checkpoint(
                TaskState(
                    id=task_id,
                    research_spec_id=task_id,
                    current_phase=TaskPhase.PAPER_PARSING,
                )
            )
            step = PaperProcessingStepState(
                status="PASS",
                revision_count=1,
                input_artifacts=["papers/source.pdf"],
                output_artifacts=["papers/parsed.json"],
                started_at=datetime(2026, 8, 19, 12, 0, 0),
                completed_at=datetime(2026, 8, 19, 12, 1, 0),
            )

            await persistence.update_paper_processing_step(task_id, "parse", step)

            manifest_path = persistence.base_dir / task_id / MANIFEST_FILENAME
            manifest_data = json.loads(manifest_path.read_text())
            persisted = manifest_data["phases"]["paper_parsing"]["paper_processing_steps"]["parse"]
            assert persisted["status"] == "PASS"
            assert persisted["revision_count"] == 1
            assert persisted["input_artifacts"] == ["papers/source.pdf"]
            assert persisted["output_artifacts"] == ["papers/parsed.json"]
            assert persisted["completed_at"] == "2026-08-19T12:01:00"
            state_data = json.loads(
                (persistence.base_dir / task_id / "task_state.json").read_text()
            )
            assert state_data["current_phase"] == TaskPhase.PAPER_PARSING.value
            assert state_data["paper_processing_steps"]["parse"]["status"] == "PASS"
            index_data = json.loads((persistence.base_dir / "tasks_index.json").read_text())
            index_entry = next(item for item in index_data["tasks"] if item["task_id"] == task_id)
            assert index_entry["current_phase"] == TaskPhase.PAPER_PARSING.value

            loaded = persistence.load_paper_processing_steps(task_id)
            assert loaded["parse"].output_artifacts == ["papers/parsed.json"]
            assert loaded["parse"].status == "PASS"
            restored_state = await persistence.load_checkpoint(str(persistence.get_latest_checkpoint(task_id)))
            assert restored_state.paper_processing_steps["parse"].status == "PASS"

    asyncio.run(_run())


def test_checkpoint_round_trip_preserves_paper_processing_steps():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            state = TaskState(
                id="task-p30-checkpoint",
                research_spec_id="spec-p30-checkpoint",
                current_phase=TaskPhase.PAPER_PARSING,
            )
            state.paper_processing_steps["download"] = PaperProcessingStepState(
                status="PASS",
                output_artifacts=["papers/2401.00001.pdf", "papers/2401.00001.json"],
                completed_at=datetime(2026, 8, 19, 12, 2, 0),
            )
            state.paper_processing_steps["parse"].status = "running"
            state.paper_processing_steps["parse"].input_artifacts = ["papers/2401.00001.pdf"]

            checkpoint = await persistence.save_checkpoint(state)
            restored = await persistence.load_checkpoint(str(checkpoint))

            assert restored.current_phase is TaskPhase.PAPER_PARSING
            assert restored.paper_processing_steps["download"].status == "PASS"
            assert restored.paper_processing_steps["download"].output_artifacts == [
                "papers/2401.00001.pdf",
                "papers/2401.00001.json",
            ]
            assert restored.paper_processing_steps["parse"].status == "running"
            assert restored.paper_processing_steps["parse"].input_artifacts == ["papers/2401.00001.pdf"]

    asyncio.run(_run())


def test_task_state_rejects_unknown_or_invalid_paper_processing_steps():
    base_state = TaskState(
        id="task-p30-invalid-state-model",
        research_spec_id="spec-p30-invalid-state-model",
    ).model_dump(mode="json")

    unknown_step = {**base_state, "paper_processing_steps": {"unexpected": {}}}
    with pytest.raises(ValueError, match="Unknown paper processing substep"):
        TaskState.model_validate(unknown_step)

    invalid_value = {**base_state, "paper_processing_steps": {"parse": "invalid"}}
    with pytest.raises(ValueError, match="Invalid paper processing step 'parse'"):
        TaskState.model_validate(invalid_value)


def test_load_checkpoint_rejects_unknown_paper_processing_step():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-invalid-checkpoint"
            checkpoint_path = persistence.base_dir / task_id / "checkpoint.json"
            checkpoint_path.parent.mkdir(parents=True)
            checkpoint_data = TaskState(
                id=task_id,
                research_spec_id=task_id,
            ).model_dump(mode="json")
            checkpoint_data["paper_processing_steps"]["unexpected"] = {}
            checkpoint_path.write_text(json.dumps(checkpoint_data), encoding="utf-8")

            with pytest.raises(ValueError, match="Unknown paper processing substep"):
                await persistence.load_checkpoint(str(checkpoint_path))

    asyncio.run(_run())


def test_legacy_task_state_and_manifest_without_substeps_are_readable():
    legacy_state = {
        "id": "legacy-task",
        "created_at": "2026-08-18T10:00:00",
        "updated_at": "2026-08-18T10:00:00",
        "research_spec_id": "legacy-spec",
        "current_phase": "paper_parsing",
    }
    restored_state = TaskState(**legacy_state)
    assert restored_state.current_phase is TaskPhase.PAPER_PARSING
    assert set(restored_state.paper_processing_steps) == set(PAPER_PROCESSING_SUBSTEPS)

    legacy_manifest = create_empty_manifest("legacy-task", "legacy")
    legacy_data = legacy_manifest.model_dump(mode="json")
    for phase in legacy_data["phases"].values():
        phase.pop("paper_processing_steps", None)

    restored_manifest = dict_to_manifest(legacy_data)
    assert restored_manifest is not None
    assert restored_manifest.phases["paper_parsing"].paper_processing_steps == {}


def test_dict_to_manifest_rejects_invalid_paper_processing_steps():
    manifest_data = create_empty_manifest("task-p30-invalid-manifest-steps").model_dump(mode="json")
    manifest_data["phases"]["paper_parsing"]["paper_processing_steps"]["unexpected"] = {}

    assert dict_to_manifest(manifest_data) is None


def test_load_manifest_rebuilds_after_corrupt_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = _make_persistence(tmpdir)
        task_id = "task-p30-manifest-rebuild"
        task_dir = persistence.base_dir / task_id
        task_dir.mkdir()
        state = TaskState(
            id=task_id,
            research_spec_id=task_id,
            current_phase=TaskPhase.PAPER_PARSING,
        )
        state.paper_processing_steps["parse"] = PaperProcessingStepState(status="PASS")
        (task_dir / "task_state.json").write_text(
            json.dumps(state.model_dump(mode="json")),
            encoding="utf-8",
        )
        (task_dir / MANIFEST_FILENAME).write_text("{not valid json", encoding="utf-8")

        restored = persistence.load_manifest(task_id)

        assert restored is not None
        assert restored.phases["paper_parsing"].paper_processing_steps["parse"].status == "PASS"
        assert json.loads((task_dir / MANIFEST_FILENAME).read_text())["task_id"] == task_id


def test_paper_processing_manifest_failure_rolls_back_all_and_is_propagated():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-failure"
            await persistence.create_task_manifest(_make_spec(task_id))
            await persistence.save_checkpoint(
                TaskState(
                    id=task_id,
                    research_spec_id=task_id,
                    current_phase=TaskPhase.PAPER_RETRIEVAL,
                )
            )
            step = PaperProcessingStepState(status="PASS", output_artifacts=["result.json"])

            state_path = persistence.base_dir / task_id / "task_state.json"
            manifest_path = persistence.base_dir / task_id / MANIFEST_FILENAME
            index_path = persistence.base_dir / "tasks_index.json"
            state_before = state_path.read_bytes()
            manifest_before = manifest_path.read_bytes()
            index_before = index_path.read_bytes()

            def fail_after_state_write(*args):
                assert len(args) == 2
                state_after_write = json.loads(state_path.read_text())
                assert state_after_write["current_phase"] == TaskPhase.PAPER_PARSING.value
                assert state_after_write["paper_processing_steps"]["summary"]["status"] == "PASS"
                raise OSError("manifest disk full")

            with patch.object(persistence, "_update_manifest", side_effect=fail_after_state_write):
                with pytest.raises(OSError, match="manifest disk full"):
                    await persistence.update_paper_processing_step(task_id, "summary", step)

            assert state_path.read_bytes() == state_before
            assert manifest_path.read_bytes() == manifest_before
            assert json.loads(index_path.read_bytes())["tasks"] == json.loads(index_before)["tasks"]

    asyncio.run(_run())


def test_paper_processing_index_persistence_failure_is_propagated():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-index-failure"
            await persistence.create_task_manifest(_make_spec(task_id))
            rebuild_index = persistence._do_update_tasks_index

            def fail_incremental_update(updated_task_id):
                if updated_task_id == task_id:
                    raise OSError("index disk full")
                return rebuild_index(updated_task_id)

            with patch.object(
                persistence,
                "_do_update_tasks_index",
                side_effect=fail_incremental_update,
            ):
                with pytest.raises(OSError, match="index disk full"):
                    await persistence.update_paper_processing_step(
                        task_id,
                        "download",
                        PaperProcessingStepState(status="PASS"),
                    )

    asyncio.run(_run())


def test_paper_processing_index_failure_rolls_back_state_and_manifest():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-index-rollback"
            await persistence.create_task_manifest(_make_spec(task_id))
            checkpoint_state = TaskState(
                id=task_id,
                research_spec_id=task_id,
                current_phase=TaskPhase.PAPER_PARSING,
            )
            checkpoint_state.paper_processing_steps["download"] = PaperProcessingStepState(status="PASS")
            await persistence.save_checkpoint(checkpoint_state)

            state_path = persistence.base_dir / task_id / "task_state.json"
            manifest_path = persistence.base_dir / task_id / MANIFEST_FILENAME
            index_path = persistence.base_dir / "tasks_index.json"
            state_before = state_path.read_bytes()
            manifest_before = manifest_path.read_bytes()
            rebuild_index = persistence._do_update_tasks_index

            def fail_incremental_update(updated_task_id):
                if updated_task_id == task_id:
                    raise OSError("index disk full")
                return rebuild_index(updated_task_id)

            with patch.object(persistence, "_do_update_tasks_index", side_effect=fail_incremental_update):
                with pytest.raises(OSError, match="index disk full"):
                    await persistence.update_paper_processing_step(
                        task_id,
                        "parse",
                        PaperProcessingStepState(status="PASS"),
                    )

            assert state_path.read_bytes() == state_before
            assert manifest_path.read_bytes() == manifest_before
            index_data = json.loads(index_path.read_text())
            assert [entry["task_id"] for entry in index_data["tasks"]] == [task_id]
            assert index_data["tasks"][0]["current_phase"] == TaskPhase.TASK_INITIALIZATION.value

    asyncio.run(_run())


def test_paper_processing_rollback_does_not_create_missing_manifest_or_index_entry():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_without_manifest = "task-p30-rollback-no-manifest"
            other_task = "task-p30-rollback-existing"

            await persistence.create_task_manifest(_make_spec(other_task))

            task_dir = persistence.base_dir / task_without_manifest
            task_dir.mkdir()
            state_path = task_dir / "task_state.json"
            state_before = TaskState(
                id=task_without_manifest,
                research_spec_id=task_without_manifest,
                current_phase=TaskPhase.PAPER_PARSING,
            )
            state_before.paper_processing_steps["download"] = PaperProcessingStepState(status="PASS")
            state_bytes_before = json.dumps(
                state_before.model_dump(mode="json"),
                indent=2,
            ).encode("utf-8")
            state_path.write_bytes(state_bytes_before)

            manifest_path = task_dir / MANIFEST_FILENAME
            index_path = persistence.base_dir / TASKS_INDEX_FILENAME
            assert not manifest_path.exists()
            assert [
                entry["task_id"]
                for entry in json.loads(index_path.read_text())["tasks"]
            ] == [other_task]

            original_update = persistence._do_update_tasks_index

            def fail_incremental_update(updated_task_id):
                if updated_task_id == task_without_manifest:
                    raise OSError("index disk full")
                return original_update(updated_task_id)

            with patch.object(
                persistence,
                "_do_update_tasks_index",
                side_effect=fail_incremental_update,
            ):
                with pytest.raises(OSError, match="index disk full"):
                    await persistence.update_paper_processing_step(
                        task_without_manifest,
                        "parse",
                        PaperProcessingStepState(status="PASS"),
                    )

            assert state_path.read_bytes() == state_bytes_before
            assert not manifest_path.exists()
            index_entries = json.loads(index_path.read_text())["tasks"]
            assert [entry["task_id"] for entry in index_entries] == [other_task]

    asyncio.run(_run())


def test_paper_processing_rollback_rebuild_preserves_other_task_index_entry():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_a = "task-p30-rollback-a"
            task_b = "task-p30-rollback-b"
            await persistence.create_task_manifest(_make_spec(task_a))
            await persistence.create_task_manifest(_make_spec(task_b))
            rebuild_index = persistence._do_update_tasks_index

            def fail_after_task_b_update(updated_task_id):
                if updated_task_id is None:
                    return rebuild_index(None)
                assert updated_task_id == task_a

                def mark_task_b_completed(manifest):
                    manifest.status = "completed"

                persistence._update_manifest(task_b, mark_task_b_completed)
                rebuild_index(task_b)
                raise OSError("index disk full")

            with patch.object(
                persistence,
                "_do_update_tasks_index",
                side_effect=fail_after_task_b_update,
            ):
                with pytest.raises(OSError, match="index disk full"):
                    await persistence.update_paper_processing_step(
                        task_a,
                        "parse",
                        PaperProcessingStepState(status="PASS"),
                    )

            index_data = json.loads((persistence.base_dir / "tasks_index.json").read_text())
            entries = {entry["task_id"]: entry for entry in index_data["tasks"]}
            assert entries[task_a]["current_phase"] == TaskPhase.TASK_INITIALIZATION.value
            assert entries[task_b]["status"] == "completed"

    asyncio.run(_run())


def test_paper_processing_rollback_failure_is_propagated():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-rollback-failure"
            await persistence.create_task_manifest(_make_spec(task_id))

            with patch.object(
                persistence,
                "_do_update_tasks_index",
                side_effect=OSError("index disk full"),
            ), patch.object(
                persistence,
                "_restore_file",
                side_effect=OSError("rollback disk full"),
            ):
                with pytest.raises(RuntimeError) as exc_info:
                    await persistence.update_paper_processing_step(
                        task_id,
                        "parse",
                        PaperProcessingStepState(status="PASS"),
                    )

            assert "rollback failure" in str(exc_info.value)
            assert "rollback disk full" in str(exc_info.value)
            assert isinstance(exc_info.value.__cause__, OSError)
            assert "index disk full" in str(exc_info.value.__cause__)

    asyncio.run(_run())


def test_paper_processing_step_creates_minimal_state_when_missing():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-missing-state"
            await persistence.create_task_manifest(_make_spec(task_id))
            step = PaperProcessingStepState(status="PASS", output_artifacts=["papers/result.json"])

            await persistence.update_paper_processing_step(task_id, "download", step)

            state_path = persistence.base_dir / task_id / "task_state.json"
            assert state_path.exists()
            restored = await persistence.load_checkpoint(str(state_path))
            assert restored.id == task_id
            assert restored.research_spec_id == task_id
            assert restored.current_phase is TaskPhase.PAPER_PARSING
            assert restored.paper_processing_steps["download"].status == "PASS"
            assert restored.paper_processing_steps["download"].output_artifacts == [
                "papers/result.json"
            ]

    asyncio.run(_run())


def test_rebuild_manifest_restores_paper_processing_steps():
    with tempfile.TemporaryDirectory() as tmpdir:
        task_dir = Path(tmpdir) / "task"
        task_dir.mkdir()
        state = TaskState(
            id="task-p30-rebuild",
            research_spec_id="spec-p30-rebuild",
            current_phase=TaskPhase.PAPER_PARSING,
        )
        state.paper_processing_steps["parse"] = PaperProcessingStepState(
            status="PASS",
            revision_count=1,
            input_artifacts=["papers/source.pdf"],
            output_artifacts=["papers/parsed.json"],
        )

        manifest = rebuild_manifest_from_state(
            task_dir,
            state.id,
            state.model_dump(mode="json"),
        )

        restored = manifest.phases["paper_parsing"].paper_processing_steps["parse"]
        assert restored.status == "PASS"
        assert restored.revision_count == 1
        assert restored.input_artifacts == ["papers/source.pdf"]
        assert restored.output_artifacts == ["papers/parsed.json"]


def test_load_paper_processing_steps_reports_corrupt_state_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = _make_persistence(tmpdir)
        task_dir = persistence.base_dir / "task-p30-corrupt-state"
        task_dir.mkdir()
        (task_dir / "task_state.json").write_text("{not valid json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            persistence.load_paper_processing_steps(task_dir.name)


def test_load_paper_processing_steps_rejects_corrupt_manifest_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = _make_persistence(tmpdir)
        task_id = "task-p30-load-corrupt-manifest"
        task_dir = persistence.base_dir / task_id
        task_dir.mkdir()
        (task_dir / MANIFEST_FILENAME).write_text("{not valid json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            persistence.load_paper_processing_steps(task_id)


def test_load_paper_processing_steps_rejects_unknown_state_substep():
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = _make_persistence(tmpdir)
        task_id = "task-p30-invalid-state-steps"
        task_dir = persistence.base_dir / task_id
        task_dir.mkdir()
        state = TaskState(id=task_id, research_spec_id=task_id)
        state_data = state.model_dump(mode="json")
        state_data["paper_processing_steps"]["unexpected"] = {}
        (task_dir / "task_state.json").write_text(json.dumps(state_data), encoding="utf-8")

        with pytest.raises(ValueError, match="Unknown paper processing substep"):
            persistence.load_paper_processing_steps(task_id)


def test_update_paper_processing_step_rejects_corrupt_manifest_json():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-corrupt-manifest"
            await persistence.create_task_manifest(_make_spec(task_id))
            manifest_path = persistence.base_dir / task_id / MANIFEST_FILENAME
            corrupt_manifest = b"{not valid json"
            manifest_path.write_bytes(corrupt_manifest)

            with pytest.raises(json.JSONDecodeError):
                await persistence.update_paper_processing_step(
                    task_id,
                    "parse",
                    PaperProcessingStepState(status="PASS"),
                )

            assert manifest_path.read_bytes() == corrupt_manifest

    asyncio.run(_run())


def test_update_paper_processing_step_rejects_invalid_manifest_structure():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-invalid-manifest"
            await persistence.create_task_manifest(_make_spec(task_id))
            manifest_path = persistence.base_dir / task_id / MANIFEST_FILENAME
            invalid_manifest = {"task_id": task_id}
            manifest_path.write_text(json.dumps(invalid_manifest), encoding="utf-8")

            with pytest.raises(ValueError, match="Invalid Manifest structure"):
                await persistence.update_paper_processing_step(
                    task_id,
                    "parse",
                    PaperProcessingStepState(status="PASS"),
                )

            assert json.loads(manifest_path.read_text()) == invalid_manifest

    asyncio.run(_run())


def test_update_paper_processing_step_rejects_null_manifest():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            task_id = "task-p30-null-manifest"
            await persistence.create_task_manifest(_make_spec(task_id))
            manifest_path = persistence.base_dir / task_id / MANIFEST_FILENAME
            manifest_path.write_text("null", encoding="utf-8")

            with pytest.raises(ValueError, match="Invalid Manifest JSON structure"):
                await persistence.update_paper_processing_step(
                    task_id,
                    "parse",
                    PaperProcessingStepState(status="PASS"),
                )

            assert manifest_path.read_text(encoding="utf-8") == "null"

    asyncio.run(_run())


def test_rebuild_manifest_rejects_invalid_paper_processing_steps():
    invalid_steps = (
        None,
        {"unknown": {}},
        {"parse": "not a dict"},
        {"parse": {"revision_count": "not an integer"}},
    )
    for invalid_value in invalid_steps:
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "task"
            task_dir.mkdir()
            state_data = {
                "id": "task-p30-invalid-rebuild",
                "research_spec_id": "spec-p30-invalid-rebuild",
                "current_phase": TaskPhase.PAPER_PARSING.value,
                "paper_processing_steps": invalid_value,
            }

            with pytest.raises(ValueError):
                rebuild_manifest_from_state(task_dir, state_data["id"], state_data)


def test_unknown_paper_processing_substep_is_rejected():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = _make_persistence(tmpdir)
            with pytest.raises(ValueError, match="Unknown paper processing substep"):
                await persistence.update_paper_processing_step(
                    "task-p30-invalid", "unknown", PaperProcessingStepState()
                )

    asyncio.run(_run())


if __name__ == "__main__":
    tests = [
        test_default_task_state_has_all_paper_processing_steps,
        test_paper_processing_step_serialization_round_trip,
        test_manifest_persists_paper_processing_step_state,
        test_checkpoint_round_trip_preserves_paper_processing_steps,
        test_legacy_task_state_and_manifest_without_substeps_are_readable,
        test_paper_processing_manifest_failure_rolls_back_all_and_is_propagated,
        test_paper_processing_index_persistence_failure_is_propagated,
        test_paper_processing_index_failure_rolls_back_state_and_manifest,
        test_paper_processing_rollback_failure_is_propagated,
        test_paper_processing_step_creates_minimal_state_when_missing,
        test_rebuild_manifest_restores_paper_processing_steps,
        test_load_paper_processing_steps_reports_corrupt_state_json,
        test_load_paper_processing_steps_rejects_corrupt_manifest_json,
        test_load_paper_processing_steps_rejects_unknown_state_substep,
        test_update_paper_processing_step_rejects_corrupt_manifest_json,
        test_update_paper_processing_step_rejects_invalid_manifest_structure,
        test_update_paper_processing_step_rejects_null_manifest,
        test_rebuild_manifest_rejects_invalid_paper_processing_steps,
        test_unknown_paper_processing_substep_is_rejected,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")

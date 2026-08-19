"""
D01-D04 索引检索体系 单元测试
覆盖:
  D01: naming.py 命名生成+解析
  D02: manifest.py Pydantic模型+原子写+重建
  D03: tasks_index 全局索引+自动重建+降级
  D04: CLI 子命令JSON输出
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from paper_agent.common.models.base import TaskPhase
from paper_agent.common.models.task_state import TaskState, StageStatus
from paper_agent.common.models.execution_plan import ExecutionPlan, PlanStep
from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.models.evaluation_result import EvaluationResult, EvaluationVerdict
from paper_agent.common.persistence.naming import (
    artifact_filename, parse_artifact_filename, phase_short, phase_from_short,
    PHASE_SHORT_NAMES, SHORT_TO_PHASE, VALID_TYPES,
)
from paper_agent.common.persistence.manifest import (
    TaskManifest, PhaseEntry, StepSummary, FileEntry, TasksIndex, TaskIndexEntry,
    create_empty_manifest, atomic_write_json, load_json, manifest_to_dict,
    rebuild_manifest_from_state, scan_artifacts_for_files,
    MANIFEST_FILENAME, TASKS_INDEX_FILENAME,
)
from paper_agent.common.persistence import StatePersistence


# ==================== D01 naming tests ====================

def test_d01_phase_short_mapping_covers_all_phases():
    for p in TaskPhase:
        if p.value in ("completed", "failed"):
            continue
        assert p.value in PHASE_SHORT_NAMES, f"Missing short name for {p}"
        short = PHASE_SHORT_NAMES[p.value]
        assert SHORT_TO_PHASE[short] == p.value
    print("✅ D01-1: 所有7个phase都有short name映射")

def test_d01_artifact_filename_step_level():
    n = artifact_filename(TaskPhase.PAPER_RETRIEVAL, "result", step_id="s1", tool="arxiv_search")
    assert n == "paper_retrieval_s1_arxiv_search_result.json"
    assert n.endswith("_result.json")
    print(f"✅ D01-2: step级文件名生成正确 → {n}")

def test_d01_artifact_filename_phase_level():
    n = artifact_filename(TaskPhase.REPRODUCTION_PLANNING, "plan")
    assert n == "repro_plan_plan.json"
    print(f"✅ D01-3: phase级文件名生成正确 → {n}")

def test_d01_artifact_filename_with_revision():
    n = artifact_filename(TaskPhase.EXPERIMENT_EXECUTION, "result", step_id="s2", tool="python_run", revision=2)
    assert n == "exp_exec_s2_python_run_result_r2.json"
    assert "_r2" in n
    print(f"✅ D01-4: revision后缀正确 → {n}")

def test_d01_parse_roundtrip():
    for phase in [TaskPhase.PAPER_RETRIEVAL, TaskPhase.CODE_LOCATION, TaskPhase.EXPERIMENT_EXECUTION]:
        for atype in ["result", "error", "plan", "output"]:
            for rev in [None, 1, 3]:
                fname = artifact_filename(phase, atype, step_id="s1", tool="fake_tool", revision=rev)
                parsed = parse_artifact_filename(fname)
                assert parsed is not None, f"Failed to parse {fname}"
                assert parsed["phase"] == phase.value
                assert parsed["type"] == atype
                assert parsed["step_id"] == "s1"
                assert parsed["tool"] == "fake_tool"
                expected_rev = rev if rev is not None else 0
                assert parsed["revision"] == expected_rev
    print("✅ D01-5: 生成→解析 roundtrip 正确")

def test_d01_parse_fixed_names():
    assert parse_artifact_filename("research_spec.json")["type"] == "spec"
    assert parse_artifact_filename("task_state.json")["type"] == "state"
    cp = parse_artifact_filename("checkpoint_paper_retrieval_s1.json")
    assert cp["type"] == "checkpoint"
    print("✅ D01-6: 固定命名(research_spec/task_state/checkpoint)解析正确")

def test_d01_parse_invalid():
    assert parse_artifact_filename("random.json") is None
    assert parse_artifact_filename("not_a_file.txt") is None
    print("✅ D01-7: 无效文件名返回None")


# ==================== D02 manifest model tests ====================

def test_d02_create_empty_manifest():
    m = create_empty_manifest("task-001", "test topic")
    assert m.task_id == "task-001"
    assert m.topic == "test topic"
    assert m.status == "running"
    assert len(m.phases) == 7
    assert m.phases["task_initialization"].status == "running"
    for pshort in ["paper_retrieval", "paper_parsing", "code_location", "reproduction_planning", "experiment_execution", "result_reporting"]:
        assert m.phases[pshort].status == "not_started"
    print("✅ D02-1: 空manifest初始化7个phase为not_started")

def test_d02_atomic_write(tmp_path=None):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "test.json"
        atomic_write_json(p, {"a": 1, "b": [2,3]})
        assert p.exists()
        d = json.loads(p.read_text())
        assert d["a"] == 1
        assert d["b"] == [2,3]
        assert not (p.parent / (p.name + ".tmp")).exists()
        print("✅ D02-2: atomic_write_json写入正确，无tmp残留")

def test_d02_load_json_corrupt():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bad.json"
        p.write_text("{not valid json")
        assert load_json(p) is None
        p2 = Path(td) / "missing.json"
        assert load_json(p2) is None
        print("✅ D02-3: load_json对损坏/缺失文件返回None")

def test_d02_scan_artifacts():
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        (tdir / "paper_retrieval_s1_result.json").write_text("{}")
        (tdir / "research_spec.json").write_text("{}")
        (tdir / "task_state.json").write_text("{}")
        (tdir / "manifest.json").write_text("{}")
        (tdir / "tasks_index.json").write_text("{}")
        (tdir / "checkpoint_init.json").write_text("{}")
        (tdir / "evaluations").mkdir()
        (tdir / "evaluations" / "eval_paper_retrieval.json").write_text("{}")
        files = scan_artifacts_for_files(tdir)
        names = {f.name for f in files}
        assert "paper_retrieval_s1_result.json" in names
        assert "research_spec.json" in names
        assert "manifest.json" not in names
        assert "tasks_index.json" not in names
        assert "checkpoint_init.json" not in names
        print(f"✅ D02-4: scan_artifacts正确过滤 → {len(files)} files: {names}")

def test_d02_manifest_serialization():
    m = create_empty_manifest("t1", "topic1")
    d = manifest_to_dict(m)
    assert d["task_id"] == "t1"
    assert "phases" in d
    assert isinstance(d["phases"], dict)
    print("✅ D02-5: manifest序列化正确")


# ==================== D03 StatePersistence manifest+index tests ====================

def _make_sp(tmpdir):
    sp = StatePersistence()
    sp.base_dir = Path(tmpdir) / "artifacts"
    sp.base_dir.mkdir(parents=True, exist_ok=True)
    return sp

def _make_spec(tmpdir, task_id=None):
    import uuid
    tid = task_id or uuid.uuid4().hex[:16]
    spec = ResearchSpec(
        id=tid,
        user_query="test paper research",
        task_type="topic_research",
        keywords=["test"],
    )
    task_dir = Path(tmpdir) / "artifacts" / tid
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "research_spec.json").write_text(spec.model_dump_json())
    return tid, spec

def test_d03_create_manifest_and_index():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid, spec = _make_spec(td)
            m = await sp.create_task_manifest(spec)
            assert m.task_id == tid
            mpath = sp.base_dir / tid / MANIFEST_FILENAME
            assert mpath.exists()
            idx_path = sp.base_dir / TASKS_INDEX_FILENAME
            assert idx_path.exists()
            idx_data = json.loads(idx_path.read_text())
            assert idx_data["version"] == 1
            assert tid in [e["task_id"] for e in idx_data["tasks"]]
            print("✅ D03-1: create_task_manifest创建manifest+更新index")
    asyncio.run(_run())

def test_d03_load_manifest_rebuilds_on_corrupt():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid, spec = _make_spec(td)
            task_dir = sp.base_dir / tid
            state = TaskState(id=tid, research_spec_id=tid, current_phase=TaskPhase.PAPER_RETRIEVAL,
                              metadata={"research_spec": {"user_query": "test"}})
            (task_dir / "task_state.json").write_text(state.model_dump_json())
            (task_dir / MANIFEST_FILENAME).write_text("{corrupt!!!")
            m = sp.load_manifest(tid)
            assert m is not None
            assert m.task_id == tid
            print("✅ D03-2: manifest损坏时自动rebuild")
    asyncio.run(_run())

def test_d03_mark_phase_and_save_plan():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid, spec = _make_spec(td)
            await sp.create_task_manifest(spec)
            await sp.mark_phase_started(tid, TaskPhase.PAPER_RETRIEVAL)
            m = sp.load_manifest(tid)
            assert m.phases["paper_retrieval"].status == "running"
            assert m.phases["paper_retrieval"].started_at is not None
            plan = ExecutionPlan(phase=TaskPhase.PAPER_RETRIEVAL, objective="find papers", steps=[
                PlanStep(step_id="s1", description="search", tool_name="arxiv_search", arguments={"q": "x"})
            ])
            await sp.save_phase_plan(tid, TaskPhase.PAPER_RETRIEVAL, plan)
            m2 = sp.load_manifest(tid)
            assert m2.phases["paper_retrieval"].artifacts.plan is not None
            assert (sp.base_dir / tid / m2.phases["paper_retrieval"].artifacts.plan).exists()
            print("✅ D03-3: mark_phase_started + save_phase_plan正确写入")
    asyncio.run(_run())

def test_d03_update_step_and_errors():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid, spec = _make_spec(td)
            await sp.create_task_manifest(spec)
            await sp.mark_phase_started(tid, TaskPhase.PAPER_RETRIEVAL)
            await sp.update_step_in_manifest(tid, TaskPhase.PAPER_RETRIEVAL, "s1", "arxiv_search",
                                             success=True, artifact_name="paper_retrieval_s1_arxiv_search_result.json",
                                             error_msg=None, duration_ms=1500)
            await sp.update_step_in_manifest(tid, TaskPhase.PAPER_RETRIEVAL, "s2", "paper_parser",
                                             success=False, artifact_name=None,
                                             error_msg="Parse failed", duration_ms=300)
            m = sp.load_manifest(tid)
            assert len(m.phases["paper_retrieval"].steps) == 2
            assert m.phases["paper_retrieval"].steps["s1"].status == "success"
            assert m.phases["paper_retrieval"].steps["s1"].artifact == "paper_retrieval_s1_arxiv_search_result.json"
            assert m.phases["paper_retrieval"].steps["s2"].status == "failed"
            assert len(m.phases["paper_retrieval"].errors) >= 1
            assert m.total_errors >= 1
            print(f"✅ D03-4: update_step_in_manifest记录成功/失败steps+errors")
    asyncio.run(_run())

def test_d03_mark_task_completed_and_index():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid, spec = _make_spec(td)
            await sp.create_task_manifest(spec)
            await sp.mark_phase_started(tid, TaskPhase.PAPER_RETRIEVAL)
            await sp.save_phase_summary(tid, TaskPhase.PAPER_RETRIEVAL, {"summary": "ok", "key_findings": ["f1"], "next_actions": []})
            await sp.mark_phase_completed(tid, TaskPhase.PAPER_RETRIEVAL, EvaluationVerdict.PASS, score=0.9)
            await sp.mark_task_completed(tid, "passed")
            m = sp.load_manifest(tid)
            assert m.status == "passed"
            assert m.phases["paper_retrieval"].status == "PASS"
            tasks = sp.list_tasks()
            found = [t for t in tasks if t["task_id"] == tid]
            assert len(found) == 1
            assert found[0]["status"] == "passed"
            print(f"✅ D03-5: mark_task_completed正确更新manifest+index, list_tasks返回{len(tasks)}个任务")
    asyncio.run(_run())

def test_d03_index_corrupt_triggers_rebuild():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid1, spec1 = _make_spec(td)
            tid2, spec2 = _make_spec(td)
            await sp.create_task_manifest(spec1)
            await sp.create_task_manifest(spec2)
            idx_path = sp.base_dir / TASKS_INDEX_FILENAME
            assert idx_path.exists()
            idx_path.write_text("{garbage!")
            tasks = sp.list_tasks()
            assert len(tasks) == 2
            assert idx_path.exists()
            data = json.loads(idx_path.read_text())
            assert data["version"] == 1
            print(f"✅ D03-6: index损坏时自动重建, {len(tasks)}个任务恢复")
    asyncio.run(_run())

def test_d03_save_eval_output_summary():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid, spec = _make_spec(td)
            await sp.create_task_manifest(spec)
            await sp.mark_phase_started(tid, TaskPhase.RESULT_REPORTING)
            await sp.save_phase_output(tid, TaskPhase.RESULT_REPORTING, {"report": "final report content"})
            await sp.save_phase_summary(tid, TaskPhase.RESULT_REPORTING, {"summary": "done", "key_findings": [], "next_actions": []})
            eval_result = EvaluationResult(
                id="eval_001",
                task_state_id=tid, phase=TaskPhase.RESULT_REPORTING,
                verdict=EvaluationVerdict.PASS, score=0.95,
                evidence_summary="all good",
            )
            await sp.save_phase_eval(tid, TaskPhase.RESULT_REPORTING, EvaluationVerdict.PASS, eval_result)
            m = sp.load_manifest(tid)
            assert m.phases["result_reporting"].artifacts.output is not None
            assert m.phases["result_reporting"].artifacts.summary is not None
            assert m.phases["result_reporting"].artifacts.eval is not None
            assert m.phases["result_reporting"].score == 0.95
            print("✅ D03-7: save_phase_output/summary/eval全部正确写入manifest")
    asyncio.run(_run())

def test_d03_record_revision():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid, spec = _make_spec(td)
            await sp.create_task_manifest(spec)
            await sp.mark_phase_started(tid, TaskPhase.EXPERIMENT_EXECUTION)
            await sp.record_revision(tid, TaskPhase.EXPERIMENT_EXECUTION, 2)
            m = sp.load_manifest(tid)
            assert m.phases["experiment_execution"].revisions == 2
            assert m.total_revisions == 2
            print("✅ D03-8: record_revision正确累计revisions计数")
    asyncio.run(_run())


# ==================== D04 CLI tests (argparse parsing) ====================

def test_d04_cli_imports():
    from paper_agent.cli import main, cmd_tasks_list, cmd_task_show, cmd_task_errors, cmd_task_artifacts, cmd_task_resume
    print("✅ D04-1: CLI模块和5个子命令handler全部可导入")

def test_d04_cli_subcommand_help():
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "paper_agent.cli", "--help"],
        cwd=str(Path(__file__).parent.parent / "src"),
        capture_output=True, text=True, timeout=10,
    )
    assert "tasks" in result.stdout
    assert "task" in result.stdout
    assert "run" in result.stdout
    print("✅ D04-2: CLI help显示run/tasks/task子命令")

def test_d04_cli_tasks_list_json_output():
    async def _run():
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as td:
            os.environ["ARTIFACTS_DIR"] = str(Path(td) / "artifacts")
            sp = _make_sp(td)
            tid, spec = _make_spec(td)
            await sp.create_task_manifest(spec)
            from paper_agent import cli
            class FakeArgs:
                pass
            args = FakeArgs()
            f = io.StringIO()
            with redirect_stdout(f):
                try:
                    await cli.cmd_tasks_list(args)
                except SystemExit:
                    pass
            out = f.getvalue()
            data = json.loads(out)
            assert "tasks" in data
            assert "total" in data
            print(f"✅ D04-3: tasks list JSON输出正确, total={data['total']}")
    asyncio.run(_run())

def test_d04_cli_task_not_found_returns_error_json():
    async def _run():
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as td:
            os.environ["ARTIFACTS_DIR"] = str(Path(td) / "artifacts")
            from paper_agent import cli
            class FakeArgs:
                task_id = "nonexistent_task_xyz"
            args = FakeArgs()
            f = io.StringIO()
            try:
                with redirect_stdout(f):
                    await cli.cmd_task_show(args)
            except SystemExit as e:
                assert e.code == 1
            out = f.getvalue()
            data = json.loads(out)
            assert "error" in data
            assert data["error"] == "task_not_found"
            print(f"✅ D04-4: task not found返回error JSON + exit 1")
    asyncio.run(_run())


# ==================== Run all tests ====================

if __name__ == "__main__":
    tests = [
        # D01
        test_d01_phase_short_mapping_covers_all_phases,
        test_d01_artifact_filename_step_level,
        test_d01_artifact_filename_phase_level,
        test_d01_artifact_filename_with_revision,
        test_d01_parse_roundtrip,
        test_d01_parse_fixed_names,
        test_d01_parse_invalid,
        # D02
        test_d02_create_empty_manifest,
        test_d02_atomic_write,
        test_d02_load_json_corrupt,
        test_d02_scan_artifacts,
        test_d02_manifest_serialization,
        # D03
        test_d03_create_manifest_and_index,
        test_d03_load_manifest_rebuilds_on_corrupt,
        test_d03_mark_phase_and_save_plan,
        test_d03_update_step_and_errors,
        test_d03_mark_task_completed_and_index,
        test_d03_index_corrupt_triggers_rebuild,
        test_d03_save_eval_output_summary,
        test_d03_record_revision,
        # D04
        test_d04_cli_imports,
        test_d04_cli_subcommand_help,
        test_d04_cli_tasks_list_json_output,
        test_d04_cli_task_not_found_returns_error_json,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"❌ FAIL {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed > 0:
        sys.exit(1)

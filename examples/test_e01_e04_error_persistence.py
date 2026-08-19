"""
E01-E04 失败落盘持久化 单元测试
覆盖:
  E01: ErrorContext/PhaseCompletionRecord模型、序列化、命名
  E02: dump_error_context/save_completion_record StatePersistence方法
  E03: TaskJsonLogger 事件写入+JSONL格式
  E04: trim_checkpoints自动清理
"""
import asyncio
import json
import shutil
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from paper_agent.common.models.base import EvaluationVerdict, TaskPhase
from paper_agent.common.models.execution_plan import ExecutionPlan, PlanStep
from paper_agent.common.models.evaluation_result import EvaluationResult
from paper_agent.common.persistence import StatePersistence
from paper_agent.common.persistence.error_context import (
    ErrorContext, PhaseCompletionRecord, StepSnapshot,
    build_error_filename, build_completion_filename,
    build_step_snapshots_from_plan, format_traceback,
    snapshot_messages, snapshot_model,
    write_error_context, write_completion_record,
)
from paper_agent.common.persistence.manifest import MANIFEST_FILENAME
from paper_agent.common.persistence.naming import artifact_filename, parse_artifact_filename
from paper_agent.common.persistence.task_jsonl_logger import TaskJsonLogger
from paper_agent.common.models.research_spec import ResearchSpec


def _make_sp(tmpdir):
    sp = StatePersistence()
    sp.base_dir = Path(tmpdir) / "artifacts"
    sp.base_dir.mkdir(parents=True, exist_ok=True)
    return sp

def _make_spec_and_task(sp, tmpdir, user_query="test query"):
    import uuid
    tid = uuid.uuid4().hex[:16]
    spec = ResearchSpec(id=tid, user_query=user_query, task_type="topic_research", keywords=["t"])
    task_dir = sp.base_dir / tid
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "research_spec.json").write_text(spec.model_dump_json())
    return tid, spec


# ==================== E01 ErrorContext model tests ====================

def test_e01_error_context_model_creation():
    ctx = ErrorContext(
        task_id="t1", phase="paper_retrieval", revision=0,
        error_type="exception", error_message="KeyError: 'results'",
    )
    assert ctx.id is not None
    assert ctx.timestamp is not None
    assert ctx.error_type == "exception"
    assert ctx.phase == "paper_retrieval"
    assert len(ctx.step_snapshots) == 0
    print("✅ E01-1: ErrorContext模型默认值正确")

def test_e01_phase_completion_record():
    rec = PhaseCompletionRecord(
        task_id="t1", phase="paper_retrieval", verdict="PASS",
        score=0.9, steps_total=3, steps_succeeded=3, steps_failed=0,
        duration_ms=15000, artifacts=["a.json", "b.json"],
    )
    assert rec.completed_at is not None
    assert rec.steps_total == 3
    assert rec.score == 0.9
    d = json.loads(rec.model_dump_json())
    assert d["verdict"] == "PASS"
    print("✅ E01-2: PhaseCompletionRecord模型序列化正确")

def test_e01_build_error_filename():
    n = build_error_filename(TaskPhase.PAPER_RETRIEVAL, "revise", revision=2)
    assert "paper_retrieval" in n
    assert "_error" in n
    assert "_r2" in n
    assert n.endswith(".json")

    n2 = build_error_filename(TaskPhase.EXPERIMENT_EXECUTION, "exception", revision=0)
    assert "exp_exec" in n2
    assert "fatal_error" in n2

    n3 = build_error_filename(TaskPhase.PAPER_PARSING, "blocked", revision=1)
    assert "_r1" in n3
    assert "_fatal" in n3
    print(f"✅ E01-3: error文件名生成正确 → {n}, {n2}, {n3}")

def test_e01_build_completion_filename():
    n = build_completion_filename(TaskPhase.PAPER_RETRIEVAL)
    assert n == "paper_retrieval_completion.json"
    parsed = parse_artifact_filename(n)
    assert parsed is not None
    assert parsed["type"] == "completion"
    print(f"✅ E01-4: completion文件名生成+解析正确 → {n}")

def test_e01_format_traceback():
    try:
        raise ValueError("test error for traceback")
    except ValueError as e:
        tb = format_traceback(e)
        assert tb is not None
        assert "ValueError" in tb
        assert "test error for traceback" in tb
    tb_none = format_traceback(None)
    assert tb_none is None
    print("✅ E01-5: format_traceback正确捕获异常栈")

def test_e01_build_step_snapshots_from_plan():
    steps = [
        PlanStep(step_id="s1", description="search", tool_name="arxiv_search",
                 arguments={"q": "test"}, executed=True, success=True,
                 artifact_id="paper_retrieval_s1_arxiv_search_result.json",
                 duration_ms=1200),
        PlanStep(step_id="s2", description="parse", tool_name="paper_parser",
                 arguments={}, executed=True, success=False,
                 error="Parse failed", duration_ms=500),
    ]
    plan = ExecutionPlan(phase=TaskPhase.PAPER_RETRIEVAL, objective="test", steps=steps)
    snaps = build_step_snapshots_from_plan(plan)
    assert len(snaps) == 2
    assert snaps[0].step_id == "s1"
    assert snaps[0].success is True
    assert snaps[0].artifact_id is not None
    assert snaps[1].success is False
    assert snaps[1].error == "Parse failed"
    print("✅ E01-6: build_step_snapshots_from_plan从plan构建快照正确")

def test_e01_snapshot_messages():
    msgs = [
        {"role": "system", "content": "you are a helpful assistant"},
        {"role": "user", "content": "search papers"},
    ]
    result = snapshot_messages(msgs)
    assert len(result) == 2
    assert result[0]["role"] == "system"
    print("✅ E01-7: snapshot_messages正确序列化消息列表")

def test_e01_write_error_and_completion_files():
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        ctx = ErrorContext(
            task_id="t1", phase="paper_retrieval", error_type="exception",
            error_message="test err", traceback="Traceback:\n...",
            step_snapshots=[StepSnapshot(step_id="s1", tool_name="arxiv_search", success=True)],
        )
        path = write_error_context(tdir, ctx)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["error_type"] == "exception"
        assert len(data["step_snapshots"]) == 1

        rec = PhaseCompletionRecord(
            task_id="t1", phase="paper_retrieval", verdict="PASS",
            score=0.95, steps_total=1, steps_succeeded=1,
        )
        p2 = write_completion_record(tdir, rec)
        assert p2.exists()
        d2 = json.loads(p2.read_text())
        assert d2["verdict"] == "PASS"
        print(f"✅ E01-8: write_error_context/write_completion_record落盘正确 → {path.name}, {p2.name}")


# ==================== E03 TaskJsonLogger tests ====================

def test_e03_jsonl_logger_writes_events():
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        jl = TaskJsonLogger(tdir, "task_test")
        jl.phase_started("paper_retrieval", revision=0)
        jl.step_executed("s1", "arxiv_search", True, duration_ms=1500,
                         artifact="paper_retrieval_s1_result.json")
        jl.step_executed("s2", "paper_parser", False, error="parse failed")
        jl.revision_triggered("exp_exec", 1, reason="low score")
        jl.checkpoint_saved("ckpt_001.json")
        jl.error_dumped("exception", "exp_exec_fatal_error.json", "KeyError")
        jl.warning("something suspicious", detail="value")
        jl.cleanup(["checkpoint_old1.json", "checkpoint_old2.json"])
        jl.phase_completed("paper_retrieval", "PASS", score=0.9, duration_ms=30000)
        jl.task_completed("passed", total_duration_ms=60000, total_phases=3, total_revisions=0)
        jl.close()

        log_path = tdir / "logs" / "run.jsonl"
        assert log_path.exists()
        lines = [json.loads(l) for l in log_path.read_text().strip().split("\n")]
        events = [l["event"] for l in lines]
        assert events == [
            "phase_started", "step_executed", "step_executed",
            "revision_triggered", "checkpoint_saved", "error_dumped",
            "warning", "cleanup", "phase_completed", "task_completed",
        ]
        assert lines[0]["phase"] == "paper_retrieval"
        assert lines[1]["success"] is True
        assert lines[1]["artifact"] == "paper_retrieval_s1_result.json"
        assert lines[2]["success"] is False
        assert lines[2]["error"] == "parse failed"
        assert lines[5]["error_type"] == "exception"
        assert lines[7]["count"] == 2
        assert lines[9]["status"] == "passed"
        print(f"✅ E03-1: JSONL写入10种事件，格式正确，共{len(lines)}行")


# ==================== E04 trim_checkpoints tests ====================

def test_e04_trim_checkpoints_keeps_latest_n():
    with tempfile.TemporaryDirectory() as td:
        sp = _make_sp(td)
        tid, _ = _make_spec_and_task(sp, td)
        task_dir = sp.base_dir / tid
        ckpt_dir = task_dir / "checkpoints"
        ckpt_dir.mkdir(exist_ok=True)
        for i in range(10):
            (ckpt_dir / f"checkpoint_20260818_12000{i}.json").write_text("{}")
        import time
        time.sleep(0.01)
        deleted = sp.trim_checkpoints(tid, keep=5)
        remaining = list(ckpt_dir.glob("checkpoint_*.json"))
        assert len(remaining) == 5
        assert len(deleted) == 5
        print(f"✅ E04-1: trim_checkpoints保留最近5个，删除{len(deleted)}个旧checkpoint")

def test_e04_trim_under_limit_no_op():
    with tempfile.TemporaryDirectory() as td:
        sp = _make_sp(td)
        tid, _ = _make_spec_and_task(sp, td)
        task_dir = sp.base_dir / tid
        ckpt_dir = task_dir / "checkpoints"
        ckpt_dir.mkdir(exist_ok=True)
        for i in range(3):
            (ckpt_dir / f"checkpoint_20260818_12000{i}.json").write_text("{}")
        deleted = sp.trim_checkpoints(tid, keep=5)
        assert len(deleted) == 0
        assert len(list(ckpt_dir.glob("checkpoint_*.json"))) == 3
        print("✅ E04-2: checkpoint数量≤keep时不删除")


# ==================== E02 StatePersistence integration tests ====================

def test_e02_dump_error_context_creates_file_and_updates_manifest():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid, spec = _make_spec_and_task(sp, td)
            await sp.create_task_manifest(spec)

            plan = ExecutionPlan(phase=TaskPhase.PAPER_RETRIEVAL, objective="test", steps=[
                PlanStep(step_id="s1", description="search papers", tool_name="arxiv_search",
                         arguments={"q": "test"}, executed=True, success=True,
                         duration_ms=1500, artifact_id="paper_retrieval_s1_result.json"),
                PlanStep(step_id="s2", description="bad tool", tool_name="bad_tool",
                         arguments={}, executed=True, success=False,
                         error="tool failed", duration_ms=200),
            ])
            eval_result = EvaluationResult(
                id="eval_001", task_state_id=tid, phase=TaskPhase.PAPER_RETRIEVAL,
                verdict=EvaluationVerdict.REVISE, score=0.5,
                evidence_summary="too many issues",
            )

            try:
                raise RuntimeError("simulated failure")
            except RuntimeError as e:
                path = await sp.dump_error_context(
                    tid, TaskPhase.PAPER_RETRIEVAL, "exception",
                    error_message=str(e), exc=e, plan=plan,
                    eval_result=eval_result, revision=1,
                    messages=[{"role": "user", "content": "test"}],
                )

            assert path is not None
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["error_type"] == "exception"
            assert data["traceback"] is not None
            assert "RuntimeError" in data["traceback"]
            assert len(data["step_snapshots"]) == 2
            assert data["step_snapshots"][0]["tool_name"] == "arxiv_search"
            assert len(data["messages_snapshot"]) == 1
            assert data["eval_result"]["score"] == 0.5

            m = sp.load_manifest(tid)
            assert m is not None
            assert m.phases["paper_retrieval"].artifacts is not None
            assert m.total_errors >= 1
            assert any("error" in f.type for f in m.files)
            print(f"✅ E02-1: dump_error_context落盘完整现场+更新manifest+注册files → {path.name}")
    asyncio.run(_run())

def test_e02_save_completion_record():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            tid, spec = _make_spec_and_task(sp, td)
            await sp.create_task_manifest(spec)
            await sp.mark_phase_started(tid, TaskPhase.PAPER_RETRIEVAL)

            plan = ExecutionPlan(phase=TaskPhase.PAPER_RETRIEVAL, objective="test", steps=[
                PlanStep(step_id="s1", description="search", tool_name="arxiv_search", arguments={"q":"t"},
                         executed=True, success=True, duration_ms=1000,
                         artifact_id="paper_retrieval_s1_result.json"),
                PlanStep(step_id="s2", description="parse", tool_name="paper_parser", arguments={},
                         executed=True, success=True, duration_ms=2000),
            ])
            path = await sp.save_completion_record(
                tid, TaskPhase.PAPER_RETRIEVAL, EvaluationVerdict.PASS,
                score=0.95, duration_ms=15000, plan=plan, revision=0,
            )
            assert path is not None
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["verdict"] == "PASS"
            assert data["score"] == 0.95
            assert data["steps_total"] == 2
            assert data["steps_succeeded"] == 2
            assert data["steps_failed"] == 0
            assert "paper_retrieval_s1_result.json" in data["artifacts"]
            print(f"✅ E02-2: save_completion_record正确统计steps+artifacts → {path.name}")
    asyncio.run(_run())

def test_e02_dump_error_degrades_gracefully():
    async def _run():
        with tempfile.TemporaryDirectory() as td:
            sp = _make_sp(td)
            path = await sp.dump_error_context(
                "nonexistent_task", TaskPhase.PAPER_RETRIEVAL, "exception",
                error_message="test",
            )
            assert path is None
            print("✅ E02-3: dump_error_context对不存在task降级返回None(不抛异常)")
    asyncio.run(_run())


# ==================== Run all tests ====================

if __name__ == "__main__":
    tests = [
        # E01
        test_e01_error_context_model_creation,
        test_e01_phase_completion_record,
        test_e01_build_error_filename,
        test_e01_build_completion_filename,
        test_e01_format_traceback,
        test_e01_build_step_snapshots_from_plan,
        test_e01_snapshot_messages,
        test_e01_write_error_and_completion_files,
        # E03
        test_e03_jsonl_logger_writes_events,
        # E04
        test_e04_trim_checkpoints_keeps_latest_n,
        test_e04_trim_under_limit_no_op,
        # E02
        test_e02_dump_error_context_creates_file_and_updates_manifest,
        test_e02_save_completion_record,
        test_e02_dump_error_degrades_gracefully,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"❌ FAIL {t.__name__}: {e}")
            import traceback as tb
            tb.print_exc()
            failed += 1
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed > 0:
        sys.exit(1)

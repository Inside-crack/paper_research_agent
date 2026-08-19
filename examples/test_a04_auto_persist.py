#!/usr/bin/env python3
"""
A04: Tool result auto-persistence (artifact save-on-execute) tests.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.paper_agent.common.models.execution_plan import ExecutionPlan, PlanStep
from src.paper_agent.common.models.task_state import TaskPhase, TaskState
from src.paper_agent.common.tools.base import ToolResult
from src.paper_agent.common.tools.registry import ToolRegistry
from src.paper_agent.orchestrator.orchestrator import Orchestrator
from src.paper_agent.research_agent import ResearchAgent
from src.paper_agent.common.logging import setup_logging


def _make_fake_research():
    from src.paper_agent.common.agent_base import BaseAgent
    research = MagicMock(spec=ResearchAgent)
    research.message_history = []
    research.system_prompt = "test system prompt"
    research._current_phase = None

    def fake_compact(tool_name, result):
        if tool_name == "arxiv_search" and isinstance(result, dict):
            papers = result.get("results", [])
            return {"results": [
                {"arxiv_id": p.get("arxiv_id", p.get("id", "")), "title": p.get("title", ""),
                 "authors": p.get("authors", [])[:1], "abstract_preview": (p.get("abstract_preview") or "")[:200]}
                for p in papers
            ], "total_results": result.get("total_results", len(papers))}
        return result
    research._compact_result = MagicMock(side_effect=fake_compact)
    research.record_step_result = MagicMock()
    research.initialize = AsyncMock()
    research.start_new_phase = AsyncMock()
    research._on_start_new_phase = AsyncMock()
    research.inject_message = MagicMock()
    research._build_results_prompt = lambda plan: BaseAgent._build_results_prompt(research, plan)
    return research


def _make_orchestrator(tmpdir: str):
    """Orchestrator with fully mocked tools.execute - no real file I/O."""
    tool_registry = ToolRegistry()
    research = _make_fake_research()
    evaluator = MagicMock()
    evaluator.evaluate_phase = AsyncMock(return_value=MagicMock(
        verdict="PASS", score=0.95, issues=[], summary="Good"
    ))
    orch = Orchestrator(research, evaluator, tool_registry)
    orch._tmpdir = tmpdir

    saved_files = {}

    async def fake_tools_execute(tool_name, **kwargs):
        if tool_name == "save_artifact":
            name = kwargs.get("artifact_name", "out.json")
            data = kwargs.get("data", {})
            art_dir = Path(tmpdir) / "artifacts" / kwargs.get("task_id", "")
            art_dir.mkdir(parents=True, exist_ok=True)
            path = art_dir / name
            with open(path, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            saved_files[name] = data
            return ToolResult(success=True, data={"path": str(path), "artifact_name": name}, error=None)
        if tool_name == "arxiv_search":
            return ToolResult(success=True, data=kwargs.get("_mock_data", {"results": [], "total_results": 0}), error=None)
        return ToolResult(success=False, data=None, error=f"unknown tool: {tool_name}")

    orch.tools.execute = AsyncMock(side_effect=fake_tools_execute)
    orch._saved_files = saved_files
    return orch


def _make_task_state(tmpdir: str) -> TaskState:
    ts = TaskState(
        research_spec_id="test-spec",
        workspace_dir=tmpdir,
        artifact_dir=os.path.join(tmpdir, "artifacts"),
    )
    ts.metadata["user_query"] = "test query"
    ts.metadata["research_spec"] = {"task_type": "topic_research", "domain": "test"}
    return ts


def test_planstep_has_artifact_id_field():
    step = PlanStep(step_id="s1", description="test", tool_name="arxiv_search", arguments={"query": "test"})
    assert step.artifact_id is None
    step.artifact_id = "paper_retrieval_s1_result.json"
    assert step.artifact_id == "paper_retrieval_s1_result.json"
    print("✅ Test 1: PlanStep.artifact_id field exists")


def test_successful_step_auto_persists():
    async def _run():
        tmpdir = tempfile.mkdtemp()
        try:
            orch = _make_orchestrator(tmpdir)
            task = _make_task_state(tmpdir)
            step = PlanStep(step_id="step_1", description="search", tool_name="arxiv_search", arguments={"query": "test"})
            fake_results = {"results": [
                {"arxiv_id": "2401.00001", "title": "Paper A", "authors": ["X"], "abstract_preview": "abs A"},
                {"arxiv_id": "2401.00002", "title": "Paper B", "authors": ["Y"], "abstract_preview": "abs B"},
            ], "total_results": 2}

            async def fake_execute(tool_name, **kwargs):
                if tool_name == "arxiv_search":
                    return ToolResult(success=True, data=fake_results, error=None)
                if tool_name == "save_artifact":
                    name = kwargs.get("artifact_name")
                    art_dir = Path(tmpdir) / "artifacts" / kwargs.get("task_id", "")
                    art_dir.mkdir(parents=True, exist_ok=True)
                    with open(art_dir / name, "w") as f:
                        json.dump(kwargs.get("data", {}), f, ensure_ascii=False)
                    return ToolResult(success=True, data={"path": str(art_dir / name), "artifact_name": name}, error=None)
                return ToolResult(success=False, error=f"unknown: {tool_name}")

            orch.tools.execute = AsyncMock(side_effect=fake_execute)
            plan = ExecutionPlan(phase="paper_retrieval", steps=[step])
            await orch._execute_plan(plan, task, TaskPhase.PAPER_RETRIEVAL)

            assert step.success
            assert step.artifact_id and step.artifact_id.endswith("_result.json")
            assert "paper_retrieval" in step.artifact_id
            assert "arxiv_search" in step.artifact_id
            p = Path(tmpdir) / "artifacts" / task.id / step.artifact_id
            assert p.exists(), f"not found: {p}"
            saved = json.loads(p.read_text())
            assert len(saved["results"]) == 2
            print(f"✅ Test 2: Success auto-persisted → {step.artifact_id}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    asyncio.run(_run())


def test_failed_step_auto_persists_error():
    async def _run():
        tmpdir = tempfile.mkdtemp()
        try:
            orch = _make_orchestrator(tmpdir)
            task = _make_task_state(tmpdir)
            step = PlanStep(step_id="step_bad", description="bad", tool_name="arxiv_search", arguments={"query": "test"})

            async def fake_execute(tool_name, **kwargs):
                if tool_name == "arxiv_search":
                    return ToolResult(success=False, data=None, error="API rate limit exceeded")
                if tool_name == "save_artifact":
                    name = kwargs.get("artifact_name")
                    art_dir = Path(tmpdir) / "artifacts" / kwargs.get("task_id", "")
                    art_dir.mkdir(parents=True, exist_ok=True)
                    with open(art_dir / name, "w") as f:
                        json.dump(kwargs.get("data", {}), f, ensure_ascii=False)
                    return ToolResult(success=True, data={"path": str(art_dir / name), "artifact_name": name}, error=None)
                return ToolResult(success=False, error=f"unknown: {tool_name}")

            orch.tools.execute = AsyncMock(side_effect=fake_execute)
            plan = ExecutionPlan(phase="paper_retrieval", steps=[step])
            await orch._execute_plan(plan, task, TaskPhase.PAPER_RETRIEVAL)

            assert not step.success
            assert "_error.json" in step.artifact_id
            p = Path(tmpdir) / "artifacts" / task.id / step.artifact_id
            assert p.exists()
            err = json.loads(p.read_text())
            assert err["step_id"] == "step_bad"
            assert err["tool_name"] == "arxiv_search"
            assert err["success"] is False
            assert "API rate limit" in err["error"]
            assert "timestamp" in err
            print(f"✅ Test 3: Failed step error persisted → {step.artifact_id}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    asyncio.run(_run())


def test_save_artifact_not_recursively_persisted():
    async def _run():
        tmpdir = tempfile.mkdtemp()
        try:
            orch = _make_orchestrator(tmpdir)
            task = _make_task_state(tmpdir)
            step = PlanStep(step_id="step_save", description="save", tool_name="save_artifact",
                            arguments={"artifact_name": "my_output.json", "data": {"key": "value"}})

            async def fake_execute(tool_name, **kwargs):
                if tool_name == "save_artifact":
                    name = kwargs.get("artifact_name", "out.json")
                    art_dir = Path(tmpdir) / "artifacts" / kwargs.get("task_id", "")
                    art_dir.mkdir(parents=True, exist_ok=True)
                    with open(art_dir / name, "w") as f:
                        json.dump(kwargs.get("data", {}), f, ensure_ascii=False)
                    return ToolResult(success=True, data={"artifact_name": name}, error=None)
                return ToolResult(success=False, error=f"unknown: {tool_name}")

            orch.tools.execute = AsyncMock(side_effect=fake_execute)
            plan = ExecutionPlan(phase="paper_retrieval", steps=[step])
            await orch._execute_plan(plan, task, TaskPhase.PAPER_RETRIEVAL)

            assert step.success
            assert step.artifact_id == "my_output.json"
            art_dir = Path(tmpdir) / "artifacts" / task.id
            recursive = [f for f in art_dir.glob("*") if "paper_retrieval_step_save" in f.name]
            assert len(recursive) == 0, f"recursive: {[f.name for f in recursive]}"
            assert (art_dir / "my_output.json").exists()
            print("✅ Test 4: save_artifact does NOT recursively auto-persist")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    asyncio.run(_run())


def test_trace_includes_artifact_id():
    async def _run():
        tmpdir = tempfile.mkdtemp()
        try:
            orch = _make_orchestrator(tmpdir)
            task = _make_task_state(tmpdir)
            step = PlanStep(step_id="step_t", description="search", tool_name="arxiv_search", arguments={"query": "test"})

            async def fake_execute(tool_name, **kwargs):
                if tool_name == "arxiv_search":
                    return ToolResult(success=True, data={"results": [{"arxiv_id": "1", "title": "T1"}], "total_results": 1}, error=None)
                if tool_name == "save_artifact":
                    name = kwargs.get("artifact_name")
                    art_dir = Path(tmpdir) / "artifacts" / kwargs.get("task_id", "")
                    art_dir.mkdir(parents=True, exist_ok=True)
                    with open(art_dir / name, "w") as f:
                        json.dump(kwargs.get("data", {}), f)
                    return ToolResult(success=True, data={"artifact_name": name}, error=None)
                return ToolResult(success=False, error="unknown")

            orch.tools.execute = AsyncMock(side_effect=fake_execute)
            plan = ExecutionPlan(phase="paper_retrieval", steps=[step])
            await orch._execute_plan(plan, task, TaskPhase.PAPER_RETRIEVAL)

            assert step.artifact_id is not None
            assert len(task.trace) >= 1
            last = task.trace[-1]
            assert last.action == "tool_executed"
            print(f"✅ Test 5: Trace recorded, step.artifact_id = {step.artifact_id}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    asyncio.run(_run())


def test_results_prompt_includes_artifact_column():
    research = _make_fake_research()
    step = PlanStep(step_id="s1", description="test", tool_name="arxiv_search", arguments={"query": "test"},
                    executed=True, success=True,
                    result={"results": [{"arxiv_id": "1", "title": "T", "authors": ["A"], "abstract": "abs text", "published_date": "2024-01-01", "categories": [], "code_available_hint": False}]},
                    artifact_id="paper_retrieval_s1_result.json")
    plan = ExecutionPlan(phase="paper_retrieval", steps=[step])
    prompt = research._build_results_prompt(plan)
    assert "| Artifact |" in prompt
    assert "paper_retrieval_s1_result.json" in prompt
    assert "load_artifact" in prompt
    assert "persisted artifact" in prompt.lower() or "Persisted artifact:" in prompt
    print("✅ Test 6: results_prompt has Artifact column + load_artifact reference")


def test_persistence_failure_raises_runtime_error():
    async def _run():
        tmpdir = tempfile.mkdtemp()
        try:
            orch = _make_orchestrator(tmpdir)
            task = _make_task_state(tmpdir)
            step = PlanStep(step_id="step_flaky", description="search", tool_name="arxiv_search", arguments={"query": "test"})

            async def flaky_execute(tool_name, **kwargs):
                if tool_name == "save_artifact" and kwargs.get("_agent") == "orchestrator":
                    return ToolResult(success=False, data=None, error="Disk full!")
                if tool_name == "arxiv_search":
                    return ToolResult(success=True, data={"results": [{"arxiv_id": "1", "title": "T"}], "total_results": 1}, error=None)
                return ToolResult(success=False, error="unknown")

            orch.tools.execute = AsyncMock(side_effect=flaky_execute)
            plan = ExecutionPlan(phase="paper_retrieval", steps=[step])
            raised = False
            try:
                await orch._execute_plan(plan, task, TaskPhase.PAPER_RETRIEVAL)
            except RuntimeError as e:
                raised = True
                assert "Failed to persist tool result" in str(e)
                print(f"✅ Test 7: Persistence failure raises RuntimeError: {str(e)[:70]}...")
            assert raised
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    asyncio.run(_run())


def test_error_persistence_structure():
    async def _run():
        tmpdir = tempfile.mkdtemp()
        try:
            orch = _make_orchestrator(tmpdir)
            task = _make_task_state(tmpdir)
            step = PlanStep(step_id="step_err", description="failing", tool_name="arxiv_search", arguments={"query": "test"})

            async def fake_execute(tool_name, **kwargs):
                if tool_name == "arxiv_search":
                    return ToolResult(success=False, data=None, error="Connection timeout")
                if tool_name == "save_artifact":
                    name = kwargs.get("artifact_name")
                    art_dir = Path(tmpdir) / "artifacts" / kwargs.get("task_id", "")
                    art_dir.mkdir(parents=True, exist_ok=True)
                    with open(art_dir / name, "w") as f:
                        json.dump(kwargs.get("data", {}), f, ensure_ascii=False)
                    return ToolResult(success=True, data={"artifact_name": name}, error=None)
                return ToolResult(success=False, error="unknown")

            orch.tools.execute = AsyncMock(side_effect=fake_execute)
            plan = ExecutionPlan(phase="paper_retrieval", steps=[step])
            await orch._execute_plan(plan, task, TaskPhase.PAPER_RETRIEVAL)

            assert step.artifact_id and "_error" in step.artifact_id
            err = json.loads((Path(tmpdir) / "artifacts" / task.id / step.artifact_id).read_text())
            for f in ("step_id", "tool_name", "phase", "success", "error", "arguments", "timestamp"):
                assert f in err, f"missing: {f}"
            assert err["step_id"] == "step_err"
            assert "Connection timeout" in err["error"]
            print(f"✅ Test 8: Error artifact has all required fields: {sorted(err.keys())}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    asyncio.run(_run())


if __name__ == "__main__":
    setup_logging()
    test_planstep_has_artifact_id_field()
    test_successful_step_auto_persists()
    test_failed_step_auto_persists_error()
    test_save_artifact_not_recursively_persisted()
    test_trace_includes_artifact_id()
    test_results_prompt_includes_artifact_column()
    test_persistence_failure_raises_runtime_error()
    test_error_persistence_structure()
    print("\n🎉 All 8 A04 unit tests passed!")

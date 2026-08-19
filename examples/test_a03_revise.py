#!/usr/bin/env python3
"""A03 REVISE重试策略优化 - 单元测试"""

import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.paper_agent.common.models.base import EvaluationVerdict, SeverityLevel, TaskPhase
from src.paper_agent.common.models.evaluation_result import EvaluationResult, EvaluationIssue
from src.paper_agent.common.models.execution_plan import ExecutionPlan, PlanStep
from src.paper_agent.common.models.task_state import StageStatus, TaskState
from src.paper_agent.orchestrator.orchestrator import Orchestrator
from src.paper_agent.research_agent import ResearchAgent


def make_task_state(phase: TaskPhase, revision: int = 0) -> TaskState:
    ts = TaskState(
        research_spec_id="test-spec",
        workspace_dir="/tmp/test_a03",
        artifact_dir="/tmp/test_a03",
    )
    ts.metadata["user_query"] = "test query"
    ts.metadata["research_spec"] = {"task_type": "topic_research", "domain": "test"}
    stage = StageStatus(phase=phase, revision_count=revision)
    ts.stages[phase] = stage
    return ts


def make_plan_with_results() -> ExecutionPlan:
    steps = []
    for i in range(3):
        s = PlanStep(
            step_id=f"step_{i+1}",
            description=f"Search {i+1}",
            tool_name="arxiv_search",
            arguments={"query": f"query {i+1}"},
        )
        s.executed = True
        s.success = True
        s.result = {
            "query": f"query {i+1}",
            "total_found": 15,
            "results": [
                {
                    "arxiv_id": f"2401.{1000+i*100+j:04d}",
                    "title": f"Paper about topic {j}",
                    "authors": ["Author A", "Author B"],
                    "published_date": "2024-01-15",
                    "categories": ["cs.AI"],
                    "abstract": "This paper presents a novel approach to " * 5,
                }
                for j in range(15)
            ],
        }
        steps.append(s)

    fail_step = PlanStep(
        step_id="step_4",
        description="Save candidates",
        tool_name="save_artifact",
        arguments={"content": "wrong param name"},
    )
    fail_step.executed = True
    fail_step.success = False
    fail_step.error = "Missing required parameter: data"
    steps.append(fail_step)

    return ExecutionPlan(plan_name="test_plan", steps=steps)


def make_eval_result() -> EvaluationResult:
    issues = [
        EvaluationIssue(
            issue_type="error",
            severity=SeverityLevel.HIGH,
            description="save_artifact was not called correctly, candidates not saved",
            suggestion="Use 'data' parameter instead of 'content' when calling save_artifact",
        ),
        EvaluationIssue(
            issue_type="warning",
            severity=SeverityLevel.MEDIUM,
            description="Only 45 papers considered, code_available field not checked",
            suggestion="Filter papers with code repositories available",
        ),
    ]
    return EvaluationResult(
        task_state_id="test-spec",
        phase=TaskPhase.PAPER_RETRIEVAL,
        verdict=EvaluationVerdict.REVISE,
        score=0.65,
        summary="Plan executed but artifact saving failed",
        issues=issues,
    )


def test_record_round_results():
    print("=== Test 1: _record_round_results ===")
    orch = Orchestrator()
    ts = make_task_state(TaskPhase.PAPER_RETRIEVAL, revision=0)
    plan = make_plan_with_results()
    eval_result = make_eval_result()

    orch._record_round_results(ts, TaskPhase.PAPER_RETRIEVAL, plan, eval_result)

    rr = ts.metadata.get("last_round_results")
    assert rr is not None, "last_round_results should exist"
    assert rr["phase"] == "paper_retrieval"
    assert rr["revision"] == 0
    assert rr["total_steps"] == 4
    assert rr["succeeded_steps"] == 3
    assert rr["failed_steps"] == 1
    assert rr["total_papers"] == 45, f"Expected 45 unique papers, got {rr['total_papers']}"
    assert len(rr["eval_issues"]) == 2
    assert rr["eval_issues"][0]["severity"] == "high"
    assert rr["eval_score"] == 0.65
    assert rr["verdict"] == "REVISE"
    assert len(rr["steps"]) == 4
    assert rr["steps"][3]["success"] is False
    assert "Missing required parameter" in rr["steps"][3]["error"]

    print(f"  ✅ last_round_results stored: {rr['total_steps']} steps, "
          f"{rr['succeeded_steps']}/{rr['total_steps']} ok, "
          f"{rr['total_papers']} papers, {len(rr['eval_issues'])} issues")
    print()


def test_build_correction_notes():
    print("=== Test 2: _build_correction_notes ===")
    orch = Orchestrator()
    ts = make_task_state(TaskPhase.PAPER_RETRIEVAL, revision=1)
    plan = make_plan_with_results()
    eval_result = make_eval_result()
    orch._record_round_results(ts, TaskPhase.PAPER_RETRIEVAL, plan, eval_result)
    rr = ts.metadata["last_round_results"]

    notes = orch._build_correction_notes(ts, TaskPhase.PAPER_RETRIEVAL, rr)

    assert "未通过评估" in notes
    assert "3个成功" in notes or "3个步骤中3个成功" in notes
    assert "1个失败" in notes or "1个失败" in notes
    assert "save_artifact" in notes.lower()
    assert "Missing required parameter" in notes
    assert "必须修复以下问题" in notes
    assert "[HIGH]" in notes
    assert "Use 'data' parameter" in notes
    assert "不需要重复执行" in notes
    assert "45" in notes

    print(f"  ✅ correction_notes generated ({len(notes)} chars)")
    print(f"     Preview: {notes[:200]}...")
    print()


def test_build_previous_results_message():
    print("=== Test 3: _build_previous_results_message ===")
    orch = Orchestrator()
    ts = make_task_state(TaskPhase.PAPER_RETRIEVAL, revision=0)
    plan = make_plan_with_results()
    eval_result = make_eval_result()
    orch._record_round_results(ts, TaskPhase.PAPER_RETRIEVAL, plan, eval_result)
    rr = ts.metadata["last_round_results"]

    msg = orch._build_previous_results_message(rr, TaskPhase.PAPER_RETRIEVAL)

    assert "=== 上一轮执行：已有可用数据 ===" in msg
    assert "✅ 成功步骤" in msg
    assert "❌ 失败步骤" in msg
    assert "📄 去重后已有论文列表" in msg
    assert "共45篇" in msg
    assert "展示前30篇" in msg
    assert "不需要重新搜索" in msg
    assert "step_4" in msg
    assert "save_artifact" in msg
    assert "Missing required parameter" in msg

    paper_count_in_msg = msg.count("2401.1")
    assert paper_count_in_msg == 30, f"Should show 30 papers, got {paper_count_in_msg}"

    print(f"  ✅ previous_results_message generated ({len(msg)} chars)")
    print(f"     Papers shown: {paper_count_in_msg}")
    print()


def test_paper_limit_30():
    print("=== Test 4: Paper list capped at 30 ===")
    orch = Orchestrator()
    ts = make_task_state(TaskPhase.PAPER_RETRIEVAL, revision=0)

    steps = []
    for i in range(5):
        s = PlanStep(
            step_id=f"step_{i+1}",
            description=f"Search {i+1}",
            tool_name="arxiv_search",
            arguments={"query": f"q{i}"},
        )
        s.executed = True
        s.success = True
        s.result = {
            "query": f"q{i}",
            "total_found": 20,
            "results": [
                {
                    "arxiv_id": f"2402.{2000+i*100+j:04d}",
                    "title": f"Unique paper {i*20+j}",
                    "authors": ["X"],
                    "published_date": "2024-01-01",
                    "categories": ["cs.AI"],
                    "abstract": "abstract " * 20,
                }
                for j in range(20)
            ],
        }
        steps.append(s)

    plan = ExecutionPlan(plan_name="big_plan", steps=steps)
    eval_result = make_eval_result()
    orch._record_round_results(ts, TaskPhase.PAPER_RETRIEVAL, plan, eval_result)
    rr = ts.metadata["last_round_results"]

    assert rr["total_papers"] == 100, f"Expected 100 unique papers, got {rr['total_papers']}"
    assert len(rr["all_papers"]) == 50, f"all_papers should be capped at 50 for storage"

    msg = orch._build_previous_results_message(rr, TaskPhase.PAPER_RETRIEVAL)
    assert "共100篇" in msg
    assert "展示前30篇" in msg
    assert "另有70篇未展示" in msg

    paper_count = msg.count("2402.2")
    assert paper_count == 30, f"Message should show 30 papers, got {paper_count}"

    print(f"  ✅ 100 papers → stores 50, displays 30, mentions 70 hidden")
    print()


def test_non_paper_phase():
    print("=== Test 5: Non-paper-retrieval phase (no paper list) ===")
    orch = Orchestrator()
    ts = make_task_state(TaskPhase.CODE_LOCATION, revision=0)

    steps = [
        PlanStep(step_id="s1", description="Clone repo", tool_name="clone_repo",
                 arguments={"url": "https://example.com/repo"}),
    ]
    steps[0].executed = True
    steps[0].success = True
    steps[0].result = {"status": "cloned", "path": "/tmp/repo"}

    plan = ExecutionPlan(plan_name="code_plan", steps=steps)
    eval_result = EvaluationResult(
        task_state_id="test",
        phase=TaskPhase.CODE_LOCATION,
        verdict=EvaluationVerdict.PASS,
        score=0.9,
        summary="OK",
        issues=[],
    )
    orch._record_round_results(ts, TaskPhase.CODE_LOCATION, plan, eval_result)
    rr = ts.metadata["last_round_results"]
    msg = orch._build_previous_results_message(rr, TaskPhase.CODE_LOCATION)

    assert "📄" not in msg, "Non-paper phase should not show paper list"
    assert "成功步骤" in msg
    assert rr["total_papers"] == 0

    print(f"  ✅ Non-paper phase message correct ({len(msg)} chars, no paper list)")
    print()


def test_degraded_mode_no_last_round():
    print("=== Test 6: Graceful degradation (correction without last_round) ===")
    orch = Orchestrator()
    ts = make_task_state(TaskPhase.PAPER_RETRIEVAL, revision=1)
    ts.metadata.pop("last_round_results", None)

    notes = orch._build_correction_notes(ts, TaskPhase.PAPER_RETRIEVAL, None)
    assert notes  # Should return generic message, not crash
    assert "corrected plan" in notes.lower() or "修正" in notes

    print(f"  ✅ Degraded correction works: {notes[:80]}...")
    print()


def test_degraded_mode_incomplete_data():
    print("=== Test 7: Graceful degradation (incomplete last_round) ===")
    orch = Orchestrator()
    ts = make_task_state(TaskPhase.PAPER_RETRIEVAL, revision=1)
    broken_round = {
        "phase": "paper_retrieval",
        "revision": 0,
    }
    notes = orch._build_correction_notes(ts, TaskPhase.PAPER_RETRIEVAL, broken_round)
    assert notes
    assert "修正" in notes or "corrected" in notes.lower()

    msg = orch._build_previous_results_message(broken_round, TaskPhase.PAPER_RETRIEVAL)
    assert msg
    assert "=== 上一轮执行" in msg
    print(f"  ✅ Incomplete data handled without crash")
    print()


def test_inject_message_requires_init():
    print("=== Test 8: Negative - inject_message before init raises RuntimeError ===")
    agent = ResearchAgent()
    try:
        agent.inject_message("test")
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "not initialized" in str(e)
        print(f"  ✅ inject_message before init raises RuntimeError: {str(e)[:60]}...")
    print()


def test_force_reset_clears_history():
    print("=== Test 9: start_new_phase(force=True) clears history ===")
    async def run():
        agent = ResearchAgent()
        ts = make_task_state(TaskPhase.PAPER_RETRIEVAL, revision=0)
        await agent.start_new_phase(TaskPhase.PAPER_RETRIEVAL, ts, [])
        initial_len = len(agent.message_history)
        agent.inject_message("some garbage from previous round")
        agent.inject_message("more garbage")
        assert len(agent.message_history) == initial_len + 2

        await agent.start_new_phase(TaskPhase.PAPER_RETRIEVAL, ts, [], force=True)
        assert len(agent.message_history) == initial_len, \
            f"After force reset, history should be {initial_len} (anchors only), got {len(agent.message_history)}"
        for msg in agent.message_history:
            assert "garbage" not in msg.content, "Old messages should be cleared"

    asyncio.run(run())
    print(f"  ✅ force=True correctly resets history, old messages removed")
    print()


if __name__ == "__main__":
    print("A03 REVISE重试策略优化 - 单元测试")
    print("=" * 60)
    print()

    test_record_round_results()
    test_build_correction_notes()
    test_build_previous_results_message()
    test_paper_limit_30()
    test_non_paper_phase()
    test_degraded_mode_no_last_round()
    test_degraded_mode_incomplete_data()
    test_inject_message_requires_init()
    test_force_reset_clears_history()

    print("=" * 60)
    print("ALL A03 UNIT TESTS PASSED ✅")

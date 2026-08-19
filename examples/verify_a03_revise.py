"""
E2E验证：A03 REVISE重试策略优化
1. 运行task_initialization → PASS
2. 构造一个失败的paper_retrieval revision=0（3个arxiv_search成功，save_artifact失败）
3. 触发REVISE（revision=1），检查Research Agent的message_history：
   - 旧的LLM对话（revision=0的plan/results_prompt）已被清空
   - 锚点保留（system + spec + 摘要卡）
   - "=== 上一轮执行：已有可用数据 ===" 消息存在
   - 论文列表存在（去重后≤30篇展示）
   - 失败步骤信息存在
   - CORRECTION REQUIRED 段落包含Eval issues
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.config import get_settings
from paper_agent.common.logging import setup_logging
from paper_agent.common.models.base import (
    TaskPhase, EvaluationVerdict, SeverityLevel, Budget,
)
from paper_agent.common.models.evaluation_result import EvaluationResult, EvaluationIssue
from paper_agent.common.models.execution_plan import ExecutionPlan, PlanStep
from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.models.task_state import TaskState
from paper_agent.orchestrator import Orchestrator
from paper_agent.tools import get_default_registry


def check(condition, description):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status}: {description}")
    return condition


def make_failed_paper_retrieval_plan() -> ExecutionPlan:
    """Create a plan where arxiv_search steps succeeded but save_artifact failed"""
    steps = []
    for i, q in enumerate(["multi-agent LLM", "tool use learning", "agent planning"]):
        s = PlanStep(
            step_id=f"step_{i+1}",
            description=f"Search {q}",
            tool_name="arxiv_search",
            arguments={"query": q, "max_results": 10},
        )
        s.executed = True
        s.success = True
        s.duration_ms = 1500
        s.result = {
            "query": q,
            "total_found": 10,
            "results": [
                {
                    "arxiv_id": f"2401.{1000+i*100+j:04d}",
                    "title": f"Paper: {q} - study {j}",
                    "authors": [f"Author{j}", f"Author{j+1}"],
                    "published_date": f"2024-{(j%12)+1:02d}-15",
                    "categories": ["cs.AI", "cs.CL"],
                    "abstract": f"We study {q} and present novel findings about aspect {j}. " * 3,
                    "pdf_url": f"http://arxiv.org/pdf/2401.{1000+i*100+j:04d}",
                }
                for j in range(10)
            ],
        }
        steps.append(s)

    fail_step = PlanStep(
        step_id="step_4",
        description="Save candidates",
        tool_name="save_artifact",
        arguments={"content": []},
    )
    fail_step.executed = True
    fail_step.success = False
    fail_step.duration_ms = 50
    fail_step.error = "Missing required parameter: data"
    steps.append(fail_step)

    return ExecutionPlan(plan_name="paper_retrieval_plan_v0", steps=steps)


def make_revise_eval_result() -> EvaluationResult:
    return EvaluationResult(
        task_state_id="test",
        phase=TaskPhase.PAPER_RETRIEVAL,
        verdict=EvaluationVerdict.REVISE,
        score=0.60,
        summary="save_artifact failed due to wrong parameter name",
        issues=[
            EvaluationIssue(
                issue_type="error",
                severity=SeverityLevel.HIGH,
                description="save_artifact was called with 'content' parameter but requires 'data'",
                suggestion="Call save_artifact with data=<list of papers> to persist candidates",
            ),
            EvaluationIssue(
                issue_type="warning",
                severity=SeverityLevel.MEDIUM,
                description="code_available_hint not checked for papers",
                suggestion="Filter papers that have code repositories available",
            ),
        ],
    )


async def main():
    setup_logging()
    settings = get_settings()
    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    user_query = "帮我调研一下 LLM Agent 相关的最新论文"
    research_spec = ResearchSpec(
        user_query=user_query,
        budget=Budget(max_tokens=20000, max_gpu_minutes=10, max_wall_time_minutes=5),
    )

    task_workspace = settings.workspace_dir / research_spec.id
    task_artifacts = settings.artifact_dir / research_spec.id
    task_workspace.mkdir(parents=True, exist_ok=True)
    task_artifacts.mkdir(parents=True, exist_ok=True)

    task_state = TaskState(
        research_spec_id=research_spec.id,
        workspace_dir=str(task_workspace),
        artifact_dir=str(task_artifacts),
    )
    task_state.metadata["user_query"] = user_query
    task_state.metadata["research_spec"] = research_spec.model_dump(mode="json")

    await orchestrator._ensure_stages_initialized(task_state)
    await orchestrator.evaluation.initialize(task_state)

    print("=" * 70)
    print("Phase 1: task_initialization (normal PASS)")
    print("=" * 70)

    stage_init = task_state.stages[TaskPhase.TASK_INITIALIZATION]
    stage_init.started_at = datetime.utcnow()

    eval1 = await orchestrator._execute_phase_flow(TaskPhase.TASK_INITIALIZATION, task_state)
    print(f"Verdict: {eval1.verdict.value}, Score: {eval1.score:.2f}")

    if eval1.verdict != EvaluationVerdict.PASS:
        print("task_initialization didn't PASS, cannot continue")
        return 1

    stage_init.verdict = EvaluationVerdict.PASS
    stage_init.completed_at = datetime.utcnow()
    output1 = task_state.metadata.get("phase_output_task_initialization", {})
    card1 = orchestrator._build_phase_summary_card(TaskPhase.TASK_INITIALIZATION, output1, eval1)
    task_state.phase_summaries.append(card1)

    print("\n" + "=" * 70)
    print("Phase 2: paper_retrieval revision=0 (simulated REVISE)")
    print("=" * 70)

    stage_pr = task_state.stages[TaskPhase.PAPER_RETRIEVAL]
    stage_pr.started_at = datetime.utcnow()

    # Manually record a failed round (simulating revision=0 failure)
    failed_plan = make_failed_paper_retrieval_plan()
    revise_eval = make_revise_eval_result()
    orchestrator._record_round_results(task_state, TaskPhase.PAPER_RETRIEVAL, failed_plan, revise_eval)
    stage_pr.revision_count = 1  # Mark that revision 0 failed
    task_state.total_revisions = 1

    rr = task_state.metadata["last_round_results"]
    print(f"Recorded failed round: {rr['succeeded_steps']}/{rr['total_steps']} ok, "
          f"{rr['total_papers']} papers, score={rr['eval_score']:.2f}")

    # Now simulate what _execute_phase_flow does on REVISE:
    # start_new_phase(force=True) → inject previous results message → capture history
    await orchestrator.research.start_new_phase(
        TaskPhase.PAPER_RETRIEVAL, task_state, task_state.phase_summaries, force=True
    )

    prev_msg = orchestrator._build_previous_results_message(rr, TaskPhase.PAPER_RETRIEVAL)
    orchestrator.research.inject_message(prev_msg)

    # Build correction notes that would be in CORRECTION section
    correction_notes = orchestrator._build_correction_notes(task_state, TaskPhase.PAPER_RETRIEVAL, rr)

    # Capture history at this point (this is what LLM sees when generating revised plan)
    captured_history = list(orchestrator.research.message_history)

    print("\n" + "=" * 70)
    print("A03 REVISE Strategy Verification - Inspecting captured history")
    print("=" * 70)

    all_ok = True
    history_text = "\n".join(m.content for m in captured_history)

    print(f"Total messages in history at start of revision=1: {len(captured_history)}")

    # Check 1: anchors preserved
    has_system = any(m.role.value == "system" for m in captured_history)
    all_ok &= check(has_system, "System prompt is present (anchor)")

    has_spec = "研究任务规格" in history_text or "Research Spec" in history_text
    all_ok &= check(has_spec, "Research Spec is present (anchor)")

    has_summary = "已完成阶段进度" in history_text or "task_initialization" in history_text
    all_ok &= check(has_summary, "task_initialization summary card is present (anchor)")

    # Check 2: old revision=0 LLM dialogue cleared (no old plan/results_prompt)
    no_old_plan = "paper_retrieval_plan_v0" not in history_text
    all_ok &= check(no_old_plan, "Old revision=0 plan JSON not in history (no anchoring)")

    # Check 3: previous results message is injected
    has_prev_data_header = "=== 上一轮执行：已有可用数据 ===" in history_text
    all_ok &= check(has_prev_data_header, "'已有可用数据' message is injected")

    has_success_steps = "✅ 成功步骤" in history_text
    all_ok &= check(has_success_steps, "Successful steps are listed")

    has_failed_steps = "❌ 失败步骤" in history_text
    all_ok &= check(has_failed_steps, "Failed steps are listed")

    has_save_error = "Missing required parameter: data" in history_text
    all_ok &= check(has_save_error, "Save_artifact error message is present")

    has_paper_list_header = "去重后已有论文列表" in history_text
    all_ok &= check(has_paper_list_header, "Paper list section is present")

    paper_count = history_text.count("2401.1")
    has_papers = paper_count == 30, f"30 papers shown (got {paper_count})"
    all_ok &= check(paper_count == 30, f"Paper list shows exactly 30 papers (got {paper_count})")

    has_no_repeat_hint = "不需要重新搜索" in history_text or "不需要重复" in history_text
    all_ok &= check(has_no_repeat_hint, "Hint about not needing to re-search is present")

    # Check 4: correction_notes content
    has_correction_header = "未通过评估" in correction_notes
    all_ok &= check(has_correction_header, "Correction notes mention evaluation failure")

    has_high_issue = "[HIGH]" in correction_notes
    all_ok &= check(has_high_issue, "HIGH severity issues are in correction notes")

    has_param_fix = "data" in correction_notes and "save_artifact" in correction_notes.lower()
    all_ok &= check(has_param_fix, "Correction includes specific fix for save_artifact parameter")

    # Check 5: history is compact (no bloat)
    # Expected: system + spec + summaries + prev_data_msg = 4 messages (phase_prompt added later by generate_plan)
    is_compact = len(captured_history) <= 5
    all_ok &= check(is_compact, f"History is compact at REVISE start ({len(captured_history)} messages, expected ≤5)")

    # Check 6: correction + prev_data total size reasonable
    total_injected = len(prev_msg) + len(correction_notes)
    reasonable_size = total_injected < 15000
    all_ok &= check(reasonable_size, f"Injected correction+data size reasonable ({total_injected} chars, expected <15K)")

    print(f"\n  Injected message sizes: prev_data={len(prev_msg)} chars, correction={len(correction_notes)} chars")

    print(f"\nHistory message breakdown:")
    for i, m in enumerate(captured_history):
        role = m.role.value if hasattr(m.role, 'value') else str(m.role)
        preview = (m.content[:150].replace('\n', ' ') + "...") if len(m.content) > 150 else m.content.replace('\n', ' ')
        print(f"  [{i}] {role}: {preview}")

    print(f"\nCorrection notes preview:")
    for line in correction_notes.split('\n')[:12]:
        print(f"  {line}")

    print("\n" + "=" * 70)
    if all_ok:
        print("🎉 A03 REVISE策略优化验证全部通过！")
    else:
        print("❌ 部分验证失败")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

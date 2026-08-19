"""
E2E验证：A01 阶段间上下文隔离效果
1. 运行task_initialization
2. 进入paper_retrieval后，立即检查Research Agent的message_history
3. 验证：
   - 有system prompt
   - 有research_spec
   - 有task_initialization摘要卡
   - 没有task_initialization的原始save_artifact工具结果（没有大段JSON）
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.config import get_settings
from paper_agent.common.logging import setup_logging
from paper_agent.common.models.base import TaskPhase, EvaluationVerdict, Budget
from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.models.task_state import TaskState
from paper_agent.orchestrator import Orchestrator
from paper_agent.tools import get_default_registry


def check(condition, description):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status}: {description}")
    return condition


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
    print("Phase 1: task_initialization")
    print("=" * 70)

    stage = task_state.stages[TaskPhase.TASK_INITIALIZATION]
    stage.started_at = datetime.utcnow()

    eval1 = await orchestrator._execute_phase_flow(TaskPhase.TASK_INITIALIZATION, task_state)
    print(f"Verdict: {eval1.verdict.value}, Score: {eval1.score}")

    if eval1.verdict != EvaluationVerdict.PASS:
        print("task_initialization didn't PASS, cannot verify isolation")
        return 1

    stage.verdict = EvaluationVerdict.PASS
    stage.completed_at = datetime.utcnow()
    output1 = task_state.metadata.get("phase_output_task_initialization", {})
    card1 = orchestrator._build_phase_summary_card(TaskPhase.TASK_INITIALIZATION, output1, eval1)
    task_state.phase_summaries.append(card1)
    print(f"Summary card added, total summaries: {len(task_state.phase_summaries)}")

    # Count messages in history AFTER task_initialization (before reset)
    history_after_init = len(orchestrator.research.message_history)
    print(f"History messages after task_init: {history_after_init}")

    print("\n" + "=" * 70)
    print("Phase 2: paper_retrieval (start_new_phase will reset context)")
    print("=" * 70)

    stage2 = task_state.stages[TaskPhase.PAPER_RETRIEVAL]
    stage2.started_at = datetime.utcnow()

    # _execute_phase_flow will call start_new_phase internally because revision_count=0
    # We need to inspect history RIGHT AFTER start_new_phase but BEFORE generate_plan sends to LLM
    # To do this, we monkey-patch generate_plan to capture the history state
    captured_history = []
    original_generate_plan = orchestrator.research.generate_plan

    async def capturing_generate_plan(phase, task_state, **kwargs):
        # Capture history at this point (after start_new_phase, before first LLM call)
        captured_history.extend(orchestrator.research.message_history)
        return await original_generate_plan(phase, task_state, **kwargs)

    orchestrator.research.generate_plan = capturing_generate_plan

    eval2 = await orchestrator._execute_phase_flow(TaskPhase.PAPER_RETRIEVAL, task_state)
    print(f"Verdict: {eval2.verdict.value}, Score: {eval2.score}")

    # Restore
    orchestrator.research.generate_plan = original_generate_plan

    print("\n" + "=" * 70)
    print("Isolation Verification - Inspecting captured history (after start_new_phase)")
    print("=" * 70)

    if not captured_history:
        print("❌ FAIL: No history captured!")
        return 1

    print(f"Total messages in history at start of paper_retrieval: {len(captured_history)}")

    history_text = "\n".join(m.content for m in captured_history if hasattr(m, 'content') and m.content)
    all_ok = True

    # Checks
    has_system = any(m.role.value == "system" for m in captured_history)
    all_ok &= check(has_system, "System prompt is present")

    has_spec = "研究任务规格" in history_text or "Research Spec" in history_text
    all_ok &= check(has_spec, "Research Spec is injected")

    has_summary_card = "已完成阶段进度" in history_text or "task_initialization" in history_text
    all_ok &= check(has_summary_card, "Summary card for task_initialization is present")

    # Critical: no raw tool results from task_initialization
    # task_initialization only does save_artifact, so check for save_artifact result JSON blobs
    # The raw result from save_artifact would contain things like "artifact_path" or large JSON structures
    no_raw_tool_results = "artifact_path" not in history_text or '"artifact_path"' not in history_text
    all_ok &= check(no_raw_tool_results, "No raw tool execution results from previous phase in context")

    # Check: history is SMALL (not accumulating)
    msg_count = len(captured_history)
    is_small = msg_count <= 5  # system + spec + summaries + phase_prompt = ~4 messages
    all_ok &= check(is_small, f"History is compact ({msg_count} messages, expected <=5)")

    # Check: summary card content is visible
    card_conclusion = card1.get("conclusion", "")
    has_conclusion = card_conclusion in history_text
    all_ok &= check(has_conclusion, f"Summary card conclusion visible: '{card_conclusion[:50]}...'")

    print(f"\nHistory message breakdown:")
    for i, m in enumerate(captured_history):
        role = m.role.value if hasattr(m.role, 'value') else str(m.role)
        content_preview = (m.content[:120] + "...") if len(m.content) > 120 else m.content
        print(f"  [{i}] {role}: {content_preview}")

    print("\n" + "=" * 70)
    if all_ok:
        print("🎉 上下文隔离验证全部通过！")
    else:
        print("❌ 部分验证失败")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

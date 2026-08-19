"""
端到端测试：任务初始化 → 论文检索
"""
import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.config import get_settings
from paper_agent.common.logging import setup_logging
from paper_agent.common.models.base import TaskPhase, EvaluationVerdict, Budget
from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.models.task_state import TaskState
from paper_agent.orchestrator import Orchestrator
from paper_agent.tools import get_default_registry


async def run_phase(orchestrator, task_state, phase):
    phase_config = orchestrator._get_phase_config(phase)
    print(f"\n{'='*60}")
    print(f"Phase: {phase_config.display_name} ({phase.value})")
    print('='*60)

    stage_status = task_state.stages.get(phase)
    from datetime import datetime
    if not stage_status:
        stage_status = task_state.stages[phase]
    stage_status.started_at = datetime.utcnow()

    eval_result = await orchestrator._execute_phase_flow(phase, task_state)

    print(f"\nVerdict: {eval_result.verdict.value}, Score: {eval_result.score}")
    print(f"Deterministic checks: {eval_result.deterministic_checks_passed} passed, {eval_result.deterministic_checks_failed} failed")
    if eval_result.issues:
        print(f"Issues ({len(eval_result.issues)}):")
        for issue in eval_result.issues:
            print(f"  [{issue.severity.value}] {issue.description[:120]}")
    else:
        print("No issues")

    orchestrator._save_phase_output(phase, task_state, task_state.metadata.get(f"phase_output_{phase.value}", {}))
    return eval_result


async def main():
    setup_logging()
    settings = get_settings()

    print("=" * 70)
    print("End-to-End: Task Init → Paper Retrieval")
    print("=" * 70)

    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    user_query = "帮我调研一下 LLM Agent 相关的最新论文，重点关注多智能体协作和工具使用，2024年以后的"
    print(f"\nQuery: {user_query}\n")

    research_spec = ResearchSpec(
        user_query=user_query,
        budget=Budget(
            max_tokens=settings.budget.max_tokens_per_task,
            max_gpu_minutes=settings.budget.max_gpu_minutes,
            max_wall_time_minutes=settings.budget.max_wall_time_minutes,
        ),
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

    print(f"Task ID: {task_state.id}\n")

    phases_to_run = [TaskPhase.TASK_INITIALIZATION, TaskPhase.PAPER_RETRIEVAL]

    for phase in phases_to_run:
        eval_result = await run_phase(orchestrator, task_state, phase)
        if eval_result.verdict == EvaluationVerdict.PASS:
            stage_status = task_state.stages[phase]
            stage_status.verdict = EvaluationVerdict.PASS
            from datetime import datetime
            stage_status.completed_at = datetime.utcnow()

            research_output = task_state.metadata.get(f"phase_output_{phase.value}", {})
            summary_card = orchestrator._build_phase_summary_card(phase, research_output, eval_result)
            task_state.phase_summaries.append(summary_card)

            history_len = len(orchestrator.research.message_history)
            print(f"✅ {phase.value} PASSED (summary card added, history has {history_len} messages)\n")
        else:
            print(f"❌ {phase.value} {eval_result.verdict.value}, stopping.")
            break

    print("\n" + "="*70)
    print("Final Summary")
    print("="*70)

    retrieval_output = task_state.metadata.get("phase_output_paper_retrieval", {})
    candidates = retrieval_output.get("candidates", [])

    if candidates:
        print(f"\nFound {len(candidates)} candidate papers:")
        for i, paper in enumerate(candidates[:10], 1):
            arxiv_id = paper.get("arxiv_id", "?")
            title = paper.get("title", "?")[:80]
            year = paper.get("published_date", "?")
            code = "🔗code" if paper.get("code_available_hint") else ""
            print(f"  {i}. [{arxiv_id}] ({year}) {title} {code}")

    init_output = task_state.metadata.get("phase_output_task_initialization", {})
    if init_output.get("keywords_english"):
        print(f"\nSearch keywords used: {init_output['keywords_english'][:5]}")

    print(f"\nArtifacts in {task_state.artifact_dir}:")
    artifact_dir = Path(task_state.artifact_dir)
    for f in artifact_dir.glob("*"):
        if f.is_file():
            print(f"  - {f.name} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    asyncio.run(main())

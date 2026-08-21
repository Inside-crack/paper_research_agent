"""
测试任务初始化单阶段
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


async def main():
    setup_logging()
    settings = get_settings()

    print("=" * 70)
    print("Test: TASK_INITIALIZATION phase (single phase)")
    print("=" * 70)

    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    user_query = "帮我调研一下 Agent 相关的最新论文，重点关注多智能体协作和工具使用方向，2024年以后的"
    print(f"\nUser query: {user_query}\n")

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
    await orchestrator.research.initialize(task_state)
    await orchestrator.evaluation.initialize(task_state)

    print(f"Task ID: {task_state.id}")
    print(f"Phase: {task_state.current_phase.value}")
    print()

    print("--- Running task initialization phase flow ---")
    eval_result, _ = await orchestrator._execute_phase_flow(TaskPhase.TASK_INITIALIZATION, task_state)

    print()
    print("=" * 60)
    print(f"Phase verdict: {eval_result.verdict.value}")
    print(f"Score: {eval_result.score}")
    print(f"Deterministic checks: {eval_result.deterministic_checks_passed} passed, {eval_result.deterministic_checks_failed} failed")
    print()

    if eval_result.issues:
        print(f"Issues ({len(eval_result.issues)}):")
        for issue in eval_result.issues:
            print(f"  [{issue.severity.value}] {issue.description}")
            if issue.suggestion:
                print(f"    -> {issue.suggestion}")
    else:
        print("No issues found")

    print()
    print("Research output:")
    phase_output = task_state.metadata.get(f"phase_output_{TaskPhase.TASK_INITIALIZATION.value}", {})
    print(json.dumps(phase_output, ensure_ascii=False, indent=2)[:2000])

    print()
    print("=" * 60)
    print("Artifacts saved:")
    artifact_dir = Path(task_state.artifact_dir)
    if artifact_dir.exists():
        for f in artifact_dir.glob("*"):
            if f.is_file():
                print(f"  - {f.name} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    asyncio.run(main())

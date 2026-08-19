"""
测试任务初始化阶段
"""
import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.config import get_settings
from paper_agent.common.logging import setup_logging
from paper_agent.common.models.base import TaskPhase
from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.models.task_state import TaskState
from paper_agent.orchestrator import Orchestrator
from paper_agent.tools import get_default_registry


async def test_plan_generation():
    setup_logging()
    settings = get_settings()

    print("=" * 60)
    print("Testing Research Agent plan generation for task initialization")
    print("=" * 60)

    registry = get_default_registry()
    print(f"\nRegistered tools: {registry.list_tools()}")

    orchestrator = Orchestrator(tool_registry=registry)

    user_query = "分析论文 ReAct: Synergizing Reasoning and Acting in Language Models (arXiv:2210.03629)"

    research_spec = ResearchSpec(
        user_query=user_query,
        target_paper_arxiv_id="2210.03629",
        task_type="paper_analysis",
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

    print("\n--- Building phase prompt ---")
    phase_prompt = await orchestrator.research._build_phase_prompt(TaskPhase.TASK_INITIALIZATION, task_state)
    print(f"Phase prompt preview (first 500 chars):")
    print(phase_prompt[:500])
    print("...")
    print()

    print("\n--- Generating plan for TASK_INITIALIZATION phase ---")
    plan = await orchestrator.research.generate_plan(
        TaskPhase.TASK_INITIALIZATION,
        task_state,
    )

    print(f"\nPlan name: {plan.plan_name}")
    print(f"Requires human confirmation: {plan.requires_human_confirmation}")
    print(f"Number of steps: {len(plan.steps)}")
    print("\nSteps:")
    for step in plan.steps:
        print(f"  [{step.step_id}] {step.tool_name}")
        print(f"    Description: {step.description}")
        args_str = json.dumps(step.arguments, ensure_ascii=False)[:200]
        print(f"    Arguments: {args_str}")
        print()

    print("\n--- Executing plan steps ---")
    await orchestrator._execute_plan(plan, task_state, TaskPhase.TASK_INITIALIZATION)

    print("\n--- Step execution results ---")
    for step in plan.steps:
        print(f"  [{step.step_id}] {step.tool_name}: success={step.success}")
        if step.success:
            print(f"    Result: {json.dumps(step.result, ensure_ascii=False)[:300]}")
        elif step.error:
            print(f"    Error: {step.error[:200]}")

    print("\n--- Synthesizing result ---")
    result = await orchestrator.research.synthesize_result(TaskPhase.TASK_INITIALIZATION, task_state, plan)
    print(f"\nSynthesized result:")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:1000])

    print("\n\nPlan generation + execution + synthesis test complete!")


if __name__ == "__main__":
    asyncio.run(test_plan_generation())

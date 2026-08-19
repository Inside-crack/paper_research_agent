"""
端到端测试：从用户查询到论文检索
"""
import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.config import get_settings
from paper_agent.common.logging import setup_logging
from paper_agent.common.models.base import TaskPhase, EvaluationVerdict
from paper_agent.orchestrator import Orchestrator
from paper_agent.tools import get_default_registry


async def main():
    setup_logging(level="INFO")
    settings = get_settings()

    print("=" * 70)
    print("End-to-End Test: Task Init → Paper Retrieval")
    print("=" * 70)

    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    user_query = "帮我调研一下 Agent 相关的最新论文，重点关注多智能体协作和工具使用方向，2024年以后的"
    print(f"\nUser query: {user_query}\n")

    task_state = await orchestrator.start_task(user_query=user_query)

    print(f"\nTask created: {task_state.id}")
    print(f"Initial phase: {task_state.current_phase}")
    print()

    max_phases = 3
    phase_count = 0

    while phase_count < max_phases:
        current_phase = task_state.current_phase

        if current_phase in (TaskPhase.COMPLETED, TaskPhase.FAILED):
            break

        phase_config = orchestrator._get_phase_config(current_phase)
        print(f"\n{'='*60}")
        print(f"Running phase: {phase_config.display_name} ({current_phase.value})")
        print('='*60)

        evaluation = await orchestrator.run_phase(task_state)

        print(f"\nPhase verdict: {evaluation.verdict}")
        print(f"Score: {evaluation.score}")
        if evaluation.issues:
            print(f"Issues found: {len(evaluation.issues)}")
            for issue in evaluation.issues[:3]:
                print(f"  - [{issue.severity}] {issue.description[:100]}")

        if evaluation.verdict == EvaluationVerdict.PASS:
            phase_count += 1
            print(f"\n✅ Phase {current_phase.value} PASSED")
        elif evaluation.verdict == EvaluationVerdict.BLOCKED:
            print(f"\n⛔ Phase BLOCKED, stopping.")
            break

        orchestrator.persistence.save_checkpoint(task_state)

    print("\n" + "="*70)
    print("Final Task State:")
    print(f"  Task ID: {task_state.id}")
    print(f"  Current phase: {task_state.current_phase}")
    print(f"  Completed phases:")
    for phase, status in task_state.stages.items():
        if status.completed_at:
            print(f"    - {phase.value}: {status.verdict} (revisions: {status.revision_count})")
    print(f"  Trace entries: {len(task_state.trace)}")
    print(f"  Checkpoint saved at: {task_state.checkpoint_path}")
    print("="*70)

    print("\nArtifacts saved:")
    artifact_dir = Path(task_state.artifact_dir)
    if artifact_dir.exists():
        for f in artifact_dir.glob("**/*"):
            if f.is_file():
                print(f"  - {f.relative_to(artifact_dir)} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    asyncio.run(main())

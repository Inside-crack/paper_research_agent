"""
基础使用示例：启动研究任务
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.config import get_settings
from paper_agent.common.logging import setup_logging
from paper_agent.orchestrator import Orchestrator


async def main():
    setup_logging()
    settings = get_settings()

    orchestrator = Orchestrator()

    # 示例1：从研究主题开始
    query = "ReAct: Synergizing Reasoning and Acting in Language Models"

    print(f"Starting research task: {query}")
    print("=" * 60)

    task_state = await orchestrator.start_task(user_query=query)

    print(f"\nTask finished with status: {task_state.current_phase.value}")
    print(f"Task ID: {task_state.id}")
    print(f"Workspace: {task_state.workspace_dir}")
    print(f"Artifacts: {task_state.artifact_dir}")
    print(f"Trace entries: {len(task_state.trace)}")


if __name__ == "__main__":
    asyncio.run(main())

import asyncio

import pytest

from paper_agent.common.models.base import EvaluationVerdict, TaskPhase
from paper_agent.common.models.evaluation_result import EvaluationResult
from paper_agent.common.models.execution_plan import ExecutionPlan
from paper_agent.common.models.task_state import TaskState
from paper_agent.workflows import PaperProcessingWorkflow


def result() -> tuple[EvaluationResult, ExecutionPlan]:
    return (
        EvaluationResult(
            task_state_id="task-1",
            phase=TaskPhase.PAPER_PARSING,
            verdict=EvaluationVerdict.PASS,
        ),
        ExecutionPlan(
            phase=TaskPhase.PAPER_PARSING.value,
            plan_name="paper_processing_fixed_flow",
        ),
    )


def test_workflow_executes_injected_runner_without_orchestrator_dependency():
    calls: list[str] = []

    async def runner(task_state: TaskState):
        calls.append(task_state.id)
        return result()

    workflow = PaperProcessingWorkflow(runner)
    returned = asyncio.run(
        workflow.run(TaskState(id="task-1", research_spec_id="spec-1"))
    )

    assert calls == ["task-1"]
    assert returned[0].verdict == EvaluationVerdict.PASS


def test_workflow_rejects_invalid_result():
    async def runner(_task_state: TaskState):
        return "not-a-workflow-result"

    with pytest.raises(TypeError, match="must return"):
        asyncio.run(
            PaperProcessingWorkflow(runner).run(
                TaskState(id="task-1", research_spec_id="spec-1")
            )
        )


def test_workflow_rejects_invalid_task_state():
    async def runner(_task_state: TaskState):
        return result()

    with pytest.raises(TypeError, match="task_state"):
        asyncio.run(PaperProcessingWorkflow(runner).run("task-1"))  # type: ignore[arg-type]

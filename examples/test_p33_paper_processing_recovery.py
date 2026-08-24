import asyncio

from paper_agent.common.models.task_state import (
    PaperProcessingStepState,
    TaskState,
)
from paper_agent.workflows import PaperProcessingWorkflow


class FakePersistence:
    def __init__(self):
        self.steps = {
            "download": PaperProcessingStepState(
                status="PASS",
                output_artifacts=["papers/download.json", "papers/paper.pdf"],
            )
        }
        self.updates: list[tuple[str, str]] = []

    async def load_paper_processing_steps(self, task_id: str):
        assert task_id == "task-1"
        return self.steps

    async def update_paper_processing_step(self, task_id, substep, state):
        self.updates.append((task_id, substep))
        self.steps[substep] = state


def test_workflow_reloads_passed_step_state_for_resume():
    async def runner(_task_state: TaskState):
        raise AssertionError("resume state helpers must not execute the runner")

    persistence = FakePersistence()
    workflow = PaperProcessingWorkflow(runner, persistence=persistence)
    task_state = TaskState(id="task-1", research_spec_id="spec-1")

    loaded = asyncio.run(workflow.load_steps(task_state))
    plan = workflow.build_plan()

    assert loaded["download"].status == "PASS"
    assert loaded["download"].output_artifacts == [
        "papers/download.json",
        "papers/paper.pdf",
    ]
    assert [step.step_id for step in plan.steps] == [
        "download",
        "parse",
        "glossary",
        "translate",
        "summary",
    ]


def test_workflow_persists_running_and_pass_step_state():
    async def runner(_task_state: TaskState):
        raise AssertionError("not used")

    persistence = FakePersistence()
    workflow = PaperProcessingWorkflow(runner, persistence=persistence)
    task_state = TaskState(id="task-1", research_spec_id="spec-1")

    asyncio.run(
        workflow.persist_step(
            task_state,
            "parse",
            status="RUNNING",
            input_artifacts=["papers/paper.pdf"],
            output_artifacts=[],
            error=None,
        )
    )
    asyncio.run(
        workflow.persist_step(
            task_state,
            "parse",
            status="PASS",
            input_artifacts=["papers/paper.pdf"],
            output_artifacts=["papers/paper.json"],
            error=None,
        )
    )

    assert task_state.paper_processing_steps["parse"].status == "PASS"
    assert persistence.updates == [("task-1", "parse"), ("task-1", "parse")]

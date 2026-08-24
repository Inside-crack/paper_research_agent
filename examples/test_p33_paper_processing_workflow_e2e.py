from __future__ import annotations

import asyncio
from pathlib import Path

from paper_agent.common.models.base import EvaluationVerdict, TaskPhase
from paper_agent.common.models.task_state import (
    PAPER_PROCESSING_SUBSTEPS,
    PaperProcessingStepState,
    StageStatus,
    TaskState,
)
from paper_agent.workflows import PaperProcessingWorkflow

from examples.test_p30_t2_orchestrator_paper_pipeline import (
    FakeEvaluationAgent,
    FakePersistence,
    FakeResearchAgent,
    FakeToolRegistry,
    _artifact,
)


def make_task(persistence: FakePersistence) -> TaskState:
    state = TaskState(
        id="task-p33-e2e",
        research_spec_id="task-p33-e2e",
        current_phase=TaskPhase.PAPER_PARSING,
        artifact_dir=str(persistence.base_dir / "task-p33-e2e"),
    )
    state.metadata["paper_candidates"] = [
        {
            "arxiv_id": "2401.00001v1",
            "title": "Selected Paper",
            "authors": ["Author"],
            "pdf_url": "https://arxiv.org/pdf/2401.00001v1",
        }
    ]
    for phase in TaskPhase:
        if phase not in (TaskPhase.COMPLETED, TaskPhase.FAILED):
            state.stages[phase] = StageStatus(phase=phase)
    return state


def make_workflow(
    persistence: FakePersistence,
    registry: FakeToolRegistry,
    research: FakeResearchAgent | None = None,
) -> PaperProcessingWorkflow:
    async def gather_evidence(task_state: TaskState, _phase: TaskPhase):
        return {"selected_paper": task_state.metadata.get("selected_paper")}

    def save_phase_output(
        phase: TaskPhase,
        task_state: TaskState,
        output: dict,
    ) -> None:
        task_state.metadata[f"phase_output_{phase.value}"] = output

    def record_round_result(*_args):
        return None

    return PaperProcessingWorkflow(
        persistence=persistence,
        research=research or FakeResearchAgent(),
        evaluation=FakeEvaluationAgent(),
        tools=registry,
        trace_recorder=lambda *_args, **_kwargs: None,
        evidence_gatherer=gather_evidence,
        phase_output_saver=save_phase_output,
        round_result_recorder=record_round_result,
    )


def test_workflow_runs_complete_flow_without_orchestrator(tmp_path: Path):
    persistence = FakePersistence(tmp_path / "artifacts")
    registry = FakeToolRegistry(
        persistence,
        {
            "download": _artifact(),
            "parse": _artifact(parsed=True),
            "glossary": _artifact(parsed=True),
            "translate": _artifact(parsed=True, translated=True),
            "summary": _artifact(
                parsed=True,
                translated=True,
                summarized=True,
            ),
        },
    )
    workflow = make_workflow(persistence, registry)

    result, plan = asyncio.run(workflow.run(make_task(persistence)))

    assert result.verdict == EvaluationVerdict.PASS
    assert [step.step_id for step in plan.steps] == list(PAPER_PROCESSING_SUBSTEPS)
    assert [name for name, _ in registry.calls] == [
        "paper_download",
        "paper_parse",
        "paper_glossary",
        "paper_translate",
        "paper_summary",
    ]


def test_workflow_resumes_persisted_pass_steps_without_rerunning_them(
    tmp_path: Path,
):
    persistence = FakePersistence(tmp_path / "artifacts")
    task = make_task(persistence)
    task_id = task.id
    persistence.write_paper_artifact(
        task_id,
        "papers/selected.json",
        _artifact(parsed=True, translated=True),
    )
    for name in ("download", "parse", "glossary"):
        persistence.steps[name] = PaperProcessingStepState(
            status="PASS",
            output_artifacts=["papers/selected.pdf", "papers/selected.json"],
        )
    registry = FakeToolRegistry(
        persistence,
        {
            "translate": _artifact(parsed=True, translated=True),
            "summary": _artifact(
                parsed=True,
                translated=True,
                summarized=True,
            ),
        },
    )
    workflow = make_workflow(persistence, registry)

    result, _ = asyncio.run(workflow.run(task))

    assert result.verdict == EvaluationVerdict.PASS
    assert [name for name, _ in registry.calls] == [
        "paper_translate",
        "paper_summary",
    ]


def test_workflow_blocks_when_passed_artifact_cannot_be_loaded(tmp_path: Path):
    persistence = FakePersistence(tmp_path / "artifacts")
    task = make_task(persistence)
    persistence.steps["download"] = PaperProcessingStepState(
        status="PASS",
        output_artifacts=["papers/missing.pdf", "papers/missing.json"],
    )
    registry = FakeToolRegistry(persistence, {})
    workflow = make_workflow(persistence, registry)

    result, _ = asyncio.run(workflow.run(task))

    assert result.verdict == EvaluationVerdict.BLOCKED
    assert "artifact" in (result.human_intervention_reason or "").lower()
    assert registry.calls == []

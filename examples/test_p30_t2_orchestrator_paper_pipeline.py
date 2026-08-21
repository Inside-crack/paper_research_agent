"""Offline tests for the P30 T2 fixed paper-processing flow."""

from __future__ import annotations

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models.base import EvaluationVerdict, TaskPhase
from paper_agent.common.models.evaluation_result import EvaluationResult
from paper_agent.common.models.execution_plan import ExecutionPlan, PlanStep
from paper_agent.common.models.paper_artifact import PaperArtifact, PaperSection, TermEntry
from paper_agent.common.models.task_state import (
    PAPER_PROCESSING_SUBSTEPS,
    PaperProcessingStepState,
    StageStatus,
    TaskState,
)
from paper_agent.common.tools.base import ToolResult
from paper_agent.orchestrator import Orchestrator


class FakePersistence:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.steps = {
            name: PaperProcessingStepState() for name in PAPER_PROCESSING_SUBSTEPS
        }
        self.step_updates: list[tuple[str, str, list[str], list[str]]] = []
        self.saved_plans = []
        self.saved_outputs = []
        self.saved_evaluations = []

    def _get_task_dir(self, task_id: str) -> Path:
        path = self.base_dir / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def load_paper_processing_steps(self, task_id: str):
        return {
            name: PaperProcessingStepState.model_validate(state.model_dump(mode="json"))
            for name, state in self.steps.items()
        }

    async def update_paper_processing_step(self, task_id, substep, step_state):
        self.steps[substep] = step_state
        self.step_updates.append(
            (
                substep,
                step_state.status,
                list(step_state.input_artifacts),
                list(step_state.output_artifacts),
            )
        )

    async def save_phase_plan(self, task_id, phase, plan):
        self.saved_plans.append(plan)

    async def save_phase_output(self, task_id, phase, output):
        self.saved_outputs.append(output)

    async def save_phase_eval(self, task_id, phase, verdict, result):
        self.saved_evaluations.append(result)

    def write_paper_artifact(self, task_id: str, artifact_path: str, artifact: PaperArtifact):
        path = self._get_task_dir(task_id) / artifact_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )


class FakeToolRegistry:
    def __init__(
        self,
        persistence: FakePersistence,
        artifacts: dict[str, PaperArtifact],
        fail_step: str | None = None,
    ):
        self.persistence = persistence
        self.artifacts = artifacts
        self.fail_step = fail_step
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        self.calls.append((tool_name, deepcopy(kwargs)))
        substep = tool_name.removeprefix("paper_")
        if substep == self.fail_step:
            return ToolResult.fail(error=f"{substep} failed in fake registry")

        previous = self.artifacts.get(substep)
        if previous is None:
            return ToolResult.fail(error=f"no fake artifact for {substep}")
        self.persistence.write_paper_artifact(
            kwargs["task_id"], "papers/selected.json", previous
        )
        return ToolResult.ok(
            data={
                "artifact_path": "papers/selected.json",
                "pdf_path": "papers/selected.pdf",
                "output_artifacts": ["papers/selected.json"],
            }
        )


class FakeResearchAgent:
    def __init__(self):
        self.started = 0
        self.generated: list[tuple[str, dict[str, Any]]] = []

    async def start_new_phase(self, phase, task_state, summaries, force=False):
        self.started += 1

    async def generate_step_content(self, *, phase, substep, task_state, context):
        self.generated.append((substep, context))
        if substep == "glossary":
            return {
                "terms": [
                    {
                        "source_term": "retrieval",
                        "target_term": "检索",
                        "context": "paper retrieval",
                        "confidence": 0.9,
                    }
                ]
            }
        if substep == "translate":
            return {
                "translations": [
                    {
                        "section_id": section["section_id"],
                        "translated_text": f"译文: {section['original_text']}",
                    }
                    for section in context["sections"]
                ]
            }
        return {
            "summary": {
                "research_questions": ["What is evaluated?"],
                "methodology_summary": "The paper evaluates retrieval.",
                "contributions": ["A retrieval result."],
                "conclusions": ["The result is traceable."],
                "limitations": [],
                "evidence": {
                    "research_questions": ["section_1"],
                    "methodology_summary": ["section_1"],
                    "contributions": ["section_1"],
                    "conclusions": ["section_1"],
                },
            }
        }


class LegacyPlanResearchAgent:
    """Exercise the legacy generate_plan fallback without reusing its plans."""

    def __init__(self):
        self.started = 0
        self.plan_calls: list[dict[str, Any]] = []
        self.synthesize_calls = 0

    async def start_new_phase(self, phase, task_state, summaries, force=False):
        self.started += 1

    async def generate_plan(self, phase, task_state, **kwargs):
        self.plan_calls.append(kwargs)
        substep = kwargs.get("paper_processing_step")
        if substep is None:
            return ExecutionPlan(
                phase=phase.value,
                plan_name="legacy_multi_step_plan",
                steps=[
                    PlanStep(
                        step_id="download",
                        description="download",
                        tool_name="paper_download",
                        arguments={
                            "paper": {
                                "arxiv_id": "2401.00001v1",
                                "title": "Selected Paper",
                            }
                        },
                    ),
                    PlanStep(
                        step_id="glossary",
                        description="legacy glossary",
                        tool_name="paper_glossary",
                        arguments={"terms": []},
                    ),
                    PlanStep(
                        step_id="translate",
                        description="legacy translation",
                        tool_name="paper_translate",
                        arguments={"translations": []},
                    ),
                    PlanStep(
                        step_id="summary",
                        description="legacy summary",
                        tool_name="paper_summary",
                        arguments={"summary": {}},
                    ),
                ],
            )

        context = kwargs["paper_artifact_context"]
        if substep == "glossary":
            arguments = {
                "terms": [
                    {
                        "source_term": "retrieval",
                        "target_term": "检索",
                        "context": "paper retrieval",
                        "confidence": 0.9,
                    }
                ]
            }
        elif substep == "translate":
            arguments = {
                "translations": [
                    {
                        "section_id": section["section_id"],
                        "translated_text": f"译文: {section['original_text']}",
                    }
                    for section in context["sections"]
                ]
            }
        else:
            arguments = {
                "summary": {
                    "research_questions": ["What is evaluated?"],
                    "methodology_summary": "The paper evaluates retrieval.",
                    "contributions": ["A retrieval result."],
                    "conclusions": ["The result is traceable."],
                    "limitations": [],
                    "evidence": {
                        "research_questions": ["section_1"],
                        "methodology_summary": ["section_1"],
                        "contributions": ["section_1"],
                        "conclusions": ["section_1"],
                    },
                }
            }
        return ExecutionPlan(
            phase=phase.value,
            plan_name=f"legacy_{substep}_plan",
            steps=[
                PlanStep(
                    step_id=substep,
                    description=substep,
                    tool_name=f"paper_{substep}",
                    arguments=arguments,
                )
            ],
        )

    async def synthesize_result(self, *args, **kwargs):
        self.synthesize_calls += 1
        raise AssertionError("PAPER_PARSING must use PaperArtifact output directly")


class FakeEvaluationAgent:
    async def evaluate_phase(
        self,
        *,
        phase,
        task_state,
        research_output,
        original_evidence,
        execution_plan,
        **kwargs,
    ):
        return EvaluationResult(
            task_state_id=task_state.id,
            phase=phase,
            verdict=EvaluationVerdict.PASS,
            score=1.0,
        )


def _artifact(*, parsed=False, translated=False, summarized=False) -> PaperArtifact:
    section = PaperSection(
        section_id="section_1",
        title="Introduction",
        level=1,
        original_text="1 Introduction\nretrieval score 95.",
        translated_text="译文: 1 Introduction\nretrieval score 95." if translated else "",
    )
    return PaperArtifact(
        id="artifact-selected",
        research_spec_id="task-p30-t2",
        candidate_id="2401.00001v1",
        arxiv_id="2401.00001v1",
        title="Selected Paper",
        authors=["Author"],
        pdf_path="papers/selected.pdf",
        sections=[section] if parsed else [],
        glossary=[
            TermEntry(
                source_term="retrieval",
                target_term="检索",
                context="paper retrieval",
                confidence=0.9,
            )
        ] if parsed else [],
        full_text_original=section.original_text if parsed else "",
        full_text_translated=section.translated_text if translated else "",
        research_questions=["What is evaluated?"] if summarized else [],
        methodology_summary="The paper evaluates retrieval." if summarized else "",
        contributions=["A retrieval result."] if summarized else [],
        conclusions=["The result is traceable."] if summarized else [],
        summary_evidence={"conclusions": ["section_1"]} if summarized else {},
    )


def _task(persistence: FakePersistence, candidates: list[dict[str, Any]]) -> TaskState:
    state = TaskState(
        id="task-p30-t2",
        research_spec_id="task-p30-t2",
        current_phase=TaskPhase.PAPER_PARSING,
        artifact_dir=str(persistence.base_dir / "task-p30-t2"),
    )
    state.metadata["user_query"] = "offline P30"
    state.metadata["paper_candidates"] = candidates
    for phase in (
        TaskPhase.TASK_INITIALIZATION,
        TaskPhase.PAPER_RETRIEVAL,
        TaskPhase.PAPER_PARSING,
        TaskPhase.CODE_LOCATION,
        TaskPhase.REPRODUCTION_PLANNING,
        TaskPhase.EXPERIMENT_EXECUTION,
        TaskPhase.RESULT_REPORTING,
    ):
        state.stages[phase] = StageStatus(phase=phase)
    return state


def _orchestrator(tmp_path, registry, persistence, research=None):
    return Orchestrator(
        research_agent=research or FakeResearchAgent(),
        evaluation_agent=FakeEvaluationAgent(),
        tool_registry=registry,
        persistence=persistence,
    )


def _assert_no_failed_statuses(state: TaskState):
    assert all(
        step.status != "FAILED" for step in state.paper_processing_steps.values()
    )


def test_fixed_flow_passes_real_artifacts_in_order(tmp_path):
    persistence = FakePersistence(tmp_path / "artifacts")
    registry = FakeToolRegistry(
        persistence,
        {
            "download": _artifact(),
            "parse": _artifact(parsed=True),
            "glossary": _artifact(parsed=True),
            "translate": _artifact(parsed=True, translated=True),
            "summary": _artifact(parsed=True, translated=True, summarized=True),
        }
    )
    research = FakeResearchAgent()
    orchestrator = _orchestrator(tmp_path, registry, persistence, research)
    candidate = {
        "arxiv_id": "2401.00001v1",
        "title": "Selected Paper",
        "authors": ["Author"],
        "pdf_url": "https://arxiv.org/pdf/2401.00001v1",
    }
    state = _task(persistence, [candidate])

    result, plan = asyncio.run(
        orchestrator._execute_phase_flow(TaskPhase.PAPER_PARSING, state)
    )

    assert result.verdict is EvaluationVerdict.PASS
    assert [name for name, _ in registry.calls] == [
        "paper_download",
        "paper_parse",
        "paper_glossary",
        "paper_translate",
        "paper_summary",
    ]
    assert registry.calls[0][1]["paper"] == candidate
    assert registry.calls[1][1]["artifact_path"] == "papers/selected.json"
    assert registry.calls[1][1]["pdf_path"] == "papers/selected.pdf"
    assert registry.calls[2][1]["artifact_path"] == "papers/selected.json"
    assert registry.calls[2][1]["terms"][0]["target_term"] == "检索"
    assert registry.calls[3][1]["translations"][0]["section_id"] == "section_1"
    assert registry.calls[4][1]["summary"]["evidence"]["conclusions"] == ["section_1"]
    persisted = json.loads(
        (
            persistence._get_task_dir(state.id) / "papers" / "selected.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted["sections"][0]["section_id"] == "section_1"
    assert persisted["glossary"][0]["target_term"] == "检索"
    assert persisted["sections"][0]["translated_text"].startswith("译文:")
    assert persisted["summary_evidence"]["conclusions"] == ["section_1"]
    contexts = {substep: context for substep, context in research.generated}
    assert contexts["glossary"]["sections"][0]["section_id"] == "section_1"
    assert contexts["translate"]["glossary"][0]["target_term"] == "检索"
    assert contexts["summary"]["translations"][0]["section_id"] == "section_1"
    assert [step.step_id for step in plan.steps] == list(PAPER_PROCESSING_SUBSTEPS)
    assert all(step.success for step in plan.steps)
    assert state.metadata["paper_artifact"]["sections"][0]["section_id"] == "section_1"
    assert state.metadata["paper_artifact"]["glossary"][0]["target_term"] == "检索"
    assert state.metadata["paper_artifact"]["full_text_translated"].startswith("译文:")
    assert state.metadata["paper_artifact"]["methodology_summary"] == (
        "The paper evaluates retrieval."
    )
    assert state.metadata["paper_artifact"]["summary_evidence"]["conclusions"] == ["section_1"]
    assert state.paper_processing_steps["summary"].output_artifacts == [
        "papers/selected.json"
    ]
    assert [substep for substep, status, _, _ in persistence.step_updates if status == "RUNNING"] == list(
        PAPER_PROCESSING_SUBSTEPS
    )


def test_empty_candidates_are_blocked_without_tools(tmp_path):
    persistence = FakePersistence(tmp_path / "artifacts")
    registry = FakeToolRegistry(persistence, {})
    orchestrator = _orchestrator(tmp_path, registry, persistence)
    state = _task(persistence, [])

    result, plan = asyncio.run(
        orchestrator._execute_phase_flow(TaskPhase.PAPER_PARSING, state)
    )

    assert result.verdict is EvaluationVerdict.BLOCKED
    assert registry.calls == []
    assert plan.steps[0].success is False
    assert state.paper_processing_steps["download"].status == "BLOCKED"
    assert state.paper_processing_steps["download"].completed_at is not None
    _assert_no_failed_statuses(state)


def test_parse_failure_stops_before_glossary(tmp_path):
    persistence = FakePersistence(tmp_path / "artifacts")
    registry = FakeToolRegistry(
        persistence,
        {"download": _artifact()},
        fail_step="parse",
    )
    orchestrator = _orchestrator(tmp_path, registry, persistence)
    state = _task(
        persistence,
        [{"arxiv_id": "2401.00001v1", "pdf_url": "https://arxiv.org/pdf/2401.00001v1"}],
    )

    result, _ = asyncio.run(
        orchestrator._execute_phase_flow(TaskPhase.PAPER_PARSING, state)
    )

    assert result.verdict is EvaluationVerdict.BLOCKED
    assert [name for name, _ in registry.calls] == [
        "paper_download",
        "paper_parse",
    ]
    assert state.paper_processing_steps["parse"].status == "BLOCKED"
    assert state.paper_processing_steps["parse"].completed_at is not None
    assert state.paper_processing_steps["glossary"].status == "not_started"
    _assert_no_failed_statuses(state)


def test_tool_failure_is_blocked(tmp_path):
    persistence = FakePersistence(tmp_path / "artifacts")
    registry = FakeToolRegistry(
        persistence, {"download": _artifact()}, fail_step="download"
    )
    orchestrator = _orchestrator(tmp_path, registry, persistence)
    state = _task(
        persistence,
        [{"arxiv_id": "2401.00001v1", "pdf_url": "https://arxiv.org/pdf/2401.00001v1"}],
    )

    result, _ = asyncio.run(
        orchestrator._execute_phase_flow(TaskPhase.PAPER_PARSING, state)
    )

    assert result.verdict is EvaluationVerdict.BLOCKED
    assert [name for name, _ in registry.calls] == ["paper_download"]
    assert state.paper_processing_steps["download"].status == "BLOCKED"
    assert state.paper_processing_steps["download"].completed_at is not None
    _assert_no_failed_statuses(state)


def test_recovery_artifact_load_failure_is_blocked(tmp_path):
    persistence = FakePersistence(tmp_path / "artifacts")
    persistence.steps["download"] = PaperProcessingStepState(
        status="PASS",
        output_artifacts=["papers/missing.json", "papers/selected.pdf"],
    )
    registry = FakeToolRegistry(persistence, {})
    orchestrator = _orchestrator(tmp_path, registry, persistence)
    state = _task(
        persistence,
        [{"arxiv_id": "2401.00001v1", "pdf_url": "https://arxiv.org/pdf/2401.00001v1"}],
    )

    result, _ = asyncio.run(
        orchestrator._execute_phase_flow(TaskPhase.PAPER_PARSING, state)
    )

    assert result.verdict is EvaluationVerdict.BLOCKED
    assert registry.calls == []
    assert state.paper_processing_steps["download"].status == "BLOCKED"
    assert state.paper_processing_steps["download"].completed_at is not None
    assert "Paper artifact not found" in state.paper_processing_steps["download"].error
    _assert_no_failed_statuses(state)


def test_checkpoint_pass_steps_are_skipped_and_artifact_is_loaded(tmp_path):
    persistence = FakePersistence(tmp_path / "artifacts")
    task_id = "task-p30-t2"
    artifact_path = persistence._get_task_dir(task_id) / "papers" / "selected.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            _artifact(parsed=True, translated=True, summarized=False).model_dump(
                mode="json"
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
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
            "summary": _artifact(parsed=True, translated=True, summarized=True),
        }
    )
    research = FakeResearchAgent()
    orchestrator = _orchestrator(tmp_path, registry, persistence, research)
    state = _task(
        persistence,
        [{"arxiv_id": "2401.00001v1", "pdf_url": "https://arxiv.org/pdf/2401.00001v1"}],
    )

    result, _ = asyncio.run(
        orchestrator._execute_phase_flow(TaskPhase.PAPER_PARSING, state)
    )

    assert result.verdict is EvaluationVerdict.PASS
    assert [name for name, _ in registry.calls] == [
        "paper_translate",
        "paper_summary",
    ]
    assert [step for step, _ in research.generated] == ["translate", "summary"]
    assert state.paper_processing_steps["download"].status == "PASS"
    assert state.paper_processing_steps["parse"].status == "PASS"
    assert state.paper_processing_steps["glossary"].status == "PASS"


def test_legacy_plan_is_parsed_once_and_not_reused_across_content_steps(tmp_path):
    persistence = FakePersistence(tmp_path / "artifacts")
    registry = FakeToolRegistry(
        persistence,
        {
            "download": _artifact(),
            "parse": _artifact(parsed=True),
            "glossary": _artifact(parsed=True),
            "translate": _artifact(parsed=True, translated=True),
            "summary": _artifact(parsed=True, translated=True, summarized=True),
        },
    )
    research = LegacyPlanResearchAgent()
    orchestrator = _orchestrator(tmp_path, registry, persistence, research)
    state = _task(persistence, [])
    state.metadata.pop("paper_candidates")

    result, _ = asyncio.run(
        orchestrator._execute_phase_flow(TaskPhase.PAPER_PARSING, state)
    )

    assert result.verdict is EvaluationVerdict.PASS
    assert len(research.plan_calls) == 4
    assert [
        call["paper_processing_step"] for call in research.plan_calls[1:]
    ] == ["glossary", "translate", "summary"]
    assert research.plan_calls[1]["paper_artifact_context"]["sections"]
    assert research.plan_calls[2]["paper_artifact_context"]["glossary"]
    assert research.plan_calls[3]["paper_artifact_context"]["translations"]
    assert research.synthesize_calls == 0


def main():
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()

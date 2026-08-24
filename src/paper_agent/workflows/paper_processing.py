from __future__ import annotations

import json
import inspect
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol

from ..common.models.execution_plan import ExecutionPlan, PlanStep
from ..common.models.task_state import (
    PAPER_PROCESSING_SUBSTEPS,
    PaperProcessingStepState,
)
from ..common.models.base import TaskPhase
from ..common.models.base import EvaluationVerdict, SeverityLevel
from ..common.models.evaluation_result import EvaluationIssue
from ..common.models.paper_artifact import PaperArtifact

from ..common.models.evaluation_result import EvaluationResult
from ..common.models.task_state import TaskState

WorkflowResult = tuple[EvaluationResult, ExecutionPlan]
WorkflowExecutor = Callable[[TaskState], Awaitable[WorkflowResult]]
TraceRecorder = Callable[..., None]
EvidenceGatherer = Callable[[TaskState, TaskPhase], Awaitable[dict[str, Any]]]
PhaseOutputSaver = Callable[[TaskPhase, TaskState, dict[str, Any]], None]
RoundResultRecorder = Callable[
    [TaskState, TaskPhase, ExecutionPlan, EvaluationResult], None
]


class PaperProcessingWorkflowPort(Protocol):
    async def run(self, task_state: TaskState) -> WorkflowResult:
        ...


class PaperProcessingWorkflow:
    """Replaceable boundary for the fixed P10-P14 paper workflow.

    The first migration step delegates to an injected executor. This keeps the
    Orchestrator API stable while allowing the legacy implementation to move
    behind this boundary incrementally.
    """

    def __init__(
        self,
        executor: Optional[WorkflowExecutor] = None,
        *,
        persistence: Any = None,
        research: Any = None,
        evaluation: Any = None,
        tools: Any = None,
        trace_recorder: Optional[TraceRecorder] = None,
        evidence_gatherer: Optional[EvidenceGatherer] = None,
        phase_output_saver: Optional[PhaseOutputSaver] = None,
        round_result_recorder: Optional[RoundResultRecorder] = None,
    ):
        if executor is not None and not callable(executor):
            raise TypeError("executor must be callable")
        self._executor = executor
        self.persistence = persistence
        self.research = research
        self.evaluation = evaluation
        self.tools = tools
        self.trace_recorder = trace_recorder
        self.evidence_gatherer = evidence_gatherer
        self.phase_output_saver = phase_output_saver
        self.round_result_recorder = round_result_recorder

    def build_plan(self) -> ExecutionPlan:
        tools = {
            "download": "paper_download",
            "parse": "paper_parse",
            "glossary": "paper_glossary",
            "translate": "paper_translate",
            "summary": "paper_summary",
        }
        return ExecutionPlan(
            phase=TaskPhase.PAPER_PARSING.value,
            plan_name="paper_processing_fixed_flow",
            summary_note=(
                "Fixed artifact-driven flow: "
                "download -> parse -> glossary -> translate -> summary"
            ),
            steps=[
                PlanStep(
                    step_id=name,
                    description=f"Execute PAPER_PARSING substep: {name}",
                    tool_name=tools[name],
                )
                for name in PAPER_PROCESSING_SUBSTEPS
            ],
        )

    @staticmethod
    def select_paper_candidate(task_state: TaskState) -> dict[str, Any] | None:
        selected = task_state.metadata.get("paper_processing_selected_candidate")
        if isinstance(selected, dict):
            return selected
        sources = [
            task_state.metadata.get("paper_candidates"),
            task_state.metadata.get("phase_output_paper_retrieval"),
            task_state.metadata.get("paper_retrieval"),
            task_state.metadata.get("paper_retrieval_result"),
        ]
        for source in sources:
            candidates: Any = source
            if isinstance(source, dict):
                candidates = source.get("candidates")
                if candidates is None:
                    candidates = source.get("results")
            if isinstance(candidates, list) and candidates:
                first = candidates[0]
                if isinstance(first, dict):
                    return dict(first)
                if hasattr(first, "model_dump"):
                    return first.model_dump(mode="json")
        return None

    @staticmethod
    def has_paper_retrieval_metadata(task_state: TaskState) -> bool:
        return any(
            key in task_state.metadata
            for key in (
                "paper_candidates",
                "phase_output_paper_retrieval",
                "paper_retrieval",
                "paper_retrieval_result",
            )
        )

    @staticmethod
    def candidate_from_legacy_plan(plan: Any) -> dict[str, Any] | None:
        if not isinstance(plan, ExecutionPlan):
            return None
        steps = [
            step
            for step in plan.steps
            if step.step_id == "download" or step.tool_name == "paper_download"
        ]
        if not steps:
            return None
        arguments = steps[0].arguments
        paper = arguments.get("paper")
        if isinstance(paper, dict):
            return dict(paper)
        candidate = {
            key: arguments.get(key)
            for key in ("arxiv_id", "pdf_url")
            if arguments.get(key)
        }
        return candidate or None

    async def generate_step_content(
        self,
        research: Any,
        task_state: TaskState,
        substep: str,
        artifact_path: str,
        artifact: PaperArtifact,
    ) -> Any:
        context = {
            "substep": substep,
            "artifact_path": artifact_path,
            "full_text_original": artifact.full_text_original,
            "sections": [
                section.model_dump(mode="json") for section in artifact.sections
            ],
            "glossary": [
                term.model_dump(mode="json") for term in artifact.glossary
            ],
            "translations": [
                {
                    "section_id": section.section_id,
                    "translated_text": section.translated_text,
                }
                for section in artifact.sections
                if section.translated_text
            ],
            "summary": {
                key: getattr(artifact, key)
                for key in (
                    "research_questions",
                    "methodology_summary",
                    "contributions",
                    "conclusions",
                    "limitations",
                    "summary_evidence",
                )
            },
        }
        if hasattr(research, "generate_step_content"):
            generated = research.generate_step_content(
                phase=TaskPhase.PAPER_PARSING,
                substep=substep,
                task_state=task_state,
                context=context,
            )
            return await generated if inspect.isawaitable(generated) else generated
        if hasattr(research, "inject_message"):
            research.inject_message(
                "=== PAPER_PARSING 当前子步骤 ===\n"
                + json.dumps(context, ensure_ascii=False, indent=2)
                + "\n只生成当前子步骤所需的内容，不要规划或执行其他子步骤。",
                anchor=True,
                priority=92,
            )
        generated_plan = await research.generate_plan(
            TaskPhase.PAPER_PARSING,
            task_state,
            paper_processing_step=substep,
            paper_artifact_context=context,
        )
        return self.content_from_plan(generated_plan, substep)

    @staticmethod
    def content_from_plan(plan: Any, substep: str) -> Any:
        key = {"glossary": "terms", "translate": "translations", "summary": "summary"}[
            substep
        ]
        if isinstance(plan, dict):
            if key in plan:
                return plan
            arguments = plan.get("arguments")
            return arguments if isinstance(arguments, dict) else plan
        if isinstance(plan, ExecutionPlan):
            matching = [
                step
                for step in plan.steps
                if step.step_id == substep or step.tool_name == f"paper_{substep}"
            ]
            step = matching[0] if matching else (
                plan.steps[0] if len(plan.steps) == 1 else None
            )
            if step is None:
                raise ValueError(f"ResearchAgent did not provide content for {substep}")
            return step.arguments
        raise TypeError(f"Unsupported generated content for {substep}: {type(plan)!r}")

    @staticmethod
    def content_value(content: Any, key: str) -> Any:
        if isinstance(content, dict) and key in content:
            return content[key]
        if key == "summary" and isinstance(content, dict):
            return content
        raise ValueError(f"Generated paper content is missing '{key}'")

    @staticmethod
    def blocked_result(
        task_state: TaskState,
        description: str,
        *,
        input_artifacts: list[str],
        output_artifacts: list[str],
    ) -> EvaluationResult:
        return EvaluationResult(
            task_state_id=task_state.id,
            phase=TaskPhase.PAPER_PARSING,
            verdict=EvaluationVerdict.BLOCKED,
            score=0.0,
            issues=[
                EvaluationIssue(
                    issue_type="paper_processing_blocked",
                    severity=SeverityLevel.CRITICAL,
                    description=description,
                    suggestion=(
                        "Provide a valid first paper candidate or repair "
                        "the failed substep."
                    ),
                )
            ],
            deterministic_checks_failed=1,
            input_artifacts=input_artifacts,
            output_artifacts=output_artifacts,
            requires_human_intervention=True,
            human_intervention_reason=description,
        )

    async def load_steps(
        self,
        task_state: TaskState,
    ) -> dict[str, PaperProcessingStepState]:
        """Load persisted step state without allowing unknown step names."""
        loaded = task_state.paper_processing_steps
        if self.persistence is not None:
            loader = getattr(self.persistence, "load_paper_processing_steps", None)
            if loader is not None:
                result = loader(task_state.id)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, dict):
                    raise ValueError("load_paper_processing_steps must return a dict")
                for name in PAPER_PROCESSING_SUBSTEPS:
                    if name in result:
                        state = result[name]
                        if not isinstance(state, PaperProcessingStepState):
                            state = PaperProcessingStepState.model_validate(state)
                        loaded[name] = state
        return loaded

    async def persist_step(
        self,
        task_state: TaskState,
        substep: str,
        *,
        status: str,
        input_artifacts: list[str],
        output_artifacts: list[str],
        error: str | None,
    ) -> None:
        if substep not in PAPER_PROCESSING_SUBSTEPS:
            raise ValueError(f"Unknown paper processing substep: {substep}")
        previous = task_state.paper_processing_steps[substep]
        step_state = PaperProcessingStepState(
            status=status,
            revision_count=previous.revision_count,
            input_artifacts=list(dict.fromkeys(input_artifacts)),
            output_artifacts=list(dict.fromkeys(output_artifacts)),
            error=error,
            started_at=previous.started_at or datetime.utcnow(),
            completed_at=datetime.utcnow()
            if status in ("PASS", "BLOCKED")
            else None,
        )
        task_state.paper_processing_steps[substep] = step_state
        if status == "RUNNING":
            step_state.completed_at = None
        if self.persistence is not None:
            updater = getattr(self.persistence, "update_paper_processing_step", None)
            if updater is not None:
                result = updater(task_state.id, substep, step_state)
                if inspect.isawaitable(result):
                    await result

    def relative_artifact_path(
        self,
        task_state: TaskState,
        value: Any,
    ) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(self.task_artifact_dir(task_state))
            except ValueError:
                return None
        if ".." in path.parts:
            return None
        return path.as_posix()

    def task_artifact_dir(self, task_state: TaskState) -> Path:
        if self.persistence is not None and hasattr(self.persistence, "_get_task_dir"):
            return self.persistence._get_task_dir(task_state.id)
        base_dir = getattr(self.persistence, "base_dir", None)
        if base_dir is not None:
            return Path(base_dir) / task_state.id
        return Path(task_state.artifact_dir)

    def load_paper_artifact(
        self,
        task_state: TaskState,
        artifact_path: str,
    ) -> tuple[PaperArtifact, dict[str, Any]]:
        path = self.task_artifact_dir(task_state) / artifact_path
        if not path.exists():
            raise FileNotFoundError(f"Paper artifact not found: {artifact_path}")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return PaperArtifact.model_validate(data), data

    @staticmethod
    def artifact_pdf_path(
        artifact: PaperArtifact | None,
        artifact_data: dict[str, Any],
        output_artifacts: list[str],
    ) -> str | None:
        if artifact and artifact.pdf_path:
            return artifact.pdf_path
        value = artifact_data.get("pdf_path")
        if isinstance(value, str):
            return value
        for path in output_artifacts:
            if path.endswith(".pdf"):
                return path
        return None

    @staticmethod
    def first_json_artifact(paths: list[str]) -> str | None:
        return next((path for path in paths if path.endswith(".json")), None)

    def paper_step_input_artifacts(
        self,
        substep: str,
        artifact_path: str | None,
        pdf_path: str | None,
    ) -> list[str]:
        if substep == "parse":
            return [path for path in (pdf_path, artifact_path) if path]
        if substep in ("glossary", "translate", "summary"):
            return [artifact_path] if artifact_path else []
        return []

    def paper_phase_input_artifacts(
        self,
        task_state: TaskState,
        artifact_path: str,
        pdf_path: str | None,
    ) -> list[str]:
        return [
            path
            for path in (
                self.relative_artifact_path(task_state, pdf_path),
                self.relative_artifact_path(task_state, artifact_path),
            )
            if path
        ]

    def paper_output_artifacts(
        self,
        task_state: TaskState,
        substep: str,
        result_data: dict[str, Any],
        artifact_path: str | None,
        pdf_path: str | None,
    ) -> list[str]:
        paths: list[str] = []
        if substep == "download" and pdf_path:
            paths.append(pdf_path)
        if artifact_path:
            paths.append(artifact_path)
        for value in result_data.get("output_artifacts", []):
            if isinstance(value, str):
                path = self.relative_artifact_path(task_state, value)
                if path and path.endswith((".json", ".pdf")) and path not in paths:
                    paths.append(path)
        return list(dict.fromkeys(paths))

    @staticmethod
    def paper_artifact_data(
        artifact: PaperArtifact,
        artifact_data: dict[str, Any],
    ) -> dict[str, Any]:
        return artifact.model_dump(mode="json") if artifact else dict(artifact_data)

    @staticmethod
    def build_paper_phase_output(
        candidate: dict[str, Any],
        artifact_path: str,
        pdf_path: str | None,
        artifact_data: dict[str, Any],
    ) -> dict[str, Any]:
        sections = artifact_data.get("sections", [])
        translations = [
            {
                "section_id": section.get("section_id"),
                "translated_text": section.get("translated_text", ""),
            }
            for section in sections
            if isinstance(section, dict)
        ]
        summary = {
            key: artifact_data.get(key)
            for key in (
                "research_questions",
                "methodology_summary",
                "contributions",
                "conclusions",
                "limitations",
                "summary_evidence",
            )
        }
        return {
            "selected_paper": candidate,
            "paper_artifact_id": artifact_data.get("id"),
            "artifact_path": artifact_path,
            "pdf_path": pdf_path or artifact_data.get("pdf_path"),
            "sections": sections,
            "full_text_original": artifact_data.get("full_text_original", ""),
            "glossary": artifact_data.get("glossary", []),
            "translations": translations,
            "full_text_translated": artifact_data.get("full_text_translated", ""),
            "summary": summary,
            "summary_evidence": artifact_data.get("summary_evidence", {}),
        }

    async def run(self, task_state: TaskState) -> WorkflowResult:
        if not isinstance(task_state, TaskState):
            raise TypeError("task_state must be a TaskState")
        if self._executor is not None:
            result = self._executor(task_state)
        else:
            result = self._run_core(task_state)
        if inspect.isawaitable(result):
            result = await result
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[0], EvaluationResult)
            or not isinstance(result[1], ExecutionPlan)
        ):
            raise TypeError(
                "paper processing workflow must return "
                "(EvaluationResult, ExecutionPlan)"
            )
        return result

    async def _run_core(self, task_state: TaskState) -> WorkflowResult:
        if any(
            dependency is None
            for dependency in (
                self.persistence,
                self.research,
                self.evaluation,
                self.tools,
                self.evidence_gatherer,
                self.phase_output_saver,
                self.round_result_recorder,
            )
        ):
            raise RuntimeError(
                "PaperProcessingWorkflow requires all execution dependencies"
            )

        phase = TaskPhase.PAPER_PARSING
        persisted_steps = await self.load_steps(task_state)
        plan = self.build_plan()
        candidate = self.select_paper_candidate(task_state)
        research_started = False

        if candidate is None and not self.has_paper_retrieval_metadata(task_state):
            await self.research.start_new_phase(
                phase, task_state, task_state.phase_summaries
            )
            research_started = True
            legacy_plan = await self.research.generate_plan(phase, task_state)
            candidate = self.candidate_from_legacy_plan(legacy_plan)

        if candidate is None:
            error = "No paper candidate available from paper_retrieval"
            plan.steps[0].executed = True
            plan.steps[0].success = False
            plan.steps[0].error = error
            await self.persistence.save_phase_plan(task_state.id, phase, plan)
            await self.persist_step(
                task_state,
                "download",
                status="BLOCKED",
                input_artifacts=[],
                output_artifacts=[],
                error=error,
            )
            result = self.blocked_result(
                task_state,
                error,
                input_artifacts=[],
                output_artifacts=[],
            )
            await self.persistence.save_phase_eval(
                task_state.id, phase, result.verdict, result
            )
            return result, plan

        task_state.metadata["paper_processing_selected_candidate"] = candidate
        task_state.metadata["selected_paper"] = candidate
        await self.persistence.save_phase_plan(task_state.id, phase, plan)

        artifact_path: str | None = None
        pdf_path: str | None = None
        artifact: PaperArtifact | None = None
        artifact_data: dict[str, Any] = {}
        final_output_artifacts: list[str] = []

        for index, substep in enumerate(PAPER_PROCESSING_SUBSTEPS):
            step = plan.steps[index]
            step_state = (
                persisted_steps.get(substep)
                or task_state.paper_processing_steps[substep]
            )
            if step_state.status.upper() == "PASS":
                step.executed = True
                step.success = True
                step.result = {
                    "skipped": True,
                    "output_artifacts": step_state.output_artifacts,
                }
                step.artifact_id = self.relative_artifact_path(
                    task_state,
                    self.first_json_artifact(step_state.output_artifacts),
                )
                step.arguments = {
                    "skipped": True,
                    "output_artifacts": step_state.output_artifacts,
                }
                try:
                    artifact_path = artifact_path or self.relative_artifact_path(
                        task_state,
                        self.first_json_artifact(step_state.output_artifacts),
                    )
                    if artifact_path:
                        artifact, artifact_data = self.load_paper_artifact(
                            task_state, artifact_path
                        )
                        pdf_path = pdf_path or self.relative_artifact_path(
                            task_state,
                            self.artifact_pdf_path(
                                artifact, artifact_data, step_state.output_artifacts
                            ),
                        )
                except Exception as exc:
                    error = f"Passed {substep} artifact could not be loaded: {exc}"
                    step.success = False
                    step.error = error
                    await self.persist_step(
                        task_state,
                        substep,
                        status="BLOCKED",
                        input_artifacts=step_state.input_artifacts,
                        output_artifacts=step_state.output_artifacts,
                        error=error,
                    )
                    await self.persistence.save_phase_plan(
                        task_state.id, phase, plan
                    )
                    result = self.blocked_result(
                        task_state,
                        error,
                        input_artifacts=step_state.input_artifacts,
                        output_artifacts=step_state.output_artifacts,
                    )
                    await self.persistence.save_phase_eval(
                        task_state.id, phase, result.verdict, result
                    )
                    return result, plan
                continue

            input_artifacts = self.paper_step_input_artifacts(
                substep, artifact_path, pdf_path
            )
            await self.persist_step(
                task_state,
                substep,
                status="RUNNING",
                input_artifacts=input_artifacts,
                output_artifacts=[],
                error=None,
            )
            try:
                if substep == "download":
                    arguments = {"task_id": task_state.id, "paper": candidate}
                elif substep == "parse":
                    if not artifact_path or not pdf_path:
                        raise RuntimeError(
                            "download did not produce artifact_path and pdf_path"
                        )
                    arguments = {
                        "task_id": task_state.id,
                        "artifact_path": artifact_path,
                        "pdf_path": pdf_path,
                    }
                else:
                    if not artifact_path or artifact is None:
                        raise RuntimeError(
                            f"{substep} requires a persisted PaperArtifact from parse"
                        )
                    if not research_started:
                        await self.research.start_new_phase(
                            phase, task_state, task_state.phase_summaries
                        )
                        research_started = True
                    generated = await self.generate_step_content(
                        self.research,
                        task_state,
                        substep,
                        artifact_path,
                        artifact,
                    )
                    arguments = {
                        "task_id": task_state.id,
                        "artifact_path": artifact_path,
                    }
                    if substep == "glossary":
                        arguments["terms"] = self.content_value(generated, "terms")
                    elif substep == "translate":
                        arguments["translations"] = self.content_value(
                            generated, "translations"
                        )
                    else:
                        arguments["summary"] = self.content_value(
                            generated, "summary"
                        )

                step.arguments = {
                    key: value for key, value in arguments.items() if key != "task_id"
                }
                tool_result = await self.tools.execute(
                    f"paper_{substep}",
                    **arguments,
                    _agent="orchestrator",
                    _phase=phase.value,
                )
                step.executed = True
                step.success = tool_result.success
                step.result = tool_result.data if tool_result.success else None
                step.error = tool_result.error
                step.duration_ms = tool_result.duration_ms
                if self.trace_recorder:
                    self.trace_recorder(
                        task_state,
                        phase,
                        "tool_executed",
                        step_id=substep,
                        tool_name=f"paper_{substep}",
                        success=tool_result.success,
                        duration_ms=tool_result.duration_ms,
                    )
                if not tool_result.success:
                    error = tool_result.error or f"{substep} tool failed"
                    await self.persist_step(
                        task_state,
                        substep,
                        status="BLOCKED",
                        input_artifacts=input_artifacts,
                        output_artifacts=[],
                        error=error,
                    )
                    await self.persistence.save_phase_plan(
                        task_state.id, phase, plan
                    )
                    result = self.blocked_result(
                        task_state,
                        f"{substep} failed: {error}",
                        input_artifacts=input_artifacts,
                        output_artifacts=[],
                    )
                    await self.persistence.save_phase_eval(
                        task_state.id, phase, result.verdict, result
                    )
                    return result, plan

                result_data = (
                    tool_result.data
                    if isinstance(tool_result.data, dict)
                    else {}
                )
                returned_artifact_path = self.relative_artifact_path(
                    task_state, result_data.get("artifact_path")
                )
                if returned_artifact_path:
                    artifact_path = returned_artifact_path
                returned_pdf_path = self.relative_artifact_path(
                    task_state, result_data.get("pdf_path")
                )
                if returned_pdf_path:
                    pdf_path = returned_pdf_path
                if substep == "download" and not artifact_path:
                    raise RuntimeError(
                        "paper_download succeeded without artifact_path"
                    )
                if artifact_path:
                    artifact, artifact_data = self.load_paper_artifact(
                        task_state, artifact_path
                    )
                    pdf_path = pdf_path or self.relative_artifact_path(
                        task_state,
                        self.artifact_pdf_path(artifact, artifact_data, []),
                    )
                output_artifacts = self.paper_output_artifacts(
                    task_state,
                    substep,
                    result_data,
                    artifact_path,
                    pdf_path,
                )
                final_output_artifacts = output_artifacts
                step.result = {
                    **result_data,
                    "artifact_path": artifact_path,
                    "output_artifacts": output_artifacts,
                }
                step.artifact_id = artifact_path
                await self.persist_step(
                    task_state,
                    substep,
                    status="PASS",
                    input_artifacts=input_artifacts,
                    output_artifacts=output_artifacts,
                    error=None,
                )
            except Exception as exc:
                step.executed = True
                step.success = False
                step.error = str(exc)
                await self.persist_step(
                    task_state,
                    substep,
                    status="BLOCKED",
                    input_artifacts=input_artifacts,
                    output_artifacts=[],
                    error=str(exc),
                )
                await self.persistence.save_phase_plan(task_state.id, phase, plan)
                result = self.blocked_result(
                    task_state,
                    f"{substep} failed: {exc}",
                    input_artifacts=input_artifacts,
                    output_artifacts=[],
                )
                await self.persistence.save_phase_eval(
                    task_state.id, phase, result.verdict, result
                )
                return result, plan

        if artifact is None or not artifact_path:
            result = self.blocked_result(
                task_state,
                "PAPER_PARSING completed without a persisted PaperArtifact",
                input_artifacts=[],
                output_artifacts=final_output_artifacts,
            )
            await self.persistence.save_phase_eval(
                task_state.id, phase, result.verdict, result
            )
            return result, plan

        final_artifact_data = self.paper_artifact_data(artifact, artifact_data)
        research_output = self.build_paper_phase_output(
            candidate, artifact_path, pdf_path, final_artifact_data
        )
        task_state.metadata["paper_artifact"] = final_artifact_data
        task_state.metadata["paper_summary"] = research_output.get("summary", {})
        self.phase_output_saver(phase, task_state, research_output)
        await self.persistence.save_phase_output(
            task_state.id, phase, research_output
        )
        await self.persistence.save_phase_plan(task_state.id, phase, plan)
        original_evidence = await self.evidence_gatherer(task_state, phase)
        eval_result = await self.evaluation.evaluate_phase(
            phase=phase,
            task_state=task_state,
            research_output=research_output,
            original_evidence=original_evidence,
            execution_plan=plan,
        )
        eval_result.input_artifacts = self.paper_phase_input_artifacts(
            task_state, artifact_path, pdf_path
        )
        eval_result.output_artifacts = final_output_artifacts or [artifact_path]
        await self.persistence.save_phase_eval(
            task_state.id, phase, eval_result.verdict, eval_result
        )
        if phase in task_state.stages:
            task_state.stages[phase].artifact_ids.extend(
                path
                for path in eval_result.output_artifacts
                if path not in task_state.stages[phase].artifact_ids
            )
        try:
            self.round_result_recorder(task_state, phase, plan, eval_result)
        except Exception:
            # Round-result telemetry is auxiliary; it must not turn a
            # successfully completed paper workflow into a failure.
            pass
        return eval_result, plan

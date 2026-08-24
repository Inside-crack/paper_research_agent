from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from ..common.config import get_settings
from ..common.logging import get_logger
from ..common.models.base import (
    Budget,
    EvaluationVerdict,
    TaskPhase,
    TraceEntry,
)
from ..common.models.evaluation_result import EvaluationResult
from ..common.models.execution_plan import ExecutionPlan, PlanStep
from ..common.models.research_spec import ResearchSpec
from ..common.models.task_state import (
    StageStatus,
    TaskState,
)
from ..common.persistence import StatePersistence
from ..common.persistence.error_context import build_error_filename
from ..common.persistence.naming import artifact_filename
from ..common.persistence.task_jsonl_logger import TaskJsonLogger
from ..common.tools import ToolRegistry
from ..workflows import PaperProcessingWorkflow
from ..evaluation_agent import EvaluationAgent
from ..research_agent import ResearchAgent
from ..tools import get_default_registry

logger = get_logger(__name__)

PHASE_TRANSITIONS: dict[TaskPhase, TaskPhase] = {
    TaskPhase.TASK_INITIALIZATION: TaskPhase.PAPER_RETRIEVAL,
    TaskPhase.PAPER_RETRIEVAL: TaskPhase.PAPER_PARSING,
    TaskPhase.PAPER_PARSING: TaskPhase.CODE_LOCATION,
    TaskPhase.CODE_LOCATION: TaskPhase.REPRODUCTION_PLANNING,
    TaskPhase.REPRODUCTION_PLANNING: TaskPhase.EXPERIMENT_EXECUTION,
    TaskPhase.EXPERIMENT_EXECUTION: TaskPhase.RESULT_REPORTING,
    TaskPhase.RESULT_REPORTING: TaskPhase.COMPLETED,
}

HumanConfirmCallback = Callable[[TaskState, TaskPhase, ExecutionPlan], Awaitable[bool]]


class Orchestrator:
    def __init__(
        self,
        research_agent: Optional[ResearchAgent] = None,
        evaluation_agent: Optional[EvaluationAgent] = None,
        tool_registry: Optional[ToolRegistry] = None,
        persistence: Optional[StatePersistence] = None,
        human_confirm_callback: Optional[HumanConfirmCallback] = None,
        paper_processing_workflow: Optional[PaperProcessingWorkflow] = None,
    ):
        self.settings = get_settings()
        self.tools = tool_registry or get_default_registry()

        self.research = research_agent or ResearchAgent(tool_registry=self.tools)
        self.evaluation = evaluation_agent or EvaluationAgent(tool_registry=self.tools)
        self.persistence = persistence or StatePersistence()
        self.human_confirm = human_confirm_callback or self._default_human_confirm
        self.paper_processing_workflow = paper_processing_workflow or PaperProcessingWorkflow(
            persistence=self.persistence,
            research=self.research,
            evaluation=self.evaluation,
            tools=self.tools,
            trace_recorder=self.add_trace,
            evidence_gatherer=self._gather_evidence,
            phase_output_saver=self._save_phase_output,
            round_result_recorder=self._record_round_results,
        )

        self._verdict_hooks: dict[EvaluationVerdict, list[Callable]] = {v: [] for v in EvaluationVerdict}
        self._phase_hooks: dict[TaskPhase, list[Callable]] = {p: [] for p in TaskPhase}
        self._plan_validation_hooks: list[Callable] = []
        self._task_start_time: float = 0.0
        self.event_logger: Optional[TaskJsonLogger] = None

    def on_verdict(self, verdict: EvaluationVerdict, hook: Callable) -> None:
        self._verdict_hooks[verdict].append(hook)

    def on_phase(self, phase: TaskPhase, hook: Callable) -> None:
        self._phase_hooks[phase].append(hook)

    def on_plan_validation(self, hook: Callable) -> None:
        self._plan_validation_hooks.append(hook)

    async def start_task(
        self,
        user_query: str,
        target_paper_url: Optional[str] = None,
        target_arxiv_id: Optional[str] = None,
        research_spec: Optional[ResearchSpec] = None,
        resume_from_checkpoint: Optional[str] = None,
    ) -> TaskState:
        if resume_from_checkpoint:
            task_state = await self.persistence.load_checkpoint(resume_from_checkpoint)
            logger.info(f"Resumed task {task_state.id} from checkpoint: {resume_from_checkpoint}")
            await self.persistence.rebuild_manifest_if_missing(task_state.id)
            task_dir = self.persistence._get_task_dir(task_state.id)
            self.event_logger = TaskJsonLogger(task_dir, task_state.id)
            deleted = self.persistence.trim_checkpoints(task_state.id, keep=5)
            if deleted:
                self.event_logger.cleanup(deleted)
        else:
            if research_spec is None:
                research_spec = ResearchSpec(
                    user_query=user_query,
                    target_paper_url=target_paper_url,
                    target_paper_arxiv_id=target_arxiv_id,
                    budget=Budget(
                        max_tokens=self.settings.budget.max_tokens_per_task,
                        max_gpu_minutes=self.settings.budget.max_gpu_minutes,
                        max_wall_time_minutes=self.settings.budget.max_wall_time_minutes,
                    ),
                )

            task_workspace = self.settings.workspace_dir / research_spec.id
            task_artifacts = self.settings.artifact_dir / research_spec.id
            task_workspace.mkdir(parents=True, exist_ok=True)
            task_artifacts.mkdir(parents=True, exist_ok=True)

            task_state = TaskState(
                research_spec_id=research_spec.id,
                workspace_dir=str(task_workspace),
                artifact_dir=str(task_artifacts),
            )
            task_state.metadata["user_query"] = user_query
            task_state.metadata["research_spec"] = research_spec.model_dump(mode="json")

            await self.persistence.save_research_spec(research_spec)
            await self.persistence.create_task_manifest(research_spec)

            task_dir = self.persistence._get_task_dir(task_state.id)
            self.event_logger = TaskJsonLogger(task_dir, task_state.id)

        await self._ensure_stages_initialized(task_state)
        await self.persistence.save_checkpoint(task_state)
        await self.run(task_state)
        return task_state

    async def run(self, task_state: TaskState) -> None:
        self._task_start_time = time.time()

        while task_state.current_phase not in (TaskPhase.COMPLETED, TaskPhase.FAILED):
            if task_state.budget.is_exceeded():
                logger.error(f"Budget exceeded for task {task_state.id}")
                task_state.current_phase = TaskPhase.FAILED
                task_state.metadata["failure_reason"] = "Budget exceeded"
                if self.event_logger:
                    self.event_logger.error("Budget exceeded", phase=task_state.current_phase.value)
                break

            phase = task_state.current_phase
            phase_start = time.time()
            logger.info(f"[{task_state.id}] Entering phase: {phase.value}")
            await self.persistence.mark_phase_started(task_state.id, phase)
            if self.event_logger:
                self.event_logger.phase_started(phase.value, revision=task_state.stages.get(phase, StageStatus(phase=phase)).revision_count)

            stage_status = task_state.stages.get(phase)
            if not stage_status:
                stage_status = StageStatus(phase=phase, started_at=datetime.utcnow())
                task_state.stages[phase] = stage_status
            elif not stage_status.started_at:
                stage_status.started_at = datetime.utcnow()

            current_plan = None
            try:
                await self._run_phase_hooks(phase, task_state)

                eval_result, current_plan = await self._execute_phase_flow(phase, task_state)

                await self._run_verdict_hooks(eval_result.verdict, task_state, eval_result)

                research_output = task_state.metadata.get(f"phase_output_{phase.value}", {})
                phase_duration = int((time.time() - phase_start) * 1000)

                if eval_result.verdict == EvaluationVerdict.PASS:
                    stage_status.verdict = EvaluationVerdict.PASS
                    stage_status.completed_at = datetime.utcnow()

                    summary_card = self._build_phase_summary_card(phase, research_output, eval_result)
                    task_state.phase_summaries.append(summary_card)
                    await self.persistence.save_phase_summary(task_state.id, phase, summary_card)
                    await self.persistence.save_completion_record(
                        task_state.id, phase, eval_result.verdict,
                        score=eval_result.score, duration_ms=phase_duration,
                        plan=current_plan, started_at=stage_status.started_at.isoformat() if stage_status.started_at else None,
                        revision=stage_status.revision_count,
                    )
                    if self.event_logger:
                        self.event_logger.phase_completed(phase.value, "PASS", score=eval_result.score, duration_ms=phase_duration)
                    logger.info(
                        f"[{task_state.id}] Phase {phase.value} PASSED (score={eval_result.score:.2f}) → "
                        f"next: {PHASE_TRANSITIONS.get(phase, TaskPhase.COMPLETED).value}, "
                        f"generated summary card, artifacts={summary_card.get('artifact_ids', [])}"
                    )

                    task_state.previous_phase = phase
                    task_state.current_phase = PHASE_TRANSITIONS.get(phase, TaskPhase.COMPLETED)

                elif eval_result.verdict == EvaluationVerdict.REVISE:
                    stage_status.revision_count += 1
                    task_state.total_revisions += 1
                    await self.persistence.record_revision(task_state.id, phase, stage_status.revision_count)

                    self._record_phase_failure(task_state, phase, eval_result, research_output)

                    rev = stage_status.revision_count
                    await self.persistence.dump_error_context(
                        task_state.id, phase, "revise",
                        error_message=f"REVISE (attempt {rev}): score={eval_result.score:.2f}, issues={len(eval_result.issues)}",
                        plan=current_plan, eval_result=eval_result,
                        research_output=research_output,
                        messages=self.research.messages if hasattr(self.research, 'messages') else None,
                        revision=rev,
                        recovery_hint="Applying correction notes and retrying",
                    )
                    if self.event_logger:
                        self.event_logger.revision_triggered(phase.value, rev, reason=f"score={eval_result.score:.2f}")
                        self.event_logger.error_dumped("revise", build_error_filename(phase, "revise", rev), f"score={eval_result.score:.2f}")

                    max_revisions = self.settings.budget.max_revisions_per_stage
                    if stage_status.revision_count > max_revisions:
                        eval_result.verdict = EvaluationVerdict.BLOCKED
                        eval_result.requires_human_intervention = True
                        eval_result.human_intervention_reason = f"Max revisions ({max_revisions}) exceeded"
                        task_state.current_phase = TaskPhase.FAILED
                        logger.warning(f"[{task_state.id}] Max revisions exceeded for phase {phase.value}")
                        if self.event_logger:
                            self.event_logger.error(f"Max revisions ({max_revisions}) exceeded for phase {phase.value}")
                        await self.persistence.dump_error_context(
                            task_state.id, phase, "blocked",
                            error_message=f"Max revisions ({max_revisions}) exceeded",
                            exc=None, plan=current_plan, eval_result=eval_result,
                            research_output=research_output,
                            messages=self.research.messages if hasattr(self.research, 'messages') else None,
                            revision=rev,
                            recovery_hint="Human intervention required: max revisions exhausted",
                        )
                    else:
                        logger.info(f"[{task_state.id}] Phase {phase.value} REVISE (attempt {stage_status.revision_count})")
                        await self.persistence.save_checkpoint(task_state)
                        if self.event_logger:
                            self.event_logger.checkpoint_saved("revision_checkpoint")
                        deleted = self.persistence.trim_checkpoints(task_state.id, keep=5)
                        if deleted and self.event_logger:
                            self.event_logger.cleanup(deleted)
                        continue

                else:
                    logger.error(f"[{task_state.id}] Phase {phase.value} BLOCKED")
                    task_state.current_phase = TaskPhase.FAILED
                    task_state.metadata["blocked_phase"] = phase.value
                    blocked_reason = eval_result.issues[0].description if eval_result.issues else "Unknown reason"
                    task_state.metadata["blocked_reason"] = blocked_reason
                    await self.persistence.dump_error_context(
                        task_state.id, phase, "blocked",
                        error_message=f"BLOCKED: {blocked_reason}",
                        exc=None, plan=current_plan, eval_result=eval_result,
                        research_output=research_output,
                        messages=self.research.messages if hasattr(self.research, 'messages') else None,
                        revision=stage_status.revision_count,
                        recovery_hint="Human intervention required",
                    )
                    if self.event_logger:
                        self.event_logger.error_dumped("blocked", build_error_filename(phase, "blocked", stage_status.revision_count), blocked_reason)

                await self.persistence.mark_phase_completed(
                    task_state.id, phase, eval_result.verdict,
                    score=eval_result.score,
                )
                stage_status.evaluation_result_ids.append(eval_result.id)
                task_state.evaluation_result_ids.append(eval_result.id)
                await self.persistence.save_evaluation_result(eval_result)
                await self.persistence.save_checkpoint(task_state)
                if self.event_logger:
                    self.event_logger.checkpoint_saved("phase_completion")
                deleted = self.persistence.trim_checkpoints(task_state.id, keep=5)
                if deleted and self.event_logger:
                    self.event_logger.cleanup(deleted)

            except Exception as e:
                logger.exception(f"[{task_state.id}] Phase {phase.value} failed with exception")
                task_state.current_phase = TaskPhase.FAILED
                task_state.metadata["exception"] = str(e)
                if phase in task_state.stages:
                    task_state.stages[phase].error = str(e)
                rev = task_state.stages.get(phase, StageStatus(phase=phase)).revision_count
                await self.persistence.dump_error_context(
                    task_state.id, phase, "exception",
                    error_message=str(e), exc=e, plan=current_plan,
                    messages=self.research.messages if hasattr(self.research, 'messages') else None,
                    revision=rev,
                    recovery_hint="Unhandled exception during phase execution",
                )
                if self.event_logger:
                    self.event_logger.error_dumped("exception", build_error_filename(phase, "exception", rev), str(e)[:200])
                await self.persistence.save_checkpoint(task_state)
                if self.event_logger:
                    self.event_logger.checkpoint_saved("exception_checkpoint")
                break

        self._update_budget_tracking(task_state)
        await self.persistence.save_checkpoint(task_state)
        final_status = "passed" if task_state.current_phase == TaskPhase.COMPLETED else "failed"
        await self.persistence.mark_task_completed(task_state.id, final_status)
        total_duration = int((time.time() - self._task_start_time) * 1000) if self._task_start_time else 0
        if self.event_logger:
            total_phases = sum(1 for s in task_state.stages.values() if s.completed_at or s.error)
            self.event_logger.task_completed(
                final_status, total_duration_ms=total_duration,
                total_phases=total_phases,
                total_errors=task_state.stages.get(TaskPhase.FAILED, StageStatus(phase=TaskPhase.FAILED)).revision_count if TaskPhase.FAILED in task_state.stages else 0,
                total_revisions=task_state.total_revisions,
            )
        logger.info(f"[{task_state.id}] Task finished: {task_state.current_phase.value}")

    async def _execute_phase_flow(self, phase: TaskPhase, task_state: TaskState) -> tuple[EvaluationResult, Optional[ExecutionPlan]]:
        if phase == TaskPhase.PAPER_PARSING:
            return await self.paper_processing_workflow.run(task_state)

        is_revision = task_state.stages[phase].revision_count > 0
        correction_notes = ""

        if is_revision:
            if task_state.stages[phase].revision_count == 0:
                raise RuntimeError(
                    f"State inconsistency: is_revision=True but revision_count=0 for phase {phase.value}"
                )
            logger.info(
                f"[{task_state.id}] REVISE retry for phase {phase.value} "
                f"(attempt {task_state.stages[phase].revision_count + 1}), resetting context with smart correction"
            )
            await self.research.start_new_phase(phase, task_state, task_state.phase_summaries, force=True)

            last_round = task_state.metadata.get("last_round_results")
            if last_round:
                try:
                    prev_msg = self._build_previous_results_message(last_round, phase)
                    self.research.inject_message(prev_msg, anchor=True, priority=85)
                    logger.info(
                        f"[{task_state.id}] Injected previous round results: "
                        f"{last_round.get('succeeded_steps', 0)}/{last_round.get('total_steps', 0)} steps succeeded, "
                        f"{last_round.get('total_papers', 0)} papers available, "
                        f"{len(last_round.get('eval_issues', []))} issues"
                    )
                except Exception as e:
                    logger.error(f"Failed to build previous results message: {e}", exc_info=True)
                    self.research.inject_message(
                        f"=== 上一轮执行数据不完整 ===\n"
                        f"上一轮执行遇到异常，结果数据不完整。请重新完整规划当前阶段的所有步骤。",
                        anchor=True, priority=85,
                    )
                correction_notes = self._build_correction_notes(task_state, phase, last_round)
            else:
                logger.warning(f"[{task_state.id}] REVISE but no last_round_results found, generating generic correction")
                correction_notes = "Previous attempt had issues. Please review your plan and generate a corrected plan addressing all evaluation feedback."
        else:
            task_state.metadata.pop("last_round_results", None)
            logger.info(
                f"[{task_state.id}] Starting new phase: {phase.value}, "
                f"injecting {len(task_state.phase_summaries)} previous summary cards"
            )
            await self.research.start_new_phase(phase, task_state, task_state.phase_summaries)

        plan = await self.research.generate_plan(
            phase, task_state, is_revision=is_revision, correction_notes=correction_notes
        )

        await self.persistence.save_phase_plan(task_state.id, phase, plan)

        self.add_trace(task_state, phase, "plan_generated", plan_id=plan.id, steps=len(plan.steps))

        plan_valid = await self._validate_plan(plan, task_state, phase)
        if not plan_valid:
            return EvaluationResult(
                task_state_id=task_state.id,
                phase=phase,
                verdict=EvaluationVerdict.BLOCKED,
                summary="Plan validation failed",
            ), plan

        if plan.requires_human_confirmation:
            confirmed = await self.human_confirm(task_state, phase, plan)
            plan.confirmed = confirmed
            if not confirmed:
                return EvaluationResult(
                    task_state_id=task_state.id,
                    phase=phase,
                    verdict=EvaluationVerdict.BLOCKED,
                    summary="Plan rejected by human",
                    requires_human_intervention=True,
                ), plan

        await self._execute_plan(plan, task_state, phase)

        if phase == TaskPhase.PAPER_RETRIEVAL:
            self._deduplicate_search_results(plan)

        research_output = await self.research.synthesize_result(phase, task_state, plan)

        self._save_phase_output(phase, task_state, research_output)
        await self.persistence.save_phase_output(task_state.id, phase, research_output)

        original_evidence = await self._gather_evidence(task_state, phase)

        eval_result = await self.evaluation.evaluate_phase(
            phase=phase,
            task_state=task_state,
            research_output=research_output,
            original_evidence=original_evidence,
            execution_plan=plan,
        )

        await self.persistence.save_phase_eval(task_state.id, phase, eval_result.verdict, eval_result)

        if phase in task_state.stages:
            task_state.stages[phase].artifact_ids.extend([
                k for k in research_output.keys() if isinstance(research_output[k], str) and len(research_output[k]) < 64
            ])

        try:
            self._record_round_results(task_state, phase, plan, eval_result)
        except Exception as e:
            logger.error(f"Failed to record round results: {e}", exc_info=True)

        return eval_result, plan

    async def _validate_plan(self, plan: ExecutionPlan, task_state: TaskState, phase: TaskPhase) -> bool:
        for hook in self._plan_validation_hooks:
            try:
                if not await hook(plan, task_state, phase):
                    return False
            except Exception as e:
                logger.warning(f"Plan validation hook failed: {e}")

        if not plan.steps:
            logger.warning("Plan contains no steps")
            return False

        available_tools = set(self.tools.list_tools())
        for step in plan.steps:
            if step.tool_name not in available_tools:
                logger.warning(f"Plan references unknown tool: {step.tool_name} (available: {available_tools})")
                return False

        return True

    async def _execute_plan(self, plan: ExecutionPlan, task_state: TaskState, phase: TaskPhase) -> None:
        revision = task_state.stages[phase].revision_count if phase in task_state.stages else 0
        for step in plan.steps:
            logger.info(f"[{task_state.id}] Executing step {step.step_id}: {step.tool_name}")
            start_time = time.time()

            try:
                args = {**step.arguments, "_agent": "orchestrator", "_phase": phase.value}
                task_id = task_state.id
                if "task_id" not in args:
                    args["task_id"] = task_id
                tool_result = await self.tools.execute(step.tool_name, **args)

                step.duration_ms = int((time.time() - start_time) * 1000)
                step.executed = True
                step.success = tool_result.success
                step.result = tool_result.data if tool_result.success else None
                step.error = tool_result.error

                await self._auto_persist_step_result(step, task_state, phase, revision)

                self.research.record_step_result(step)
                self.add_trace(
                    task_state, phase, "tool_executed",
                    step_id=step.step_id, tool_name=step.tool_name,
                    success=step.success, duration_ms=step.duration_ms,
                    artifact_id=step.artifact_id,
                )

                if not step.success:
                    logger.warning(f"Step {step.step_id} ({step.tool_name}) failed: {step.error}")

                if self.event_logger:
                    self.event_logger.step_executed(
                        step.step_id, step.tool_name, step.success,
                        duration_ms=step.duration_ms,
                        artifact=step.artifact_id,
                        error=step.error,
                    )

            except Exception as e:
                step.duration_ms = int((time.time() - start_time) * 1000)
                step.executed = True
                step.success = False
                step.error = str(e)
                try:
                    await self._auto_persist_step_error(step, task_state, phase, str(e), revision)
                except Exception as persist_err:
                    logger.error(f"Failed to persist step error for {step.step_id}: {persist_err}")
                    raise RuntimeError(
                        f"Step {step.step_id} ({step.tool_name}) failed and error persistence also failed: {persist_err}. "
                        f"Original error: {e}"
                    ) from persist_err
                self.research.record_step_result(step)
                logger.exception(f"Step {step.step_id} threw exception: {e}")
                if self.event_logger:
                    self.event_logger.step_executed(
                        step.step_id, step.tool_name, False,
                        duration_ms=step.duration_ms, error=str(e),
                    )

    async def _auto_persist_step_result(
        self, step: PlanStep, task_state: TaskState, phase: TaskPhase, revision: int = 0
    ) -> None:
        if step.tool_name == "save_artifact":
            if step.success and isinstance(step.result, dict):
                step.artifact_id = step.result.get("artifact_name", "")
                await self.persistence.update_step_in_manifest(
                    task_state.id, phase, step.step_id, step.tool_name,
                    True, step.artifact_id, None, step.duration_ms, revision,
                )
            return

        if not step.success:
            await self._auto_persist_step_error(step, task_state, phase, step.error or "Unknown error", revision)
            return

        if step.result is None:
            return

        try:
            compact = self.research._compact_result(step.tool_name, step.result)
            artifact_name = artifact_filename(
                phase, "result", step_id=step.step_id, tool=step.tool_name,
                revision=revision if revision > 0 else None,
            )
            save_result = await self.tools.execute(
                "save_artifact",
                artifact_name=artifact_name,
                data=compact,
                task_id=task_state.id,
                _agent="orchestrator",
                _phase=phase.value,
            )
            if not save_result.success:
                raise RuntimeError(f"auto_persist failed for {step.step_id}: {save_result.error}")
            if isinstance(save_result.data, dict):
                step.artifact_id = save_result.data.get("artifact_name", artifact_name)
            else:
                step.artifact_id = artifact_name
            await self.persistence.update_step_in_manifest(
                task_state.id, phase, step.step_id, step.tool_name,
                True, step.artifact_id, None, step.duration_ms, revision,
            )
            logger.debug(
                f"[{task_state.id}] Auto-persisted step {step.step_id} result → {step.artifact_id}"
            )
        except Exception as e:
            logger.error(f"[{task_state.id}] Failed to auto-persist step {step.step_id}: {e}", exc_info=True)
            raise RuntimeError(
                f"Critical: Failed to persist tool result for step '{step.step_id}' ({step.tool_name}): {e}. "
                f"Result persistence is required for downstream phases to access data."
            ) from e

    async def _auto_persist_step_error(
        self, step: PlanStep, task_state: TaskState, phase: TaskPhase, error_msg: str, revision: int = 0
    ) -> None:
        if step.tool_name == "save_artifact":
            return
        try:
            error_data = {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "phase": phase.value,
                "success": False,
                "error": error_msg,
                "arguments": {k: v for k, v in step.arguments.items() if k not in ("_agent", "_phase", "task_id")},
                "timestamp": datetime.utcnow().isoformat(),
            }
            artifact_name = artifact_filename(
                phase, "error", step_id=step.step_id, tool=step.tool_name,
                revision=revision if revision > 0 else None,
            )
            save_result = await self.tools.execute(
                "save_artifact",
                artifact_name=artifact_name,
                data=error_data,
                task_id=task_state.id,
                _agent="orchestrator",
                _phase=phase.value,
            )
            if not save_result.success:
                raise RuntimeError(f"auto_persist error failed: {save_result.error}")
            if isinstance(save_result.data, dict):
                step.artifact_id = save_result.data.get("artifact_name", artifact_name)
            else:
                step.artifact_id = artifact_name
            await self.persistence.update_step_in_manifest(
                task_state.id, phase, step.step_id, step.tool_name,
                False, step.artifact_id, error_msg, step.duration_ms, revision,
            )
            logger.debug(
                f"[{task_state.id}] Auto-persisted step {step.step_id} error → {step.artifact_id}"
            )
        except Exception as e:
            logger.error(f"[{task_state.id}] Failed to auto-persist step error {step.step_id}: {e}", exc_info=True)
            raise

    async def _gather_evidence(self, task_state: TaskState, phase: TaskPhase) -> dict[str, Any]:
        evidence: dict[str, Any] = {}
        evidence["user_query"] = task_state.metadata.get("user_query", "")

        spec_data = task_state.metadata.get("research_spec")
        if spec_data:
            evidence["research_spec"] = spec_data

        if phase == TaskPhase.PAPER_PARSING:
            selected = self.paper_processing_workflow.select_paper_candidate(task_state)
            if selected:
                evidence["selected_paper"] = selected

        if phase == TaskPhase.CODE_LOCATION:
            paper_artifact = task_state.metadata.get("phase_output_paper_parsing")
            if paper_artifact:
                evidence["paper_summary"] = paper_artifact

        if phase == TaskPhase.REPRODUCTION_PLANNING:
            code_loc = task_state.metadata.get("phase_output_code_location")
            if code_loc:
                evidence["code_location_results"] = code_loc

        return evidence

    def _build_correction_notes(
        self,
        task_state: TaskState,
        phase: TaskPhase,
        last_round: dict[str, Any] | None,
    ) -> str:
        if not last_round:
            return "Previous attempt had issues. Please generate a corrected plan addressing all evaluation feedback."
        try:
            lines: list[str] = []
            lines.append(f"上一轮(revision={last_round.get('revision', 0)})未通过评估（score={last_round.get('eval_score', 0):.2f}）。")
            lines.append("")

            succeeded = last_round.get("succeeded_steps", 0)
            failed = last_round.get("failed_steps", 0)
            total = last_round.get("total_steps", 0)
            lines.append(f"执行概况：{total}个步骤中{succeeded}个成功，{failed}个失败。")

            failed_steps = [s for s in last_round.get("steps", []) if not s.get("success", False)]
            if failed_steps:
                lines.append("")
                lines.append("失败步骤：")
                for fs in failed_steps[:3]:
                    lines.append(f"  - {fs.get('step_id', '?')} ({fs.get('tool_name', '?')}): {fs.get('error', '未知错误')[:200]}")

            eval_issues = last_round.get("eval_issues", [])
            high_critical = [i for i in eval_issues if i.get("severity", "").lower() in ("high", "critical")]
            if high_critical:
                lines.append("")
                lines.append("必须修复以下问题：")
                for idx, issue in enumerate(high_critical[:5], 1):
                    sev = issue.get("severity", "high").upper()
                    desc = issue.get("description", "")[:300]
                    suggestion = issue.get("suggestion", "")
                    lines.append(f"  {idx}. [{sev}] {desc}")
                    if suggestion:
                        lines.append(f"     → 建议：{suggestion[:200]}")

            total_papers = last_round.get("total_papers", 0)
            if total_papers > 0:
                lines.append("")
                lines.append(f"上一轮已获得{total_papers}篇去重论文（见上方消息），你可以直接使用这些结果，不需要重复执行已成功的arxiv_search。")

            lines.append("")
            lines.append("请基于上述数据和问题，生成修正后的Plan，重点修复标记的问题。")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Error building correction notes: {e}", exc_info=True)
            return "Previous attempt had issues. Please generate a corrected plan addressing all evaluation feedback."

    def _build_previous_results_message(
        self,
        last_round: dict[str, Any],
        phase: TaskPhase,
    ) -> str:
        lines: list[str] = []
        lines.append("=== 上一轮执行：已有可用数据 ===")
        lines.append("")

        revision = last_round.get("revision", 0)
        succeeded = last_round.get("succeeded_steps", 0)
        failed = last_round.get("failed_steps", 0)
        total = last_round.get("total_steps", 0)
        lines.append(f"上一轮(revision={revision})执行概况：{total}个步骤中{succeeded}个成功，{failed}个失败。")
        lines.append("")

        steps = last_round.get("steps", [])
        success_steps = [s for s in steps if s.get("success", False)]
        fail_steps = [s for s in steps if not s.get("success", False)]

        if success_steps:
            lines.append("✅ 成功步骤（结果可复用，你可以选择不重复执行）：")
            for s in success_steps:
                summary = s.get("result_summary", "completed")
                lines.append(f"  - {s.get('step_id', '?')} ({s.get('tool_name', '?')}): {summary}")
            lines.append("")

        if fail_steps:
            lines.append("❌ 失败步骤（需要修正）：")
            for s in fail_steps:
                err = s.get("error", "未知错误")[:200]
                lines.append(f"  - {s.get('step_id', '?')} ({s.get('tool_name', '?')}): {err}")
            lines.append("")

        all_papers = last_round.get("all_papers", [])
        total_papers = last_round.get("total_papers", len(all_papers))
        if all_papers and phase == TaskPhase.PAPER_RETRIEVAL:
            shown = all_papers[:30]
            lines.append(f"📄 去重后已有论文列表（共{total_papers}篇，展示前{len(shown)}篇）：")
            for idx, paper in enumerate(shown, 1):
                arxiv_id = paper.get("arxiv_id", "?")
                title = paper.get("title", "Untitled")[:100]
                authors_list = paper.get("authors", [])
                author_str = authors_list[0] if authors_list else "Unknown"
                if len(authors_list) > 1:
                    author_str += " et al."
                year = paper.get("year") or "?"
                code_hint = " [code✓]" if paper.get("code_available") else ""
                abstract = (paper.get("abstract", "") or "")[:150]
                lines.append(f"  {idx}. {arxiv_id} - \"{title}\" - {author_str} ({year}){code_hint}")
                if abstract:
                    lines.append(f"     {abstract}")
            if total_papers > 30:
                lines.append(f"  ... 另有{total_papers - 30}篇未展示，完整列表在各步骤artifact中，可load_artifact加载。")
            lines.append("")
            lines.append("⚠️ 你可以直接使用上述论文结果，不需要重新搜索。")
            if fail_steps:
                lines.append("⚠️ 必须修复失败步骤的问题，确保所有必要的artifact都被保存。")

        return "\n".join(lines)

    def _record_round_results(
        self,
        task_state: TaskState,
        phase: TaskPhase,
        plan: ExecutionPlan,
        eval_result: EvaluationResult,
    ) -> None:
        steps_data: list[dict[str, Any]] = []
        all_papers: list[dict[str, Any]] = []
        seen_paper_ids: set[str] = set()
        succeeded = 0
        failed = 0

        for step in plan.steps:
            step_info: dict[str, Any] = {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "description": step.description[:200] if step.description else "",
                "success": step.success,
                "error": step.error[:200] if step.error else None,
            }

            compact_result = None
            result_summary = ""

            if step.success and step.result is not None:
                succeeded += 1
                compact_result = self.research._compact_result(step.tool_name, step.result)

                if step.tool_name == "arxiv_search" and isinstance(compact_result, dict) and "results" in compact_result:
                    papers = compact_result.get("results", [])
                    result_summary = f"{len(papers)} results"
                    for p in papers:
                        pid = (p.get("arxiv_id", "") or "").split("v")[0]
                        if pid and pid not in seen_paper_ids:
                            seen_paper_ids.add(pid)
                            all_papers.append(p)
                else:
                    if isinstance(compact_result, dict):
                        result_summary = f"completed, keys={list(compact_result.keys())[:5]}"
                    else:
                        result_summary = "completed"
            else:
                failed += 1
                result_summary = f"FAILED: {step.error[:80] if step.error else 'unknown error'}"

            step_info["result_summary"] = result_summary
            step_info["compact_result"] = compact_result
            steps_data.append(step_info)

        def _get_severity(issue: Any) -> str:
            if hasattr(issue, 'severity'):
                sev = issue.severity
                return (sev.value if hasattr(sev, 'value') else str(sev)).lower()
            if isinstance(issue, dict):
                return str(issue.get("severity", "")).lower()
            return ""

        eval_issues = []
        for issue in eval_result.issues[:15]:
            issue_dict: dict[str, Any] = {
                "severity": _get_severity(issue),
            }
            if hasattr(issue, 'description'):
                issue_dict["description"] = (issue.description or "")[:300]
                issue_dict["suggestion"] = (issue.suggestion or "")[:200] if hasattr(issue, 'suggestion') else ""
            elif isinstance(issue, dict):
                issue_dict["description"] = str(issue.get("description", ""))[:300]
                issue_dict["suggestion"] = str(issue.get("suggestion", ""))[:200]
            eval_issues.append(issue_dict)

        round_data = {
            "phase": phase.value,
            "revision": task_state.stages[phase].revision_count,
            "total_steps": len(plan.steps),
            "succeeded_steps": succeeded,
            "failed_steps": failed,
            "steps": steps_data,
            "all_papers": all_papers[:50],
            "total_papers": len(all_papers),
            "eval_issues": eval_issues,
            "eval_score": eval_result.score,
            "verdict": eval_result.verdict.value,
            "recorded_at": datetime.utcnow().isoformat(),
        }

        task_state.metadata["last_round_results"] = round_data
        logger.debug(
            f"[{task_state.id}] Recorded round results for {phase.value} "
            f"(rev={round_data['revision']}, {succeeded}/{len(plan.steps)} ok, {len(all_papers)} papers, "
            f"{len(eval_issues)} issues, score={eval_result.score:.2f})"
        )

    def _save_phase_output(self, phase: TaskPhase, task_state: TaskState, output: dict[str, Any]) -> None:
        phase_key = f"phase_output_{phase.value}"
        task_state.metadata[phase_key] = output

        if phase == TaskPhase.TASK_INITIALIZATION and "research_spec" in output:
            task_state.metadata["research_spec"] = output["research_spec"]

        if phase == TaskPhase.PAPER_RETRIEVAL:
            if "candidate_set_id" in output:
                task_state.paper_candidate_set_id = output["candidate_set_id"]
            if "candidates" in output:
                task_state.metadata["paper_candidates"] = output["candidates"]

        if phase == TaskPhase.PAPER_PARSING and "paper_artifact_id" in output:
            task_state.paper_artifact_id = output["paper_artifact_id"]

        if phase == TaskPhase.CODE_LOCATION and "reproduction_spec_id" in output:
            task_state.reproduction_spec_id = output["reproduction_spec_id"]

        if phase == TaskPhase.EXPERIMENT_EXECUTION and "experiment_run_ids" in output:
            task_state.experiment_run_ids = output["experiment_run_ids"]

        if phase == TaskPhase.RESULT_REPORTING and "final_report_id" in output:
            task_state.final_report_id = output["final_report_id"]

    async def _ensure_stages_initialized(self, task_state: TaskState) -> None:
        all_phases = [
            TaskPhase.TASK_INITIALIZATION,
            TaskPhase.PAPER_RETRIEVAL,
            TaskPhase.PAPER_PARSING,
            TaskPhase.CODE_LOCATION,
            TaskPhase.REPRODUCTION_PLANNING,
            TaskPhase.EXPERIMENT_EXECUTION,
            TaskPhase.RESULT_REPORTING,
        ]
        for phase in all_phases:
            if phase not in task_state.stages:
                task_state.stages[phase] = StageStatus(phase=phase)

        if not task_state.current_phase or task_state.current_phase == TaskPhase.COMPLETED:
            task_state.current_phase = TaskPhase.TASK_INITIALIZATION

    def add_trace(self, task_state: TaskState, phase: TaskPhase, action: str, **kwargs: Any) -> None:
        entry = TraceEntry(phase=phase, agent="orchestrator", action=action, **kwargs)
        task_state.trace.append(entry)

    def _get_phase_config(self, phase: TaskPhase):
        for cfg in self.settings.stages:
            if cfg.name == phase.value:
                return cfg
        class NullConfig:
            display_name = phase.value
        return NullConfig()

    def _deduplicate_search_results(self, plan: ExecutionPlan) -> None:
        seen_ids = set()
        total_unique = 0
        for step in plan.steps:
            if step.tool_name == "arxiv_search" and step.success and step.result and "results" in step.result:
                deduped_results = []
                for paper in step.result.get("results", []):
                    arxiv_id = paper.get("arxiv_id", "")
                    base_id = arxiv_id.split("v")[0] if arxiv_id else ""
                    if base_id and base_id not in seen_ids:
                        seen_ids.add(base_id)
                        deduped_results.append(paper)
                step.result["results"] = deduped_results
                step.result["total_found_after_dedup"] = len(deduped_results)
                total_unique += len(deduped_results)

    async def _run_phase_hooks(self, phase: TaskPhase, task_state: TaskState) -> None:
        for hook in self._phase_hooks.get(phase, []):
            try:
                await hook(task_state)
            except Exception as e:
                logger.warning(f"Phase hook failed for {phase.value}: {e}")

    async def _run_verdict_hooks(
        self, verdict: EvaluationVerdict, task_state: TaskState, eval_result: EvaluationResult
    ) -> None:
        for hook in self._verdict_hooks.get(verdict, []):
            try:
                await hook(task_state, eval_result)
            except Exception as e:
                logger.warning(f"Verdict hook failed for {verdict.value}: {e}")

    def _update_budget_tracking(self, task_state: TaskState) -> None:
        elapsed_minutes = (time.time() - self._task_start_time) / 60 if self._task_start_time else 0
        task_state.budget.wall_time_minutes_used = elapsed_minutes
        total_input = sum(t.input_tokens for t in task_state.trace)
        total_output = sum(t.output_tokens for t in task_state.trace)
        task_state.budget.tokens_used = total_input + total_output

    def _build_phase_summary_card(
        self,
        phase: TaskPhase,
        research_output: dict[str, Any],
        eval_result: EvaluationResult,
    ) -> dict[str, Any]:
        phase_name = phase.value
        conclusion = ""
        artifact_ids: list[str] = []
        key_info: dict[str, Any] = {}
        notes = ""

        for k, v in research_output.items():
            if isinstance(v, str) and len(v) < 64 and k.endswith("_id"):
                artifact_ids.append(v)

        if phase == TaskPhase.TASK_INITIALIZATION:
            spec = research_output.get("research_spec", {})
            task_type = spec.get("task_type", "unknown")
            domain = spec.get("domain", "")
            keywords = spec.get("keywords", [])
            conclusion = f"任务类型={task_type}，研究领域={domain or '未指定'}"
            if keywords:
                key_info["keywords"] = keywords[:5]
            if "research_spec" in research_output:
                artifact_ids.append("research_spec")

        elif phase == TaskPhase.PAPER_RETRIEVAL:
            candidates = research_output.get("candidates", [])
            total = len(candidates)
            top_ids = [c.get("arxiv_id", "") for c in candidates[:3] if isinstance(c, dict)]
            conclusion = f"检索去重后保留{total}篇候选论文"
            if top_ids:
                key_info["top3"] = top_ids
            if "candidate_set_id" in research_output:
                artifact_ids.append(research_output["candidate_set_id"])
            elif "candidates" in research_output:
                artifact_ids.append("paper_candidates")
            if eval_result.issues:
                def _get_severity(issue: Any) -> str:
                    if hasattr(issue, 'severity'):
                        sev = issue.severity
                        return sev.value if hasattr(sev, 'value') else str(sev).lower()
                    if isinstance(issue, dict):
                        return issue.get("severity", "").lower()
                    return ""
                critical = [i for i in eval_result.issues if _get_severity(i) in ("critical", "high")]
                if critical:
                    notes = f"仍有{len(critical)}个待改进项"

        elif phase == TaskPhase.PAPER_PARSING:
            conclusion = "目标论文全文解析完成"
            if "paper_artifact_id" in research_output:
                artifact_ids.append(research_output["paper_artifact_id"])

        elif phase == TaskPhase.CODE_LOCATION:
            conclusion = "论文代码仓库定位完成"
            if "reproduction_spec_id" in research_output:
                artifact_ids.append(research_output["reproduction_spec_id"])

        elif phase == TaskPhase.REPRODUCTION_PLANNING:
            conclusion = "复现实验方案规划完成"
            if "reproduction_spec_id" in research_output:
                artifact_ids.append(research_output["reproduction_spec_id"])

        elif phase == TaskPhase.EXPERIMENT_EXECUTION:
            run_ids = research_output.get("experiment_run_ids", [])
            conclusion = f"实验执行完成，共{len(run_ids)}次运行"
            artifact_ids.extend(run_ids)

        elif phase == TaskPhase.RESULT_REPORTING:
            conclusion = "最终报告生成完成"
            if "final_report_id" in research_output:
                artifact_ids.append(research_output["final_report_id"])

        if not conclusion:
            conclusion = f"阶段{phase_name}完成"

        conclusion = conclusion[:100]

        return {
            "phase": phase_name,
            "verdict": eval_result.verdict.value,
            "score": eval_result.score,
            "conclusion": conclusion,
            "artifact_ids": artifact_ids,
            "key_info": key_info,
            "notes": notes[:50] if notes else "",
        }

    def _record_phase_failure(
        self,
        task_state: TaskState,
        phase: TaskPhase,
        eval_result: EvaluationResult,
        research_output: dict[str, Any],
    ) -> None:
        failures = task_state.metadata.get("phase_failures", {})
        phase_key = phase.value
        if phase_key not in failures:
            failures[phase_key] = []

        failure_record = {
            "revision": task_state.stages[phase].revision_count,
            "score": eval_result.score,
            "issues": [
                {
                    "severity": (issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity)),
                    "description": (issue.description or "")[:200],
                }
                for issue in eval_result.issues[:10]
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
        failures[phase_key].append(failure_record)
        task_state.metadata["phase_failures"] = failures
        logger.info(
            f"[{task_state.id}] Recorded failure for {phase.value} "
            f"(revision {failure_record['revision']}, score={eval_result.score:.2f}, "
            f"{len(failure_record['issues'])} issues)"
        )

    async def _default_human_confirm(
        self, task_state: TaskState, phase: TaskPhase, plan: ExecutionPlan
    ) -> bool:
        print(f"\n{'='*60}")
        print(f"Human confirmation required for phase: {phase.value}")
        print(f"Plan: {plan.plan_name}")
        print(f"Steps ({len(plan.steps)}):")
        for step in plan.steps:
            print(f"  - [{step.step_id}] {step.tool_name}: {step.description}")
        print(f"{'='*60}")
        print("(Default: confirming automatically in framework mode; override via callback)")
        return True

from __future__ import annotations

import json
from typing import Any

from ..common.agent_base import AgentConfig, BaseAgent
from ..common.config import get_settings
from ..common.llm import LLMMessage, MessageRole
from ..common.logging import get_logger
from ..common.models.base import EvaluationVerdict, SeverityLevel, TaskPhase
from ..common.models.evaluation_result import EvaluationResult
from ..common.models.execution_plan import ExecutionPlan
from ..common.models.task_state import TaskState

logger = get_logger(__name__)


class EvaluationAgent(BaseAgent):
    def __init__(self, llm=None, tool_registry=None):
        settings = get_settings()
        config = AgentConfig(
            name="evaluation_agent",
            model=settings.evaluation_agent.model or settings.llm.eval_model,
            temperature=settings.evaluation_agent.temperature,
            system_prompt_path=settings.evaluation_agent.system_prompt_path,
            max_parse_attempts=2,
        )
        super().__init__(config, llm=llm, tool_registry=tool_registry)

    async def evaluate_phase(
        self,
        phase: TaskPhase,
        task_state: TaskState,
        research_output: dict[str, Any],
        original_evidence: dict[str, Any],
        execution_plan: ExecutionPlan | None = None,
        is_revision: bool = False,
    ) -> EvaluationResult:
        if not self.system_prompt:
            await self.initialize(task_state)

        evaluation_input = self._build_evaluation_prompt(
            phase, task_state, research_output, original_evidence, execution_plan
        )
        self.message_history.append(LLMMessage(
            role=MessageRole.USER, content=evaluation_input,
            metadata={"anchor": True, "priority": 90, "msg_type": "eval_prompt"},
        ))

        deterministic_passed, deterministic_failed, det_issues = await self._run_deterministic_checks(
            phase, research_output, original_evidence, execution_plan
        )

        model_result = await self._parse_llm_to_json()

        evaluation_result = EvaluationResult(
            task_state_id=task_state.id,
            phase=phase,
            deterministic_checks_passed=deterministic_passed,
            deterministic_checks_failed=deterministic_failed,
            reviewer_model=self.config.model,
            input_artifacts=list(research_output.keys()),
            revision_count=task_state.total_revisions,
        )

        if deterministic_failed > 0:
            evaluation_result.verdict = EvaluationVerdict.BLOCKED
            evaluation_result.issues.extend(det_issues)
        else:
            try:
                verdict_str = model_result.get("verdict", "REVISE").upper()
                evaluation_result.verdict = EvaluationVerdict(verdict_str)
                evaluation_result.score = model_result.get("score", 0.0)
                evaluation_result.evidence_summary = model_result.get("summary", "")
                evaluation_result.requires_human_intervention = model_result.get("requires_human_intervention", False)
                evaluation_result.human_intervention_reason = model_result.get("human_intervention_reason")

                for issue_data in model_result.get("issues", []):
                    try:
                        from ..common.models.evaluation_result import EvaluationIssue
                        issue = EvaluationIssue(
                            issue_id=issue_data.get("issue_id", ""),
                            issue_type=issue_data.get("issue_type", "unknown"),
                            severity=SeverityLevel(issue_data.get("severity", "MEDIUM").lower()),
                            location=issue_data.get("location", ""),
                            description=issue_data.get("description", ""),
                            evidence=issue_data.get("evidence", ""),
                            evidence_refs=issue_data.get("evidence_refs", []),
                            suggestion=issue_data.get("suggestion", ""),
                        )
                        evaluation_result.issues.append(issue)
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Skipping invalid issue: {e}")
            except (ValueError, KeyError) as e:
                logger.warning(f"Failed to parse model evaluation result: {e}")
                evaluation_result.verdict = EvaluationVerdict.REVISE
                evaluation_result.issues.append(
                    EvaluationIssue(
                        issue_type="evaluation_error",
                        severity=SeverityLevel.LOW,
                        description=f"Failed to parse evaluation result: {str(e)}",
                        suggestion="Re-run evaluation",
                    )
                )

        max_revisions = self.settings.budget.max_revisions_per_stage
        if phase in task_state.stages and task_state.stages[phase].revision_count >= max_revisions:
            if evaluation_result.verdict == EvaluationVerdict.REVISE:
                evaluation_result.verdict = EvaluationVerdict.BLOCKED
                evaluation_result.requires_human_intervention = True
                evaluation_result.human_intervention_reason = (
                    f"Max revision attempts ({max_revisions}) exceeded for this phase"
                )

        return evaluation_result

    async def _build_system_prompt(self, task_state: TaskState) -> str:
        return self._read_prompt_file("prompts/evaluation_agent/system.txt")

    async def _build_phase_prompt(self, phase: TaskPhase, task_state: TaskState, **kwargs: Any) -> str:
        return ""

    def _build_evaluation_prompt(
        self,
        phase: TaskPhase,
        task_state: TaskState,
        research_output: dict[str, Any],
        original_evidence: dict[str, Any],
        execution_plan: ExecutionPlan | None,
    ) -> str:
        prompt = f"## EVALUATION TASK: Phase {phase.value}\n\n"

        prompt += "### Original User Query\n"
        prompt += task_state.metadata.get("user_query", "") + "\n\n"

        evidence_summary = self._trim_evidence(original_evidence)
        prompt += "### Original Evidence (ground truth - base your judgment on this first)\n"
        prompt += "```json\n" + json.dumps(evidence_summary, ensure_ascii=False, indent=2)[:6000] + "\n```\n\n"

        if execution_plan:
            prompt += "### Execution Plan (what was planned)\n"
            prompt += f"Plan name: {execution_plan.plan_name}\n"
            prompt += f"Steps: {len(execution_plan.steps)}\n"
            failed = execution_plan.failed_steps()
            if failed:
                prompt += f"FAILED steps: {[s.step_id for s in failed]}\n"
            prompt += "\n"

        output_summary = self._trim_output(research_output)
        prompt += "### Research Agent Output (to evaluate)\n"
        prompt += "```json\n" + json.dumps(output_summary, ensure_ascii=False, indent=2)[:10000] + "\n```\n\n"

        prompt += "### Phase Completion Checklist\n"
        checklist = self._get_phase_checklist(phase)
        for item in checklist:
            prompt += f"- [ ] {item}\n"

        prompt += "\nEvaluate independently and return JSON verdict as specified. Be concise - focus on critical/high severity issues only."
        return prompt

    def _trim_evidence(self, evidence: dict[str, Any]) -> dict[str, Any]:
        result = {}
        for k, v in evidence.items():
            if k == "research_spec" and isinstance(v, dict):
                result[k] = {
                    key: v[key] for key in [
                        "user_query",
                        "task_type",
                        "domain",
                        "keywords",
                        "constraints",
                        "target_paper_arxiv_id",
                        "target_paper_url",
                    ]
                    if key in v
                }
            elif k == "selected_paper" and isinstance(v, dict):
                result[k] = {"arxiv_id": v.get("arxiv_id"), "title": v.get("title")}
            elif k == "candidates" and isinstance(v, list):
                result[k] = f"[{len(v)} papers in candidate set]"
            else:
                result[k] = v
        return result

    @staticmethod
    def _normalize_arxiv_id(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        normalized = value.strip().rstrip("/")
        if "/abs/" in normalized:
            normalized = normalized.rsplit("/abs/", 1)[-1]
        if normalized.startswith("arXiv:"):
            normalized = normalized[6:]
        return normalized.split("v", 1)[0]

    def _trim_output(self, output: dict[str, Any]) -> dict[str, Any]:
        result = {}
        for k, v in output.items():
            if k == "candidates" and isinstance(v, list):
                result[k] = v[:15]
            elif isinstance(v, list) and len(v) > 30:
                result[k] = f"[{len(v)} items, showing first 10]"
                result[k + "_preview"] = v[:10]
            else:
                result[k] = v
        return result

    def _get_phase_checklist(self, phase: TaskPhase) -> list[str]:
        checklists = {
            TaskPhase.TASK_INITIALIZATION: [
                "Task type correctly identified",
                "Domain/keywords extracted",
                "Constraints (budget, compute, time) captured",
                "Missing information flagged if any",
            ],
            TaskPhase.PAPER_RETRIEVAL: [
                "Keywords cover the research topic",
                "Sources are reliable (arXiv, official)",
                "Papers are classified correctly (survey/method/etc)",
                "Ranking considers both relevance AND reproducibility",
                "Selection rationale provided for each candidate",
            ],
            TaskPhase.PAPER_PARSING: [
                "Paper version/DOI/arXiv ID match user target",
                "All major sections parsed",
                "Glossary terms defined correctly",
                "Translation preserves formulas/numbers/citations",
                "Summary conclusions traceable to specific sections",
            ],
            TaskPhase.CODE_LOCATION: [
                "Code source marked as official/third-party/unknown with evidence",
                "Code version matches paper publication date",
                "Repository structure analysis cites file paths",
                "Paper-code mapping identifies unpublished components",
            ],
            TaskPhase.REPRODUCTION_PLANNING: [
                "Target level matches user intent and budget",
                "Environment/dataset/weight dependencies listed",
                "Experiment plan specifies commands/configs/seeds/metrics",
                "Blockers and feasibility risks identified",
            ],
            TaskPhase.EXPERIMENT_EXECUTION: [
                "Commands executed match plan",
                "Exit codes logged",
                "Metrics extracted from actual logs",
                "Failed steps are reported not hidden",
            ],
            TaskPhase.RESULT_REPORTING: [
                "Reproduced values come from actual experiment runs",
                "Comparisons use same metric units/definitions as paper",
                "Difference analysis separates evidence from speculation",
                "Reproduction level is supported by evidence",
                "All limitations and uncertainties noted",
            ],
        }
        return checklists.get(phase, ["All required outputs present", "No fabricated content"])

    async def _run_deterministic_checks(
        self,
        phase: TaskPhase,
        output: dict[str, Any],
        evidence: dict[str, Any],
        plan: ExecutionPlan | None,
    ) -> tuple[int, int, list]:
        from ..common.models.evaluation_result import EvaluationIssue
        passed = 0
        failed = 0
        issues = []

        if not output or "error" in output:
            failed += 1
            issues.append(EvaluationIssue(
                issue_type="missing_output",
                severity=SeverityLevel.CRITICAL,
                description="Research agent produced no valid output or returned an error",
                evidence=str(output.get("error", "empty output")) if output else "empty output",
                suggestion="Fix the error and regenerate output",
            ))
            return passed, failed, issues

        passed += 1

        required_keys = {
            TaskPhase.TASK_INITIALIZATION: ["task_type"],
            TaskPhase.PAPER_RETRIEVAL: ["candidates"],
            TaskPhase.PAPER_PARSING: ["sections"],
            TaskPhase.CODE_LOCATION: ["repo_url"],
            TaskPhase.REPRODUCTION_PLANNING: ["experiment_plan"],
            TaskPhase.EXPERIMENT_EXECUTION: ["exit_code", "metrics"],
            TaskPhase.RESULT_REPORTING: ["reproduction_level"],
        }
        required = required_keys.get(phase, [])
        missing = [k for k in required if k not in output]
        if missing:
            failed += 1
            issues.append(EvaluationIssue(
                issue_type="missing_fields",
                severity=SeverityLevel.HIGH,
                description=f"Output missing required keys: {missing}",
                evidence=f"Keys present: {list(output.keys())}",
                suggestion=f"Add the missing required fields: {missing}",
            ))
        else:
            passed += 1

        if phase == TaskPhase.PAPER_RETRIEVAL:
            spec = evidence.get("research_spec", {})
            target_id = self._normalize_arxiv_id(
                spec.get("target_paper_arxiv_id")
            ) if isinstance(spec, dict) else ""
            if target_id:
                target = output.get("target_paper")
                actual_id = self._normalize_arxiv_id(
                    target.get("arxiv_id")
                ) if isinstance(target, dict) else ""
                if not output.get("target_paper_verified") or actual_id != target_id:
                    failed += 1
                    issues.append(EvaluationIssue(
                        issue_type="target_paper_missing",
                        severity=SeverityLevel.CRITICAL,
                        description="Confirmed target paper was not fetched into target_paper",
                        evidence=f"expected={target_id}, actual={actual_id or 'missing'}",
                        suggestion="Fetch the target with arxiv_get_paper before related-paper search",
                    ))
                else:
                    passed += 1

        if plan:
            if plan.failed_steps() and phase != TaskPhase.EXPERIMENT_EXECUTION:
                failed_steps = [s.step_id for s in plan.failed_steps()]
                issues.append(EvaluationIssue(
                    issue_type="step_failures",
                    severity=SeverityLevel.MEDIUM,
                    description=f"Plan steps failed: {failed_steps}",
                    evidence="Check tool execution trace for details",
                    suggestion="Address failures or explain their impact",
                ))

        return passed, failed, issues

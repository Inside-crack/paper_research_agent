from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .config import get_settings
from .llm import BaseLLM, LLMMessage, MessageRole, create_llm
from .logging import get_logger, trace_logger
from .models.base import TaskPhase, TraceEntry
from .models.execution_plan import ExecutionPlan, PlanStep
from .models.task_state import TaskState
from .tools import ToolRegistry, global_registry

logger = get_logger(__name__)


def _summarize_value(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v[:100] + "..." if len(v) > 100 else v
    if isinstance(v, list):
        if not v:
            return []
        if len(v) > 3:
            return [_summarize_value(v[0]), f"... ({len(v)} items total)"]
        return [_summarize_value(x) for x in v[:3]]
    if isinstance(v, dict):
        keys = list(v.keys())[:5]
        return {k: _summarize_value(v[k]) for k in keys}
    return str(v)[:80]


class AgentConfig(BaseModel):
    name: str
    model: str = ""
    temperature: float = 0.3
    system_prompt_path: str = ""
    max_parse_attempts: int = 3


class BaseAgent(ABC):
    def __init__(
        self,
        config: AgentConfig,
        llm: Optional[BaseLLM] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        self.config = config
        self.settings = get_settings()
        self.llm = llm or create_llm(model=config.model, temperature=config.temperature)
        self.tools = tool_registry or global_registry
        self.system_prompt: str = ""
        self.message_history: list[LLMMessage] = []
        self._current_phase: TaskPhase | None = None

    async def initialize(self, task_state: TaskState) -> None:
        self.message_history = []
        self.system_prompt = await self._load_system_prompt(task_state)
        self.message_history.append(LLMMessage(
            role=MessageRole.SYSTEM, content=self.system_prompt,
            metadata={"anchor": True, "priority": 100, "msg_type": "system_prompt"},
        ))
        await self._on_initialize(task_state)

    async def start_new_phase(
        self,
        phase: TaskPhase,
        task_state: TaskState,
        previous_summaries: list[dict[str, Any]],
        force: bool = False,
    ) -> None:
        if not force and self._current_phase == phase:
            raise RuntimeError(
                f"start_new_phase called twice for the same phase '{phase.value}'. "
                f"Each phase must call start_new_phase exactly once at the beginning. "
                f"Use force=True to reset context for REVISE retries within the same phase."
            )

        self._current_phase = phase
        await self.initialize(task_state)
        await self._on_start_new_phase(phase, task_state, previous_summaries)
        logger.info(
            f"[{self.config.name}] Started new phase: {phase.value}, "
            f"injected {len(previous_summaries)} previous summary cards"
            f"{' (force reset for REVISE)' if force else ''}"
        )

    async def _on_start_new_phase(
        self,
        phase: TaskPhase,
        task_state: TaskState,
        previous_summaries: list[dict[str, Any]],
    ) -> None:
        pass

    def inject_message(self, content: str, role: MessageRole = MessageRole.USER,
                       anchor: bool = False, priority: int = 60) -> None:
        if not self.system_prompt:
            raise RuntimeError(
                f"Agent '{self.config.name}' not initialized. "
                f"start_new_phase() or initialize() must be called before inject_message()."
            )
        self.message_history.append(LLMMessage(role=role, content=content, metadata={
            "anchor": anchor, "priority": priority,
        }))
        logger.debug(f"[{self.config.name}] Injected {role.value} message ({len(content)} chars, anchor={anchor})")

    async def generate_plan(
        self,
        phase: TaskPhase,
        task_state: TaskState,
        is_revision: bool = False,
        correction_notes: str = "",
        **kwargs: Any,
    ) -> ExecutionPlan:
        if not self.system_prompt:
            raise RuntimeError(
                f"Agent '{self.config.name}' not initialized for phase {phase.value}. "
                f"start_new_phase() must be called before generate_plan()."
            )

        phase_prompt = await self._build_phase_prompt(phase, task_state, **kwargs)
        if is_revision and correction_notes:
            phase_prompt += f"\n\n## CORRECTION REQUIRED\n{correction_notes}\n\nGenerate a revised plan addressing these specific issues only."

        self.message_history.append(LLMMessage(
            role=MessageRole.USER, content=phase_prompt,
            metadata={"anchor": True, "priority": 90, "msg_type": "phase_prompt"},
        ))

        trace_logger.log_agent_action(
            agent=self.config.name,
            phase=phase.value,
            action="generate_plan",
        )

        plan = await self._parse_llm_to_plan(phase)
        self.message_history.append(
            LLMMessage(role=MessageRole.ASSISTANT, content=json.dumps({
                "action": "plan",
                "plan_name": plan.plan_name,
                "steps": [{"step_id": s.step_id, "tool_name": s.tool_name, "arguments": s.arguments} for s in plan.steps]
            }, ensure_ascii=False), metadata={"anchor": False, "priority": 40, "msg_type": "plan_response"})
        )
        plan.phase = phase.value
        self.add_trace(task_state, phase, "plan_generated", plan_id=plan.id, step_count=len(plan.steps))
        return plan

    async def synthesize_result(
        self,
        phase: TaskPhase,
        task_state: TaskState,
        plan: ExecutionPlan,
        **kwargs: Any,
    ) -> dict[str, Any]:
        results_prompt = self._build_results_prompt(plan)
        self.message_history.append(LLMMessage(
            role=MessageRole.USER, content=results_prompt,
            metadata={"anchor": True, "priority": 80, "msg_type": "results_prompt"},
        ))

        trace_logger.log_agent_action(
            agent=self.config.name,
            phase=phase.value,
            action="synthesize_result",
        )

        result = await self._parse_llm_to_json()
        self.message_history.append(
            LLMMessage(role=MessageRole.ASSISTANT, content=json.dumps(result, ensure_ascii=False)[:4000],
                       metadata={"anchor": False, "priority": 50, "msg_type": "synthesize_response"})
        )
        return result

    def record_step_result(self, step: PlanStep) -> None:
        pass

    @abstractmethod
    async def _build_system_prompt(self, task_state: TaskState) -> str:
        pass

    @abstractmethod
    async def _build_phase_prompt(self, phase: TaskPhase, task_state: TaskState, **kwargs: Any) -> str:
        pass

    async def _on_initialize(self, task_state: TaskState) -> None:
        pass

    async def _load_system_prompt(self, task_state: TaskState) -> str:
        prompt_path = self.config.system_prompt_path
        if prompt_path:
            content = self._read_prompt_file(prompt_path)
            if content:
                return content

        return await self._build_system_prompt(task_state)

    def _read_prompt_file(self, path: str) -> str:
        prompt_path = Path(path)
        if not prompt_path.is_absolute():
            prompt_path = Path(__file__).parents[3] / path
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return ""

    def _load_phase_prompt(self, phase: TaskPhase) -> str:
        phase_file_map = {
            TaskPhase.TASK_INITIALIZATION: "task_initialization.txt",
            TaskPhase.PAPER_RETRIEVAL: "paper_retrieval.txt",
            TaskPhase.PAPER_PARSING: "paper_parsing.txt",
            TaskPhase.CODE_LOCATION: "code_location.txt",
            TaskPhase.REPRODUCTION_PLANNING: "reproduction_planning.txt",
            TaskPhase.EXPERIMENT_EXECUTION: "experiment_execution.txt",
            TaskPhase.RESULT_REPORTING: "result_reporting.txt",
        }
        filename = phase_file_map.get(phase)
        if not filename:
            return f"Proceed with phase: {phase.value}"

        prompt_dir = Path(__file__).parents[3] / "prompts" / self.config.name / "phases"
        return self._read_prompt_file(str(prompt_dir / filename))

    async def _parse_llm_to_plan(self, phase: TaskPhase) -> ExecutionPlan:
        for attempt in range(self.config.max_parse_attempts):
            response = await self.llm.agenerate(messages=self.message_history)
            try:
                data = self._extract_json(response.content)
                if "action" in data and data["action"] == "plan":
                    steps = []
                    for i, step_data in enumerate(data.get("steps", [])):
                        steps.append(PlanStep(
                            step_id=step_data.get("step_id", f"step_{i}"),
                            description=step_data.get("description", ""),
                            tool_name=step_data.get("tool_name", ""),
                            arguments=step_data.get("arguments", {}),
                            expected_output=step_data.get("expected_output", ""),
                        ))
                    return ExecutionPlan(
                        plan_name=data.get("plan_name", f"{phase.value}_plan"),
                        requires_human_confirmation=data.get("requires_human_confirmation", False),
                        steps=steps,
                        summary_note=data.get("note", ""),
                    )
                else:
                    self.message_history.append(LLMMessage(
                        role=MessageRole.USER,
                        content="Response must have action='plan' and a 'steps' array. Please output only the plan JSON.",
                        metadata={"anchor": False, "priority": 20, "msg_type": "retry_correction"},
                    ))
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"Plan parse attempt {attempt+1} failed: {e}")
                self.message_history.append(LLMMessage(
                    role=MessageRole.USER,
                    content=f"Failed to parse plan JSON. Error: {e}. Respond with valid plan JSON only.",
                    metadata={"anchor": False, "priority": 20, "msg_type": "retry_correction"},
                ))

        raise ValueError(f"Failed to get valid ExecutionPlan after {self.config.max_parse_attempts} attempts")

    async def _parse_llm_to_json(self) -> dict[str, Any]:
        for attempt in range(self.config.max_parse_attempts):
            response = await self.llm.agenerate(messages=self.message_history)
            try:
                data = self._extract_json(response.content)
                if isinstance(data, list):
                    if data and isinstance(data[0], dict):
                        data = data[0]
                    else:
                        data = {"items": data, "verdict": "REVISE", "score": 0.5}
                return data
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse attempt {attempt+1} failed: {e}")
                fixed = self._try_fix_json(response.content)
                if fixed:
                    try:
                        data = json.loads(fixed)
                        if isinstance(data, list):
                            data = data[0] if data and isinstance(data[0], dict) else {"items": data}
                        return data
                    except:
                        pass
                self.message_history.append(LLMMessage(
                    role=MessageRole.USER,
                    content=f"Failed to parse JSON. Error: {e}. Respond with valid JSON only, no markdown wrapping, no text before/after. Output a single JSON object.",
                    metadata={"anchor": False, "priority": 20, "msg_type": "retry_correction"},
                ))

        return {"verdict": "REVISE", "score": 0.0, "issues": [{"severity": "critical", "description": "Failed to parse output after multiple attempts"}]}

    def _try_fix_json(self, content: str) -> str | None:
        content = content.strip()
        if content.startswith("```"):
            return None
        if not (content.startswith("{") or content.startswith("[")):
            start = content.find("{")
            if start >= 0:
                content = content[start:]
            else:
                return None

        open_braces = content.count("{") - content.count("}")
        open_brackets = content.count("[") - content.count("]")
        if open_braces > 0 or open_brackets > 0:
            content = content.rstrip(",\n ")
            if open_braces > 0:
                content += "}" * open_braces
            if open_brackets > 0:
                content += "]" * open_brackets
        return content

    def _extract_json(self, content: str) -> dict[str, Any]:
        content = content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        if content.startswith("`") and content.endswith("`"):
            content = content.strip("`")
        return json.loads(content)

    def _build_results_prompt(self, plan: ExecutionPlan) -> str:
        MAX_PAPERS_IN_PROMPT = 30

        prompt = "## Tool Execution Results\n\nAll steps in your plan have been executed. Here are the results:\n\n"
        prompt += "| Step | Tool | Success | Artifact | Summary |\n"
        prompt += "|------|------|---------|----------|----------|\n"

        arxiv_steps: list[tuple[PlanStep, dict]] = []
        other_steps: list[PlanStep] = []

        for step in plan.steps:
            status = "✓" if step.success else "✗"
            artifact = step.artifact_id or "-"
            result_preview = ""
            compact = None
            if step.result:
                compact = self._compact_result(step.tool_name, step.result)
                result_preview = json.dumps(compact, ensure_ascii=False)[:200]
            elif step.error:
                result_preview = f"ERROR: {step.error[:150]}"
            prompt += f"| {step.step_id} | {step.tool_name} | {status} | {artifact} | {result_preview} |\n"

            if step.success and step.tool_name == "arxiv_search" and isinstance(compact, dict) and "results" in compact:
                arxiv_steps.append((step, compact))
            else:
                other_steps.append(step)

        if arxiv_steps:
            all_papers: dict[str, dict] = {}
            total_per_query: list[tuple[str, int]] = []
            for step, compact in arxiv_steps:
                q = compact.get("query", "")
                papers = compact.get("results", [])
                total_per_query.append((q, len(papers)))
                for p in papers:
                    pid = p.get("arxiv_id")
                    if pid and pid not in all_papers:
                        all_papers[pid] = p

            paper_list = list(all_papers.values())
            total_found_sum = sum(t for _, t in total_per_query)
            unique_count = len(paper_list)
            shown = paper_list[:MAX_PAPERS_IN_PROMPT]

            prompt += "\n### Deduplicated Paper List\n"
            prompt += f"Across {len(arxiv_steps)} arxiv_search call(s): {total_found_sum} results returned, {unique_count} unique papers after deduplication"
            if unique_count > MAX_PAPERS_IN_PROMPT:
                prompt += f", showing top {MAX_PAPERS_IN_PROMPT} (full list persisted in step artifacts)"
            prompt += ".\n\n"
            prompt += "```json\n"
            prompt += json.dumps({"papers": shown, "total_unique": unique_count, "shown": len(shown)}, ensure_ascii=False, indent=2)
            prompt += "\n```\n"

            for step, _compact in arxiv_steps:
                if step.artifact_id:
                    prompt += f"- Step {step.step_id} persisted artifact: `{step.artifact_id}` (load with load_artifact for complete list)\n"

        prompt += "\n### Other Step Results\n"
        for step in other_steps:
            prompt += f"\n#### Step: {step.step_id} ({step.tool_name})\n"
            prompt += f"Description: {step.description}\n"
            if step.artifact_id:
                prompt += f"Persisted artifact: `{step.artifact_id}` (load with load_artifact if needed in later phases)\n"
            if step.success:
                compact = self._compact_result(step.tool_name, step.result) if step.result else None
                if compact is not None:
                    text = json.dumps(compact, ensure_ascii=False, indent=2)
                    if len(text) > 4000:
                        text = text[:4000] + "\n... [truncated, full result in artifact]"
                    prompt += "Result:\n```json\n"
                    prompt += text
                    prompt += "\n```\n"
            else:
                prompt += f"FAILED: {step.error}\n"
                if step.artifact_id:
                    prompt += f"Error details persisted to: `{step.artifact_id}`\n"

        failed = plan.failed_steps()
        if failed:
            prompt += f"\n### IMPORTANT: {len(failed)} step(s) failed. Note the failures in your output and work with available results.\n"

        prompt += "\nNow synthesize these results into the final structured output for this phase. Return ONLY the output JSON, no plan wrapper."
        return prompt

    def _compact_result(self, tool_name: str, result: Any) -> Any:
        if not isinstance(result, dict):
            return result

        if tool_name == "arxiv_search" and "results" in result:
            compact_results = []
            for paper in result.get("results", []):
                authors = paper.get("authors", []) or []
                abstract = paper.get("abstract", "") or ""
                compact_results.append({
                    "arxiv_id": paper.get("arxiv_id"),
                    "title": paper.get("title"),
                    "authors": authors[:1],
                    "year": paper.get("published_date", "")[:4] if paper.get("published_date") else None,
                    "code_available": paper.get("code_available_hint", False),
                    "code_url": paper.get("code_url_hint"),
                    "abstract": abstract[:150],
                })
            return {
                "query": result.get("query"),
                "total_found": result.get("total_found"),
                "results": compact_results,
            }

        if tool_name == "arxiv_get_paper" and "arxiv_id" in result:
            authors = result.get("authors", []) or []
            abstract = result.get("abstract", "") or ""
            return {
                "arxiv_id": result.get("arxiv_id"),
                "title": result.get("title"),
                "authors": authors[:3],
                "year": result.get("published_date", "")[:4] if result.get("published_date") else None,
                "categories": result.get("categories", []),
                "code_available": result.get("code_available_hint", False),
                "code_url": result.get("code_url_hint"),
                "abstract": abstract[:500],
                "pdf_url": result.get("pdf_url"),
            }

        if tool_name == "load_artifact":
            data = result.get("data") if isinstance(result.get("data"), (dict, list)) else result.get("data")
            if isinstance(data, dict):
                keys = list(data.keys())[:20]
                preview = {k: _summarize_value(data[k]) for k in keys}
                return {
                    "artifact_name": result.get("artifact_name"),
                    "loaded": True,
                    "type": "dict",
                    "keys": keys,
                    "total_keys": len(data),
                    "preview": preview,
                }
            if isinstance(data, list):
                return {
                    "artifact_name": result.get("artifact_name"),
                    "loaded": True,
                    "type": "list",
                    "length": len(data),
                    "first_item": _summarize_value(data[0]) if data else None,
                }
            return result

        if tool_name in ("save_artifact", "download_file"):
            return result

        data = result
        if isinstance(data, dict):
            keys = list(data.keys())[:10]
            return {
                "_type": "tool_result",
                "tool": tool_name,
                "keys": keys,
                "size": len(json.dumps(data, ensure_ascii=False)),
                "preview": {k: _summarize_value(data[k]) for k in keys},
            }

        return result

    def add_trace(
        self,
        task_state: TaskState,
        phase: TaskPhase,
        action: str,
        **kwargs: Any,
    ) -> None:
        entry = TraceEntry(
            phase=phase,
            agent=self.config.name,
            action=action,
            **kwargs,
        )
        task_state.trace.append(entry)

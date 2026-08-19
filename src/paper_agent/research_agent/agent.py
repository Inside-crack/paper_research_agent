from __future__ import annotations

from typing import Any

from ..common.agent_base import AgentConfig, BaseAgent
from ..common.config import get_settings
from ..common.llm import LLMMessage, MessageRole
from ..common.models.base import TaskPhase
from ..common.models.task_state import TaskState


class ResearchAgent(BaseAgent):
    MAX_SUMMARY_CARD_CHARS = 200

    def __init__(self, llm=None, tool_registry=None):
        settings = get_settings()
        config = AgentConfig(
            name="research_agent",
            model=settings.research_agent.model or settings.llm.model,
            temperature=settings.research_agent.temperature,
            system_prompt_path=settings.research_agent.system_prompt_path,
            max_parse_attempts=3,
        )
        super().__init__(config, llm=llm, tool_registry=tool_registry)

    async def _build_system_prompt(self, task_state: TaskState) -> str:
        system_prompt = self._read_prompt_file("prompts/research_agent/system.txt")
        tools_desc = self._build_tools_description()
        system_prompt = system_prompt.replace("{available_tools}", tools_desc)
        return system_prompt

    async def _on_start_new_phase(
        self,
        phase: TaskPhase,
        task_state: TaskState,
        previous_summaries: list[dict[str, Any]],
    ) -> None:
        spec_data = task_state.metadata.get("research_spec")
        if spec_data:
            spec_content = "=== 研究任务规格 (Research Spec) ===\n"
            spec_content += self._pretty_json(spec_data)
            self.message_history.append(
                LLMMessage(role=MessageRole.USER, content=spec_content,
                           metadata={"anchor": True, "priority": 100, "msg_type": "research_spec"})
            )

        if previous_summaries:
            summaries_content = "=== 已完成阶段进度 ===\n"
            for card in previous_summaries:
                summaries_content += self._format_summary_card(card) + "\n\n"
            self.message_history.append(
                LLMMessage(role=MessageRole.USER, content=summaries_content.rstrip(),
                           metadata={"anchor": True, "priority": 95, "msg_type": "phase_summaries"})
            )

    def _format_summary_card(self, card: dict[str, Any]) -> str:
        phase_name = card.get("phase", "unknown")
        verdict = card.get("verdict", "PASS")
        score = card.get("score", 0.0)
        conclusion = card.get("conclusion", "")
        artifact_ids = card.get("artifact_ids", [])
        notes = card.get("notes", "")
        key_info = card.get("key_info", {})

        icon = "✅" if verdict == "PASS" else "⚠️"
        lines = [
            f"{icon} {phase_name}: {verdict} (score: {score:.2f})",
            f"   核心结论: {conclusion}",
        ]
        if artifact_ids:
            lines.append(f"   产物: {', '.join(artifact_ids)}")
        if key_info:
            for k, v in key_info.items():
                val_str = str(v)
                if len(val_str) > 80:
                    val_str = val_str[:77] + "..."
                lines.append(f"   {k}: {val_str}")
        if notes:
            lines.append(f"   备注: {notes}")

        result = "\n".join(lines)
        if len(result) > self.MAX_SUMMARY_CARD_CHARS:
            result = result[: self.MAX_SUMMARY_CARD_CHARS - 3] + "..."
        return result

    def _build_tools_description(self) -> str:
        lines = []
        for tool_name in self.tools.list_tools():
            tool = self.tools.get(tool_name)
            if tool:
                lines.append(f"- **{tool.name}**: {tool.description}")
        return "\n".join(lines)

    async def _build_phase_prompt(self, phase: TaskPhase, task_state: TaskState, **kwargs: Any) -> str:
        phase_prompt_template = self._load_phase_prompt(phase)

        template_vars = {
            "user_query": task_state.metadata.get("user_query", ""),
            "target_paper_info": "",
            "current_state": self._format_current_state(task_state),
            "research_spec": "",
            "selected_paper": "",
            "paper_summary": "",
        }

        spec_data = task_state.metadata.get("research_spec")
        if spec_data:
            template_vars["research_spec"] = self._pretty_json(spec_data)
            if spec_data.get("target_paper_url") or spec_data.get("target_paper_arxiv_id"):
                template_vars["target_paper_info"] = self._pretty_json({
                    "url": spec_data.get("target_paper_url"),
                    "arxiv_id": spec_data.get("target_paper_arxiv_id"),
                })

        template_vars.update(kwargs)

        result = phase_prompt_template
        for key, value in template_vars.items():
            result = result.replace("{" + key + "}", str(value))
        return result

    def _format_current_state(self, task_state: TaskState) -> str:
        state = {
            "current_phase": task_state.current_phase.value,
            "completed_phases": [
                p.value for p, s in task_state.stages.items()
                if s.completed_at is not None and s.verdict and s.verdict.value == "PASS"
            ],
            "total_revisions": task_state.total_revisions,
        }
        return self._pretty_json(state)

    def _pretty_json(self, data: Any) -> str:
        import json
        return json.dumps(data, ensure_ascii=False, indent=2)

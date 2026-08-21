from __future__ import annotations

from typing import Any

from .base import CapabilityAdapter, CapabilityResult, ExecutionContext


class PaperSummaryAdapter(CapabilityAdapter):
    """Expose paper_summary as a task-bound evidence-linked summary capability."""

    name = "paper_summary"

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        if not isinstance(context, ExecutionContext):
            return CapabilityResult.failed("context must be an ExecutionContext")
        if not context.task_id:
            return CapabilityResult.blocked(
                "paper_summary requires context.task_id",
                next_actions=["先创建或绑定一个任务"],
            )
        if not isinstance(arguments, dict):
            return CapabilityResult.failed("arguments must be an object")

        artifact_path = arguments.get("artifact_path")
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            return CapabilityResult.blocked(
                "paper_summary requires artifact_path",
                next_actions=["先完成论文结构解析"],
            )

        if "summary" not in arguments:
            return CapabilityResult.blocked(
                "paper_summary requires summary",
                next_actions=["先生成带章节证据的论文总结"],
            )
        summary = arguments["summary"]
        if not isinstance(summary, dict):
            return CapabilityResult.failed("summary must be an object")

        tool_result = await self.tool_registry.execute(
            "paper_summary",
            task_id=context.task_id,
            artifact_path=artifact_path.strip(),
            summary=summary,
        )
        if not tool_result.success:
            return CapabilityResult.failed(
                tool_result.error or "paper_summary failed",
                next_actions=["检查总结字段和章节证据后重试"],
            )
        if not isinstance(tool_result.data, dict):
            return CapabilityResult.failed(
                "Invalid paper_summary output: expected an object"
            )

        required_output = (
            "paper_artifact_id",
            "artifact_path",
            "evidence_categories",
            "summary_fields",
        )
        missing_output = [
            field
            for field in required_output
            if field not in tool_result.data or tool_result.data[field] is None
        ]
        if missing_output:
            return CapabilityResult.failed(
                "Invalid paper_summary output: missing "
                + ", ".join(missing_output)
            )
        if not isinstance(tool_result.data["summary_fields"], list):
            return CapabilityResult.failed(
                "Invalid paper_summary output: summary_fields must be a list"
            )

        return CapabilityResult.succeeded(
            data=tool_result.data,
            artifact_refs=[tool_result.data["artifact_path"]],
            next_actions=["论文处理链路已完成"],
        )

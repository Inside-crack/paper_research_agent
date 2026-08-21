from __future__ import annotations

from typing import Any

from .base import CapabilityAdapter, CapabilityResult, ExecutionContext


class PaperParseAdapter(CapabilityAdapter):
    """Expose paper_parse as a task-bound paper structure capability."""

    name = "paper_parse"

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        if not isinstance(context, ExecutionContext):
            return CapabilityResult.failed("context must be an ExecutionContext")
        if not context.task_id:
            return CapabilityResult.blocked(
                "paper_parse requires context.task_id",
                next_actions=["先创建或绑定一个任务"],
            )
        if not isinstance(arguments, dict):
            return CapabilityResult.failed("arguments must be an object")

        artifact_path = arguments.get("artifact_path")
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            return CapabilityResult.blocked(
                "paper_parse requires artifact_path",
                next_actions=["先下载论文或提供 PaperArtifact 路径"],
            )

        tool_result = await self.tool_registry.execute(
            "paper_parse",
            task_id=context.task_id,
            artifact_path=artifact_path.strip(),
        )
        if not tool_result.success:
            return CapabilityResult.failed(
                tool_result.error or "paper_parse failed",
                next_actions=["检查 PaperArtifact 和 PDF 后重试"],
            )
        if not isinstance(tool_result.data, dict):
            return CapabilityResult.failed(
                "Invalid paper_parse output: expected an object"
            )

        required_output = (
            "paper_artifact_id",
            "artifact_path",
            "page_count",
            "section_count",
            "text_length",
            "parsing_errors",
        )
        missing_output = [
            field
            for field in required_output
            if field not in tool_result.data or tool_result.data[field] is None
        ]
        if missing_output:
            return CapabilityResult.failed(
                "Invalid paper_parse output: missing "
                + ", ".join(missing_output)
            )

        parsing_errors = tool_result.data["parsing_errors"]
        if not isinstance(parsing_errors, list):
            return CapabilityResult.failed(
                "Invalid paper_parse output: parsing_errors must be a list"
            )

        return CapabilityResult.succeeded(
            data=tool_result.data,
            artifact_refs=[tool_result.data["artifact_path"]],
            next_actions=["继续生成论文术语表"],
        )

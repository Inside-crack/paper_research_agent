from __future__ import annotations

from typing import Any

from .base import CapabilityAdapter, CapabilityResult, ExecutionContext


class PaperGlossaryAdapter(CapabilityAdapter):
    """Expose paper_glossary as a task-bound glossary capability."""

    name = "paper_glossary"

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        if not isinstance(context, ExecutionContext):
            return CapabilityResult.failed("context must be an ExecutionContext")
        if not context.task_id:
            return CapabilityResult.blocked(
                "paper_glossary requires context.task_id",
                next_actions=["先创建或绑定一个任务"],
            )
        if not isinstance(arguments, dict):
            return CapabilityResult.failed("arguments must be an object")

        artifact_path = arguments.get("artifact_path")
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            return CapabilityResult.blocked(
                "paper_glossary requires artifact_path",
                next_actions=["先完成论文结构解析"],
            )

        if "terms" not in arguments:
            return CapabilityResult.blocked(
                "paper_glossary requires terms",
                next_actions=["先生成术语候选后重试"],
            )
        terms = arguments["terms"]
        if not isinstance(terms, list):
            return CapabilityResult.failed("terms must be a list")

        tool_result = await self.tool_registry.execute(
            "paper_glossary",
            task_id=context.task_id,
            artifact_path=artifact_path.strip(),
            terms=terms,
        )
        if not tool_result.success:
            return CapabilityResult.failed(
                tool_result.error or "paper_glossary failed",
                next_actions=["检查论文原文证据和术语候选后重试"],
            )
        if not isinstance(tool_result.data, dict):
            return CapabilityResult.failed(
                "Invalid paper_glossary output: expected an object"
            )

        required_output = (
            "paper_artifact_id",
            "artifact_path",
            "term_count",
            "terms",
        )
        missing_output = [
            field
            for field in required_output
            if field not in tool_result.data or tool_result.data[field] is None
        ]
        if missing_output:
            return CapabilityResult.failed(
                "Invalid paper_glossary output: missing "
                + ", ".join(missing_output)
            )
        if not isinstance(tool_result.data["terms"], list):
            return CapabilityResult.failed(
                "Invalid paper_glossary output: terms must be a list"
            )

        return CapabilityResult.succeeded(
            data=tool_result.data,
            artifact_refs=[tool_result.data["artifact_path"]],
            next_actions=["继续翻译论文章节"],
        )

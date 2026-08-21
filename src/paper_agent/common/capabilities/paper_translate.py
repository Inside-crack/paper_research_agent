from __future__ import annotations

from typing import Any

from .base import CapabilityAdapter, CapabilityResult, ExecutionContext


class PaperTranslateAdapter(CapabilityAdapter):
    """Expose paper_translate as a task-bound translation capability."""

    name = "paper_translate"

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        if not isinstance(context, ExecutionContext):
            return CapabilityResult.failed("context must be an ExecutionContext")
        if not context.task_id:
            return CapabilityResult.blocked(
                "paper_translate requires context.task_id",
                next_actions=["先创建或绑定一个任务"],
            )
        if not isinstance(arguments, dict):
            return CapabilityResult.failed("arguments must be an object")

        artifact_path = arguments.get("artifact_path")
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            return CapabilityResult.blocked(
                "paper_translate requires artifact_path",
                next_actions=["先完成论文结构解析"],
            )

        if "translations" not in arguments:
            return CapabilityResult.blocked(
                "paper_translate requires translations",
                next_actions=["先生成各章节译文后重试"],
            )
        translations = arguments["translations"]
        if not isinstance(translations, list):
            return CapabilityResult.failed("translations must be a list")

        tool_result = await self.tool_registry.execute(
            "paper_translate",
            task_id=context.task_id,
            artifact_path=artifact_path.strip(),
            translations=translations,
        )
        if not tool_result.success:
            return CapabilityResult.failed(
                tool_result.error or "paper_translate failed",
                next_actions=["检查章节完整性和受保护内容后重试"],
            )
        if not isinstance(tool_result.data, dict):
            return CapabilityResult.failed(
                "Invalid paper_translate output: expected an object"
            )

        required_output = (
            "paper_artifact_id",
            "artifact_path",
            "section_count",
            "translated_text_length",
        )
        missing_output = [
            field
            for field in required_output
            if field not in tool_result.data or tool_result.data[field] is None
        ]
        if missing_output:
            return CapabilityResult.failed(
                "Invalid paper_translate output: missing "
                + ", ".join(missing_output)
            )

        return CapabilityResult.succeeded(
            data=tool_result.data,
            artifact_refs=[tool_result.data["artifact_path"]],
            next_actions=["继续生成论文总结"],
        )

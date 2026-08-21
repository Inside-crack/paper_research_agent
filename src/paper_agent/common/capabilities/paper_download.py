from __future__ import annotations

from typing import Any

from .base import CapabilityAdapter, CapabilityResult, ExecutionContext


class PaperDownloadAdapter(CapabilityAdapter):
    """Expose paper_download as a task-bound capability."""

    name = "paper_download"

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        if not isinstance(context, ExecutionContext):
            return CapabilityResult.failed("context must be an ExecutionContext")
        if not context.task_id:
            return CapabilityResult.blocked(
                "paper_download requires context.task_id",
                next_actions=["先创建或绑定一个任务"],
            )
        if not isinstance(arguments, dict):
            return CapabilityResult.failed("arguments must be an object")

        selected_paper = context.selected_paper
        if selected_paper is not None and not isinstance(selected_paper, dict):
            return CapabilityResult.failed("context.selected_paper must be an object")

        paper = dict(selected_paper or {})
        for field in ("arxiv_id", "pdf_url"):
            if field in arguments and arguments[field] is not None:
                value = arguments[field]
                if not isinstance(value, str) or not value.strip():
                    return CapabilityResult.failed(f"{field} must be a non-empty string")
                paper[field] = value.strip()

        if not paper.get("arxiv_id") and not paper.get("pdf_url"):
            return CapabilityResult.blocked(
                "paper_download requires selected_paper.arxiv_id or selected_paper.pdf_url",
                next_actions=["先选择一篇论文"],
            )

        tool_arguments: dict[str, Any] = {
            "task_id": context.task_id,
            "paper": paper,
        }
        for field in ("arxiv_id", "pdf_url"):
            if field in arguments and arguments[field] is not None:
                tool_arguments[field] = paper[field]

        tool_result = await self.tool_registry.execute(
            "paper_download",
            **tool_arguments,
        )
        if not tool_result.success:
            return CapabilityResult.failed(
                tool_result.error or "paper_download failed",
                next_actions=["检查论文版本或下载地址后重试"],
            )
        if not isinstance(tool_result.data, dict):
            return CapabilityResult.failed(
                "Invalid paper_download output: expected an object"
            )

        required_output = ("paper_artifact_id", "pdf_path", "artifact_path")
        missing_output = [
            field for field in required_output if not tool_result.data.get(field)
        ]
        if missing_output:
            return CapabilityResult.failed(
                "Invalid paper_download output: missing "
                + ", ".join(missing_output)
            )

        artifact_refs = [
            tool_result.data["artifact_path"],
            tool_result.data["pdf_path"],
        ]
        return CapabilityResult.succeeded(
            data=tool_result.data,
            artifact_refs=artifact_refs,
            next_actions=["继续解析论文结构"],
        )

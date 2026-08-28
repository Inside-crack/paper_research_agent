from __future__ import annotations

from typing import Any, Optional, Protocol

from .base import CapabilityAdapter, CapabilityResult, ExecutionContext


class PaperComparisonWorkflowRunner(Protocol):
    async def run(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        ...


class PaperComparisonWorkflowAdapter(CapabilityAdapter):
    """Expose the controlled multi-paper comparison workflow."""

    name = "compare_papers"

    def __init__(
        self,
        workflow_runner: Optional[PaperComparisonWorkflowRunner] = None,
    ):
        super().__init__(tool_registry=None)  # type: ignore[arg-type]
        self.workflow_runner = workflow_runner

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        if not context.task_id:
            return CapabilityResult.blocked(
                "compare_papers requires ExecutionContext.task_id"
            )
        references = arguments.get("paper_refs")
        if not isinstance(references, list) or len(references) < 2:
            return CapabilityResult.failed(
                "compare_papers requires at least two paper references"
            )
        if self.workflow_runner is None:
            return CapabilityResult.blocked(
                "paper comparison workflow runner is not configured"
            )
        result = await self.workflow_runner.run(context, dict(arguments))
        if not isinstance(result, CapabilityResult):
            raise TypeError(
                "paper comparison workflow runner must return CapabilityResult"
            )
        return result

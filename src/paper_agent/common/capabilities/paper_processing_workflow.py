from __future__ import annotations

from typing import Any, Optional, Protocol

from .base import CapabilityAdapter, CapabilityResult, ExecutionContext


class PaperProcessingWorkflowRunner(Protocol):
    async def run(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        """Run the fixed download -> summary paper workflow."""


class PaperProcessingWorkflowAdapter(CapabilityAdapter):
    """Route the selected-paper intent to the controlled P10-P14 workflow."""

    name = "process_selected_paper"

    def __init__(
        self,
        workflow_runner: Optional[PaperProcessingWorkflowRunner] = None,
    ):
        # Workflow adapters do not call a ToolRegistry directly.  The runner
        # will be supplied by the workflow layer once P33 extracts the flow.
        super().__init__(tool_registry=None)  # type: ignore[arg-type]
        self.workflow_runner = workflow_runner

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        if not context.task_id:
            return CapabilityResult.blocked(
                "process_selected_paper requires ExecutionContext.task_id"
            )
        if not context.selected_paper:
            return CapabilityResult.blocked(
                "process_selected_paper requires a selected paper"
            )
        if self.workflow_runner is None:
            # Registration and routing are safe before P33 is extracted, but
            # never pretend that an unconfigured workflow produced results.
            return CapabilityResult.blocked(
                "paper processing workflow runner is not configured"
            )

        result = await self.workflow_runner.run(context, dict(arguments))
        if not isinstance(result, CapabilityResult):
            raise TypeError(
                "paper processing workflow runner must return CapabilityResult"
            )
        return result

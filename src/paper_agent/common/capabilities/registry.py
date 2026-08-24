from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .base import CapabilityAdapter


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    description: str
    adapter: CapabilityAdapter
    enabled: bool = True
    execution_kind: Literal["tool", "workflow"] = "tool"
    input_schema: dict[str, Any] | None = None
    required_arguments: list[str] | None = None
    preconditions: list[str] | None = None
    confirmation_required: bool = False
    allowed_intents: list[str] | None = None


class CapabilityRegistry:
    """In-memory registry for explicitly executable capabilities."""

    def __init__(self):
        self._capabilities: dict[str, CapabilitySpec] = {}

    def register(
        self,
        adapter: CapabilityAdapter,
        *,
        name: str | None = None,
        description: str = "",
        enabled: bool = True,
        execution_kind: Literal["tool", "workflow"] = "tool",
        input_schema: dict[str, Any] | None = None,
        required_arguments: list[str] | None = None,
        preconditions: list[str] | None = None,
        confirmation_required: bool = False,
        allowed_intents: list[str] | None = None,
    ) -> None:
        capability_name = name or adapter.name
        if not capability_name:
            raise ValueError("Capability must have a name")
        if capability_name in self._capabilities:
            raise ValueError(f"Capability already registered: {capability_name}")
        self._capabilities[capability_name] = CapabilitySpec(
            name=capability_name,
            description=description or adapter.__class__.__doc__ or "",
            adapter=adapter,
            enabled=enabled,
            execution_kind=execution_kind,
            input_schema=input_schema or {},
            required_arguments=required_arguments or [],
            preconditions=preconditions or [],
            confirmation_required=confirmation_required,
            allowed_intents=allowed_intents or [],
        )

    def resolve(self, name: str) -> CapabilitySpec:
        capability = self._capabilities.get(name)
        if capability is None:
            raise KeyError(f"Capability not found: {name}")
        if not capability.enabled:
            raise RuntimeError(f"Capability is disabled: {name}")
        return capability

    def list_enabled(self) -> list[CapabilitySpec]:
        return [
            capability
            for capability in self._capabilities.values()
            if capability.enabled
        ]

    def list_names(self) -> list[str]:
        return [capability.name for capability in self.list_enabled()]


def register_default_capabilities(
    registry: CapabilityRegistry,
    tool_registry: Any,
    *,
    workflow_runner: Any = None,
) -> CapabilityRegistry:
    """Register paper Tools and the controlled paper-processing Workflow."""
    from .catalog import metadata_for_capability
    from .paper_download import PaperDownloadAdapter
    from .paper_glossary import PaperGlossaryAdapter
    from .paper_parse import PaperParseAdapter
    from .paper_search import PaperSearchAdapter
    from .paper_summary import PaperSummaryAdapter
    from .paper_translate import PaperTranslateAdapter
    from .paper_processing_workflow import PaperProcessingWorkflowAdapter

    adapters = (
        PaperSearchAdapter(tool_registry),
        PaperDownloadAdapter(tool_registry),
        PaperParseAdapter(tool_registry),
        PaperGlossaryAdapter(tool_registry),
        PaperTranslateAdapter(tool_registry),
        PaperSummaryAdapter(tool_registry),
    )
    for adapter in adapters:
        metadata = metadata_for_capability(adapter.name)
        registry.register(adapter, **metadata)
    workflow = PaperProcessingWorkflowAdapter(workflow_runner)
    registry.register(
        workflow,
        **metadata_for_capability(workflow.name),
    )
    return registry

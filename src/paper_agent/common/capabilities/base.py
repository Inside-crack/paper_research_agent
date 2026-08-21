from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..tools import ToolRegistry


CapabilityStatus = Literal["succeeded", "failed", "blocked"]


class ExecutionContext(BaseModel):
    """Runtime context supplied by the conversation application service."""

    model_config = ConfigDict(extra="forbid")

    session_id: Optional[str] = None
    task_id: Optional[str] = None
    selected_paper: Optional[dict[str, Any]] = None
    artifact_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityResult(BaseModel):
    """Stable result contract exposed by a Capability Adapter."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    status: CapabilityStatus
    data: Optional[dict[str, Any]] = None
    artifact_refs: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    next_actions: list[str] = Field(default_factory=list)

    @classmethod
    def succeeded(
        cls,
        data: dict[str, Any],
        *,
        artifact_refs: Optional[list[str]] = None,
        next_actions: Optional[list[str]] = None,
    ) -> "CapabilityResult":
        return cls(
            success=True,
            status="succeeded",
            data=data,
            artifact_refs=artifact_refs or [],
            next_actions=next_actions or [],
        )

    @classmethod
    def failed(
        cls,
        error: str,
        *,
        next_actions: Optional[list[str]] = None,
    ) -> "CapabilityResult":
        return cls(
            success=False,
            status="failed",
            error=error,
            next_actions=next_actions or [],
        )

    @classmethod
    def blocked(
        cls,
        error: str,
        *,
        next_actions: Optional[list[str]] = None,
    ) -> "CapabilityResult":
        return cls(
            success=False,
            status="blocked",
            error=error,
            next_actions=next_actions or [],
        )


class CapabilityAdapter(ABC):
    """Base contract for a business capability backed by one or more Tools."""

    name: str = ""

    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry

    @abstractmethod
    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        """Execute the capability without exposing raw ToolResult to callers."""

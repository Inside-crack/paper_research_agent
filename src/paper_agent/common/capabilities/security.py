from __future__ import annotations

from pathlib import PurePosixPath
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .catalog import CapabilityCatalog
from .decision_validator import (
    CapabilityDecisionValidationError,
    CapabilityDecisionValidator,
)
from .intent_schema import IntentDecision


class SecurityDecision(BaseModel):
    """Authorization result produced before a Capability is executed."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    requires_confirmation: bool = False
    reason: Optional[str] = None


class CapabilityExecutionSecurityPolicy:
    """Enforce the allowlist and execution boundary for routed decisions."""

    def __init__(
        self,
        catalog: CapabilityCatalog,
        *,
        allowed_capabilities: Optional[set[str]] = None,
    ):
        self.catalog = catalog
        self.validator = CapabilityDecisionValidator(catalog)
        self.allowed_capabilities = (
            set(catalog.list_names())
            if allowed_capabilities is None
            else set(allowed_capabilities)
        )

    def authorize(
        self,
        decision: IntentDecision,
        *,
        confirmed: bool = False,
    ) -> SecurityDecision:
        if not isinstance(decision, IntentDecision):
            raise TypeError("decision must be an IntentDecision")
        if not decision.matched or not decision.capability_name:
            return SecurityDecision(
                allowed=False,
                reason="Only a matched decision can be executed",
            )
        if decision.capability_name not in self.allowed_capabilities:
            return SecurityDecision(
                allowed=False,
                reason=f"Capability is outside the execution allowlist: "
                f"{decision.capability_name}",
            )

        try:
            entry = self.catalog.resolve(decision.capability_name)
            self.validator.validate(decision)
        except (KeyError, RuntimeError, CapabilityDecisionValidationError) as exc:
            return SecurityDecision(
                allowed=False,
                reason=str(exc),
            )

        path_error = self._path_argument_error(decision)
        if path_error:
            return SecurityDecision(allowed=False, reason=path_error)

        if entry.confirmation_required and not confirmed:
            return SecurityDecision(
                allowed=False,
                requires_confirmation=True,
                reason=f"Capability requires explicit confirmation: {entry.name}",
            )

        return SecurityDecision(allowed=True)

    @staticmethod
    def _path_argument_error(decision: IntentDecision) -> Optional[str]:
        for key in ("artifact_path", "workspace_path", "path"):
            value = decision.arguments.get(key)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                return f"Invalid path argument: {key}"
            if "\x00" in value or "\\" in value:
                return f"Unsafe path argument: {key}"
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts:
                return f"Path must be a task-relative safe path: {key}"
        return None

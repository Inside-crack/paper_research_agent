from __future__ import annotations

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .catalog import CapabilityCatalog
from .intent_schema import IntentDecision


class CapabilityDecisionValidationError(ValueError):
    """Raised when a matched decision is not executable by its Catalog entry."""


class CapabilityDecisionValidator:
    """Validate an IntentDecision against the allowlisted Capability Catalog."""

    def __init__(self, catalog: CapabilityCatalog):
        self.catalog = catalog

    def validate(self, decision: IntentDecision) -> IntentDecision:
        if not isinstance(decision, IntentDecision):
            raise TypeError("decision must be an IntentDecision")
        if not decision.matched:
            return decision
        if not decision.capability_name:
            raise CapabilityDecisionValidationError(
                "matched decision requires capability_name"
            )

        try:
            entry = self.catalog.resolve(decision.capability_name)
        except KeyError as exc:
            raise CapabilityDecisionValidationError(
                f"Capability is not allowlisted: {decision.capability_name}"
            ) from exc

        if decision.execution_kind != entry.execution_kind:
            raise CapabilityDecisionValidationError(
                f"Execution kind mismatch for {entry.name}: "
                f"expected {entry.execution_kind}, got {decision.execution_kind}"
            )
        if entry.allowed_intents and decision.intent not in entry.allowed_intents:
            raise CapabilityDecisionValidationError(
                f"Intent is not allowed for {entry.name}: {decision.intent}"
            )

        try:
            validator = Draft202012Validator(
                entry.input_schema,
                format_checker=FormatChecker(),
            )
            errors = sorted(
                validator.iter_errors(decision.arguments),
                key=lambda error: list(error.path),
            )
        except SchemaError as exc:
            raise CapabilityDecisionValidationError(
                f"Invalid input schema for {entry.name}"
            ) from exc

        if errors:
            error = errors[0]
            location = ".".join(str(part) for part in error.path) or "$"
            raise CapabilityDecisionValidationError(
                f"Invalid arguments for {entry.name} at {location}: "
                f"{error.message}"
            )

        return decision

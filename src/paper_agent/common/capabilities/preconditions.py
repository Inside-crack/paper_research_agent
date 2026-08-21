from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .catalog import CapabilityCatalog
from .context_projection import IntentContextProjection
from .decision_validator import (
    CapabilityDecisionValidationError,
    CapabilityDecisionValidator,
)
from .intent_schema import ContextReference, IntentDecision


class IntentResolution(BaseModel):
    """Normalized decision plus context updates, without executing a capability."""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    decision: IntentDecision
    normalized_arguments: dict[str, Any] = Field(default_factory=dict)
    context_updates: dict[str, Any] = Field(default_factory=dict)
    missing_arguments: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class IntentPreconditionResolver:
    """Resolve typed context references and evaluate dynamic prerequisites."""

    _TASK_BOUND_CAPABILITIES = {
        "paper_download",
        "paper_parse",
        "paper_glossary",
        "paper_translate",
        "paper_summary",
    }
    _ARTIFACT_BOUND_CAPABILITIES = {
        "paper_parse",
        "paper_glossary",
        "paper_translate",
        "paper_summary",
    }

    def __init__(self, catalog: CapabilityCatalog):
        self.catalog = catalog
        self.validator = CapabilityDecisionValidator(catalog)

    def resolve(
        self,
        decision: IntentDecision,
        projection: IntentContextProjection,
    ) -> IntentResolution:
        if not isinstance(decision, IntentDecision):
            raise TypeError("decision must be an IntentDecision")
        if not isinstance(projection, IntentContextProjection):
            raise TypeError("projection must be an IntentContextProjection")
        if not decision.matched:
            return IntentResolution(
                ready=False,
                decision=decision,
                normalized_arguments=dict(decision.arguments),
            )

        normalized_arguments = dict(decision.arguments)
        context_updates: dict[str, Any] = {}
        errors: list[str] = []

        for reference in decision.references:
            try:
                self._resolve_reference(
                    reference,
                    projection,
                    normalized_arguments,
                    context_updates,
                )
            except ValueError as exc:
                errors.append(str(exc))

        capability_name = decision.capability_name or ""
        missing_arguments = self._missing_arguments(
            capability_name,
            normalized_arguments,
            projection,
            context_updates,
        )

        normalized_decision = decision.model_copy(
            update={"arguments": normalized_arguments}
        )
        if not errors:
            try:
                self.validator.validate(normalized_decision)
            except CapabilityDecisionValidationError as exc:
                errors.append(str(exc))

        if errors or missing_arguments:
            reason = errors[0] if errors else "Required context or arguments are missing"
            return IntentResolution(
                ready=False,
                decision=self._blocked_decision(
                    normalized_decision,
                    reason=reason,
                    missing_arguments=missing_arguments,
                ),
                normalized_arguments=normalized_arguments,
                context_updates=context_updates,
                missing_arguments=missing_arguments,
                errors=errors,
            )

        return IntentResolution(
            ready=True,
            decision=normalized_decision,
            normalized_arguments=normalized_arguments,
            context_updates=context_updates,
        )

    def _resolve_reference(
        self,
        reference: ContextReference,
        projection: IntentContextProjection,
        arguments: dict[str, Any],
        context_updates: dict[str, Any],
    ) -> None:
        if reference.type == "candidate_index":
            if isinstance(reference.value, bool) or not isinstance(reference.value, int):
                raise ValueError("candidate_index reference must be an integer")
            index = reference.value
            if index < 1 or index > len(projection.candidate_papers):
                raise ValueError(f"candidate_index is out of range: {index}")
            context_updates["selected_paper"] = projection.candidate_papers[index - 1]
            return

        if reference.type == "selected_paper":
            selected = self._find_candidate(projection, reference.value)
            if selected is None:
                raise ValueError(
                    f"selected_paper reference was not found: {reference.value}"
                )
            context_updates["selected_paper"] = selected
            return

        if reference.type == "artifact_ref":
            if not isinstance(reference.value, str):
                raise ValueError("artifact_ref reference must be a string")
            if reference.value not in projection.artifact_refs:
                raise ValueError(
                    f"artifact_ref is not present in projected context: {reference.value}"
                )
            arguments.setdefault("artifact_path", reference.value)
            context_updates.setdefault("artifact_refs", []).append(reference.value)
            return

        if reference.type == "task_id":
            if reference.value != projection.active_task_id:
                raise ValueError("task_id reference does not match active task")
            return

        if reference.type == "selected_section":
            if not isinstance(reference.value, str) or not reference.value.strip():
                raise ValueError("selected_section reference must be non-empty")
            if reference.value not in projection.selected_sections:
                raise ValueError(
                    f"selected_section is not available in projected context: "
                    f"{reference.value}"
                )
            selected_sections = context_updates.setdefault("selected_sections", [])
            if reference.value not in selected_sections:
                selected_sections.append(reference.value)
            return

        raise ValueError(f"Unsupported context reference type: {reference.type}")

    @staticmethod
    def _find_candidate(
        projection: IntentContextProjection,
        value: str | int,
    ) -> Optional[dict[str, Any]]:
        if not isinstance(value, str) or not value.strip():
            return None
        for candidate in projection.candidate_papers:
            if value in {
                candidate.get("id"),
                candidate.get("arxiv_id"),
                candidate.get("doi"),
            }:
                return candidate
        return None

    def _missing_arguments(
        self,
        capability_name: str,
        arguments: dict[str, Any],
        projection: IntentContextProjection,
        context_updates: dict[str, Any],
    ) -> list[str]:
        missing: list[str] = []
        if (
            capability_name in self._TASK_BOUND_CAPABILITIES
            and not projection.active_task_id
        ):
            missing.append("task_id")

        if capability_name == "paper_download":
            has_selected = bool(
                projection.selected_paper
                or context_updates.get("selected_paper")
            )
            has_direct_paper = bool(arguments.get("arxiv_id") or arguments.get("pdf_url"))
            if not has_selected and not has_direct_paper:
                missing.append("selected_paper")

        if capability_name in self._ARTIFACT_BOUND_CAPABILITIES:
            artifact_path = arguments.get("artifact_path")
            if not isinstance(artifact_path, str) or not artifact_path.strip():
                missing.append("artifact_path")
            elif not self._is_safe_relative_ref(artifact_path):
                missing.append("artifact_path")

        if capability_name == "paper_glossary" and "terms" not in arguments:
            missing.append("terms")
        if capability_name == "paper_translate" and "translations" not in arguments:
            missing.append("translations")
        if capability_name == "paper_summary" and "summary" not in arguments:
            missing.append("summary")

        return list(dict.fromkeys(missing))

    @staticmethod
    def _is_safe_relative_ref(value: str) -> bool:
        path = Path(value.strip())
        return not path.is_absolute() and "\\" not in value and ".." not in path.parts

    @staticmethod
    def _blocked_decision(
        decision: IntentDecision,
        *,
        reason: str,
        missing_arguments: list[str],
    ) -> IntentDecision:
        return decision.model_copy(
            update={
                "matched": False,
                "source": "fallback",
                "missing_arguments": missing_arguments,
                "reason": reason,
                "clarification_question": "请补充执行该操作所需的上下文或参数。",
            }
        )

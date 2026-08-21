from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ...common.models.paper_artifact import PaperArtifact, TermEntry
from ...common.persistence import StatePersistence
from ...common.tools.base import BaseTool, ToolResult


class PaperGlossaryTool(BaseTool):
    name = "paper_glossary"
    description = (
        "Validate and persist bilingual glossary candidates for a parsed paper. "
        "Parameters: task_id, artifact_path, terms (list of source_term, target_term, "
        "context, confidence). Source terms must occur in the paper original text."
    )

    def __init__(self, persistence: Optional[StatePersistence] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.persistence = persistence or StatePersistence()

    async def _execute(self, **kwargs: Any) -> ToolResult:
        task_id = kwargs.get("task_id")
        artifact_path = kwargs.get("artifact_path")
        terms = kwargs.get("terms")
        if not task_id or not artifact_path:
            return ToolResult.fail(error="Missing required parameter: task_id or artifact_path")
        if terms is None:
            return ToolResult.fail(error="Missing required parameter: terms")
        if not isinstance(terms, list):
            return ToolResult.fail(error="terms must be a list")

        relative_path = Path(artifact_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return ToolResult.fail(error=f"Invalid artifact path: {artifact_path}")

        artifact_file = self.persistence.base_dir / task_id / relative_path
        if not artifact_file.exists():
            return ToolResult.fail(error=f"Paper artifact not found: {artifact_path}")
        data = self.persistence._load_json(artifact_file)
        if not data:
            return ToolResult.fail(error=f"Paper artifact is invalid: {artifact_path}")

        try:
            artifact = PaperArtifact(**data)
        except Exception as exc:
            return ToolResult.fail(error=f"Paper artifact validation failed: {exc}")
        if not artifact.full_text_original.strip():
            return ToolResult.fail(error="Paper artifact has no original text; P11 parsing is required")

        validated: dict[str, TermEntry] = {}
        source_text = artifact.full_text_original.casefold()
        for index, raw_term in enumerate(terms):
            if not isinstance(raw_term, dict):
                return ToolResult.fail(error=f"Invalid terminology candidate at index {index}")

            source_term = raw_term.get("source_term")
            target_term = raw_term.get("target_term")
            context = raw_term.get("context", "")
            confidence = raw_term.get("confidence", 1.0)
            if not isinstance(source_term, str) or not source_term.strip():
                return ToolResult.fail(error=f"Missing source_term at index {index}")
            if not isinstance(target_term, str) or not target_term.strip():
                return ToolResult.fail(error=f"Missing target_term for {source_term}")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                return ToolResult.fail(error=f"Invalid confidence for {source_term}")
            if not 0.0 <= float(confidence) <= 1.0:
                return ToolResult.fail(error=f"Invalid confidence for {source_term}: must be between 0 and 1")
            if not isinstance(context, str):
                return ToolResult.fail(error=f"Invalid context for {source_term}")

            normalized_source = source_term.strip()
            key = normalized_source.casefold()
            if key not in source_text:
                return ToolResult.fail(
                    error=f"Source term has no evidence in paper text: {normalized_source}"
                )

            candidate = TermEntry(
                source_term=normalized_source,
                target_term=target_term.strip(),
                context=context.strip(),
                confidence=float(confidence),
            )
            previous = validated.get(key)
            if previous is None or candidate.confidence > previous.confidence:
                validated[key] = candidate

        glossary = sorted(validated.values(), key=lambda term: term.source_term.casefold())
        artifact.glossary = glossary
        try:
            await self.persistence.update_paper_artifact(task_id, artifact_path, artifact)
        except Exception as exc:
            return ToolResult.fail(error=f"Failed to persist glossary: {exc}")

        return ToolResult.ok(
            data={
                "paper_artifact_id": artifact.id,
                "artifact_path": artifact_path,
                "term_count": len(glossary),
                "terms": [term.model_dump(mode="json") for term in glossary],
            }
        )

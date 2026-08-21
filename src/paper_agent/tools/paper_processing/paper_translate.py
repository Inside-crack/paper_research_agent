from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from ...common.models.paper_artifact import PaperArtifact, PaperSection
from ...common.persistence import StatePersistence
from ...common.tools.base import BaseTool, ToolResult


_NUMBER = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_CITATION = re.compile(r"\[[^\]\n]+\]")
_FORMULA_MARKER = re.compile(r"=|\b(?:equation|formula|eq\.?)\b|公式|[∑∫√∂]", re.IGNORECASE)


class PaperTranslateTool(BaseTool):
    name = "paper_translate"
    description = (
        "Validate and persist section-by-section paper translations. "
        "Parameters: task_id, artifact_path, translations (list of section_id and "
        "translated_text). Numbers, citations, formula markers and glossary terms must be preserved."
    )

    def __init__(self, persistence: Optional[StatePersistence] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.persistence = persistence or StatePersistence()

    async def _execute(self, **kwargs: Any) -> ToolResult:
        task_id = kwargs.get("task_id")
        artifact_path = kwargs.get("artifact_path")
        translations = kwargs.get("translations")
        if not task_id or not artifact_path:
            return ToolResult.fail(error="Missing required parameter: task_id or artifact_path")
        if translations is None:
            return ToolResult.fail(error="Missing required parameter: translations")
        if not isinstance(translations, list):
            return ToolResult.fail(error="translations must be a list")

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
        if not artifact.sections or not artifact.full_text_original.strip():
            return ToolResult.fail(error="Paper artifact has no parsed sections; P11 parsing is required")

        translation_map: dict[str, str] = {}
        for index, raw_translation in enumerate(translations):
            if not isinstance(raw_translation, dict):
                return ToolResult.fail(f"Invalid translation at index {index}")
            section_id = raw_translation.get("section_id")
            translated_text = raw_translation.get("translated_text")
            if not isinstance(section_id, str) or not section_id.strip():
                return ToolResult.fail(error=f"Missing section_id at index {index}")
            if section_id not in {section.section_id for section in artifact.sections}:
                return ToolResult.fail(error=f"Unknown section: {section_id}")
            if section_id in translation_map:
                return ToolResult.fail(error=f"Duplicate section translation: {section_id}")
            if not isinstance(translated_text, str) or not translated_text.strip():
                return ToolResult.fail(error=f"Empty translation for section: {section_id}")
            translation_map[section_id] = translated_text.strip()

        expected_ids = {section.section_id for section in artifact.sections}
        missing_ids = expected_ids - translation_map.keys()
        if missing_ids:
            return ToolResult.fail(error=f"Missing section translations: {sorted(missing_ids)}")

        for section in artifact.sections:
            error = self._validate_protected_content(section, translation_map[section.section_id], artifact)
            if error:
                return ToolResult.fail(error=error)

        translated_sections: list[PaperSection] = []
        for section in artifact.sections:
            translated_section = section.model_copy(
                update={"translated_text": translation_map[section.section_id]}
            )
            translated_sections.append(translated_section)
        artifact.sections = translated_sections
        artifact.full_text_translated = "\n\n".join(
            section.translated_text for section in translated_sections
        )

        try:
            await self.persistence.update_paper_artifact(task_id, artifact_path, artifact)
        except Exception as exc:
            return ToolResult.fail(error=f"Failed to persist translation: {exc}")

        return ToolResult.ok(
            data={
                "paper_artifact_id": artifact.id,
                "artifact_path": artifact_path,
                "section_count": len(translated_sections),
                "translated_text_length": len(artifact.full_text_translated),
            }
        )

    @staticmethod
    def _validate_protected_content(
        section: PaperSection,
        translated_text: str,
        artifact: PaperArtifact,
    ) -> Optional[str]:
        if section.has_formulas and not _FORMULA_MARKER.search(translated_text):
            return f"Formula marker missing in {section.section_id}"

        original_citations = Counter(_CITATION.findall(section.original_text))
        translated_citations = Counter(_CITATION.findall(translated_text))
        for token, count in original_citations.items():
            if translated_citations[token] < count:
                return f"Protected citation token missing in {section.section_id}: {token}"

        original_without_citations = _CITATION.sub("", section.original_text)
        translated_without_citations = _CITATION.sub("", translated_text)
        original_numbers = Counter(_NUMBER.findall(original_without_citations))
        translated_numbers = Counter(_NUMBER.findall(translated_without_citations))
        for token, count in original_numbers.items():
            if translated_numbers[token] < count:
                return f"Protected numeric token missing in {section.section_id}: {token}"

        original_casefold = section.original_text.casefold()
        translated_casefold = translated_text.casefold()
        for term in artifact.glossary:
            if term.source_term.casefold() in original_casefold:
                if term.target_term.casefold() not in translated_casefold:
                    return (
                        f"Glossary target missing in {section.section_id}: "
                        f"{term.source_term} -> {term.target_term}"
                    )
        return None

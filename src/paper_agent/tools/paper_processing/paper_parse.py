from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import pdfplumber

from ...common.models.paper_artifact import PaperArtifact, PaperSection
from ...common.persistence import StatePersistence
from ...common.tools.base import BaseTool, ToolResult


_NUMBERED_HEADING = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+)*)[\s.)]+(?P<title>[A-Za-z][^.!?]{2,100})\s*$"
)
_NAMED_HEADING = re.compile(
    r"^\s*(?P<title>abstract|introduction|background|related work|"
    r"method(?:ology)?|approach|experiments?|results?|discussion|"
    r"conclusion(?:s)?|limitations?|references|appendix)\s*$",
    re.IGNORECASE,
)
_FORMULA_MARKERS = re.compile(r"\b(?:equation|formula|eq\.?)\b|[∑∫√∂]", re.IGNORECASE)
_TABLE_MARKERS = re.compile(r"\btable\s*\d*\b", re.IGNORECASE)
_FIGURE_MARKERS = re.compile(r"\b(?:figure|fig\.)\s*\d*\b", re.IGNORECASE)
_CITATION = re.compile(r"\[((?:\d+\s*,\s*)*\d+)\]")


class PaperParseTool(BaseTool):
    name = "paper_parse"
    description = (
        "Parse a persisted paper PDF into structured sections. "
        "Parameters: task_id (required), artifact_path (required, relative JSON artifact path)."
    )

    def __init__(self, persistence: Optional[StatePersistence] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.persistence = persistence or StatePersistence()

    async def _execute(self, **kwargs: Any) -> ToolResult:
        task_id = kwargs.get("task_id")
        artifact_path = kwargs.get("artifact_path")
        if not task_id or not artifact_path:
            return ToolResult.fail(error="Missing required parameter: task_id or artifact_path")

        relative_artifact = Path(artifact_path)
        if relative_artifact.is_absolute() or ".." in relative_artifact.parts:
            return ToolResult.fail(error=f"Invalid artifact path: {artifact_path}")

        task_dir = self.persistence.base_dir / task_id
        json_path = task_dir / relative_artifact
        if not json_path.exists():
            return ToolResult.fail(error=f"Paper artifact not found: {artifact_path}")

        data = self.persistence._load_json(json_path)
        if not data:
            return ToolResult.fail(error=f"Paper artifact is invalid: {artifact_path}")

        try:
            artifact = PaperArtifact(**data)
        except Exception as exc:
            return ToolResult.fail(error=f"Paper artifact validation failed: {exc}")

        if not artifact.pdf_path:
            return ToolResult.fail(error="Paper artifact does not contain pdf_path")
        pdf_relative = Path(artifact.pdf_path)
        if pdf_relative.is_absolute() or ".." in pdf_relative.parts:
            return ToolResult.fail(error=f"Invalid PDF path: {artifact.pdf_path}")
        pdf_path = task_dir / pdf_relative
        if not pdf_path.exists():
            return ToolResult.fail(error=f"Paper PDF not found: {artifact.pdf_path}")

        page_texts: list[str] = []
        parsing_errors: list[str] = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                page_count = len(pdf.pages)
                for page_number, page in enumerate(pdf.pages, start=1):
                    try:
                        text = page.extract_text() or ""
                        if text.strip():
                            page_texts.append(text.strip())
                    except Exception as exc:
                        parsing_errors.append(f"page {page_number}: {exc}")
        except Exception as exc:
            return ToolResult.fail(error=f"Failed to parse PDF: {exc}")

        full_text = "\n\n".join(page_texts)
        sections = self._build_sections(full_text)
        artifact.full_text_original = full_text
        artifact.sections = sections
        artifact.parsing_errors = parsing_errors

        try:
            await self.persistence.update_paper_artifact(task_id, artifact_path, artifact)
        except Exception as exc:
            return ToolResult.fail(error=f"Failed to persist parsed artifact: {exc}")

        return ToolResult.ok(
            data={
                "paper_artifact_id": artifact.id,
                "artifact_path": artifact_path,
                "page_count": page_count,
                "section_count": len(sections),
                "text_length": len(full_text),
                "parsing_errors": parsing_errors,
            }
        )

    @classmethod
    def _build_sections(cls, full_text: str) -> list[PaperSection]:
        lines = [line.strip() for line in full_text.splitlines() if line.strip()]
        headings: list[tuple[int, str, int]] = []
        for index, line in enumerate(lines):
            numbered = _NUMBERED_HEADING.match(line)
            named = _NAMED_HEADING.match(line)
            if numbered:
                number = numbered.group("number")
                headings.append((index, numbered.group("title").strip(), number.count(".") + 1))
            elif named:
                headings.append((index, named.group("title").strip().title(), 1))

        if not headings:
            return [cls._make_section("section_1", "Document", 1, full_text)]

        sections: list[PaperSection] = []
        for position, (line_index, title, level) in enumerate(headings):
            next_index = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
            content = "\n".join(lines[line_index:next_index]).strip()
            sections.append(cls._make_section(f"section_{position + 1}", title, level, content))
        return sections

    @staticmethod
    def _make_section(section_id: str, title: str, level: int, text: str) -> PaperSection:
        references: list[str] = []
        for group in _CITATION.findall(text):
            for reference in re.findall(r"\d+", group):
                if reference not in references:
                    references.append(reference)
        return PaperSection(
            section_id=section_id,
            title=title,
            level=level,
            original_text=text,
            has_formulas=bool(_FORMULA_MARKERS.search(text)),
            has_tables=bool(_TABLE_MARKERS.search(text)),
            has_figures=bool(_FIGURE_MARKERS.search(text)),
            references=references,
        )

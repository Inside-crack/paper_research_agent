from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ...common.models.paper_artifact import PaperArtifact
from ...common.persistence import StatePersistence
from ...common.tools.base import BaseTool, ToolResult


_LIST_FIELDS = ("research_questions", "contributions", "conclusions", "limitations")
_EVIDENCE_FIELDS = _LIST_FIELDS + ("methodology_summary",)


class PaperSummaryTool(BaseTool):
    name = "paper_summary"
    description = (
        "Validate and persist an evidence-linked paper summary. Parameters: task_id, "
        "artifact_path, summary with research_questions, methodology_summary, contributions, "
        "conclusions, limitations and evidence section IDs."
    )

    def __init__(self, persistence: Optional[StatePersistence] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.persistence = persistence or StatePersistence()

    async def _execute(self, **kwargs: Any) -> ToolResult:
        task_id = kwargs.get("task_id")
        artifact_path = kwargs.get("artifact_path")
        summary = kwargs.get("summary")
        if not task_id or not artifact_path:
            return ToolResult.fail(error="Missing required parameter: task_id or artifact_path")
        if not isinstance(summary, dict):
            return ToolResult.fail(error="summary must be an object")

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

        section_ids = {section.section_id for section in artifact.sections}
        validated_lists: dict[str, list[str]] = {}
        for field in _LIST_FIELDS:
            value = summary.get(field, [])
            if not isinstance(value, list):
                return ToolResult.fail(error=f"Summary field must be a list: {field}")
            items: list[str] = []
            for index, item in enumerate(value):
                if not isinstance(item, str) or not item.strip():
                    return ToolResult.fail(error=f"Summary field contains empty item: {field}[{index}]")
                items.append(item.strip())
            validated_lists[field] = items

        methodology = summary.get("methodology_summary")
        if not isinstance(methodology, str) or not methodology.strip():
            return ToolResult.fail(error="methodology_summary must be a non-empty string")

        evidence = summary.get("evidence")
        if not isinstance(evidence, dict):
            return ToolResult.fail(error="summary.evidence must be an object")
        validated_evidence: dict[str, list[str]] = {}
        for field in _EVIDENCE_FIELDS:
            has_content = bool(methodology.strip()) if field == "methodology_summary" else bool(validated_lists[field])
            field_evidence = evidence.get(field, [])
            if not has_content:
                continue
            if not isinstance(field_evidence, list) or not field_evidence:
                return ToolResult.fail(error=f"Missing evidence for summary field: {field}")
            normalized_ids: list[str] = []
            for section_id in field_evidence:
                if not isinstance(section_id, str) or section_id not in section_ids:
                    return ToolResult.fail(error=f"Unknown evidence section for {field}: {section_id}")
                if section_id not in normalized_ids:
                    normalized_ids.append(section_id)
            validated_evidence[field] = normalized_ids

        artifact.research_questions = validated_lists["research_questions"]
        artifact.methodology_summary = methodology.strip()
        artifact.contributions = validated_lists["contributions"]
        artifact.conclusions = validated_lists["conclusions"]
        artifact.limitations = validated_lists["limitations"]
        artifact.summary_evidence = validated_evidence

        try:
            await self.persistence.update_paper_artifact(task_id, artifact_path, artifact)
        except Exception as exc:
            return ToolResult.fail(error=f"Failed to persist summary: {exc}")

        return ToolResult.ok(
            data={
                "paper_artifact_id": artifact.id,
                "artifact_path": artifact_path,
                "evidence_categories": len(validated_evidence),
                "summary_fields": list(_EVIDENCE_FIELDS),
            }
        )

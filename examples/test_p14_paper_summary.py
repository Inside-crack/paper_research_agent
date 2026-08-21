import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models.paper_artifact import PaperArtifact, PaperSection
from paper_agent.common.persistence import StatePersistence
from paper_agent.tools.paper_processing.paper_summary import PaperSummaryTool


def _make_artifact(tmp_path, parsed=True):
    persistence = StatePersistence(tmp_path / "artifacts")
    task_id = "task-p14"
    artifact_dir = persistence.base_dir / task_id / "papers"
    artifact_dir.mkdir(parents=True)
    sections = [
        PaperSection(
            section_id="section_1",
            title="Introduction",
            level=1,
            original_text="This paper studies tool use and proposes a method.",
        ),
        PaperSection(
            section_id="section_2",
            title="Results",
            level=1,
            original_text="The method improves accuracy in experiments.",
        ),
    ] if parsed else []
    artifact = PaperArtifact(
        id="artifact-p14",
        research_spec_id=task_id,
        candidate_id="paper-v1",
        arxiv_id="1706.03762v1",
        title="Test Paper",
        pdf_path="papers/paper-v1.pdf",
        sections=sections,
        full_text_original="\n\n".join(section.original_text for section in sections),
    )
    artifact_path = artifact_dir / "paper-v1.json"
    artifact_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    return persistence, task_id, "papers/paper-v1.json"


def _valid_summary():
    return {
        "research_questions": ["How can tool use be improved?"],
        "methodology_summary": "The paper proposes a method and evaluates it experimentally.",
        "contributions": ["A method for improved tool use."],
        "conclusions": ["The method improves accuracy."],
        "limitations": ["The experiments cover a limited setting."],
        "evidence": {
            "research_questions": ["section_1"],
            "methodology_summary": ["section_1"],
            "contributions": ["section_1"],
            "conclusions": ["section_2"],
            "limitations": ["section_2"],
        },
    }


def test_valid_summary_with_evidence_is_persisted(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    result = asyncio.run(
        PaperSummaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, summary=_valid_summary()
        )
    )

    assert result.success is True
    assert result.data["evidence_categories"] == 5
    artifact = json.loads((persistence.base_dir / task_id / artifact_path).read_text())
    assert artifact["methodology_summary"].startswith("The paper proposes")
    assert artifact["summary_evidence"]["conclusions"] == ["section_2"]


def test_empty_optional_lists_are_persisted_without_invention(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    summary = _valid_summary()
    summary["contributions"] = []
    summary["limitations"] = []
    summary["evidence"].pop("contributions")
    summary["evidence"].pop("limitations")
    result = asyncio.run(
        PaperSummaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, summary=summary
        )
    )

    assert result.success is True
    artifact = json.loads((persistence.base_dir / task_id / artifact_path).read_text())
    assert artifact["contributions"] == []
    assert artifact["limitations"] == []


def test_unknown_evidence_section_is_rejected_without_update(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    original = (persistence.base_dir / task_id / artifact_path).read_text()
    summary = _valid_summary()
    summary["evidence"]["conclusions"] = ["section_unknown"]
    result = asyncio.run(
        PaperSummaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, summary=summary
        )
    )

    assert result.success is False
    assert "section_unknown" in result.error
    assert (persistence.base_dir / task_id / artifact_path).read_text() == original


def test_invalid_summary_field_is_rejected(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    for invalid in (
        {**_valid_summary(), "methodology_summary": ""},
        {**_valid_summary(), "conclusions": [""]},
        {**_valid_summary(), "research_questions": "not a list"},
    ):
        result = asyncio.run(
            PaperSummaryTool(persistence=persistence)._execute(
                task_id=task_id, artifact_path=artifact_path, summary=invalid
            )
        )
        assert result.success is False


def test_unparsed_artifact_is_rejected(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path, parsed=False)
    result = asyncio.run(
        PaperSummaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, summary=_valid_summary()
        )
    )

    assert result.success is False
    assert "P11" in result.error


def test_persistence_failure_is_returned(tmp_path):
    persistence, task_id, artifact_path = _make_artifact(tmp_path)
    persistence.update_paper_artifact = AsyncMock(side_effect=RuntimeError("manifest failed"))
    result = asyncio.run(
        PaperSummaryTool(persistence=persistence)._execute(
            task_id=task_id, artifact_path=artifact_path, summary=_valid_summary()
        )
    )

    assert result.success is False
    assert "manifest failed" in result.error


def test_paper_summary_is_registered():
    from paper_agent.tools import get_default_registry

    assert "paper_summary" in get_default_registry().list_tools()


def main():
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()

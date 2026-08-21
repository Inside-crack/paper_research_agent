import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models.paper_artifact import PaperArtifact
from paper_agent.common.persistence import StatePersistence
from paper_agent.tools.paper_processing.paper_parse import PaperParseTool


class FakePage:
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error

    def extract_text(self):
        if self.error:
            raise self.error
        return self.text


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_task(tmp_path):
    persistence = StatePersistence(tmp_path / "artifacts")
    task_id = "task-p11"
    task_dir = persistence.base_dir / task_id
    papers_dir = task_dir / "papers"
    papers_dir.mkdir(parents=True)
    pdf_path = papers_dir / "paper-v1.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    artifact = PaperArtifact(
        id="paper-artifact-1",
        research_spec_id=task_id,
        candidate_id="paper-v1",
        arxiv_id="1706.03762v1",
        title="Test Paper",
        pdf_path="papers/paper-v1.pdf",
        pdf_source="arxiv",
    )
    (papers_dir / "paper-v1.json").write_text(
        artifact.model_dump_json(indent=2), encoding="utf-8"
    )
    return persistence, task_id, "papers/paper-v1.json"


def test_valid_pdf_extracts_sections_and_evidence(tmp_path):
    persistence, task_id, artifact_path = _make_task(tmp_path)
    pages = [
        FakePage(
            "1 Introduction\n"
            "We study the problem. Equation (1) describes the model.\n"
            "Figure 1 shows the result. Table 1 reports scores. [1, 2]"
        ),
        FakePage("2 Method\nThe method is described here.\n2.1 Training\nTraining details."),
    ]
    tool = PaperParseTool(persistence=persistence)

    with patch("paper_agent.tools.paper_processing.paper_parse.pdfplumber.open", return_value=FakePdf(pages)):
        result = asyncio.run(tool._execute(task_id=task_id, artifact_path=artifact_path))

    assert result.success is True
    assert result.data["page_count"] == 2
    assert result.data["section_count"] == 3
    assert result.data["parsing_errors"] == []
    updated = json.loads(
        (persistence.base_dir / task_id / artifact_path).read_text(encoding="utf-8")
    )
    assert updated["full_text_original"].startswith("1 Introduction")
    assert [s["title"] for s in updated["sections"]] == ["Introduction", "Method", "Training"]
    assert updated["sections"][0]["has_formulas"] is True
    assert updated["sections"][0]["has_figures"] is True
    assert updated["sections"][0]["has_tables"] is True
    assert updated["sections"][0]["references"] == ["1", "2"]


def test_unrecognized_headings_fall_back_to_document_section(tmp_path):
    persistence, task_id, artifact_path = _make_task(tmp_path)
    tool = PaperParseTool(persistence=persistence)

    with patch(
        "paper_agent.tools.paper_processing.paper_parse.pdfplumber.open",
        return_value=FakePdf([FakePage("plain text without a heading\nmore text")]),
    ):
        result = asyncio.run(tool._execute(task_id=task_id, artifact_path=artifact_path))

    assert result.success is True
    assert result.data["section_count"] == 1
    artifact = json.loads((persistence.base_dir / task_id / artifact_path).read_text())
    assert artifact["sections"][0]["title"] == "Document"
    assert artifact["sections"][0]["original_text"].startswith("plain text")


def test_page_error_is_recorded_while_other_pages_are_retained(tmp_path):
    persistence, task_id, artifact_path = _make_task(tmp_path)
    tool = PaperParseTool(persistence=persistence)
    pages = [FakePage("1 Introduction\nReadable text"), FakePage(error=ValueError("bad page"))]

    with patch("paper_agent.tools.paper_processing.paper_parse.pdfplumber.open", return_value=FakePdf(pages)):
        result = asyncio.run(tool._execute(task_id=task_id, artifact_path=artifact_path))

    assert result.success is True
    assert result.data["parsing_errors"] == ["page 2: bad page"]
    artifact = json.loads((persistence.base_dir / task_id / artifact_path).read_text())
    assert "Readable text" in artifact["full_text_original"]
    assert artifact["parsing_errors"] == ["page 2: bad page"]


def test_invalid_inputs_are_rejected_without_opening_pdf(tmp_path):
    persistence, task_id, artifact_path = _make_task(tmp_path)
    tool = PaperParseTool(persistence=persistence)

    with patch("paper_agent.tools.paper_processing.paper_parse.pdfplumber.open") as pdf_open:
        missing = asyncio.run(tool._execute(task_id=task_id))
        traversal = asyncio.run(tool._execute(task_id=task_id, artifact_path="../outside.json"))
        absent = asyncio.run(tool._execute(task_id=task_id, artifact_path="papers/missing.json"))

    assert missing.success is False
    assert "artifact_path" in missing.error
    assert traversal.success is False
    assert "Invalid artifact path" in traversal.error
    assert absent.success is False
    assert "not found" in absent.error
    pdf_open.assert_not_called()


def test_persistence_failure_is_returned(tmp_path):
    persistence, task_id, artifact_path = _make_task(tmp_path)
    persistence.update_paper_artifact = MagicMock(side_effect=RuntimeError("manifest failed"))
    tool = PaperParseTool(persistence=persistence)

    with patch(
        "paper_agent.tools.paper_processing.paper_parse.pdfplumber.open",
        return_value=FakePdf([FakePage("1 Introduction\nReadable text")]),
    ):
        result = asyncio.run(tool._execute(task_id=task_id, artifact_path=artifact_path))

    assert result.success is False
    assert "manifest failed" in result.error


def test_paper_parse_is_registered():
    from paper_agent.tools import get_default_registry

    assert "paper_parse" in get_default_registry().list_tools()


def main():
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()

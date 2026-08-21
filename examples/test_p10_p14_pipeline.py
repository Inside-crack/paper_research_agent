"""Offline end-to-end coverage for the P10-P14 paper research pipeline."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.persistence import StatePersistence
from paper_agent.tools.paper_processing.paper_download import PaperDownloadTool
from paper_agent.tools.paper_processing.paper_glossary import PaperGlossaryTool
from paper_agent.tools.paper_processing.paper_parse import PaperParseTool
from paper_agent.tools.paper_processing.paper_summary import PaperSummaryTool
from paper_agent.tools.paper_processing.paper_translate import PaperTranslateTool
from paper_agent.common.models.research_spec import ResearchSpec


PDF_BYTES = b"%PDF-1.7\noffline fixture\n%%EOF"
ARXIV_ID = "1706.03762v1"


class FakeResponse:
    content = PDF_BYTES
    headers = {"content-type": "application/pdf"}
    status_code = 200

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        return FakeResponse()


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class FakePdf:
    def __init__(self):
        self.pages = [
            FakePage(
                "1 Introduction\n"
                "This paper studies chain-of-thought tool use. Equation (1): x = 2. See [1]."
            ),
            FakePage(
                "2 Results\n"
                "The method reaches 95.5% accuracy on the benchmark [2]."
            ),
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _run(coro):
    return asyncio.run(coro)


def _create_task(tmp_path):
    persistence = StatePersistence(tmp_path / "artifacts")
    spec = ResearchSpec(id="e2e-p10-p14", user_query="offline paper pipeline")
    _run(persistence.save_research_spec(spec))
    _run(persistence.create_task_manifest(spec))
    return persistence, spec.id


def _download(persistence, task_id):
    candidate = {
        "arxiv_id": ARXIV_ID,
        "title": "Offline Paper Pipeline",
        "authors": ["Test Author"],
        "pdf_url": f"https://arxiv.org/pdf/{ARXIV_ID}",
        "published_date": "2017-06-12",
        "version": "1",
        "source": "arxiv",
    }
    with patch(
        "paper_agent.tools.paper_processing.paper_download.httpx.AsyncClient",
        return_value=FakeAsyncClient(),
    ):
        return _run(
            PaperDownloadTool(persistence=persistence)._execute(
                task_id=task_id, paper=candidate
            )
        )


def _parse(persistence, task_id, artifact_path):
    with patch(
        "paper_agent.tools.paper_processing.paper_parse.pdfplumber.open",
        return_value=FakePdf(),
    ):
        return _run(
            PaperParseTool(persistence=persistence)._execute(
                task_id=task_id, artifact_path=artifact_path
            )
        )


def _glossary(persistence, task_id, artifact_path):
    return _run(
        PaperGlossaryTool(persistence=persistence)._execute(
            task_id=task_id,
            artifact_path=artifact_path,
            terms=[
                {
                    "source_term": "chain-of-thought",
                    "target_term": "思维链",
                    "context": "chain-of-thought tool use",
                    "confidence": 0.95,
                },
                {
                    "source_term": "tool use",
                    "target_term": "工具使用",
                    "context": "chain-of-thought tool use",
                    "confidence": 0.9,
                },
            ],
        )
    )


def _translate(persistence, task_id, artifact_path):
    return _run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id,
            artifact_path=artifact_path,
            translations=[
                {
                    "section_id": "section_1",
                    "translated_text": "1 引言\n本文采用思维链工具使用。公式 (1)：x = 2。参见 [1]。Transformer模型。",
                },
                {
                    "section_id": "section_2",
                    "translated_text": "2 结果\n该方法在基准 [2] 上达到 95.5% 的准确率。",
                },
            ],
        )
    )


def _summary(persistence, task_id, artifact_path):
    return _run(
        PaperSummaryTool(persistence=persistence)._execute(
            task_id=task_id,
            artifact_path=artifact_path,
            summary={
                "research_questions": ["如何提升工具使用效果？"],
                "methodology_summary": "论文提出方法并在基准数据集上进行实验。",
                "contributions": ["提出一个工具使用方法。"],
                "conclusions": ["方法达到 95.5% 准确率。"],
                "limitations": [],
                "evidence": {
                    "research_questions": ["section_1"],
                    "methodology_summary": ["section_1", "section_2"],
                    "contributions": ["section_1"],
                    "conclusions": ["section_2"],
                },
            },
        )
    )


def test_p10_to_p14_offline_pipeline(tmp_path):
    persistence, task_id = _create_task(tmp_path)

    download = _download(persistence, task_id)
    assert download.success is True
    artifact_path = download.data["artifact_path"]

    parsed = _parse(persistence, task_id, artifact_path)
    assert parsed.success is True
    assert parsed.data["section_count"] == 2

    glossary = _glossary(persistence, task_id, artifact_path)
    assert glossary.success is True
    assert glossary.data["term_count"] == 2

    translated = _translate(persistence, task_id, artifact_path)
    assert translated.success is True
    assert translated.data["section_count"] == 2

    summary = _summary(persistence, task_id, artifact_path)
    assert summary.success is True
    assert summary.data["evidence_categories"] == 4

    task_dir = persistence.base_dir / task_id
    artifact = json.loads((task_dir / artifact_path).read_text(encoding="utf-8"))
    manifest = persistence.load_manifest(task_id)
    file_names = {entry.name for entry in manifest.files}
    assert artifact["glossary"][0]["target_term"] == "思维链"
    assert artifact["sections"][0]["translated_text"]
    assert artifact["full_text_translated"]
    assert artifact["summary_evidence"]["conclusions"] == ["section_2"]
    assert artifact_path in file_names
    assert artifact["pdf_path"] in file_names


def test_p10_to_p14_translation_failure_does_not_pollute_artifact(tmp_path):
    persistence, task_id = _create_task(tmp_path)
    download = _download(persistence, task_id)
    artifact_path = download.data["artifact_path"]
    assert _parse(persistence, task_id, artifact_path).success is True
    assert _glossary(persistence, task_id, artifact_path).success is True

    artifact_file = persistence.base_dir / task_id / artifact_path
    before = artifact_file.read_text(encoding="utf-8")
    result = _run(
        PaperTranslateTool(persistence=persistence)._execute(
            task_id=task_id,
            artifact_path=artifact_path,
            translations=[
                {"section_id": "section_1", "translated_text": "1 引言\n译文丢失公式和引用。"},
                {
                    "section_id": "section_2",
                    "translated_text": "2 结果\n该方法在基准 [2] 上达到 95.5% 的准确率。",
                },
            ],
        )
    )

    assert result.success is False
    assert artifact_file.read_text(encoding="utf-8") == before


def main():
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()

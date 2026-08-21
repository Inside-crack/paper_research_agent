import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.persistence import StatePersistence
from paper_agent.common.tools.base import ToolResult
from paper_agent.tools import get_default_registry
from paper_agent.tools.paper_processing.paper_download import PaperDownloadTool


PDF_BYTES = b"%PDF-1.7\nvalid paper bytes\n%%EOF"
PAPER = {
    "arxiv_id": "1706.03762v1",
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani"],
    "abstract": "A paper abstract.",
    "pdf_url": "https://arxiv.org/pdf/1706.03762v1",
    "published_date": "2017-06-12",
    "doi": None,
    "version": "1",
    "source": "arxiv",
}


class FakeResponse:
    def __init__(self, content=PDF_BYTES, status_code=200, content_type="application/pdf"):
        self.content = content
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        return self.response


def _make_persistence(tmp_path):
    persistence = StatePersistence(tmp_path / "artifacts")
    spec = ResearchSpec(id="spec-1", user_query="test paper")
    asyncio.run(persistence.save_research_spec(spec))
    asyncio.run(persistence.create_task_manifest(spec))
    return persistence, spec.id


def _metadata_result():
    return ToolResult.ok(data=PAPER)


def test_valid_arxiv_identifier_is_downloaded_and_registered(tmp_path):
    persistence, task_id = _make_persistence(tmp_path)
    tool = PaperDownloadTool(persistence=persistence)

    with patch(
        "paper_agent.tools.paper_processing.paper_download.ArxivGetPaperTool._execute",
        new=AsyncMock(return_value=_metadata_result()),
    ), patch(
        "paper_agent.tools.paper_processing.paper_download.httpx.AsyncClient",
        return_value=FakeAsyncClient(FakeResponse()),
    ):
        result = asyncio.run(tool._execute(arxiv_id="1706.03762v1", task_id=task_id))

    assert result.success is True
    assert result.data["arxiv_id"] == "1706.03762v1"
    assert result.data["version"] == "1"
    assert result.data["size_bytes"] == len(PDF_BYTES)
    task_dir = tmp_path / "artifacts" / task_id
    assert (task_dir / result.data["pdf_path"]).read_bytes() == PDF_BYTES
    paper_json = json.loads((task_dir / result.data["artifact_path"]).read_text())
    assert paper_json["pdf_path"] == result.data["pdf_path"]
    assert any(f.name == result.data["pdf_path"] for f in persistence.load_manifest(task_id).files)


def test_candidate_pdf_url_is_supported_without_metadata_request(tmp_path):
    persistence, task_id = _make_persistence(tmp_path)
    tool = PaperDownloadTool(persistence=persistence)
    candidate = {**PAPER, "arxiv_id": "1706.03762v1"}

    with patch(
        "paper_agent.tools.paper_processing.paper_download.httpx.AsyncClient",
        return_value=FakeAsyncClient(FakeResponse()),
    ), patch(
        "paper_agent.tools.paper_processing.paper_download.ArxivGetPaperTool._execute",
        new=AsyncMock(return_value=_metadata_result()),
    ) as metadata:
        result = asyncio.run(tool._execute(paper=candidate, task_id=task_id))

    assert result.success is True
    assert result.data["source"] == "arxiv"
    metadata.assert_not_awaited()


def test_missing_identifier_is_rejected_before_network_request(tmp_path):
    persistence, task_id = _make_persistence(tmp_path)
    tool = PaperDownloadTool(persistence=persistence)

    with patch(
        "paper_agent.tools.paper_processing.paper_download.httpx.AsyncClient"
    ) as client:
        result = asyncio.run(tool._execute(task_id=task_id))

    assert result.success is False
    assert "arXiv identifier" in result.error
    client.assert_not_called()


def test_non_pdf_response_is_rejected_and_temp_file_is_removed(tmp_path):
    persistence, task_id = _make_persistence(tmp_path)
    tool = PaperDownloadTool(persistence=persistence)

    with patch(
        "paper_agent.tools.paper_processing.paper_download.ArxivGetPaperTool._execute",
        new=AsyncMock(return_value=_metadata_result()),
    ), patch(
        "paper_agent.tools.paper_processing.paper_download.httpx.AsyncClient",
        return_value=FakeAsyncClient(FakeResponse(content=b"<html>not pdf</html>", content_type="text/html")),
    ):
        result = asyncio.run(tool._execute(arxiv_id="1706.03762v1", task_id=task_id))

    assert result.success is False
    assert "PDF" in result.error
    paper_dir = tmp_path / "artifacts" / task_id / "papers"
    assert not list(paper_dir.glob("*.tmp"))
    assert not list(paper_dir.glob("*.pdf"))


def test_manifest_failure_is_returned_as_tool_failure(tmp_path):
    persistence, task_id = _make_persistence(tmp_path)
    persistence.save_paper_artifact = AsyncMock(side_effect=RuntimeError("manifest write failed"))
    tool = PaperDownloadTool(persistence=persistence)

    with patch(
        "paper_agent.tools.paper_processing.paper_download.ArxivGetPaperTool._execute",
        new=AsyncMock(return_value=_metadata_result()),
    ), patch(
        "paper_agent.tools.paper_processing.paper_download.httpx.AsyncClient",
        return_value=FakeAsyncClient(FakeResponse()),
    ):
        result = asyncio.run(tool._execute(arxiv_id="1706.03762v1", task_id=task_id))

    assert result.success is False
    assert "manifest write failed" in result.error
    paper_dir = tmp_path / "artifacts" / task_id / "papers"
    assert not list(paper_dir.glob("*"))


def test_candidate_id_and_pdf_url_versions_must_match(tmp_path):
    persistence, task_id = _make_persistence(tmp_path)
    tool = PaperDownloadTool(persistence=persistence)
    candidate = {
        **PAPER,
        "arxiv_id": "1706.03762v1",
        "pdf_url": "https://arxiv.org/pdf/1706.03762v2",
    }

    with patch("paper_agent.tools.paper_processing.paper_download.httpx.AsyncClient") as client:
        result = asyncio.run(tool._execute(paper=candidate, task_id=task_id))

    assert result.success is False
    assert "does not match" in result.error
    client.assert_not_called()


def test_paper_download_is_registered():
    assert "paper_download" in get_default_registry().list_tools()


def main():
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()

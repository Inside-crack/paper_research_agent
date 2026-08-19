import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.tools.retrieval.arxiv_tool import ArxivSearchTool


async def _test_missing_query_keeps_existing_error():
    result = await ArxivSearchTool()._execute(max_results=5)
    assert result.success is False
    assert result.error == "Missing required parameter: query"


def test_missing_query_keeps_existing_error():
    asyncio.run(_test_missing_query_keeps_existing_error())


async def _test_non_positive_max_results_is_rejected_before_request():
    tool = ArxivSearchTool()
    with patch("paper_agent.tools.retrieval.arxiv_tool.arxiv.Client") as client:
        for value in (0, -1):
            result = await tool._execute(query="agent memory", max_results=value)
            assert result.success is False
            assert result.error == "max_results must be greater than 0"
        client.assert_not_called()


def test_non_positive_max_results_is_rejected_before_request():
    asyncio.run(_test_non_positive_max_results_is_rejected_before_request())


async def _test_positive_max_results_keeps_search_path():
    fake_result = SimpleNamespace(
        published=datetime(2024, 1, 15, 12, 0),
        updated=datetime(2024, 2, 1, 8, 30),
        categories=["cs.AI", "cs.LG"],
        authors=[
            SimpleNamespace(name="Ada Lovelace"),
            SimpleNamespace(name="Alan Turing"),
        ],
        pdf_url="https://arxiv.org/pdf/2401.00001v2",
        links=[
            SimpleNamespace(href="https://arxiv.org/abs/2401.00001v2"),
            SimpleNamespace(href="https://github.com/example/paper"),
        ],
        entry_id="https://arxiv.org/abs/2401.00001v2",
        title="Deterministic Paper Retrieval",
        summary="A deterministic\npaper abstract.",
        doi="10.1234/example.0001",
        journal_ref="Example Journal, 2024",
        comment="12 pages",
        primary_category="cs.AI",
        get_short_id=lambda: "2401.00001v2",
    )

    class FakeClient:
        def results(self, search):
            assert search is not None
            return [fake_result]

    with patch(
        "paper_agent.tools.retrieval.arxiv_tool.arxiv.Client",
        return_value=FakeClient(),
    ) as client:
        result = await ArxivSearchTool()._execute(query="agent memory", max_results=3)
        assert result.success is True
        assert result.data["query"] == "agent memory"
        assert result.data["total_found"] == 1
        paper = result.data["results"][0]
        assert paper["arxiv_id"] == "2401.00001v2"
        assert paper["title"] == "Deterministic Paper Retrieval"
        assert paper["authors"] == ["Ada Lovelace", "Alan Turing"]
        assert paper["abstract"] == "A deterministic paper abstract."
        assert paper["pdf_url"] == "https://arxiv.org/pdf/2401.00001v2"
        assert paper["published_date"] == "2024-01-15"
        assert paper["categories"] == ["cs.AI", "cs.LG"]
        assert paper["version"] == "2"
        assert paper["source"] == "arxiv"
        assert paper["url"] == fake_result.entry_id
        assert paper["updated_date"] == "2024-02-01"
        assert paper["code_available_hint"] is True
        assert paper["code_url_hint"] == "https://github.com/example/paper"
        client.assert_called_once()


def test_positive_max_results_keeps_search_path():
    asyncio.run(_test_positive_max_results_keeps_search_path())


def main():
    asyncio.run(_test_missing_query_keeps_existing_error())
    asyncio.run(_test_non_positive_max_results_is_rejected_before_request())
    asyncio.run(_test_positive_max_results_keeps_search_path())
    print("paper retrieval validation tests passed")


if __name__ == "__main__":
    main()

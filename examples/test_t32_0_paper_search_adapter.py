from __future__ import annotations

import asyncio
from typing import Any

from paper_agent.common.capabilities import ExecutionContext, PaperSearchAdapter
from paper_agent.common.tools import ToolResult


class FakeToolRegistry:
    def __init__(self, results: dict[str, ToolResult]):
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        self.calls.append((tool_name, kwargs))
        return self.results[tool_name]


def candidate(arxiv_id: str = "2401.12345v2") -> dict[str, Any]:
    return {
        "arxiv_id": arxiv_id,
        "title": "A Paper About Agents",
        "authors": ["Author One"],
        "abstract": "A concise abstract.",
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
        "published_date": "2024-01-01",
        "version": "2",
        "source": "arxiv",
    }


def test_search_maps_results_to_candidates_and_forwards_arguments():
    registry = FakeToolRegistry(
        {
            "arxiv_search": ToolResult.ok(
                data={
                    "query": "multi-agent systems",
                    "total_found": 1,
                    "results": [candidate()],
                }
            )
        }
    )
    adapter = PaperSearchAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(session_id="session-1"),
            {
                "query": "multi-agent systems",
                "max_results": 5,
                "categories": ["cs.AI"],
                "sort_by": "submitted_date",
            },
        )
    )

    assert result.success is True
    assert result.status == "succeeded"
    assert result.data["total"] == 1
    assert result.data["candidates"][0]["arxiv_id"] == "2401.12345v2"
    assert result.data["selected_paper"] is None
    assert registry.calls == [
        (
            "arxiv_search",
            {
                "query": "multi-agent systems",
                "max_results": 5,
                "categories": ["cs.AI"],
                "sort_by": "submitted_date",
            },
        )
    ]


def test_explicit_arxiv_id_uses_single_paper_lookup():
    registry = FakeToolRegistry(
        {"arxiv_get_paper": ToolResult.ok(data=candidate("2210.03629v3"))}
    )
    adapter = PaperSearchAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(),
            {"arxiv_id": "2210.03629v3", "query": "ignored", "max_results": 0},
        )
    )

    assert result.success is True
    assert result.data["total"] == 1
    assert result.data["query"] == "ignored"
    assert registry.calls == [("arxiv_get_paper", {"arxiv_id": "2210.03629v3"})]


def test_missing_query_is_rejected_before_tool_call():
    registry = FakeToolRegistry({})
    adapter = PaperSearchAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(adapter.execute(ExecutionContext(), {}))

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "Missing required parameter: query"
    assert registry.calls == []


def test_invalid_max_results_is_rejected_before_tool_call():
    registry = FakeToolRegistry({})
    adapter = PaperSearchAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(ExecutionContext(), {"query": "agents", "max_results": 0})
    )

    assert result.success is False
    assert result.error == "max_results must be greater than 0"
    assert registry.calls == []


def test_tool_failure_is_preserved_as_capability_failure():
    registry = FakeToolRegistry(
        {"arxiv_search": ToolResult.fail("arXiv search error: timeout")}
    )
    adapter = PaperSearchAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(ExecutionContext(), {"query": "agents"})
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "arXiv search error: timeout"
    assert result.next_actions == ["修改检索条件后重试"]


def test_malformed_tool_output_is_rejected():
    registry = FakeToolRegistry(
        {"arxiv_search": ToolResult.ok(data={"results": [{"title": "missing url"}]})}
    )
    adapter = PaperSearchAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(ExecutionContext(), {"query": "agents"})
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error.startswith("Invalid arxiv_search output:")


if __name__ == "__main__":
    test_search_maps_results_to_candidates_and_forwards_arguments()
    test_explicit_arxiv_id_uses_single_paper_lookup()
    test_missing_query_is_rejected_before_tool_call()
    test_invalid_max_results_is_rejected_before_tool_call()
    test_tool_failure_is_preserved_as_capability_failure()
    test_malformed_tool_output_is_rejected()
    print("6 passed")

from __future__ import annotations

import asyncio
from typing import Any

from paper_agent.common.capabilities import (
    ExecutionContext,
    PaperDownloadAdapter,
)
from paper_agent.common.tools import ToolResult


class FakeToolRegistry:
    def __init__(self, result: ToolResult):
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        self.calls.append((tool_name, kwargs))
        return self.result


def download_result() -> ToolResult:
    return ToolResult.ok(
        data={
            "paper_artifact_id": "artifact-1",
            "arxiv_id": "2412.05449v1",
            "version": "1",
            "pdf_path": "papers/2412.05449v1.pdf",
            "artifact_path": "papers/2412.05449v1.json",
            "size_bytes": 1024,
            "source": "arxiv",
        }
    )


def test_download_uses_selected_paper_and_task_context():
    registry = FakeToolRegistry(download_result())
    adapter = PaperDownloadAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(
                task_id="task-1",
                selected_paper={
                    "arxiv_id": "2412.05449v1",
                    "title": "A paper",
                },
            ),
            {},
        )
    )

    assert result.success is True
    assert result.status == "succeeded"
    assert result.artifact_refs == [
        "papers/2412.05449v1.json",
        "papers/2412.05449v1.pdf",
    ]
    assert registry.calls == [
        (
            "paper_download",
            {
                "task_id": "task-1",
                "paper": {
                    "arxiv_id": "2412.05449v1",
                    "title": "A paper",
                },
            },
        )
    ]


def test_explicit_arxiv_id_overrides_selected_paper():
    registry = FakeToolRegistry(download_result())
    adapter = PaperDownloadAdapter(registry)  # type: ignore[arg-type]

    asyncio.run(
        adapter.execute(
            ExecutionContext(
                task_id="task-1",
                selected_paper={"arxiv_id": "old-id"},
            ),
            {"arxiv_id": "2412.05449v1"},
        )
    )

    assert registry.calls[0][1]["paper"]["arxiv_id"] == "2412.05449v1"
    assert registry.calls[0][1]["arxiv_id"] == "2412.05449v1"


def test_missing_task_is_blocked_before_tool_call():
    registry = FakeToolRegistry(download_result())
    adapter = PaperDownloadAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(selected_paper={"arxiv_id": "2412.05449v1"}),
            {},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert registry.calls == []


def test_missing_selected_paper_is_blocked_before_tool_call():
    registry = FakeToolRegistry(download_result())
    adapter = PaperDownloadAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(ExecutionContext(task_id="task-1"), {})
    )

    assert result.success is False
    assert result.status == "blocked"
    assert registry.calls == []


def test_tool_failure_is_preserved():
    registry = FakeToolRegistry(ToolResult.fail("Failed to download paper PDF: timeout"))
    adapter = PaperDownloadAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(
                task_id="task-1",
                selected_paper={"arxiv_id": "2412.05449v1"},
            ),
            {},
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "Failed to download paper PDF: timeout"


def test_invalid_tool_output_is_rejected():
    registry = FakeToolRegistry(ToolResult.ok(data={"arxiv_id": "2412.05449v1"}))
    adapter = PaperDownloadAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(
                task_id="task-1",
                selected_paper={"arxiv_id": "2412.05449v1"},
            ),
            {},
        )
    )

    assert result.success is False
    assert result.error == (
        "Invalid paper_download output: missing "
        "paper_artifact_id, pdf_path, artifact_path"
    )


if __name__ == "__main__":
    test_download_uses_selected_paper_and_task_context()
    test_explicit_arxiv_id_overrides_selected_paper()
    test_missing_task_is_blocked_before_tool_call()
    test_missing_selected_paper_is_blocked_before_tool_call()
    test_tool_failure_is_preserved()
    test_invalid_tool_output_is_rejected()
    print("6 passed")

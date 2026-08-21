from __future__ import annotations

import asyncio
from typing import Any

from paper_agent.common.capabilities import ExecutionContext, PaperParseAdapter
from paper_agent.common.tools import ToolResult


class FakeToolRegistry:
    def __init__(self, result: ToolResult):
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        self.calls.append((tool_name, kwargs))
        return self.result


def parse_result() -> ToolResult:
    return ToolResult.ok(
        data={
            "paper_artifact_id": "artifact-1",
            "artifact_path": "papers/2412.05449v1.json",
            "page_count": 12,
            "section_count": 8,
            "text_length": 24000,
            "parsing_errors": [],
        }
    )


def test_parse_forwards_task_and_artifact_context():
    registry = FakeToolRegistry(parse_result())
    adapter = PaperParseAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/2412.05449v1.json"},
        )
    )

    assert result.success is True
    assert result.status == "succeeded"
    assert result.data["section_count"] == 8
    assert result.artifact_refs == ["papers/2412.05449v1.json"]
    assert result.next_actions == ["继续生成论文术语表"]
    assert registry.calls == [
        (
            "paper_parse",
            {
                "task_id": "task-1",
                "artifact_path": "papers/2412.05449v1.json",
            },
        )
    ]


def test_missing_task_is_blocked_before_tool_call():
    registry = FakeToolRegistry(parse_result())
    adapter = PaperParseAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(),
            {"artifact_path": "papers/paper.json"},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert registry.calls == []


def test_missing_artifact_path_is_blocked_before_tool_call():
    registry = FakeToolRegistry(parse_result())
    adapter = PaperParseAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(adapter.execute(ExecutionContext(task_id="task-1"), {}))

    assert result.success is False
    assert result.status == "blocked"
    assert result.error == "paper_parse requires artifact_path"
    assert registry.calls == []


def test_blank_artifact_path_is_rejected_before_tool_call():
    registry = FakeToolRegistry(parse_result())
    adapter = PaperParseAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "   "},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert registry.calls == []


def test_tool_failure_is_preserved_as_capability_failure():
    registry = FakeToolRegistry(ToolResult.fail("Paper PDF not found: papers/paper.pdf"))
    adapter = PaperParseAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json"},
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "Paper PDF not found: papers/paper.pdf"


def test_missing_tool_output_is_rejected():
    registry = FakeToolRegistry(
        ToolResult.ok(
            data={
                "paper_artifact_id": "artifact-1",
                "artifact_path": "papers/paper.json",
            }
        )
    )
    adapter = PaperParseAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json"},
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == (
        "Invalid paper_parse output: missing "
        "page_count, section_count, text_length, parsing_errors"
    )


def test_invalid_parsing_errors_output_is_rejected():
    data = parse_result().data
    data["parsing_errors"] = "none"
    registry = FakeToolRegistry(ToolResult.ok(data=data))
    adapter = PaperParseAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json"},
        )
    )

    assert result.success is False
    assert result.error == (
        "Invalid paper_parse output: parsing_errors must be a list"
    )


if __name__ == "__main__":
    test_parse_forwards_task_and_artifact_context()
    test_missing_task_is_blocked_before_tool_call()
    test_missing_artifact_path_is_blocked_before_tool_call()
    test_blank_artifact_path_is_rejected_before_tool_call()
    test_tool_failure_is_preserved_as_capability_failure()
    test_missing_tool_output_is_rejected()
    test_invalid_parsing_errors_output_is_rejected()
    print("7 passed")

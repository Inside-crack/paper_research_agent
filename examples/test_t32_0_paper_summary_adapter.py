from __future__ import annotations

import asyncio
from typing import Any

from paper_agent.common.capabilities import ExecutionContext, PaperSummaryAdapter
from paper_agent.common.tools import ToolResult


class FakeToolRegistry:
    def __init__(self, result: ToolResult):
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        self.calls.append((tool_name, kwargs))
        return self.result


def summary_result() -> ToolResult:
    return ToolResult.ok(
        data={
            "paper_artifact_id": "artifact-1",
            "artifact_path": "papers/2412.05449v1.json",
            "evidence_categories": 5,
            "summary_fields": [
                "research_questions",
                "contributions",
                "conclusions",
                "limitations",
                "methodology_summary",
            ],
        }
    )


def valid_summary() -> dict[str, Any]:
    return {
        "research_questions": ["How does the method work?"],
        "methodology_summary": "The paper proposes and evaluates a method.",
        "contributions": ["A new method."],
        "conclusions": ["The method is effective."],
        "limitations": ["The evaluation is limited."],
        "evidence": {
            "research_questions": ["section_1"],
            "methodology_summary": ["section_1"],
            "contributions": ["section_1"],
            "conclusions": ["section_2"],
            "limitations": ["section_2"],
        },
    }


def test_summary_forwards_task_artifact_and_summary():
    registry = FakeToolRegistry(summary_result())
    adapter = PaperSummaryAdapter(registry)  # type: ignore[arg-type]
    summary = valid_summary()

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {
                "artifact_path": "papers/2412.05449v1.json",
                "summary": summary,
            },
        )
    )

    assert result.success is True
    assert result.status == "succeeded"
    assert result.data["evidence_categories"] == 5
    assert result.artifact_refs == ["papers/2412.05449v1.json"]
    assert result.next_actions == ["论文处理链路已完成"]
    assert registry.calls == [
        (
            "paper_summary",
            {
                "task_id": "task-1",
                "artifact_path": "papers/2412.05449v1.json",
                "summary": summary,
            },
        )
    ]


def test_missing_task_is_blocked_before_tool_call():
    registry = FakeToolRegistry(summary_result())
    adapter = PaperSummaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(),
            {"artifact_path": "papers/paper.json", "summary": valid_summary()},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert registry.calls == []


def test_missing_artifact_path_is_blocked_before_tool_call():
    registry = FakeToolRegistry(summary_result())
    adapter = PaperSummaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"summary": valid_summary()},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.error == "paper_summary requires artifact_path"
    assert registry.calls == []


def test_missing_summary_is_blocked_before_tool_call():
    registry = FakeToolRegistry(summary_result())
    adapter = PaperSummaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json"},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.error == "paper_summary requires summary"
    assert registry.calls == []


def test_non_object_summary_is_rejected_before_tool_call():
    registry = FakeToolRegistry(summary_result())
    adapter = PaperSummaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {
                "artifact_path": "papers/paper.json",
                "summary": [],
            },
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "summary must be an object"
    assert registry.calls == []


def test_tool_failure_is_preserved_as_capability_failure():
    registry = FakeToolRegistry(
        ToolResult.fail("Unknown evidence section for conclusions: section_unknown")
    )
    adapter = PaperSummaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json", "summary": valid_summary()},
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "Unknown evidence section for conclusions: section_unknown"


def test_missing_tool_output_is_rejected():
    registry = FakeToolRegistry(
        ToolResult.ok(
            data={
                "paper_artifact_id": "artifact-1",
                "artifact_path": "papers/paper.json",
            }
        )
    )
    adapter = PaperSummaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json", "summary": valid_summary()},
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == (
        "Invalid paper_summary output: missing "
        "evidence_categories, summary_fields"
    )


def test_invalid_summary_fields_output_is_rejected():
    data = summary_result().data
    data["summary_fields"] = "not-a-list"
    registry = FakeToolRegistry(ToolResult.ok(data=data))
    adapter = PaperSummaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json", "summary": valid_summary()},
        )
    )

    assert result.success is False
    assert result.error == (
        "Invalid paper_summary output: summary_fields must be a list"
    )


if __name__ == "__main__":
    test_summary_forwards_task_artifact_and_summary()
    test_missing_task_is_blocked_before_tool_call()
    test_missing_artifact_path_is_blocked_before_tool_call()
    test_missing_summary_is_blocked_before_tool_call()
    test_non_object_summary_is_rejected_before_tool_call()
    test_tool_failure_is_preserved_as_capability_failure()
    test_missing_tool_output_is_rejected()
    test_invalid_summary_fields_output_is_rejected()
    print("8 passed")

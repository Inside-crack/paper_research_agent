from __future__ import annotations

import asyncio
from typing import Any

from paper_agent.common.capabilities import ExecutionContext, PaperGlossaryAdapter
from paper_agent.common.tools import ToolResult


class FakeToolRegistry:
    def __init__(self, result: ToolResult):
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        self.calls.append((tool_name, kwargs))
        return self.result


def glossary_result() -> ToolResult:
    return ToolResult.ok(
        data={
            "paper_artifact_id": "artifact-1",
            "artifact_path": "papers/2412.05449v1.json",
            "term_count": 1,
            "terms": [
                {
                    "source_term": "multi-agent",
                    "target_term": "多智能体",
                    "context": "multi-agent collaboration",
                    "confidence": 0.95,
                }
            ],
        }
    )


def test_glossary_forwards_task_artifact_and_terms():
    registry = FakeToolRegistry(glossary_result())
    adapter = PaperGlossaryAdapter(registry)  # type: ignore[arg-type]
    terms = [
        {
            "source_term": "multi-agent",
            "target_term": "多智能体",
            "context": "multi-agent collaboration",
            "confidence": 0.95,
        }
    ]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {
                "artifact_path": "papers/2412.05449v1.json",
                "terms": terms,
            },
        )
    )

    assert result.success is True
    assert result.status == "succeeded"
    assert result.data["term_count"] == 1
    assert result.artifact_refs == ["papers/2412.05449v1.json"]
    assert result.next_actions == ["继续翻译论文章节"]
    assert registry.calls == [
        (
            "paper_glossary",
            {
                "task_id": "task-1",
                "artifact_path": "papers/2412.05449v1.json",
                "terms": terms,
            },
        )
    ]


def test_missing_task_is_blocked_before_tool_call():
    registry = FakeToolRegistry(glossary_result())
    adapter = PaperGlossaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(),
            {"artifact_path": "papers/paper.json", "terms": []},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert registry.calls == []


def test_missing_artifact_path_is_blocked_before_tool_call():
    registry = FakeToolRegistry(glossary_result())
    adapter = PaperGlossaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"terms": []},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.error == "paper_glossary requires artifact_path"
    assert registry.calls == []


def test_missing_terms_is_blocked_before_tool_call():
    registry = FakeToolRegistry(glossary_result())
    adapter = PaperGlossaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json"},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.error == "paper_glossary requires terms"
    assert registry.calls == []


def test_non_list_terms_is_rejected_before_tool_call():
    registry = FakeToolRegistry(glossary_result())
    adapter = PaperGlossaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {
                "artifact_path": "papers/paper.json",
                "terms": {"source_term": "term"},
            },
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "terms must be a list"
    assert registry.calls == []


def test_tool_failure_is_preserved_as_capability_failure():
    registry = FakeToolRegistry(
        ToolResult.fail("Source term has no evidence in paper text: unknown")
    )
    adapter = PaperGlossaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json", "terms": []},
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "Source term has no evidence in paper text: unknown"


def test_missing_tool_output_is_rejected():
    registry = FakeToolRegistry(
        ToolResult.ok(
            data={
                "paper_artifact_id": "artifact-1",
                "artifact_path": "papers/paper.json",
            }
        )
    )
    adapter = PaperGlossaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json", "terms": []},
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == (
        "Invalid paper_glossary output: missing term_count, terms"
    )


def test_invalid_tool_terms_output_is_rejected():
    data = glossary_result().data
    data["terms"] = "not-a-list"
    registry = FakeToolRegistry(ToolResult.ok(data=data))
    adapter = PaperGlossaryAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json", "terms": []},
        )
    )

    assert result.success is False
    assert result.error == (
        "Invalid paper_glossary output: terms must be a list"
    )


if __name__ == "__main__":
    test_glossary_forwards_task_artifact_and_terms()
    test_missing_task_is_blocked_before_tool_call()
    test_missing_artifact_path_is_blocked_before_tool_call()
    test_missing_terms_is_blocked_before_tool_call()
    test_non_list_terms_is_rejected_before_tool_call()
    test_tool_failure_is_preserved_as_capability_failure()
    test_missing_tool_output_is_rejected()
    test_invalid_tool_terms_output_is_rejected()
    print("8 passed")

from __future__ import annotations

import asyncio
from typing import Any

from paper_agent.common.capabilities import ExecutionContext, PaperTranslateAdapter
from paper_agent.common.tools import ToolResult


class FakeToolRegistry:
    def __init__(self, result: ToolResult):
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        self.calls.append((tool_name, kwargs))
        return self.result


def translate_result() -> ToolResult:
    return ToolResult.ok(
        data={
            "paper_artifact_id": "artifact-1",
            "artifact_path": "papers/2412.05449v1.json",
            "section_count": 2,
            "translated_text_length": 3200,
        }
    )


def test_translate_forwards_task_artifact_and_translations():
    registry = FakeToolRegistry(translate_result())
    adapter = PaperTranslateAdapter(registry)  # type: ignore[arg-type]
    translations = [
        {"section_id": "section_1", "translated_text": "这是第一节。"},
        {"section_id": "section_2", "translated_text": "这是第二节。"},
    ]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {
                "artifact_path": "papers/2412.05449v1.json",
                "translations": translations,
            },
        )
    )

    assert result.success is True
    assert result.status == "succeeded"
    assert result.data["section_count"] == 2
    assert result.artifact_refs == ["papers/2412.05449v1.json"]
    assert result.next_actions == ["继续生成论文总结"]
    assert registry.calls == [
        (
            "paper_translate",
            {
                "task_id": "task-1",
                "artifact_path": "papers/2412.05449v1.json",
                "translations": translations,
            },
        )
    ]


def test_missing_task_is_blocked_before_tool_call():
    registry = FakeToolRegistry(translate_result())
    adapter = PaperTranslateAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(),
            {"artifact_path": "papers/paper.json", "translations": []},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert registry.calls == []


def test_missing_artifact_path_is_blocked_before_tool_call():
    registry = FakeToolRegistry(translate_result())
    adapter = PaperTranslateAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"translations": []},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.error == "paper_translate requires artifact_path"
    assert registry.calls == []


def test_missing_translations_is_blocked_before_tool_call():
    registry = FakeToolRegistry(translate_result())
    adapter = PaperTranslateAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json"},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.error == "paper_translate requires translations"
    assert registry.calls == []


def test_non_list_translations_is_rejected_before_tool_call():
    registry = FakeToolRegistry(translate_result())
    adapter = PaperTranslateAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {
                "artifact_path": "papers/paper.json",
                "translations": {"section_id": "section_1"},
            },
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "translations must be a list"
    assert registry.calls == []


def test_tool_failure_is_preserved_as_capability_failure():
    registry = FakeToolRegistry(
        ToolResult.fail("Missing section translations: ['section_2']")
    )
    adapter = PaperTranslateAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json", "translations": []},
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "Missing section translations: ['section_2']"


def test_missing_tool_output_is_rejected():
    registry = FakeToolRegistry(
        ToolResult.ok(
            data={
                "paper_artifact_id": "artifact-1",
                "artifact_path": "papers/paper.json",
            }
        )
    )
    adapter = PaperTranslateAdapter(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(
            ExecutionContext(task_id="task-1"),
            {"artifact_path": "papers/paper.json", "translations": []},
        )
    )

    assert result.success is False
    assert result.status == "failed"
    assert result.error == (
        "Invalid paper_translate output: missing "
        "section_count, translated_text_length"
    )


if __name__ == "__main__":
    test_translate_forwards_task_artifact_and_translations()
    test_missing_task_is_blocked_before_tool_call()
    test_missing_artifact_path_is_blocked_before_tool_call()
    test_missing_translations_is_blocked_before_tool_call()
    test_non_list_translations_is_rejected_before_tool_call()
    test_tool_failure_is_preserved_as_capability_failure()
    test_missing_tool_output_is_rejected()
    print("7 passed")

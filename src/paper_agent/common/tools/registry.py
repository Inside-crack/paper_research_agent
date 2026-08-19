from __future__ import annotations

from typing import Any, Callable

from ..logging import get_logger
from .base import BaseTool, ToolResult

logger = get_logger(__name__)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool | Callable] = {}

    def register(self, tool: BaseTool | Callable, name: str | None = None) -> None:
        if isinstance(tool, BaseTool):
            tool_name = name or tool.name
        elif hasattr(tool, "is_tool"):
            tool_name = name or getattr(tool, "tool_name", tool.__name__)
        else:
            raise ValueError(f"Cannot register {type(tool)} as a tool")

        if not tool_name:
            raise ValueError("Tool must have a name")

        self._tools[tool_name] = tool
        logger.debug(f"Registered tool: {tool_name}")

    def unregister(self, name: str) -> None:
        if name in self._tools:
            del self._tools[name]

    def get(self, name: str) -> BaseTool | Callable | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_schemas(self) -> list[dict[str, Any]]:
        schemas = []
        for name, tool in self._tools.items():
            if isinstance(tool, BaseTool):
                schemas.append(tool.get_schema())
            elif hasattr(tool, "get_schema"):
                schemas.append(tool.get_schema())
        return schemas

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult.fail(error=f"Tool not found: {tool_name}")

        kwargs.pop("name", None)

        if isinstance(tool, BaseTool):
            return await tool.execute(**kwargs)
        elif callable(tool):
            try:
                result = tool(**kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, ToolResult):
                    return result
                return ToolResult.ok(data=result)
            except Exception as e:
                return ToolResult.fail(error=str(e))

        return ToolResult.fail(error=f"Invalid tool type: {type(tool)}")


global_registry = ToolRegistry()

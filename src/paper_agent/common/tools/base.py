from __future__ import annotations

import functools
import time
import traceback
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from ..logging import get_logger, trace_logger

logger = get_logger(__name__)


class ToolResult(BaseModel):
    success: bool = True
    data: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(cls, data: Any = None, **kwargs: Any) -> "ToolResult":
        return cls(success=True, data=data, **kwargs)

    @classmethod
    def fail(cls, error: str, **kwargs: Any) -> "ToolResult":
        return cls(success=False, error=error, **kwargs)


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    def __init__(self, **kwargs: Any):
        self.config = kwargs

    @abstractmethod
    async def _execute(self, **kwargs: Any) -> ToolResult:
        pass

    async def execute(self, **kwargs: Any) -> ToolResult:
        start_time = time.time()
        agent = kwargs.pop("_agent", "unknown")
        phase = kwargs.pop("_phase", "unknown")

        try:
            result = await self._execute(**kwargs)
            result.duration_ms = int((time.time() - start_time) * 1000)

            trace_logger.log_tool_call(
                agent=agent,
                phase=phase,
                tool_name=self.name,
                tool_input=kwargs,
                tool_output={"success": result.success, "error": result.error},
                duration_ms=result.duration_ms,
            )

            return result
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            logger.error(f"Tool {self.name} failed: {error_msg}")

            trace_logger.log_tool_call(
                agent=agent,
                phase=phase,
                tool_name=self.name,
                tool_input=kwargs,
                duration_ms=duration_ms,
                error=str(e),
            )

            return ToolResult.fail(error=str(e), duration_ms=duration_ms)

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self._get_parameters_schema(),
        }

    def _get_parameters_schema(self) -> dict[str, Any]:
        return {}


def tool(name: str, description: str = "") -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(**kwargs: Any) -> ToolResult:
            start_time = time.time()
            try:
                data = await func(**kwargs) if func.__code__.co_flags & 0x80 else func(**kwargs)
                return ToolResult.ok(data=data, duration_ms=int((time.time() - start_time) * 1000))
            except Exception as e:
                return ToolResult.fail(error=str(e), duration_ms=int((time.time() - start_time) * 1000))

        wrapper.is_tool = True
        wrapper.tool_name = name
        wrapper.tool_description = description or func.__doc__ or ""
        wrapper.get_schema = lambda: {
            "name": name,
            "description": description or func.__doc__ or "",
            "parameters": {},
        }
        return wrapper

    return decorator

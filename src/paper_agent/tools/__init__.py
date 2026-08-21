from __future__ import annotations

from typing import Optional

from ..common.tools.base import BaseTool, ToolResult, tool
from ..common.tools.registry import ToolRegistry, global_registry
from .filesystem.file_tools import DownloadFileTool, LoadArtifactTool, SaveArtifactTool
from .paper_processing import (
    PaperDownloadTool,
    PaperGlossaryTool,
    PaperParseTool,
    PaperSummaryTool,
    PaperTranslateTool,
)
from .retrieval.arxiv_tool import ArxivGetPaperTool, ArxivSearchTool


def register_all_tools(registry: Optional[ToolRegistry] = None) -> ToolRegistry:
    reg = registry or global_registry

    reg.register(SaveArtifactTool())
    reg.register(LoadArtifactTool())
    reg.register(DownloadFileTool())
    reg.register(PaperDownloadTool())
    reg.register(PaperParseTool())
    reg.register(PaperGlossaryTool())
    reg.register(PaperTranslateTool())
    reg.register(PaperSummaryTool())

    reg.register(ArxivSearchTool())
    reg.register(ArxivGetPaperTool())

    return reg


def get_default_registry() -> ToolRegistry:
    if not global_registry.list_tools():
        register_all_tools(global_registry)
    return global_registry


__all__ = [
    "BaseTool",
    "ToolResult",
    "tool",
    "ToolRegistry",
    "global_registry",
    "register_all_tools",
    "get_default_registry",
    "ArxivSearchTool",
    "ArxivGetPaperTool",
    "SaveArtifactTool",
    "LoadArtifactTool",
    "DownloadFileTool",
    "PaperDownloadTool",
    "PaperGlossaryTool",
    "PaperParseTool",
    "PaperTranslateTool",
    "PaperSummaryTool",
]

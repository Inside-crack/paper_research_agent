from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ...common.tools.base import BaseTool, ToolResult
from ...common.config import get_settings


class SaveArtifactTool(BaseTool):
    name = "save_artifact"
    description = (
        "Save structured data (JSON) to the task artifact directory. "
        "Parameters: artifact_name (str, required), data (any JSON-serializable, required), "
        "format (str, optional, default 'json'). "
        "Example: {\"artifact_name\": \"research_spec\", \"data\": {...}}"
    )

    async def _execute(self, **kwargs: Any) -> ToolResult:
        settings = get_settings()

        artifact_name = kwargs.get("artifact_name") or kwargs.get("name") or kwargs.get("artifact_id")
        data = kwargs.get("data") or kwargs.get("content")
        task_id = kwargs.get("task_id", "")
        format = kwargs.get("format", "json")

        if not artifact_name:
            return ToolResult.fail(error="Missing required parameter: artifact_name")
        if data is None:
            return ToolResult.fail(error="Missing required parameter: data")

        if task_id:
            artifact_dir = settings.artifact_dir / task_id
        else:
            artifact_dir = settings.artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)

        if not artifact_name.endswith(f".{format}"):
            artifact_name = f"{artifact_name}.{format}"

        path = artifact_dir / artifact_name

        try:
            if format == "json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            elif format == "text":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(str(data))
            else:
                return ToolResult.fail(error=f"Unsupported format: {format}")

            return ToolResult.ok(data={"path": str(path), "artifact_name": artifact_name})
        except Exception as e:
            return ToolResult.fail(error=str(e))


class LoadArtifactTool(BaseTool):
    name = "load_artifact"
    description = (
        "Load a previously saved artifact from the task artifact directory. "
        "Parameters: artifact_name (str, required), format (str, optional, default 'json')."
    )

    async def _execute(self, **kwargs: Any) -> ToolResult:
        settings = get_settings()

        artifact_name = kwargs.get("artifact_name") or kwargs.get("name")
        task_id = kwargs.get("task_id", "")
        format = kwargs.get("format", "json")

        if not artifact_name:
            return ToolResult.fail(error="Missing required parameter: artifact_name")

        if task_id:
            artifact_dir = settings.artifact_dir / task_id
        else:
            artifact_dir = settings.artifact_dir

        path = artifact_dir / artifact_name

        if not path.exists():
            return ToolResult.fail(error=f"Artifact not found: {path}")

        try:
            if format == "json":
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            elif format == "text":
                with open(path, "r", encoding="utf-8") as f:
                    data = f.read()
            else:
                with open(path, "rb") as f:
                    data = f.read()

            return ToolResult.ok(data=data)
        except Exception as e:
            return ToolResult.fail(error=str(e))


class DownloadFileTool(BaseTool):
    name = "download_file"
    description = (
        "Download a file from a URL to the workspace. "
        "Parameters: url (str, required), filename (str, optional). "
        "Returns: local path, filename, size_bytes."
    )

    async def _execute(self, **kwargs: Any) -> ToolResult:
        import httpx

        settings = get_settings()

        url = kwargs.get("url")
        filename = kwargs.get("filename", "")
        task_id = kwargs.get("task_id", "")

        if not url:
            return ToolResult.fail(error="Missing required parameter: url")

        if task_id:
            workspace = settings.workspace_dir / task_id
        else:
            workspace = settings.workspace_dir
        workspace.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = url.split("/")[-1] or "downloaded_file"

        path = workspace / filename

        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()

                with open(path, "wb") as f:
                    f.write(response.content)

            return ToolResult.ok(data={
                "path": str(path),
                "filename": filename,
                "size_bytes": len(response.content),
                "content_type": response.headers.get("content-type", ""),
            })
        except Exception as e:
            return ToolResult.fail(error=str(e))

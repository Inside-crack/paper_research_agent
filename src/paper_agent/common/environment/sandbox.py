from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..config import get_settings
from ..logging import get_logger

logger = get_logger(__name__)


class CommandResult(BaseModel):
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    artifact_paths: list[str] = Field(default_factory=list)


class SandboxManager:
    def __init__(self, workspace_dir: Optional[Path] = None):
        self.settings = get_settings()
        self.workspace = workspace_dir or self.settings.workspace_dir
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run_command(
        self,
        command: str,
        working_dir: Optional[str] = None,
        timeout: int = 3600,
        env: Optional[dict[str, str]] = None,
        task_id: Optional[str] = None,
    ) -> CommandResult:
        import time

        start_time = time.time()

        cwd = Path(working_dir) if working_dir else self.workspace
        if task_id:
            cwd = cwd / task_id
        cwd.mkdir(parents=True, exist_ok=True)

        if self.settings.sandbox.enabled and self.settings.sandbox.type == "docker":
            return await self._run_in_docker(command, cwd, timeout, env)
        else:
            return await self._run_subprocess(command, cwd, timeout, env)

    async def _run_subprocess(
        self,
        command: str,
        cwd: Path,
        timeout: int,
        env: Optional[dict[str, str]],
    ) -> CommandResult:
        import time

        start_time = time.time()

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            return CommandResult(
                exit_code=process.returncode or 0,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                duration_seconds=time.time() - start_time,
            )
        except asyncio.TimeoutError:
            if process:
                process.kill()
            return CommandResult(
                exit_code=-1,
                stderr=f"Command timed out after {timeout} seconds",
                duration_seconds=time.time() - start_time,
            )
        except Exception as e:
            return CommandResult(
                exit_code=-1,
                stderr=f"Execution error: {str(e)}",
                duration_seconds=time.time() - start_time,
            )

    async def _run_in_docker(
        self,
        command: str,
        cwd: Path,
        timeout: int,
        env: Optional[dict[str, str]],
    ) -> CommandResult:
        logger.info("Docker sandbox execution is a placeholder in this initial framework version")
        return CommandResult(
            exit_code=0,
            stdout="Docker sandbox not yet implemented. Running in host mode for framework development.",
            stderr="",
        )

    def create_workspace(self, task_id: str) -> Path:
        ws = self.workspace / task_id
        ws.mkdir(parents=True, exist_ok=True)
        return ws

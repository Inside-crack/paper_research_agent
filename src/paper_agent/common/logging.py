from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog

from .config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    log_level = getattr(logging, settings.logging.level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.logging.format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    file_handler = logging.FileHandler(log_dir / "paper_agent.log")
    file_handler.setFormatter(formatter)
    logging.getLogger().addHandler(file_handler)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


class TraceLogger:
    def __init__(self):
        self.logger = get_logger("trace")
        self.trace_enabled = get_settings().logging.trace_enabled

    def log_tool_call(
        self,
        agent: str,
        phase: str,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: dict[str, Any] | None = None,
        duration_ms: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        if not self.trace_enabled:
            return

        self.logger.info(
            "tool_call",
            agent=agent,
            phase=phase,
            tool_name=tool_name,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=error,
        )

    def log_agent_action(
        self,
        agent: str,
        phase: str,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if not self.trace_enabled:
            return

        self.logger.info(
            "agent_action",
            agent=agent,
            phase=phase,
            action=action,
            details=details or {},
        )


trace_logger = TraceLogger()

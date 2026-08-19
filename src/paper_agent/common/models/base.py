from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskPhase(str, enum.Enum):
    TASK_INITIALIZATION = "task_initialization"
    PAPER_RETRIEVAL = "paper_retrieval"
    PAPER_PARSING = "paper_parsing"
    CODE_LOCATION = "code_location"
    REPRODUCTION_PLANNING = "reproduction_planning"
    EXPERIMENT_EXECUTION = "experiment_execution"
    RESULT_REPORTING = "result_reporting"
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationVerdict(str, enum.Enum):
    PASS = "PASS"
    REVISE = "REVISE"
    BLOCKED = "BLOCKED"


class SeverityLevel(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ReproductionLevel(str, enum.Enum):
    FULLY_REPRODUCED = "fully_reproduced"
    MOSTLY_REPRODUCED = "mostly_reproduced"
    TREND_CONSISTENT = "trend_consistent"
    PARTIAL_FAILURE = "partial_failure"
    NOT_REPRODUCIBLE = "not_reproducible"


class PaperType(str, enum.Enum):
    SURVEY = "survey"
    METHOD = "method"
    BENCHMARK = "benchmark"
    APPLICATION = "application"
    EXPERIMENTAL = "experimental"
    UNKNOWN = "unknown"


class CodeSource(str, enum.Enum):
    OFFICIAL = "official"
    THIRD_PARTY = "third_party"
    UNKNOWN = "unknown"


class Budget(BaseModel):
    max_tokens: int = 500000
    max_gpu_minutes: int = 60
    max_wall_time_minutes: int = 120
    tokens_used: int = 0
    gpu_minutes_used: float = 0.0
    wall_time_minutes_used: float = 0.0

    def is_exceeded(self) -> bool:
        return (
            self.tokens_used >= self.max_tokens
            or self.gpu_minutes_used >= self.max_gpu_minutes
            or self.wall_time_minutes_used >= self.max_wall_time_minutes
        )


class TraceEntry(BaseModel):
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    phase: TaskPhase
    agent: str
    action: str
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_output: Optional[dict[str, Any]] = None
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseModelWithId(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

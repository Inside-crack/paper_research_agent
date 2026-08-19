from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .base import BaseModelWithId


class ExperimentMetrics(BaseModel):
    metric_name: str
    paper_reported_value: Optional[float] = None
    reproduced_value: Optional[float] = None
    unit: str = ""
    is_higher_better: bool = True
    std_dev: Optional[float] = None


class ExperimentRun(BaseModelWithId):
    reproduction_spec_id: str
    run_name: str = "default"

    command: str = ""
    working_dir: str = ""
    config_used: dict[str, str] = Field(default_factory=dict)
    random_seed: Optional[int] = None

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    exit_code: Optional[int] = None
    success: bool = False

    stdout_log_path: Optional[str] = None
    stderr_log_path: Optional[str] = None
    artifact_paths: list[str] = Field(default_factory=list)

    cpu_usage_avg: float = 0.0
    memory_usage_avg_mb: float = 0.0
    gpu_usage_avg: float = 0.0
    duration_seconds: int = 0

    metrics: list[ExperimentMetrics] = Field(default_factory=list)
    error_message: Optional[str] = None
    recovery_attempts: int = 0

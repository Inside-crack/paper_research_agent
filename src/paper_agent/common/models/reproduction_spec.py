from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .base import BaseModelWithId, CodeSource, ReproductionLevel


class ResourceEstimate(BaseModel):
    cpu_cores: int = 2
    memory_gb: int = 8
    gpu_required: bool = False
    gpu_memory_gb: int = 0
    estimated_runtime_minutes: int = 60
    disk_space_gb: int = 10


class ExperimentStep(BaseModel):
    step_id: str
    name: str
    command: str
    working_dir: str = ""
    environment_vars: dict[str, str] = Field(default_factory=dict)
    expected_outputs: list[str] = Field(default_factory=list)
    timeout_seconds: int = 3600


class ExperimentPlan(BaseModel):
    code_version: str = ""
    commit_hash: Optional[str] = None
    docker_image: Optional[str] = None
    python_version: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    dataset_location: str = ""
    config_overrides: dict[str, str] = Field(default_factory=dict)
    random_seed: Optional[int] = None
    steps: list[ExperimentStep] = Field(default_factory=list)
    metrics_to_collect: list[str] = Field(default_factory=list)


class ReproductionSpec(BaseModelWithId):
    paper_artifact_id: str
    target_level: ReproductionLevel = ReproductionLevel.TREND_CONSISTENT

    code_repo_url: Optional[str] = None
    code_source: CodeSource = CodeSource.UNKNOWN
    code_verified: bool = False
    commit_hash: Optional[str] = None
    version_tag: Optional[str] = None

    repo_structure: dict[str, str] = Field(default_factory=dict)
    code_entry_points: dict[str, str] = Field(default_factory=dict)
    paper_code_mapping: dict[str, str] = Field(default_factory=dict)
    unpublished_components: list[str] = Field(default_factory=list)

    environment_requirements: dict[str, str] = Field(default_factory=dict)
    dataset_url: Optional[str] = None
    model_weights_url: Optional[str] = None
    license_info: Optional[str] = None

    feasibility_level: str = "unknown"
    blockers: list[str] = Field(default_factory=list)
    resource_estimate: ResourceEstimate = Field(default_factory=ResourceEstimate)
    experiment_plan: ExperimentPlan = Field(default_factory=ExperimentPlan)

    user_confirmation_required: bool = True
    user_confirmed: bool = False

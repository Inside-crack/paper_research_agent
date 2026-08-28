from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-v4-flash"
    eval_model: str = "deepseek-v4-pro"
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout: int = 120


class AgentSettings(BaseModel):
    model: str = ""
    temperature: float = 0.3
    system_prompt_path: str = ""


class BudgetConfig(BaseModel):
    max_tokens_per_task: int = 500000
    max_gpu_minutes: int = 60
    max_wall_time_minutes: int = 120
    max_revisions_per_stage: int = 1


class SandboxConfig(BaseModel):
    enabled: bool = True
    type: str = "docker"
    docker_image: str = "python:3.10-slim"
    allow_network: bool = False
    cpu_limit: str = "2"
    memory_limit: str = "4g"
    timeout: int = 1800


class RetrievalConfig(BaseModel):
    arxiv_max_results: int = 50
    arxiv_wait_seconds: int = 3
    sources: list[str] = Field(default_factory=lambda: ["arxiv", "openreview", "github"])


class StageConfig(BaseModel):
    name: str
    display_name: str
    revision_allowed: bool = True
    requires_human_confirmation: bool = False


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "json"
    trace_enabled: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = "paper-research-agent"
    app_version: str = "0.1.0"
    environment: str = "development"
    config_dir: Path = Field(default=Path("config"))

    llm: LLMConfig = Field(default_factory=LLMConfig)
    research_agent: AgentSettings = Field(default_factory=lambda: AgentSettings(
        temperature=0.3,
        system_prompt_path="prompts/research_agent/system.txt",
    ))
    evaluation_agent: AgentSettings = Field(default_factory=lambda: AgentSettings(
        temperature=0.0,
        system_prompt_path="prompts/evaluation_agent/system.txt",
    ))
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    artifact_dir: Path = Field(default=Path("data/artifacts"))
    memory_dir: Path = Field(default=Path("data/memory"))
    cache_dir: Path = Field(default=Path("data/cache"))
    log_dir: Path = Field(default=Path("data/logs"))
    workspace_dir: Path = Field(default=Path("data/workspaces"))

    stages: list[StageConfig] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, config_path: Path | None = None) -> "Settings":
        load_dotenv()

        if config_path is None:
            config_path = Path(__file__).parents[3] / "config" / "default.yaml"

        yaml_data: dict[str, Any] = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}

        llm_data = yaml_data.get("llm", {})

        api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY", "")
        if api_key and not llm_data.get("api_key"):
            llm_data["api_key"] = api_key

        provider = os.environ.get("LLM_PROVIDER")
        if provider:
            llm_data["provider"] = provider

        model = os.environ.get("LLM_MODEL")
        if model:
            llm_data["model"] = model

        eval_model = os.environ.get("LLM_EVAL_MODEL")
        if eval_model:
            llm_data["eval_model"] = eval_model

        base_url = os.environ.get("LLM_BASE_URL")
        if base_url:
            llm_data["base_url"] = base_url

        yaml_data["llm"] = llm_data

        settings = cls(**yaml_data)

        if not settings.research_agent.model:
            settings.research_agent.model = settings.llm.model
        if not settings.evaluation_agent.model:
            settings.evaluation_agent.model = settings.llm.eval_model

        settings._ensure_dirs()
        return settings

    def _ensure_dirs(self) -> None:
        for dir_path in [
            self.artifact_dir,
            self.memory_dir,
            self.cache_dir,
            self.log_dir,
            self.workspace_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings.from_yaml()

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .base import BaseModelWithId


class PlanStep(BaseModel):
    step_id: str
    description: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = ""
    executed: bool = False
    result: Optional[dict[str, Any]] = None
    success: bool = False
    error: Optional[str] = None
    duration_ms: int = 0
    artifact_id: Optional[str] = None


class ExecutionPlan(BaseModelWithId):
    phase: str = ""
    plan_name: str = ""
    requires_human_confirmation: bool = False
    confirmed: bool = False
    steps: list[PlanStep] = Field(default_factory=list)
    summary_note: str = ""

    def get_next_unexecuted_step(self) -> Optional[PlanStep]:
        for step in self.steps:
            if not step.executed:
                return step
        return None

    def all_steps_completed(self) -> bool:
        return all(s.executed for s in self.steps)

    def all_steps_succeeded(self) -> bool:
        return self.all_steps_completed() and all(s.success for s in self.steps)

    def failed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.executed and not s.success]

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .agent_event import AgentEventType


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentDetectedPayload(EventPayload):
    intent: Optional[str] = None
    capability_name: Optional[str] = None
    matched: bool = False


class CandidateFoundPayload(EventPayload):
    candidate_set_id: Optional[str] = None
    query_used: str = ""
    queried_at: Optional[str] = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)


class WorkflowStartedPayload(EventPayload):
    workflow_name: str
    phase: Optional[str] = None


class StepStartedPayload(EventPayload):
    phase: str
    step_id: str
    step_index: int = Field(ge=0)
    total_steps: int = Field(ge=1)


class StepCompletedPayload(EventPayload):
    phase: str
    step_id: str
    success: bool
    artifact_refs: list[str] = Field(default_factory=list)
    error_code: Optional[str] = None


class ArtifactCreatedPayload(EventPayload):
    artifact_refs: list[str] = Field(min_length=1)
    artifact_type: Optional[str] = None


class EvaluationCompletedPayload(EventPayload):
    verdict: str
    score: Optional[float] = None
    issue_count: int = Field(default=0, ge=0)


class TaskLifecyclePayload(EventPayload):
    reason: Optional[str] = None


class ResponseReadyPayload(EventPayload):
    status: str
    message: str
    next_actions: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)


EVENT_PAYLOAD_MODELS: dict[AgentEventType, type[EventPayload]] = {
    AgentEventType.INTENT_DETECTED: IntentDetectedPayload,
    AgentEventType.CANDIDATE_FOUND: CandidateFoundPayload,
    AgentEventType.WORKFLOW_STARTED: WorkflowStartedPayload,
    AgentEventType.STEP_STARTED: StepStartedPayload,
    AgentEventType.STEP_COMPLETED: StepCompletedPayload,
    AgentEventType.ARTIFACT_CREATED: ArtifactCreatedPayload,
    AgentEventType.EVALUATION_COMPLETED: EvaluationCompletedPayload,
    AgentEventType.TASK_PAUSED: TaskLifecyclePayload,
    AgentEventType.TASK_RESUMED: TaskLifecyclePayload,
    AgentEventType.TASK_CANCELLED: TaskLifecyclePayload,
    AgentEventType.TASK_COMPLETED: TaskLifecyclePayload,
    AgentEventType.TASK_FAILED: TaskLifecyclePayload,
    AgentEventType.RESPONSE_READY: ResponseReadyPayload,
}

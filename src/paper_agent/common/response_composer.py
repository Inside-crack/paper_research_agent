from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import AgentEvent, AgentEventType
from .event_security import EventSecurityFilter


class ComposedResponse(BaseModel):
    """User-facing representation of an internal agent event."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    task_id: Optional[str] = None
    status: str
    message: str
    next_actions: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    correlation_id: str


class ResponseComposer:
    """Translate safe, structured events into user-facing responses."""

    def compose(
        self,
        event: AgentEvent,
        *,
        context: Optional[Any] = None,
    ) -> ComposedResponse:
        if not isinstance(event, AgentEvent):
            raise TypeError("event must be an AgentEvent")

        payload = EventSecurityFilter().sanitize_payload(event.payload)
        event_type = event.event_type
        status, message, next_actions = self._compose_content(event_type, payload)
        artifact_refs = self._safe_artifacts(payload.get("artifact_refs", []))
        return ComposedResponse(
            session_id=event.session_id,
            task_id=event.task_id,
            status=status,
            message=self._sanitize(message),
            next_actions=next_actions,
            artifact_refs=artifact_refs,
            correlation_id=event.correlation_id,
        )

    def _compose_content(
        self,
        event_type: AgentEventType,
        payload: dict[str, Any],
    ) -> tuple[str, str, list[str]]:
        if event_type == AgentEventType.INTENT_DETECTED:
            if payload.get("matched"):
                return "progress", "已识别你的请求。", ["继续"]
            return "clarification", "暂时无法理解这个请求，请补充说明。", ["补充说明"]
        if event_type == AgentEventType.CANDIDATE_FOUND:
            total = payload.get("total", 0)
            return (
                "waiting_confirmation",
                f"已找到 {total} 篇候选论文，请选择一篇并确认。",
                ["select_candidate", "confirm"],
            )
        if event_type == AgentEventType.WORKFLOW_STARTED:
            name = payload.get("workflow_name") or "论文处理"
            return "progress", f"{name}已启动。", ["status", "pause", "cancel"]
        if event_type == AgentEventType.STEP_STARTED:
            step = payload.get("step_id") or "当前步骤"
            return "progress", f"正在执行：{step}。", ["status", "pause", "cancel"]
        if event_type == AgentEventType.STEP_COMPLETED:
            if payload.get("success"):
                return "progress", f"步骤 {payload.get('step_id', '当前步骤')} 已完成。", ["status"]
            return (
                "failed",
                f"步骤 {payload.get('step_id', '当前步骤')} 执行失败。",
                ["retry", "status"],
            )
        if event_type == AgentEventType.ARTIFACT_CREATED:
            return "progress", "处理产物已生成。", ["view_artifact", "status"]
        if event_type == AgentEventType.EVALUATION_COMPLETED:
            return "progress", "当前阶段评估已完成。", ["status"]
        if event_type == AgentEventType.TASK_PAUSED:
            return "paused", "任务已暂停，已保存当前进度。", ["resume", "cancel"]
        if event_type == AgentEventType.TASK_RESUMED:
            return "progress", "任务已恢复，将从最新进度继续。", ["status", "pause", "cancel"]
        if event_type == AgentEventType.TASK_CANCELLED:
            return "cancelled", "任务已取消，后续步骤不会继续执行。", []
        if event_type == AgentEventType.TASK_COMPLETED:
            return "completed", "任务已完成。", ["view_artifact"]
        if event_type == AgentEventType.TASK_FAILED:
            reason = payload.get("reason") or payload.get("error_code")
            suffix = f" 原因：{self._sanitize(str(reason))}" if reason else ""
            return "failed", f"任务处理失败。{suffix}", ["retry", "status"]
        if event_type == AgentEventType.RESPONSE_READY:
            return (
                str(payload.get("status") or "success"),
                str(payload.get("message") or "处理完成。"),
                list(payload.get("next_actions") or []),
            )
        raise ValueError(f"Unsupported agent event type: {event_type}")

    def _safe_artifacts(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        safe: list[str] = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = value.replace("\\", "/")
            if normalized in {"[PATH]", "[REDACTED]"}:
                continue
            if (
                PurePosixPath(normalized).is_absolute()
                or PureWindowsPath(value).is_absolute()
                or ".." in PurePosixPath(normalized).parts
            ):
                continue
            safe.append(normalized)
        return safe

    def _sanitize(self, value: str) -> str:
        return EventSecurityFilter().sanitize_payload(value)

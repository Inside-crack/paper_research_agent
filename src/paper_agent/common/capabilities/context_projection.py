from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..models.conversation import (
    ConversationMessage,
    ConversationSession,
)
from ..models.memory import MemoryRecallItem


class ContextProjectionConfig(BaseModel):
    """Hard limits applied before conversation context reaches a Router."""

    model_config = ConfigDict(extra="forbid")

    max_messages: int = Field(default=12, ge=1, le=100)
    max_message_chars: int = Field(default=4000, ge=100, le=20000)
    max_candidates: int = Field(default=10, ge=1, le=100)
    max_candidate_chars: int = Field(default=2000, ge=100, le=10000)
    max_artifact_refs: int = Field(default=20, ge=1, le=100)
    max_selected_sections: int = Field(default=20, ge=1, le=100)
    max_relevant_memories: int = Field(default=5, ge=1, le=100)
    max_memory_chars: int = Field(default=1200, ge=100, le=10000)


class ProjectedConversationMessage(BaseModel):
    """Safe message view with metadata and persistence internals removed."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    task_id: Optional[str] = None


class ProjectedMemory(BaseModel):
    """Bounded memory view safe to expose to a Router."""

    model_config = ConfigDict(extra="forbid")

    memory_id: str
    content: str
    memory_type: str
    scope: str
    confidence: float
    priority: int
    source_task_id: Optional[str] = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    relevance_score: float


class IntentContextProjection(BaseModel):
    """Read-only, bounded context made available to an intent Router."""

    model_config = ConfigDict(extra="forbid")

    recent_messages: list[ProjectedConversationMessage] = Field(default_factory=list)
    current_intent: Optional[str] = None
    candidate_papers: list[dict[str, Any]] = Field(default_factory=list)
    candidate_set_id: Optional[str] = None
    selected_paper: Optional[dict[str, Any]] = None
    selected_sections: list[str] = Field(default_factory=list)
    active_task_id: Optional[str] = None
    artifact_refs: list[str] = Field(default_factory=list)
    relevant_memories: list[ProjectedMemory] = Field(default_factory=list)
    memory_disclaimer: Optional[str] = None
    memory_recall_degraded: bool = False
    memory_recall_truncated: bool = False
    session_status: str


class IntentContextProjector:
    """Project persisted conversation state without filesystem lookups."""

    _PAPER_FIELDS = (
        "id",
        "arxiv_id",
        "title",
        "authors",
        "abstract",
        "url",
        "pdf_url",
        "published_date",
        "version",
        "source",
        "paper_type",
    )

    def __init__(self, config: Optional[ContextProjectionConfig] = None):
        self.config = config or ContextProjectionConfig()

    def project(
        self,
        session: ConversationSession,
        messages: Sequence[ConversationMessage],
        memories: Sequence[MemoryRecallItem] = (),
        memory_recall_degraded: bool = False,
        memory_recall_truncated: bool = False,
    ) -> IntentContextProjection:
        if not isinstance(session, ConversationSession):
            raise TypeError("session must be a ConversationSession")
        if not isinstance(messages, Sequence):
            raise TypeError("messages must be a sequence")

        for message in messages:
            if not isinstance(message, ConversationMessage):
                raise TypeError("messages must contain ConversationMessage values")
            if message.session_id != session.session_id:
                raise ValueError(
                    "message session_id does not match projection session"
                )
        if not isinstance(memories, Sequence):
            raise TypeError("memories must be a sequence")
        for memory in memories:
            if not isinstance(memory, MemoryRecallItem):
                raise TypeError("memories must contain MemoryRecallItem values")

        recent_messages = [
            ProjectedConversationMessage(
                role=message.role,
                content=self._truncate(
                    message.content,
                    self.config.max_message_chars,
                ),
                task_id=message.task_id,
            )
            for message in list(messages)[-self.config.max_messages :]
        ]

        context = session.context
        candidate_papers = [
            self._project_paper(paper)
            for paper in context.candidate_papers[: self.config.max_candidates]
            if isinstance(paper, dict)
        ]
        selected_paper = (
            self._project_paper(context.selected_paper)
            if isinstance(context.selected_paper, dict)
            else None
        )
        artifact_refs = self._project_artifact_refs(messages)
        selected_sections = self._unique_limited(
            context.selected_sections,
            self.config.max_selected_sections,
        )
        projected_memories = [
            ProjectedMemory(
                memory_id=memory.memory_id,
                content=self._truncate(
                    memory.content,
                    self.config.max_memory_chars,
                ),
                memory_type=memory.memory_type,
                scope=memory.scope,
                confidence=memory.confidence,
                priority=memory.priority,
                source_task_id=memory.source_task_id,
                source_artifact_ids=memory.source_artifact_ids[: self.config.max_artifact_refs],
                relevance_score=memory.relevance_score,
            )
            for memory in list(memories)[: self.config.max_relevant_memories]
        ]

        return IntentContextProjection(
            recent_messages=recent_messages,
            current_intent=context.current_intent,
            candidate_papers=candidate_papers,
            candidate_set_id=context.candidate_set_id,
            selected_paper=selected_paper,
            selected_sections=selected_sections,
            active_task_id=context.active_task_id or session.active_task_id,
            artifact_refs=artifact_refs,
            relevant_memories=projected_memories,
            memory_disclaimer=(
                "以下记忆来自历史任务，仅作为参考；不代表当前任务已完成，"
                "也不能替代当前任务的工具事实。"
                if projected_memories
                else None
            ),
            memory_recall_degraded=memory_recall_degraded,
            memory_recall_truncated=memory_recall_truncated,
            session_status=session.status,
        )

    def _project_paper(self, paper: dict[str, Any]) -> dict[str, Any]:
        projected: dict[str, Any] = {}
        for field in self._PAPER_FIELDS:
            value = paper.get(field)
            if value is None:
                continue
            if field == "authors":
                if isinstance(value, list):
                    projected[field] = [
                        self._truncate(str(author), self.config.max_candidate_chars)
                        for author in value[:20]
                    ]
                continue
            if isinstance(value, (str, int, float, bool)):
                projected[field] = (
                    self._truncate(value, self.config.max_candidate_chars)
                    if isinstance(value, str)
                    else value
                )
        return projected

    def _project_artifact_refs(
        self,
        messages: Sequence[ConversationMessage],
    ) -> list[str]:
        refs: list[str] = []
        for message in messages:
            for ref in message.artifact_refs:
                if not self._is_safe_relative_ref(ref):
                    continue
                if ref not in refs:
                    refs.append(ref)
                if len(refs) >= self.config.max_artifact_refs:
                    return refs
        return refs

    @staticmethod
    def _is_safe_relative_ref(value: Any) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        if "\\" in value or Path(value).is_absolute():
            return False
        path = Path(value)
        return ".." not in path.parts

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        suffix = "... [truncated]"
        return value[: max(0, limit - len(suffix))] + suffix

    @staticmethod
    def _unique_limited(values: Sequence[str], limit: int) -> list[str]:
        result: list[str] = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = value.strip()
            if normalized not in result:
                result.append(normalized)
            if len(result) >= limit:
                break
        return result

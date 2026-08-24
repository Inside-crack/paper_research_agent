from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .intent_schema import IntentDecision


ClarificationReason = Literal[
    "low_confidence",
    "missing_arguments",
    "capability_unavailable",
    "context_conflict",
    "unknown_intent",
]


class ClarificationPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low_confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)


class ClarificationResult(BaseModel):
    """Safe user-facing clarification outcome derived from a decision."""

    model_config = ConfigDict(extra="forbid")

    needs_clarification: bool
    decision: IntentDecision
    reason: Optional[ClarificationReason] = None
    question: Optional[str] = None


class ClarificationPolicy:
    """Turn unsafe or incomplete decisions into bounded clarification requests."""

    _ARGUMENT_LABELS = {
        "task_id": "当前任务",
        "selected_paper": "目标论文",
        "artifact_path": "论文产物",
        "terms": "术语候选",
        "translations": "章节译文",
        "summary": "论文总结",
        "query": "检索主题",
    }

    def __init__(self, config: Optional[ClarificationPolicyConfig] = None):
        self.config = config or ClarificationPolicyConfig()

    def evaluate(self, decision: IntentDecision) -> ClarificationResult:
        if not isinstance(decision, IntentDecision):
            raise TypeError("decision must be an IntentDecision")

        if (
            decision.matched
            and decision.confidence < self.config.low_confidence_threshold
        ):
            question = "我对你的操作意图把握不足，请明确说明要执行的论文操作。"
            blocked = decision.model_copy(
                update={
                    "matched": False,
                    "source": "fallback",
                    "reason": "Decision confidence is below clarification threshold",
                    "clarification_question": question,
                }
            )
            return ClarificationResult(
                needs_clarification=True,
                decision=blocked,
                reason="low_confidence",
                question=question,
            )

        if decision.matched:
            return ClarificationResult(
                needs_clarification=False,
                decision=decision,
            )

        reason = self._reason_for(decision)
        question = self._question_for(decision, reason)
        clarified = decision.model_copy(
            update={"clarification_question": question}
        )
        return ClarificationResult(
            needs_clarification=True,
            decision=clarified,
            reason=reason,
            question=question,
        )

    @staticmethod
    def _reason_for(decision: IntentDecision) -> ClarificationReason:
        reason = (decision.reason or "").casefold()
        if "conflict" in reason:
            return "context_conflict"
        if any(token in reason for token in ("disabled", "unavailable", "not found")):
            return "capability_unavailable"
        if decision.missing_arguments:
            return "missing_arguments"
        return "unknown_intent"

    def _question_for(
        self,
        decision: IntentDecision,
        reason: ClarificationReason,
    ) -> str:
        if reason == "missing_arguments":
            labels = [
                self._ARGUMENT_LABELS.get(argument, argument)
                for argument in decision.missing_arguments
            ]
            return f"请补充以下信息：{'、'.join(labels)}。"
        if reason == "capability_unavailable":
            capability = decision.capability_name or "该能力"
            return f"{capability} 当前不可用，请换一种操作或稍后重试。"
        if reason == "context_conflict":
            return "当前请求与会话上下文存在冲突，请明确目标论文或操作。"
        return (
            decision.clarification_question
            or "我暂时无法确定你的意图，请明确说明要执行的论文操作。"
        )

"""Regression tests for deterministic target-paper retrieval."""

from __future__ import annotations

import asyncio
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models.execution_plan import ExecutionPlan, PlanStep
from paper_agent.common.models.base import TaskPhase
from paper_agent.common.models.task_state import TaskState
from paper_agent.evaluation_agent import EvaluationAgent
from paper_agent.orchestrator import Orchestrator


TARGET_ID = "2108.01343v3"


def _task_state() -> TaskState:
    return TaskState(
        research_spec_id="spec-i3cl",
        metadata={
            "research_spec": {
                "user_query": "process I3CL",
                "target_paper_arxiv_id": TARGET_ID,
            },
            "paper_retrieval_input": {
                "target_paper_arxiv_id": TARGET_ID,
                "target_paper_url": f"https://arxiv.org/abs/{TARGET_ID}",
            },
        }
    )


def test_target_fetch_step_is_injected_before_llm_search_plan():
    plan = ExecutionPlan(
        phase="paper_retrieval",
        steps=[
            PlanStep(
                step_id="search_related",
                description="Search related papers",
                tool_name="arxiv_search",
                arguments={"query": "scene text detection"},
            )
        ],
    )

    Orchestrator._ensure_target_retrieval_step(
        object.__new__(Orchestrator),
        plan,
        _task_state(),
    )

    assert plan.steps[0].tool_name == "arxiv_get_paper"
    assert plan.steps[0].step_id == "target_paper_fetch"
    assert plan.steps[0].arguments == {"arxiv_id": TARGET_ID}


def test_target_paper_is_forced_into_retrieval_output():
    target = {
        "arxiv_id": TARGET_ID,
        "title": "I3CL",
        "url": f"https://arxiv.org/abs/{TARGET_ID}",
    }
    plan = ExecutionPlan(
        phase="paper_retrieval",
        steps=[
            PlanStep(
                step_id="target_paper_fetch",
                description="Fetch target",
                tool_name="arxiv_get_paper",
                arguments={"arxiv_id": TARGET_ID},
                executed=True,
                success=True,
                result=target,
            )
        ],
    )

    output = Orchestrator._enforce_target_paper_output(
        object.__new__(Orchestrator),
        {"candidates": [{"arxiv_id": "9999.00001"}], "top_recommendations": []},
        plan,
        _task_state(),
    )

    assert output["target_paper_verified"] is True
    assert output["target_paper"]["arxiv_id"] == TARGET_ID
    assert output["candidates"][0]["arxiv_id"] == TARGET_ID
    assert output["top_recommendations"][0] == TARGET_ID


def test_retrieval_evaluator_blocks_when_target_fetch_is_missing():
    evaluator = object.__new__(EvaluationAgent)

    _passed, failed, issues = asyncio.run(
        evaluator._run_deterministic_checks(
            phase=TaskPhase.PAPER_RETRIEVAL,
            output={
                "candidates": [{"arxiv_id": "9999.00001"}],
                "target_paper_verified": False,
            },
            evidence={
                "research_spec": {
                    "target_paper_arxiv_id": TARGET_ID,
                }
            },
            plan=None,
        )
    )

    assert failed >= 1
    assert any(issue.issue_type == "target_paper_missing" for issue in issues)

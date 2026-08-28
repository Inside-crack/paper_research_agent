from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from paper_agent.common.models.execution_plan import ExecutionPlan, PlanStep
from paper_agent.common.models.paper_candidate import PaperCandidate
from paper_agent.common.retrieval_artifact import (
    build_paper_retrieval_artifact,
    normalize_arxiv_id,
)


TARGET_ID = "2108.01343v3"
CODE_URL = (
    "https://github.com/ViTAE-Transformer/"
    "ViTAE-Transformer-Scene-Text-Detection"
)


def _paper(arxiv_id: str, *, title: str, code: bool = False) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": ["Author"],
        "abstract": "Abstract",
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        "code_available": code,
        "code_url": CODE_URL if code else None,
    }


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        phase="paper_retrieval",
        steps=[
            PlanStep(
                step_id="target",
                description="fetch target",
                tool_name="arxiv_get_paper",
                arguments={"arxiv_id": TARGET_ID},
                executed=True,
                success=True,
                result=_paper(TARGET_ID, title="I3CL", code=True),
            ),
            PlanStep(
                step_id="search",
                description="search related",
                tool_name="arxiv_search",
                arguments={"query": "scene text detection"},
                executed=True,
                success=True,
                result={
                    "query": "scene text detection",
                    "results": [
                        _paper("2108.01343", title="Wrong search copy"),
                        _paper("2401.00001v1", title="Related paper"),
                    ],
                },
            ),
        ],
    )


def test_arxiv_identity_normalizes_versions_and_urls():
    assert normalize_arxiv_id("2108.01343") == "2108.01343"
    assert normalize_arxiv_id("arXiv:2108.01343v3") == "2108.01343"
    assert normalize_arxiv_id("https://arxiv.org/abs/2108.01343v3") == "2108.01343"


def test_artifact_preserves_exact_target_facts_and_deduplicates_search_copy():
    artifact = build_paper_retrieval_artifact(
        _plan(),
        {
            "classifications": [
                {
                    "arxiv_id": TARGET_ID,
                    "type": "method",
                    "relevance_score": 1.0,
                    "reason": "Target paper",
                }
            ],
            "ordered_ids": ["9999.99999", "2401.00001v1"],
            "ranking_rationale": "relevance and reproducibility",
        },
        target_arxiv_id=TARGET_ID,
    )

    assert artifact.target_paper_verified is True
    assert artifact.target_paper.title == "I3CL"
    assert artifact.target_paper.code_available is True
    assert artifact.target_paper.code_url == CODE_URL
    assert len(artifact.candidates) == 2
    assert artifact.candidates[0].arxiv_id == TARGET_ID
    assert artifact.top_recommendations == [TARGET_ID, "2401.00001v1"]


def test_llm_cannot_override_tool_code_fact_and_reason_is_bounded():
    llm_output = {
        "classifications": [
            {
                "arxiv_id": TARGET_ID,
                "type": "method",
                "relevance_score": 0.2,
                "reason": "x" * 1000,
                "code_available": False,
                "code_url": None,
            }
        ]
    }
    artifact = build_paper_retrieval_artifact(
        _plan(), llm_output, target_arxiv_id=TARGET_ID
    )

    assert artifact.target_paper.code_available is True
    assert artifact.target_paper.code_url == CODE_URL
    assert len(artifact.target_paper.selection_rationale) == 300


def test_target_requires_successful_exact_fetch():
    plan = _plan()
    plan.steps[0].success = False
    plan.steps[0].result = None
    with pytest.raises(ValueError, match="Confirmed target paper was not fetched"):
        build_paper_retrieval_artifact(plan, {}, target_arxiv_id=TARGET_ID)


def test_legacy_hint_fields_are_normalized():
    candidate = PaperCandidate.model_validate(
        {
            "arxiv_id": "2401.00001v1",
            "title": "Legacy",
            "url": "https://arxiv.org/abs/2401.00001v1",
            "code_available_hint": True,
            "code_url_hint": CODE_URL,
            "type": "method",
        }
    )
    assert candidate.code_available is True
    assert candidate.code_url == CODE_URL
    assert candidate.paper_type.value == "method"

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.models.task_state import TaskState
from paper_agent.orchestrator import Orchestrator


def test_initialization_output_preserves_input_facts_and_filters_false_ambiguities():
    spec = ResearchSpec(
        user_query="分析场景文本检测论文",
        task_type="paper_analysis",
        target_paper_arxiv_id="2108.01343v3",
        domain="计算机视觉",
        year_range=(2020, 2026),
    )
    state = TaskState(
        research_spec_id=spec.id,
        metadata={"research_spec": spec.model_dump(mode="json")},
    )

    output = Orchestrator._enforce_task_initialization_output(
        {
            "task_type": "topic_research",
            "research_spec": {
                "task_type": "topic_research",
                "domain": None,
                "target_paper_arxiv_id": None,
                "keywords": ["scene text detection"],
            },
            "ambiguities": [
                "task_type is missing",
                "domain 未提供",
                "需要确认翻译语言",
            ],
        },
        state,
    )

    assert output["task_type"] == "paper_analysis"
    assert output["research_spec"]["task_type"] == "paper_analysis"
    assert output["research_spec"]["domain"] == "计算机视觉"
    assert output["research_spec"]["target_paper_arxiv_id"] == "2108.01343v3"
    assert output["research_spec"]["keywords"] == ["scene text detection"]
    assert output["ambiguities"] == ["需要确认翻译语言"]


def test_initialization_without_existing_domain_can_accept_llm_domain():
    spec = ResearchSpec(user_query="research scene text detection")
    state = TaskState(
        research_spec_id=spec.id,
        metadata={"research_spec": spec.model_dump(mode="json")},
    )

    output = Orchestrator._enforce_task_initialization_output(
        {
            "research_spec": {
                "domain": "computer vision",
                "keywords": ["scene text detection"],
            },
            "ambiguities": [],
        },
        state,
    )

    assert output["research_spec"]["domain"] == "computer vision"
    assert output["research_spec"]["keywords"] == ["scene text detection"]

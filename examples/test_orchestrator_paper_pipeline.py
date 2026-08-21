"""Orchestrator + ResearchAgent E2E tests for the P10-P14 paper pipeline.

The LLM boundary is deterministic, but the real agents, orchestrator, tool
registry, phase execution, evaluation, and persistence are exercised.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.llm import BaseLLM, LLMResponse
from paper_agent.common.models.base import EvaluationVerdict, TaskPhase
from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.models.task_state import TaskState
from paper_agent.common.persistence import StatePersistence
from paper_agent.common.tools.base import BaseTool, ToolResult
from paper_agent.common.tools.registry import ToolRegistry
from paper_agent.evaluation_agent import EvaluationAgent
from paper_agent.orchestrator import Orchestrator
from paper_agent.research_agent import ResearchAgent
from paper_agent.tools.paper_processing import (
    PaperDownloadTool,
    PaperGlossaryTool,
    PaperParseTool,
    PaperSummaryTool,
    PaperTranslateTool,
)


PDF_BYTES = b"%PDF-1.7\norchestrator fixture\n%%EOF"
ARXIV_ID = "1706.03762v1"
ARTIFACT_PATH = f"papers/{ARXIV_ID}.json"


class FakeLLM(BaseLLM):
    def __init__(self, responses):
        super().__init__(model="fake-e2e", temperature=0)
        self.responses = list(responses)
        self.calls = 0

    async def agenerate(self, messages, **kwargs):
        self.calls += 1
        if not self.responses:
            raise AssertionError("FakeLLM response queue exhausted")
        return LLMResponse(content=json.dumps(self.responses.pop(0), ensure_ascii=False))


class TempSaveArtifactTool(BaseTool):
    name = "save_artifact"
    description = "Save orchestrator step artifacts in the test persistence directory."

    def __init__(self, persistence):
        super().__init__()
        self.persistence = persistence

    async def _execute(self, **kwargs):
        artifact_name = kwargs.get("artifact_name")
        task_id = kwargs.get("task_id")
        if not artifact_name or not task_id:
            return ToolResult.fail(error="artifact_name and task_id are required")
        path = self.persistence.base_dir / task_id / artifact_name
        self.persistence._save_json(path, kwargs.get("data"))
        return ToolResult.ok(data={"path": str(path), "artifact_name": artifact_name})


class FakeResponse:
    content = PDF_BYTES
    headers = {"content-type": "application/pdf"}

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        return FakeResponse()


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class FakePdf:
    pages = [
        FakePage(
            "1 Introduction\n"
            "This paper studies chain-of-thought tool use. Equation (1): x = 2. See [1]."
        ),
        FakePage(
            "2 Results\n"
            "The method reaches 95.5% accuracy on the benchmark [2]."
        ),
    ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _legacy_candidate_plan():
    return {
        "action": "plan",
        "plan_name": "legacy_paper_candidate",
        "steps": [
            {
                "step_id": "download",
                "description": "Download the selected arXiv paper",
                "tool_name": "paper_download",
                "arguments": {
                    "paper": {
                        "arxiv_id": ARXIV_ID,
                        "title": "Offline Orchestrator Paper",
                        "authors": ["Test Author"],
                        "pdf_url": f"https://arxiv.org/pdf/{ARXIV_ID}",
                    }
                },
            },
        ],
    }


def _glossary_plan():
    return {
        "action": "plan",
        "plan_name": "paper_glossary_content",
        "steps": [
            {
                "step_id": "glossary",
                "description": "Persist glossary candidates",
                "tool_name": "paper_glossary",
                "arguments": {
                    "terms": [
                        {
                            "source_term": "chain-of-thought",
                            "target_term": "思维链",
                            "context": "chain-of-thought tool use",
                            "confidence": 0.95,
                        },
                        {
                            "source_term": "tool use",
                            "target_term": "工具使用",
                            "context": "chain-of-thought tool use",
                            "confidence": 0.9,
                        },
                    ],
                },
            },
        ],
    }


def _translate_plan():
    return {
        "action": "plan",
        "plan_name": "paper_translate_content",
        "steps": [
            {
                "step_id": "translate",
                "description": "Translate every parsed section",
                "tool_name": "paper_translate",
                "arguments": {
                    "translations": [
                        {
                            "section_id": "section_1",
                            "translated_text": (
                                "1 引言\n本文研究思维链工具使用。公式 (1)：x = 2。参见 [1]。"
                            ),
                        },
                        {
                            "section_id": "section_2",
                            "translated_text": "2 结果\n该方法在基准 [2] 上达到 95.5% 的准确率。",
                        },
                    ],
                },
            },
        ],
    }


def _summary_plan():
    return {
        "action": "plan",
        "plan_name": "paper_summary_content",
        "steps": [
            {
                "step_id": "summary",
                "description": "Create an evidence-linked summary",
                "tool_name": "paper_summary",
                "arguments": {
                    "summary": {
                        "research_questions": ["如何提升工具使用效果？"],
                        "methodology_summary": "论文提出方法并在基准数据集上实验。",
                        "contributions": ["提出工具使用方法。"],
                        "conclusions": ["方法在基准上达到 95.5% 准确率。"],
                        "limitations": [],
                        "evidence": {
                            "research_questions": ["section_1"],
                            "methodology_summary": ["section_1", "section_2"],
                            "contributions": ["section_1"],
                            "conclusions": ["section_2"],
                        },
                    },
                },
            },
        ],
    }


def _make_orchestrator(tmp_path, llm_responses, evaluation):
    persistence = StatePersistence(tmp_path / "artifacts")
    registry = ToolRegistry()
    registry.register(TempSaveArtifactTool(persistence))
    for tool in (
        PaperDownloadTool(persistence=persistence),
        PaperParseTool(persistence=persistence),
        PaperGlossaryTool(persistence=persistence),
        PaperTranslateTool(persistence=persistence),
        PaperSummaryTool(persistence=persistence),
    ):
        registry.register(tool)

    research = ResearchAgent(
        llm=FakeLLM(llm_responses),
        tool_registry=registry,
    )
    evaluator = EvaluationAgent(
        llm=FakeLLM([evaluation]),
        tool_registry=registry,
    )
    orchestrator = Orchestrator(
        research_agent=research,
        evaluation_agent=evaluator,
        tool_registry=registry,
        persistence=persistence,
    )
    task_id = "task-orchestrator-p10-p14"
    spec = ResearchSpec(
        id=task_id,
        user_query="Analyze and translate the selected paper",
        target_paper_arxiv_id=ARXIV_ID,
        task_type="paper_analysis",
    )
    task_state = TaskState(
        id=task_id,
        research_spec_id=task_id,
        workspace_dir=str(tmp_path / "workspace"),
        artifact_dir=str(tmp_path / "artifacts" / task_id),
    )
    task_state.metadata["user_query"] = spec.user_query
    task_state.metadata["research_spec"] = spec.model_dump(mode="json")
    asyncio.run(persistence.save_research_spec(spec))
    asyncio.run(persistence.create_task_manifest(spec))
    asyncio.run(orchestrator._ensure_stages_initialized(task_state))
    task_state.current_phase = TaskPhase.PAPER_PARSING
    return orchestrator, task_state, persistence


def test_real_orchestrator_and_research_agent_p10_p14_flow(tmp_path):
    orchestrator, task_state, persistence = _make_orchestrator(
        tmp_path,
        [
            _legacy_candidate_plan(),
            _glossary_plan(),
            _translate_plan(),
            _summary_plan(),
        ],
        {"verdict": "PASS", "score": 0.98, "summary": "All paper processing outputs are traceable."},
    )
    with patch(
        "paper_agent.tools.paper_processing.paper_download.httpx.AsyncClient",
        return_value=FakeAsyncClient(),
    ), patch(
        "paper_agent.tools.paper_processing.paper_parse.pdfplumber.open",
        return_value=FakePdf(),
    ):
        result, plan = asyncio.run(
            orchestrator._execute_phase_flow(TaskPhase.PAPER_PARSING, task_state)
        )

    assert result.verdict == EvaluationVerdict.PASS
    assert result.score == 0.98
    assert plan is not None
    assert len(plan.steps) == 5
    assert all(step.success for step in plan.steps)
    assert orchestrator.research.llm.calls == 4
    assert orchestrator.evaluation.llm.calls == 1

    artifact = json.loads(
        (persistence.base_dir / task_state.id / ARTIFACT_PATH).read_text(encoding="utf-8")
    )
    assert artifact["full_text_translated"] == (
        "1 引言\n本文研究思维链工具使用。公式 (1)：x = 2。参见 [1]。\n\n"
        "2 结果\n该方法在基准 [2] 上达到 95.5% 的准确率。"
    )
    assert artifact["summary_evidence"]["conclusions"] == ["section_2"]
    manifest = persistence.load_manifest(task_state.id)
    assert manifest is not None
    paper_phase = manifest.phases[TaskPhase.PAPER_PARSING.value]
    assert paper_phase.artifacts.output == "paper_parsing_output.json"
    assert all(
        step.status == "PASS"
        for step in paper_phase.paper_processing_steps.values()
    )
    assert any(
        entry.name == ARTIFACT_PATH and entry.type == "paper_artifact"
        for entry in manifest.files
    )


def test_real_orchestrator_does_not_pass_failed_tool_plan(tmp_path):
    invalid_plan = {
        "action": "plan",
        "plan_name": "invalid_download",
        "steps": [
            {
                "step_id": "download",
                "description": "Download without a paper identifier",
                "tool_name": "paper_download",
                "arguments": {},
            }
        ],
    }
    orchestrator, task_state, _ = _make_orchestrator(
        tmp_path,
        [invalid_plan],
        {"verdict": "REVISE", "score": 0.1, "summary": "The paper download step failed."},
    )
    result, plan = asyncio.run(
        orchestrator._execute_phase_flow(TaskPhase.PAPER_PARSING, task_state)
    )

    assert plan is not None
    assert plan.steps[0].success is False
    assert result.verdict != EvaluationVerdict.PASS


def main():
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()

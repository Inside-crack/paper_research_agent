from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from paper_agent.common.models.paper_artifact import (
    PaperArtifact,
    PaperSection,
    TermEntry,
)
from paper_agent.common.models.paper_comparison import (
    ComparisonSpec,
    PaperReference,
    normalize_arxiv_id,
)
from paper_agent.common.paper_acquisition import PaperAcquisitionService
from paper_agent.common.paper_acquisition import PaperAcquisitionResult
from paper_agent.workflows.paper_comparison import PaperComparisonWorkflow


def test_normalize_arxiv_identity():
    assert normalize_arxiv_id("2108.01343v3") == "2108.01343"
    assert normalize_arxiv_id("arXiv:2108.01343") == "2108.01343"
    assert normalize_arxiv_id("https://arxiv.org/abs/2108.01343v3") == "2108.01343"
    assert normalize_arxiv_id("https://arxiv.org/pdf/2108.01343v3.pdf") == "2108.01343"


def test_comparison_spec_rejects_duplicate_papers():
    with pytest.raises(ValueError, match="unique"):
        ComparisonSpec(
            user_query="compare",
            paper_refs=[
                PaperReference(arxiv_id="2108.01343v1"),
                PaperReference(url="https://arxiv.org/abs/2108.01343v3"),
            ],
        )


def test_local_artifact_is_preferred_and_identity_checked():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            papers = root / "legacy-task" / "papers"
            papers.mkdir(parents=True)
            artifact_path = papers / "2108.01343v3.json"
            artifact = PaperArtifact(
                research_spec_id="research",
                candidate_id="2108.01343v3",
                arxiv_id="2108.01343v3",
                title="I3CL",
                authors=["Author"],
                pdf_path="papers/2108.01343v3.pdf",
                methodology_summary="Local parsed method",
                sections=[
                    PaperSection(
                        section_id="s1",
                        title="Method",
                        level=1,
                        original_text="Original method",
                        translated_text="方法",
                    )
                ],
                glossary=[
                    TermEntry(
                        source_term="scene text",
                        target_term="场景文本",
                    )
                ],
                full_text_original="Original paper text",
                full_text_translated="论文原文翻译",
                research_questions=["How does it detect text?"],
                contributions=["A collaborative method"],
                conclusions=["It improves detection"],
                limitations=["Limited benchmarks"],
                summary_evidence={"methodology_summary": ["s1"]},
            )
            artifact_path.write_text(
                json.dumps(artifact.model_dump(mode="json")),
                encoding="utf-8",
            )
            pdf_path = papers / "2108.01343v3.pdf"
            pdf_path.write_bytes(b"%PDF-local")

            async def must_not_fetch(_reference):
                raise AssertionError("online metadata fetch should not be called")

            service = PaperAcquisitionService(
                search_roots=[root],
                metadata_fetcher=must_not_fetch,
            )
            result = await service.acquire(
                PaperReference(arxiv_id="2108.01343v3")
            )
            assert result.reused is True
            assert result.source == "local"
            assert result.artifact is not None
            assert result.artifact.title == "I3CL"
            assert result.pdf_path == str(pdf_path)
            assert result.reuse_level == "paper_artifact_complete"
            assert result.available_stages == (
                "download",
                "parse",
                "glossary",
                "translate",
                "summary",
            )
            assert result.reused_from_task_id == "legacy-task"

    asyncio.run(scenario())


def test_comparison_workflow_builds_matrix_and_preserves_unknown():
    async def scenario():
        async def fetch(reference):
            return {
                "arxiv_id": reference.arxiv_id,
                "title": reference.title or reference.arxiv_id,
                "authors": ["Author"],
            }

        service = PaperAcquisitionService(metadata_fetcher=fetch)
        workflow = PaperComparisonWorkflow(service)
        spec = ComparisonSpec(
            user_query="compare two papers",
            paper_refs=[
                PaperReference(arxiv_id="2108.01343v3", title="I3CL"),
                PaperReference(arxiv_id="2401.00001v1", title="Other"),
            ],
        )
        artifact = await workflow.run(spec)
        assert len(artifact.papers) == 2
        assert len(artifact.comparison_matrix) == len(spec.comparison_dimensions)
        assert artifact.comparison_matrix[0].values["2108.01343"] == "unknown"
        assert "2108.01343:problem_definition" in artifact.missing_information

    asyncio.run(scenario())


def test_comparison_workflow_uses_p14_summary_and_analyzer():
    async def scenario():
        artifact = PaperArtifact(
            research_spec_id="task",
            candidate_id="2108.01343v1",
            arxiv_id="2108.01343v1",
            title="Paper A",
            authors=["A"],
            sections=[
                PaperSection(
                    section_id="method",
                    title="Method",
                    level=1,
                    original_text="Method evidence",
                )
            ],
            research_questions=["Question A"],
            methodology_summary="Method A",
            contributions=["Contribution A"],
            conclusions=["Conclusion A"],
            limitations=["Limitation A"],
            summary_evidence={"methodology_summary": ["method"]},
        )

        async def fetch(reference):
            return {
                "arxiv_id": reference.arxiv_id,
                "title": reference.title or reference.arxiv_id,
                "authors": ["Author"],
            }

        calls = []

        async def analyzer(spec, facts):
            calls.append((spec, facts))
            assert facts[0].methodology_summary == "Method A"
            return {
                "commonalities": ["Both use learned representations."],
                "differences": ["Paper A uses Method A."],
                "conclusion": "The methods target different deployment constraints.",
                "missing_information": [],
            }

        async def enrich(result):
            return result

        service = PaperAcquisitionService(metadata_fetcher=fetch)
        original_acquire = service.acquire

        async def acquire(reference):
            result = await original_acquire(reference)
            return PaperAcquisitionResult(
                **{
                    **result.__dict__,
                    "artifact": artifact.model_copy(
                        deep=True,
                        update={"arxiv_id": reference.arxiv_id},
                    ),
                }
            )

        service.acquire = acquire
        workflow = PaperComparisonWorkflow(
            service,
            analyzer=analyzer,
            artifact_enricher=enrich,
        )
        spec = ComparisonSpec(
            user_query="compare",
            paper_refs=[
                PaperReference(arxiv_id="2108.01343v1"),
                PaperReference(arxiv_id="2401.00001v1"),
            ],
        )
        output = await workflow.run(spec)
        assert len(calls) == 1
        assert output.commonalities == ["Both use learned representations."]
        assert output.conclusion.startswith("The methods")
        assert output.papers[0].evidence["methodology_summary"] == ["method"]

    asyncio.run(scenario())


def test_cross_task_lookup_prefers_complete_p10_p14_artifact():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            papers = root / "old-task" / "papers"
            papers.mkdir(parents=True)
            partial = PaperArtifact(
                research_spec_id="old-task",
                candidate_id="2401.00001v1",
                arxiv_id="2401.00001v1",
                title="Partial",
                authors=["A"],
            )
            complete = partial.model_copy(
                deep=True,
                update={
                    "title": "Complete",
                    "pdf_path": "papers/2401.00001v1.pdf",
                    "sections": [
                        PaperSection(
                            section_id="s1",
                            title="Method",
                            level=1,
                            original_text="text",
                            translated_text="译文",
                        )
                    ],
                    "glossary": [
                        TermEntry(source_term="benchmark", target_term="基准")
                    ],
                    "full_text_original": "text",
                    "full_text_translated": "译文",
                    "research_questions": ["question"],
                    "methodology_summary": "method",
                    "contributions": ["contribution"],
                    "conclusions": ["conclusion"],
                    "limitations": ["limitation"],
                    "summary_evidence": {"methodology_summary": ["s1"]},
                },
            )
            (papers / "2401.00001v1-partial.json").write_text(
                json.dumps(partial.model_dump(mode="json")),
                encoding="utf-8",
            )
            (papers / "2401.00001v1-complete.json").write_text(
                json.dumps(complete.model_dump(mode="json")),
                encoding="utf-8",
            )
            (papers / "2401.00001v1.pdf").write_bytes(b"%PDF-local")

            async def must_not_fetch(_reference):
                raise AssertionError("complete cross-task artifact should be reused")

            result = await PaperAcquisitionService(
                search_roots=[root],
                metadata_fetcher=must_not_fetch,
            ).acquire(PaperReference(arxiv_id="2401.00001v1"))
            assert result.reuse_level == "paper_artifact_complete"
            assert result.artifact.title == "Complete"
            assert any(conflict.field == "title" for conflict in result.conflicts)
            assert result.reused_from_task_id == "old-task"
            assert result.available_stages == (
                "download",
                "parse",
                "glossary",
                "translate",
                "summary",
            )

    asyncio.run(scenario())


def test_explicit_local_artifact_identity_conflict_is_blocking():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "wrong.json"
            artifact = PaperArtifact(
                research_spec_id="old-task",
                candidate_id="9999.00001v1",
                arxiv_id="9999.00001v1",
                title="Wrong paper",
                authors=["A"],
            )
            path.write_text(
                json.dumps(artifact.model_dump(mode="json")),
                encoding="utf-8",
            )
            service = PaperAcquisitionService()
            with pytest.raises(ValueError, match="identity mismatch"):
                await service.acquire(
                    PaperReference(
                        arxiv_id="2401.00001v1",
                        local_artifact_path=str(path),
                    )
                )

    asyncio.run(scenario())

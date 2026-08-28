from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Optional

from ..common.models.paper_artifact import PaperArtifact
from ..common.models.paper_comparison import (
    ComparisonMatrixRow,
    ComparisonPaperFacts,
    ComparisonSpec,
    PaperComparisonArtifact,
)
from ..common.paper_acquisition import PaperAcquisitionResult, PaperAcquisitionService


ComparisonAnalyzer = Callable[
    [ComparisonSpec, list[ComparisonPaperFacts]],
    Awaitable[dict[str, Any]],
]
ArtifactEnricher = Callable[
    [PaperAcquisitionResult],
    Awaitable[PaperAcquisitionResult],
]


class PaperComparisonWorkflow:
    """Coordinate multi-paper acquisition and produce a validated comparison."""

    def __init__(
        self,
        acquisition: PaperAcquisitionService,
        *,
        analyzer: Optional[ComparisonAnalyzer] = None,
        artifact_enricher: Optional[ArtifactEnricher] = None,
    ):
        self.acquisition = acquisition
        self.analyzer = analyzer
        self.artifact_enricher = artifact_enricher

    async def run(self, spec: ComparisonSpec) -> PaperComparisonArtifact:
        results = []
        for reference in spec.paper_refs:
            result = await self.acquisition.acquire(reference)
            if (
                self.artifact_enricher is not None
                and result.artifact is not None
                and (
                    not result.artifact.sections
                    or not result.artifact.methodology_summary
                    or not result.artifact.summary_evidence
                )
            ):
                enriched = await self.artifact_enricher(result)
                if enriched is not None:
                    result = enriched
            results.append(result)
        facts = [
            self._facts_from_result(result)
            for result in results
        ]
        conflicts = [
            conflict
            for result in results
            for conflict in result.conflicts
        ]
        analysis = await self._analyze(spec, facts)
        matrix = self._build_matrix(spec.comparison_dimensions, facts)

        artifact = PaperComparisonArtifact(
            comparison_spec_id=spec.id,
            papers=facts,
            dimensions=list(spec.comparison_dimensions),
            comparison_matrix=matrix,
            commonalities=self._list_of_strings(analysis.get("commonalities")),
            differences=self._list_of_strings(analysis.get("differences")),
            conclusion=str(analysis.get("conclusion") or ""),
            missing_information=list(
                dict.fromkeys(
                    self._list_of_strings(analysis.get("missing_information"))
                    + self._missing_information(facts)
                )
            ),
            conflicts=conflicts,
        )
        return artifact

    async def _analyze(
        self,
        spec: ComparisonSpec,
        facts: list[ComparisonPaperFacts],
    ) -> dict[str, Any]:
        if self.analyzer is None:
            return self._fallback_analysis(spec, facts)
        result = await self.analyzer(spec, facts)
        return result if isinstance(result, dict) else self._fallback_analysis(spec, facts)

    @staticmethod
    def _facts_from_result(result: PaperAcquisitionResult) -> ComparisonPaperFacts:
        metadata = result.metadata
        artifact = result.artifact
        paper_id = result.paper_id
        return ComparisonPaperFacts(
            paper_id=paper_id,
            title=str(metadata.get("title") or getattr(artifact, "title", "") or ""),
            authors=list(metadata.get("authors") or getattr(artifact, "authors", []) or []),
            version=metadata.get("version") or getattr(artifact, "version", None),
            source=result.source,
            reuse_level=result.reuse_level,
            reused_from_task_id=result.reused_from_task_id,
            available_stages=list(result.available_stages),
            artifact_path=result.artifact_path,
            pdf_path=result.pdf_path,
            problem_definition=PaperComparisonWorkflow._fact_text(
                artifact,
                "research_questions",
                metadata,
                ("abstract", "summary"),
            ),
            methodology_summary=PaperComparisonWorkflow._fact_text(
                artifact,
                "methodology_summary",
                metadata,
                ("abstract", "summary"),
            ),
            training_strategy=PaperComparisonWorkflow._fact_text(
                artifact,
                "training_strategy",
                metadata,
                ("training_strategy", "abstract", "summary"),
                keywords=("train", "supervis", "loss", "optimization", "training"),
            ),
            datasets_and_metrics=PaperComparisonWorkflow._fact_text(
                artifact,
                "datasets_and_metrics",
                metadata,
                ("datasets_and_metrics", "abstract", "summary"),
                keywords=("dataset", "benchmark", "metric", "evaluate", "accuracy", "f-measure"),
            ),
            reported_results=PaperComparisonWorkflow._list_of_strings(
                metadata.get("reported_results")
                or getattr(artifact, "conclusions", None)
                or PaperComparisonWorkflow._sentences(
                    metadata.get("abstract") or metadata.get("summary") or "",
                    ("result", "performance", "outperform", "improv", "accuracy", "gain"),
                )
            ),
            limitations=PaperComparisonWorkflow._list_of_strings(
                metadata.get("limitations")
                or getattr(artifact, "limitations", None)
                or PaperComparisonWorkflow._sentences(
                    metadata.get("abstract") or metadata.get("summary") or "",
                    ("limitation", "challenge", "future work", "however"),
                )
            ),
            evidence=(
                getattr(artifact, "summary_evidence", {})
                or PaperComparisonWorkflow._metadata_evidence(metadata)
            ),
            conflicts=list(result.conflicts),
        )

    @staticmethod
    def _fact_text(
        artifact: Optional[PaperArtifact],
        artifact_field: str,
        metadata: dict[str, Any],
        metadata_fields: tuple[str, ...],
        *,
        keywords: tuple[str, ...] = (),
    ) -> str:
        value = PaperComparisonWorkflow._artifact_text(artifact, artifact_field)
        if value != "unknown":
            return value
        for field in metadata_fields:
            raw = metadata.get(field)
            text = " ".join(raw) if isinstance(raw, list) else str(raw or "").strip()
            if not text:
                continue
            if keywords:
                selected = PaperComparisonWorkflow._sentences(text, keywords)
                if selected:
                    return "; ".join(selected)
            else:
                return text[:1200]
        return "unknown"

    @staticmethod
    def _sentences(text: str, keywords: tuple[str, ...]) -> list[str]:
        if not text:
            return []
        chunks = [
            chunk.strip(" \n\t.;")
            for chunk in re.split(r"(?<=[.!?])\s+|\n+", text)
        ]
        selected = [
            chunk[:500]
            for chunk in chunks
            if len(chunk) >= 20 and any(keyword.casefold() in chunk.casefold() for keyword in keywords)
        ]
        return list(dict.fromkeys(selected))[:5]

    @staticmethod
    def _metadata_evidence(metadata: dict[str, Any]) -> dict[str, list[str]]:
        fields = {}
        if metadata.get("abstract") or metadata.get("summary"):
            source = "arxiv.abstract"
            for field in ("research_questions", "methodology_summary", "training_strategy", "datasets_and_metrics"):
                fields[field] = [source]
        return fields

    @classmethod
    def _fallback_analysis(
        cls,
        spec: ComparisonSpec,
        facts: list[ComparisonPaperFacts],
    ) -> dict[str, Any]:
        """Provide a useful, evidence-bounded result when no LLM analyzer is wired."""
        if not facts:
            return {}
        commonalities: list[str] = []
        if all("text recognition" in paper.title.casefold() for paper in facts):
            commonalities.append("两篇论文都围绕文本识别任务展开。")
        if all(paper.source in {"arxiv", "local"} for paper in facts):
            commonalities.append("两篇论文均基于论文元数据和摘要进行分析。")

        differences = [
            f"{paper.title}：{paper.methodology_summary[:240]}"
            for paper in facts
            if paper.methodology_summary != "unknown"
        ]
        evidence_gaps = list(dict.fromkeys(cls._missing_information(facts)))
        conclusion = (
            f"本次对比覆盖 {len(facts)} 篇论文，比较维度包括："
            f"{'、'.join(spec.comparison_dimensions)}。"
        )
        if evidence_gaps:
            conclusion += "部分方法和实验细节缺少可验证的全文摘要证据，未进行推断。"
        return {
            "commonalities": commonalities,
            "differences": differences,
            "conclusion": conclusion,
            "missing_information": evidence_gaps,
        }

    @staticmethod
    def _artifact_text(artifact: Optional[PaperArtifact], field: str) -> str:
        if artifact is None:
            return "unknown"
        value = getattr(artifact, field, None)
        if isinstance(value, list):
            if value:
                return "; ".join(str(item) for item in value)
        elif value:
            return str(value)

        if field == "research_questions" and artifact.abstract:
            return artifact.abstract[:1200]
        if field == "methodology_summary":
            return PaperComparisonWorkflow._section_text(
                artifact, ("method", "approach", "model", "architecture")
            )
        if field == "research_questions":
            return PaperComparisonWorkflow._section_text(
                artifact, ("abstract", "introduction", "motivation")
            )
        if field == "training_strategy":
            return PaperComparisonWorkflow._section_text(
                artifact, ("training", "implementation", "optimization")
            )
        if field == "datasets_and_metrics":
            return PaperComparisonWorkflow._section_text(
                artifact, ("dataset", "benchmark", "experiment", "evaluation")
            )
        return "unknown"

    @staticmethod
    def _section_text(artifact: PaperArtifact, keywords: tuple[str, ...]) -> str:
        selected = [
            section.original_text.strip()
            for section in artifact.sections
            if any(keyword in section.title.casefold() for keyword in keywords)
            and section.original_text.strip()
        ]
        return " ".join(selected)[:1600] if selected else "unknown"

    @staticmethod
    def _metadata_text(metadata: dict[str, Any], field: str) -> str:
        value = metadata.get(field)
        if isinstance(value, list):
            return "; ".join(str(item) for item in value) if value else "unknown"
        return str(value) if value not in (None, "") else "unknown"

    @staticmethod
    def _list_of_strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value] if value else []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item not in (None, "")]

    @classmethod
    def _build_matrix(
        cls,
        dimensions: list[str],
        facts: list[ComparisonPaperFacts],
    ) -> list[ComparisonMatrixRow]:
        field_map = {
            "研究问题": "problem_definition",
            "核心方法": "methodology_summary",
            "训练策略": "training_strategy",
            "数据集与评价指标": "datasets_and_metrics",
            "实验结果": "reported_results",
            "优点与局限": "limitations",
        }
        rows: list[ComparisonMatrixRow] = []
        for dimension in dimensions:
            field = field_map.get(dimension)
            values: dict[str, str] = {}
            for paper in facts:
                value = getattr(paper, field, "unknown") if field else "unknown"
                if isinstance(value, list):
                    value = "; ".join(value) if value else "unknown"
                values[paper.paper_id] = str(value or "unknown")
            rows.append(ComparisonMatrixRow(dimension=dimension, values=values))
        return rows

    @staticmethod
    def _missing_information(facts: list[ComparisonPaperFacts]) -> list[str]:
        missing: list[str] = []
        for paper in facts:
            for field in (
                "problem_definition",
                "methodology_summary",
                "training_strategy",
                "datasets_and_metrics",
            ):
                if getattr(paper, field) == "unknown":
                    missing.append(f"{paper.paper_id}:{field}")
        return list(dict.fromkeys(missing))

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .models.paper_artifact import PaperArtifact
from .models.paper_comparison import (
    PaperConflict,
    PaperReference,
    normalize_arxiv_id,
)
from .models.paper_candidate import PaperCandidate


MetadataFetcher = Callable[[PaperReference], Awaitable[dict[str, Any]]]
PdfFetcher = Callable[[PaperReference, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class PaperAcquisitionResult:
    paper_id: str
    metadata: dict[str, Any]
    artifact: Optional[PaperArtifact] = None
    artifact_path: Optional[str] = None
    pdf_path: Optional[str] = None
    source: str = "unknown"
    reused: bool = False
    reuse_level: str = "none"
    reused_from_task_id: Optional[str] = None
    available_stages: tuple[str, ...] = ()
    conflicts: tuple[PaperConflict, ...] = ()


class PaperAcquisitionService:
    """Resolve local paper resources before falling back to online fetchers."""

    def __init__(
        self,
        *,
        search_roots: Optional[list[Path]] = None,
        metadata_fetcher: Optional[MetadataFetcher] = None,
        pdf_fetcher: Optional[PdfFetcher] = None,
    ):
        self.search_roots = [Path(path) for path in (search_roots or [])]
        self.metadata_fetcher = metadata_fetcher
        self.pdf_fetcher = pdf_fetcher

    async def acquire(self, reference: PaperReference) -> PaperAcquisitionResult:
        identity = reference.identity
        artifact_candidates = self._find_artifact_candidates(reference, identity)
        if artifact_candidates:
            artifact_path, artifact = artifact_candidates[0]
            conflicts = self._artifact_conflicts(
                identity,
                reference,
                artifact_path,
                artifact,
                artifact_candidates,
            )
            artifact = self._merge_artifacts(artifact, artifact_candidates[1:])
            available_stages = self._available_stages(artifact)
            return PaperAcquisitionResult(
                paper_id=identity or artifact.arxiv_id or artifact.candidate_id,
                metadata=self._artifact_metadata(artifact),
                artifact=artifact,
                artifact_path=str(artifact_path),
                pdf_path=self._resolve_pdf_path(artifact_path, artifact.pdf_path),
                source="local",
                reused=True,
                reuse_level=(
                    "paper_artifact_complete"
                    if len(available_stages) >= 5
                    else "paper_artifact_partial"
                ),
                reused_from_task_id=self._task_id_from_path(artifact_path),
                available_stages=available_stages,
                conflicts=tuple(conflicts),
            )

        pdf_path = self._find_pdf(reference, identity)
        if pdf_path is not None:
            metadata = await self._fetch_metadata(reference)
            conflicts = self._metadata_conflicts(identity, reference, metadata)
            return PaperAcquisitionResult(
                paper_id=identity or str(metadata.get("arxiv_id") or reference.title),
                metadata=metadata,
                pdf_path=str(pdf_path),
                source="local",
                reused=True,
                reuse_level="pdf",
                reused_from_task_id=self._task_id_from_path(pdf_path),
                conflicts=tuple(conflicts),
            )

        metadata = await self._fetch_metadata(reference)
        if self.pdf_fetcher is None:
            conflicts = self._metadata_conflicts(identity, reference, metadata)
            return PaperAcquisitionResult(
                paper_id=identity or str(metadata.get("arxiv_id") or reference.title),
                metadata=metadata,
                source="arxiv" if self.metadata_fetcher else "unknown",
                reused=False,
                reuse_level="metadata",
                conflicts=tuple(conflicts),
            )

        downloaded = await self.pdf_fetcher(reference, metadata)
        conflicts = self._metadata_conflicts(identity, reference, metadata)
        return PaperAcquisitionResult(
            paper_id=identity or str(downloaded.get("arxiv_id") or metadata.get("arxiv_id") or reference.title),
            metadata={**metadata, **downloaded},
            pdf_path=downloaded.get("pdf_path"),
            artifact_path=downloaded.get("artifact_path"),
            source=str(downloaded.get("source") or "arxiv"),
            reused=False,
            reuse_level="downloaded",
            conflicts=tuple(conflicts),
        )

    async def _fetch_metadata(self, reference: PaperReference) -> dict[str, Any]:
        if self.metadata_fetcher is None:
            candidate = PaperCandidate(
                arxiv_id=reference.arxiv_id,
                title=reference.title or "",
                url=reference.url or (
                    f"https://arxiv.org/abs/{reference.arxiv_id}"
                    if reference.arxiv_id
                    else "https://arxiv.org"
                ),
            )
            return candidate.model_dump(mode="json")
        return await self.metadata_fetcher(reference)

    def _find_artifact_candidates(
        self,
        reference: PaperReference,
        identity: str,
    ) -> list[tuple[Path, PaperArtifact]]:
        candidates: list[Path] = []
        if reference.local_artifact_path:
            candidates.append(Path(reference.local_artifact_path))
        for root in self.search_roots:
            if identity:
                candidates.extend(root.glob(f"**/{identity}*.json"))
        valid: list[tuple[int, float, Path, PaperArtifact]] = []
        for path in candidates:
            if path.is_file():
                try:
                    data = self._load_json(path)
                    artifact_id = normalize_arxiv_id(
                        data.get("arxiv_id") or data.get("candidate_id")
                    )
                    if reference.local_artifact_path and identity and artifact_id != identity:
                        raise ValueError(
                            f"local artifact identity mismatch: expected {identity}, got {artifact_id}"
                        )
                    if identity and artifact_id != identity:
                        continue
                    if not identity and not artifact_id:
                        continue
                    artifact = PaperArtifact.model_validate(data)
                    valid.append(
                        (
                            self._artifact_quality(artifact),
                            path.stat().st_mtime,
                            path,
                            artifact,
                        )
                    )
                except ValueError:
                    if reference.local_artifact_path:
                        raise
                    continue
                except (OSError, TypeError):
                    continue
        if not valid:
            return []
        valid.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [(item[2], item[3]) for item in valid]

    def _find_artifact(self, reference: PaperReference, identity: str) -> Optional[Path]:
        candidates = self._find_artifact_candidates(reference, identity)
        return candidates[0][0] if candidates else None

    def _find_pdf(self, reference: PaperReference, identity: str) -> Optional[Path]:
        candidates: list[Path] = []
        if reference.local_pdf_path:
            candidates.append(Path(reference.local_pdf_path))
        for root in self.search_roots:
            if identity:
                candidates.extend(root.glob(f"**/{identity}*.pdf"))
        return next((path for path in candidates if path.is_file()), None)

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        import json

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"paper artifact must be an object: {path}")
        return data

    @classmethod
    def _load_artifact(cls, path: Path, identity: str) -> PaperArtifact:
        artifact = PaperArtifact.model_validate(cls._load_json(path))
        artifact_id = normalize_arxiv_id(artifact.arxiv_id or artifact.candidate_id)
        if identity and artifact_id != identity:
            raise ValueError(
                f"local paper artifact identity mismatch: expected {identity}, got {artifact_id}"
            )
        return artifact

    @staticmethod
    def _resolve_pdf_path(artifact_path: Path, pdf_path: Optional[str]) -> Optional[str]:
        if not pdf_path:
            return None
        candidate = Path(pdf_path)
        if not candidate.is_absolute():
            candidate = artifact_path.parent.parent / candidate
            if not candidate.exists():
                candidate = artifact_path.parent / pdf_path
        return str(candidate) if candidate.exists() else None

    @staticmethod
    def _artifact_metadata(artifact: PaperArtifact) -> dict[str, Any]:
        return {
            "arxiv_id": artifact.arxiv_id,
            "title": artifact.title,
            "authors": artifact.authors,
            "published_date": artifact.published_date,
            "version": artifact.version,
            "abstract": artifact.abstract,
            "url": f"https://arxiv.org/abs/{artifact.arxiv_id}" if artifact.arxiv_id else None,
            "source": "local",
        }

    @staticmethod
    def _artifact_quality(artifact: PaperArtifact) -> int:
        """Rank artifacts by how much of P10-P14 has already completed."""
        score = 0
        if artifact.pdf_path:
            score += 1
        if artifact.sections:
            score += 1
        if artifact.glossary:
            score += 1
        if any(section.translated_text for section in artifact.sections):
            score += 1
        if artifact.full_text_translated:
            score += 1
        if (
            artifact.research_questions
            or artifact.methodology_summary
            or artifact.contributions
            or artifact.conclusions
            or artifact.limitations
        ):
            score += 1
        if artifact.summary_evidence:
            score += 1
        return score

    @staticmethod
    def _available_stages(artifact: PaperArtifact) -> tuple[str, ...]:
        stages: list[str] = []
        if artifact.pdf_path:
            stages.append("download")
        if artifact.sections or artifact.full_text_original:
            stages.append("parse")
        if artifact.glossary:
            stages.append("glossary")
        if artifact.full_text_translated or any(
            section.translated_text for section in artifact.sections
        ):
            stages.append("translate")
        if (
            artifact.research_questions
            or artifact.methodology_summary
            or artifact.contributions
            or artifact.conclusions
            or artifact.limitations
        ):
            stages.append("summary")
        return tuple(stages)

    @staticmethod
    def _task_id_from_path(path: Path) -> Optional[str]:
        # Standard layout: <artifact_root>/<task_id>/papers/<paper>.json.
        if path.parent.name == "papers" and path.parent.parent.name:
            return path.parent.parent.name
        return None

    @classmethod
    def _artifact_conflicts(
        cls,
        identity: str,
        reference: PaperReference,
        selected_path: Path,
        selected: PaperArtifact,
        candidates: list[tuple[Path, PaperArtifact]],
    ) -> list[PaperConflict]:
        conflicts: list[PaperConflict] = []
        if reference.title and selected.title and cls._norm_text(reference.title) != cls._norm_text(selected.title):
            conflicts.append(
                PaperConflict(
                    paper_id=identity,
                    field="title",
                    values={"reference": reference.title, "local_artifact": selected.title},
                    severity="warning",
                    resolution="selected local artifact title",
                    selected_source=str(selected_path),
                )
            )
        fields = ("title", "version", "methodology_summary", "conclusions")
        for field in fields:
            values: dict[str, str] = {}
            for path, artifact in candidates:
                value = getattr(artifact, field, None)
                if isinstance(value, list):
                    value = "; ".join(str(item) for item in value)
                if value not in (None, ""):
                    values[str(path)] = str(value)
            if len({cls._norm_text(value) for value in values.values()}) > 1:
                conflicts.append(
                    PaperConflict(
                        paper_id=identity,
                        field=field,
                        values=values,
                        severity="info" if field == "version" else "warning",
                        resolution=f"selected highest-completeness artifact {field}",
                        selected_source=str(selected_path),
                    )
                )
        return conflicts

    @classmethod
    def _metadata_conflicts(
        cls,
        identity: str,
        reference: PaperReference,
        metadata: dict[str, Any],
    ) -> list[PaperConflict]:
        if (
            reference.title
            and metadata.get("title")
            and cls._norm_text(reference.title) != cls._norm_text(metadata["title"])
        ):
            return [
                PaperConflict(
                    paper_id=identity,
                    field="title",
                    values={
                        "reference": reference.title,
                        "metadata": str(metadata["title"]),
                    },
                    severity="warning",
                    resolution="selected fetched metadata title",
                    selected_source="metadata_fetcher",
                )
            ]
        return []

    @staticmethod
    def _merge_artifacts(
        selected: PaperArtifact,
        alternatives: list[tuple[Path, PaperArtifact]],
    ) -> PaperArtifact:
        """Fill only absent fields; never overwrite the selected source."""
        merged = selected.model_copy(deep=True)
        for _, alternative in alternatives:
            if not merged.title and alternative.title:
                merged.title = alternative.title
            if not merged.authors and alternative.authors:
                merged.authors = list(alternative.authors)
            if not merged.sections and alternative.sections:
                merged.sections = list(alternative.sections)
            if not merged.glossary and alternative.glossary:
                merged.glossary = list(alternative.glossary)
            for field in (
                "pdf_path",
                "full_text_original",
                "full_text_translated",
                "methodology_summary",
            ):
                if not getattr(merged, field) and getattr(alternative, field):
                    setattr(merged, field, getattr(alternative, field))
            for field in (
                "research_questions",
                "contributions",
                "conclusions",
                "limitations",
            ):
                if not getattr(merged, field) and getattr(alternative, field):
                    setattr(merged, field, list(getattr(alternative, field)))
            if not merged.summary_evidence and alternative.summary_evidence:
                merged.summary_evidence = dict(alternative.summary_evidence)
        return merged

    @staticmethod
    def _norm_text(value: Any) -> str:
        return " ".join(str(value).split()).casefold()

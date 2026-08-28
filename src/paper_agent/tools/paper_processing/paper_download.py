from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from ...common.models.paper_artifact import PaperArtifact
from ...common.persistence import StatePersistence
from ...common.tools.base import BaseTool, ToolResult
from ..retrieval.arxiv_tool import ArxivGetPaperTool


_ARXIV_ID_RE = re.compile(r"(?P<base>\d{4}\.\d{4,5})(?P<version>v\d+)?$")


class PaperDownloadTool(BaseTool):
    name = "paper_download"
    description = (
        "Download and validate an arXiv PDF for a task. "
        "Parameters: task_id (required), arxiv_id or paper (required). "
        "The paper may contain arxiv_id, pdf_url, title, authors, published_date, "
        "doi, abstract and version."
    )

    def __init__(self, persistence: Optional[StatePersistence] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.persistence = persistence or StatePersistence()

    async def _execute(self, **kwargs: Any) -> ToolResult:
        task_id = kwargs.get("task_id")
        if not task_id:
            return ToolResult.fail(error="Missing required parameter: task_id")

        candidate = kwargs.get("paper")
        if candidate is not None and not isinstance(candidate, dict):
            return ToolResult.fail(error="paper must be an object")
        candidate = candidate or {}

        raw_arxiv_id = candidate.get("arxiv_id") or kwargs.get("arxiv_id")
        pdf_url = candidate.get("pdf_url") or kwargs.get("pdf_url")
        arxiv_id = self._normalize_arxiv_id(raw_arxiv_id)
        if not arxiv_id and pdf_url:
            arxiv_id = self._arxiv_id_from_pdf_url(pdf_url)
        if not arxiv_id:
            return ToolResult.fail(error="Missing usable arXiv identifier or PDF URL")

        if pdf_url:
            if not self._is_arxiv_pdf_url(pdf_url):
                return ToolResult.fail(error="PDF URL must be an arXiv PDF URL")
            url_arxiv_id = self._arxiv_id_from_pdf_url(pdf_url)
            if url_arxiv_id and url_arxiv_id != arxiv_id:
                return ToolResult.fail(error="PDF URL arXiv identifier does not match paper identifier")
        else:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

        metadata = dict(candidate)
        if not metadata.get("title") or not metadata.get("authors"):
            metadata_result = await ArxivGetPaperTool()._execute(arxiv_id=arxiv_id)
            if not metadata_result.success:
                return ToolResult.fail(error=f"Failed to fetch paper metadata: {metadata_result.error}")
            metadata = {**metadata_result.data, **metadata}

        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                response = await client.get(pdf_url)
                response.raise_for_status()
        except Exception as exc:
            return ToolResult.fail(error=f"Failed to download paper PDF: {exc}")

        content = response.content
        content_type = response.headers.get("content-type", "").lower()
        if not content or not content.startswith(b"%PDF-") or "text/html" in content_type:
            return ToolResult.fail(error="Downloaded content is not a valid non-empty PDF")

        version = self._version_from_id(arxiv_id)
        relative_pdf_path = f"papers/{arxiv_id}.pdf"
        artifact = PaperArtifact(
            research_spec_id=task_id,
            candidate_id=arxiv_id,
            arxiv_id=arxiv_id,
            doi=metadata.get("doi"),
            title=metadata.get("title", ""),
            authors=metadata.get("authors", []),
            published_date=metadata.get("published_date"),
            version=version,
            abstract=str(metadata.get("abstract") or metadata.get("summary") or ""),
            pdf_path=relative_pdf_path,
            pdf_source="arxiv",
        )

        try:
            await self.persistence.save_paper_artifact(
                task_id, artifact, content, relative_pdf_path
            )
        except Exception as exc:
            return ToolResult.fail(error=f"Failed to persist paper artifact: {exc}")

        return ToolResult.ok(
            data={
                "paper_artifact_id": artifact.id,
                "arxiv_id": arxiv_id,
                "version": version,
                "pdf_path": relative_pdf_path,
                "artifact_path": f"papers/{arxiv_id}.json",
                "size_bytes": len(content),
                "source": "arxiv",
            }
        )

    @staticmethod
    def _normalize_arxiv_id(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        value = value.strip()
        match = _ARXIV_ID_RE.fullmatch(value)
        if not match:
            return None
        return f"{match.group('base')}{match.group('version') or 'v1'}"

    @classmethod
    def _arxiv_id_from_pdf_url(cls, value: Any) -> Optional[str]:
        if not isinstance(value, str) or not cls._is_arxiv_pdf_url(value):
            return None
        path_id = urlparse(value).path.removeprefix("/pdf/").removesuffix(".pdf")
        return cls._normalize_arxiv_id(path_id)

    @staticmethod
    def _is_arxiv_pdf_url(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"arxiv.org", "export.arxiv.org"}
            and parsed.path.startswith("/pdf/")
        )

    @staticmethod
    def _version_from_id(arxiv_id: str) -> str:
        return arxiv_id.rsplit("v", 1)[1]

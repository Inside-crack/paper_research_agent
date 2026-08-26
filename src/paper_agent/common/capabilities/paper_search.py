from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..models.paper_candidate import PaperCandidate
from ..tools import ToolRegistry
from .base import CapabilityAdapter, CapabilityResult, ExecutionContext
from .search_query import rank_search_candidates
from .terminology import TerminologyService


class PaperSearchAdapter(CapabilityAdapter):
    """Expose arXiv search and single-paper lookup as one capability."""

    name = "paper_search"

    def __init__(
        self,
        tool_registry: ToolRegistry,
        terminology_service: TerminologyService | None = None,
    ):
        super().__init__(tool_registry)
        self.terminology_service = terminology_service

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        if not isinstance(context, ExecutionContext):
            return CapabilityResult.failed("context must be an ExecutionContext")
        if not isinstance(arguments, dict):
            return CapabilityResult.failed("arguments must be an object")

        arxiv_id = arguments.get("arxiv_id")
        query = arguments.get("query")
        if arxiv_id is not None:
            if not isinstance(arxiv_id, str) or not arxiv_id.strip():
                return CapabilityResult.failed("arxiv_id must be a non-empty string")
        elif not isinstance(query, str) or not query.strip():
            return CapabilityResult.failed("Missing required parameter: query")

        tool_name: str
        tool_arguments: dict[str, Any]
        discovered_terms = []
        query_variants = []
        if arxiv_id is not None:
            tool_name = "arxiv_get_paper"
            tool_arguments = {"arxiv_id": arxiv_id.strip()}
        else:
            max_results = arguments.get("max_results", 10)
            if isinstance(max_results, bool) or not isinstance(max_results, int):
                return CapabilityResult.failed("max_results must be an integer")
            if max_results <= 0:
                return CapabilityResult.failed("max_results must be greater than 0")

            categories = arguments.get("categories", [])
            if not isinstance(categories, list) or not all(
                isinstance(category, str) and category.strip() for category in categories
            ):
                return CapabilityResult.failed("categories must be a list of non-empty strings")

            search_query = query.strip()
            if self.terminology_service is not None:
                query_variants, discovered_terms = (
                    await self.terminology_service.expand_queries(
                        search_query,
                        max_queries=3,
                    )
                )
            else:
                query_variants = [search_query]
            tool_name = "arxiv_search"
            tool_arguments = {
                "query": query_variants[0],
                "max_results": max_results,
                "categories": categories,
            }
            for optional_name in ("date_from", "date_to", "sort_by"):
                if optional_name in arguments and arguments[optional_name] is not None:
                    tool_arguments[optional_name] = arguments[optional_name]

        if tool_name == "arxiv_get_paper":
            tool_result = await self.tool_registry.execute(tool_name, **tool_arguments)
            if not tool_result.success:
                return CapabilityResult.failed(
                    tool_result.error or f"{tool_name} failed",
                    next_actions=["修改检索条件后重试"],
                )
            raw_results = [tool_result.data]
        else:
            raw_results = []
            errors = []
            for variant in query_variants:
                variant_arguments = dict(tool_arguments, query=variant)
                tool_result = await self.tool_registry.execute(
                    tool_name,
                    **variant_arguments,
                )
                if tool_result.success:
                    raw_results.append(tool_result.data)
                else:
                    errors.append(tool_result.error or f"{tool_name} failed")
            if not raw_results:
                return CapabilityResult.failed(
                    errors[-1] if errors else f"{tool_name} failed",
                    next_actions=["修改检索条件后重试"],
                )

        try:
            candidates = []
            for result_data in raw_results:
                candidates.extend(self._normalize_candidates(tool_name, result_data))
            raw_candidate_count = len(candidates)
            candidates = self._deduplicate_candidates(candidates)
            if tool_name == "arxiv_search":
                candidates = rank_search_candidates(
                    candidates,
                    " ".join(query_variants),
                )
        except (TypeError, ValueError, ValidationError) as exc:
            return CapabilityResult.failed(f"Invalid {tool_name} output: {exc}")

        return CapabilityResult.succeeded(
            data={
                "query": (
                    " ".join(query_variants)
                    if tool_name == "arxiv_search"
                    else query.strip() if isinstance(query, str) else None
                ),
                "total": len(candidates),
                "candidates": candidates,
                "selected_paper": None,
                "query_variants": query_variants,
                "discovered_terms": [
                    entry.model_dump(mode="json") for entry in discovered_terms
                ],
                "search_metadata": {
                    "original_query": query.strip()
                    if isinstance(query, str)
                    else None,
                    "query_variant_count": len(query_variants),
                    "raw_candidate_count": raw_candidate_count,
                    "deduplicated_count": raw_candidate_count - len(candidates),
                    "ranking": "title_match_3x_abstract_match_1x",
                },
            },
            next_actions=["从候选论文中选择一篇"] if candidates else ["修改检索条件后重试"],
        )

    @staticmethod
    def _deduplicate_candidates(
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduplicated: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            key = candidate.get("arxiv_id") or candidate.get("url")
            if not key:
                key = f"{candidate.get('title', '')}:{candidate.get('published_date', '')}"
            current = deduplicated.get(str(key))
            if current is None or candidate.get("relevance_score", 0) > current.get(
                "relevance_score", 0
            ):
                deduplicated[str(key)] = candidate
        return list(deduplicated.values())

    @staticmethod
    def _normalize_candidates(tool_name: str, data: Any) -> list[dict[str, Any]]:
        if tool_name == "arxiv_search":
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise ValueError("expected an object with a results list")
            raw_candidates = data["results"]
        else:
            if not isinstance(data, dict):
                raise ValueError("expected a paper object")
            raw_candidates = [data]

        candidates: list[dict[str, Any]] = []
        for index, raw_candidate in enumerate(raw_candidates):
            if not isinstance(raw_candidate, dict):
                raise ValueError(f"candidate at index {index} must be an object")
            candidate = PaperCandidate.model_validate(raw_candidate)
            candidates.append(candidate.model_dump(mode="json"))
        return candidates

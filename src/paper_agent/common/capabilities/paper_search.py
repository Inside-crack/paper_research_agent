from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..models.paper_candidate import PaperCandidate
from ..tools import ToolRegistry
from .base import CapabilityAdapter, CapabilityResult, ExecutionContext


class PaperSearchAdapter(CapabilityAdapter):
    """Expose arXiv search and single-paper lookup as one capability."""

    name = "paper_search"

    def __init__(self, tool_registry: ToolRegistry):
        super().__init__(tool_registry)

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

            tool_name = "arxiv_search"
            tool_arguments = {
                "query": query.strip(),
                "max_results": max_results,
                "categories": categories,
            }
            for optional_name in ("date_from", "date_to", "sort_by"):
                if optional_name in arguments and arguments[optional_name] is not None:
                    tool_arguments[optional_name] = arguments[optional_name]

        tool_result = await self.tool_registry.execute(tool_name, **tool_arguments)
        if not tool_result.success:
            return CapabilityResult.failed(
                tool_result.error or f"{tool_name} failed",
                next_actions=["修改检索条件后重试"],
            )

        try:
            candidates = self._normalize_candidates(tool_name, tool_result.data)
        except (TypeError, ValueError, ValidationError) as exc:
            return CapabilityResult.failed(f"Invalid {tool_name} output: {exc}")

        return CapabilityResult.succeeded(
            data={
                "query": query.strip() if isinstance(query, str) else None,
                "total": len(candidates),
                "candidates": candidates,
                "selected_paper": None,
            },
            next_actions=["从候选论文中选择一篇"] if candidates else ["修改检索条件后重试"],
        )

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

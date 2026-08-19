from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

import arxiv

from ...common.config import get_settings
from ...common.logging import get_logger
from ...common.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class ArxivSearchTool(BaseTool):
    name = "arxiv_search"
    description = (
        "Search arXiv for academic papers. "
        "Parameters: query (str, required, search keywords), max_results (int, optional, default 20), "
        "categories (list[str], optional, e.g. ['cs.AI','cs.LG']), "
        "date_from (str, optional, format YYYY-MM-DD), date_to (str, optional), "
        "sort_by (str, optional: 'relevance'|'submitted_date', default 'relevance'). "
        "Returns: list of papers with arxiv_id, title, authors, abstract, pdf_url, published_date, categories."
    )

    async def _execute(self, **kwargs: Any) -> ToolResult:
        settings = get_settings()

        query = kwargs.get("query", "")
        if not query:
            return ToolResult.fail(error="Missing required parameter: query")

        requested_max_results = kwargs.get("max_results", 20)
        if requested_max_results <= 0:
            return ToolResult.fail(error="max_results must be greater than 0")
        max_results = min(requested_max_results, settings.retrieval.arxiv_max_results)
        categories = kwargs.get("categories")
        date_from = kwargs.get("date_from")
        date_to = kwargs.get("date_to")
        sort_by = kwargs.get("sort_by", "relevance")

        sort_criteria = {
            "relevance": arxiv.SortCriterion.Relevance,
            "submitted_date": arxiv.SortCriterion.SubmittedDate,
            "last_updated_date": arxiv.SortCriterion.LastUpdatedDate,
        }
        sort_criterion = sort_criteria.get(sort_by, arxiv.SortCriterion.Relevance)

        search_query = query
        if categories:
            cat_query = " OR ".join([f"cat:{cat}" for cat in categories])
            if search_query:
                search_query = f"({search_query}) AND ({cat_query})"
            else:
                search_query = cat_query

        try:
            loop = asyncio.get_event_loop()

            def _search():
                search = arxiv.Search(
                    query=search_query,
                    max_results=max_results,
                    sort_by=sort_criterion,
                    sort_order=arxiv.SortOrder.Descending,
                )
                client = arxiv.Client(page_size=max_results, delay_seconds=settings.retrieval.arxiv_wait_seconds)
                results = []
                for result in client.results(search):
                    paper = self._convert_result(result)
                    if date_from:
                        if paper["published_date"] < date_from:
                            continue
                    if date_to:
                        if paper["published_date"] > date_to:
                            continue
                    results.append(paper)
                return results

            results = await loop.run_in_executor(None, _search)

            logger.info(f"arXiv search returned {len(results)} results for query: {query[:100]}")

            return ToolResult.ok(data={
                "query": query,
                "total_found": len(results),
                "results": results,
            })

        except Exception as e:
            logger.exception(f"arXiv search failed: {e}")
            return ToolResult.fail(error=f"arXiv search error: {str(e)}")

    def _convert_result(self, result: arxiv.Result) -> dict[str, Any]:
        published = result.published.strftime("%Y-%m-%d") if result.published else None
        updated = result.updated.strftime("%Y-%m-%d") if result.updated else None

        categories = []
        if result.categories:
            categories = list(result.categories)

        authors = []
        if result.authors:
            authors = [a.name for a in result.authors]

        pdf_url = None
        if result.pdf_url:
            pdf_url = result.pdf_url

        code_available = False
        code_url = None
        if result.links:
            for link in result.links:
                if "github" in link.href.lower() or "gitlab" in link.href.lower():
                    code_available = True
                    code_url = link.href
                    break

        return {
            "arxiv_id": result.get_short_id(),
            "entry_id": result.entry_id,
            "title": result.title,
            "authors": authors,
            "abstract": result.summary.replace("\n", " "),
            "pdf_url": pdf_url,
            "url": result.entry_id,
            "published_date": published,
            "updated_date": updated,
            "doi": result.doi,
            "journal_ref": result.journal_ref,
            "comment": result.comment,
            "categories": categories,
            "primary_category": result.primary_category,
            "version": result.get_short_id().split("v")[-1] if "v" in result.get_short_id() else "1",
            "links": [l.href for l in result.links],
            "code_available_hint": code_available,
            "code_url_hint": code_url,
            "source": "arxiv",
        }


class ArxivGetPaperTool(BaseTool):
    name = "arxiv_get_paper"
    description = (
        "Fetch a specific arXiv paper by its ID. "
        "Parameters: arxiv_id (str, required, e.g. '2210.03629' or '2210.03629v3'). "
        "Returns: full paper metadata including title, authors, abstract, pdf_url."
    )

    async def _execute(self, **kwargs: Any) -> ToolResult:
        arxiv_id = kwargs.get("arxiv_id")
        if not arxiv_id:
            return ToolResult.fail(error="Missing required parameter: arxiv_id")

        try:
            loop = asyncio.get_event_loop()

            def _fetch():
                client = arxiv.Client()
                search = arxiv.Search(id_list=[arxiv_id])
                for result in client.results(search):
                    return result
                return None

            result = await loop.run_in_executor(None, _fetch)

            if result is None:
                return ToolResult.fail(error=f"Paper not found: {arxiv_id}")

            paper_data = ArxivSearchTool()._convert_result(result)
            return ToolResult.ok(data=paper_data)

        except Exception as e:
            return ToolResult.fail(error=f"Failed to fetch paper {arxiv_id}: {str(e)}")

from __future__ import annotations

import re
from typing import Any, Iterable

from .models.paper_candidate import PaperCandidate, PaperRetrievalArtifact
from .models.execution_plan import ExecutionPlan


_ARXIV_ID_PATTERN = re.compile(
    r"(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)


def normalize_arxiv_id(value: Any) -> str:
    """Return a version-independent arXiv identity for deduplication."""
    if not isinstance(value, str):
        return ""
    match = _ARXIV_ID_PATTERN.search(value.strip())
    return match.group("id").split("v", 1)[0] if match else ""


def _display_arxiv_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    match = _ARXIV_ID_PATTERN.search(value.strip())
    return match.group("id") if match else value.strip()


def _candidate_from_raw(raw: dict[str, Any]) -> PaperCandidate | None:
    data = dict(raw)
    arxiv_id = _display_arxiv_id(data.get("arxiv_id") or data.get("url"))
    if arxiv_id:
        data["arxiv_id"] = arxiv_id
        data.setdefault("url", f"https://arxiv.org/abs/{arxiv_id}")
        data.setdefault("pdf_url", f"https://arxiv.org/pdf/{arxiv_id}.pdf")
    if not data.get("title") or not data.get("url"):
        return None
    try:
        return PaperCandidate.model_validate(data)
    except (TypeError, ValueError):
        return None


def _tool_candidates(plan: ExecutionPlan) -> tuple[list[PaperCandidate], list[str]]:
    candidates: list[PaperCandidate] = []
    queries: list[str] = []
    for step in plan.steps:
        if not step.success or not isinstance(step.result, dict):
            continue
        if step.tool_name == "arxiv_get_paper":
            candidate = _candidate_from_raw(step.result)
            if candidate:
                candidates.append(candidate)
        elif step.tool_name == "arxiv_search":
            query = step.result.get("query")
            if isinstance(query, str) and query:
                queries.append(query)
            for raw in step.result.get("results", []):
                if isinstance(raw, dict):
                    candidate = _candidate_from_raw(raw)
                    if candidate:
                        candidates.append(candidate)
    return candidates, queries


def _merge_candidates(
    candidates: Iterable[PaperCandidate],
    *,
    target_key: str,
) -> list[PaperCandidate]:
    merged: dict[str, PaperCandidate] = {}
    exact_target: PaperCandidate | None = None

    for candidate in candidates:
        key = normalize_arxiv_id(candidate.arxiv_id) or candidate.url
        if not key:
            continue
        if key == target_key:
            if exact_target is None:
                exact_target = candidate
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = candidate
        else:
            # Search results are weaker than a later, richer exact result.
            merged[key] = _merge_facts(current, candidate)

    result = list(merged.values())
    if exact_target is not None:
        result.insert(0, exact_target)
    return result


def _merge_facts(current: PaperCandidate, incoming: PaperCandidate) -> PaperCandidate:
    data = current.model_dump(mode="python")
    incoming_data = incoming.model_dump(mode="python")
    for field in (
        "abstract",
        "authors",
        "doi",
        "pdf_url",
        "published_date",
        "version",
        "code_url",
        "code_evidence_sources",
        "license",
        "data_evidence_source",
    ):
        value = incoming_data.get(field)
        if value and not data.get(field):
            data[field] = value
    if data.get("code_available") is None:
        data["code_available"] = incoming_data.get("code_available")
    if data.get("data_available") is None:
        data["data_available"] = incoming_data.get("data_available")
    return PaperCandidate.model_validate(data)


def _apply_llm_ranking(
    candidates: list[PaperCandidate],
    llm_output: dict[str, Any],
) -> list[PaperCandidate]:
    ranking_by_id: dict[str, dict[str, Any]] = {}
    for item in llm_output.get("classifications", []):
        if isinstance(item, dict):
            key = normalize_arxiv_id(item.get("arxiv_id"))
            if key:
                ranking_by_id[key] = item

    updated: list[PaperCandidate] = []
    for candidate in candidates:
        item = ranking_by_id.get(normalize_arxiv_id(candidate.arxiv_id))
        if not item:
            updated.append(candidate)
            continue
        data = candidate.model_dump(mode="python")
        if item.get("type") in {"survey", "method", "benchmark", "application", "experimental"}:
            data["paper_type"] = item["type"]
        if isinstance(item.get("relevance_score"), (int, float)):
            data["relevance_score"] = max(0.0, min(1.0, float(item["relevance_score"])))
        if isinstance(item.get("reproducibility_score"), (int, float)):
            data["reproducibility_score"] = max(
                0.0, min(1.0, float(item["reproducibility_score"]))
            )
        elif candidate.code_available is True:
            data["reproducibility_score"] = 1.0
        elif candidate.code_available is None:
            data["reproducibility_score"] = 0.5
        if isinstance(item.get("recency_score"), (int, float)):
            data["recency_score"] = max(0.0, min(1.0, float(item["recency_score"])))
        reason = item.get("reason")
        if isinstance(reason, str):
            data["selection_rationale"] = reason[:300]
        updated.append(PaperCandidate.model_validate(data))

    return updated


def _order_candidates(
    candidates: list[PaperCandidate],
    ordered_ids: Any,
    target_key: str,
) -> list[PaperCandidate]:
    by_key = {
        normalize_arxiv_id(candidate.arxiv_id): candidate
        for candidate in candidates
        if normalize_arxiv_id(candidate.arxiv_id)
    }
    ordered: list[PaperCandidate] = []
    used: set[str] = set()
    if isinstance(ordered_ids, list):
        for value in ordered_ids:
            key = normalize_arxiv_id(value)
            candidate = by_key.get(key)
            if candidate and key not in used and key != target_key:
                ordered.append(candidate)
                used.add(key)

    remaining = [
        candidate
        for candidate in candidates
        if normalize_arxiv_id(candidate.arxiv_id) not in used
        and normalize_arxiv_id(candidate.arxiv_id) != target_key
    ]
    remaining.sort(
        key=lambda candidate: (
            candidate.relevance_score,
            candidate.reproducibility_score,
            candidate.recency_score,
        ),
        reverse=True,
    )
    target = by_key.get(target_key)
    return ([target] if target else []) + ordered + remaining


def build_paper_retrieval_artifact(
    plan: ExecutionPlan,
    llm_output: dict[str, Any] | None,
    *,
    target_arxiv_id: str,
) -> PaperRetrievalArtifact:
    """Build the final retrieval artifact from tool facts and bounded LLM ranking."""
    target_key = normalize_arxiv_id(target_arxiv_id)
    tool_candidates, queries = _tool_candidates(plan)
    exact_target = next(
        (
            _candidate_from_raw(step.result)
            for step in plan.steps
            if (
                step.tool_name == "arxiv_get_paper"
                and step.success
                and isinstance(step.result, dict)
                and normalize_arxiv_id(step.result.get("arxiv_id")) == target_key
            )
        ),
        None,
    )
    if exact_target is None:
        raise ValueError(f"Confirmed target paper was not fetched: {target_arxiv_id}")

    ranked = _apply_llm_ranking(
        _merge_candidates(tool_candidates, target_key=target_key),
        llm_output or {},
    )
    ranked = _order_candidates(
        ranked,
        (llm_output or {}).get("ordered_ids"),
        target_key,
    )
    ranked = ranked[:11]
    target = ranked[0]
    available_ids = {
        normalize_arxiv_id(candidate.arxiv_id): candidate.arxiv_id
        for candidate in ranked
        if candidate.arxiv_id
    }

    requested_ids = (llm_output or {}).get("ordered_ids", [])
    recommendations: list[str] = [target.arxiv_id or target_arxiv_id]
    if isinstance(requested_ids, list):
        for value in requested_ids:
            key = normalize_arxiv_id(value)
            if key in available_ids and available_ids[key] not in recommendations:
                recommendations.append(available_ids[key])
    if len(recommendations) == 1:
        recommendations.extend(
            candidate.arxiv_id
            for candidate in ranked[1:3]
            if candidate.arxiv_id
        )

    rationale = (llm_output or {}).get("ranking_rationale", "")
    return PaperRetrievalArtifact(
        target_paper=target,
        target_paper_verified=True,
        candidates=ranked,
        top_recommendations=recommendations,
        search_queries_used=queries,
        ranking_rationale=rationale[:1000] if isinstance(rationale, str) else "",
        total_found=len(tool_candidates),
        candidate_set_id="paper_candidates",
    )

from __future__ import annotations

import re
from typing import Any


_TERM_TRANSLATIONS = (
    ("多智能体协作", "multi-agent collaboration"),
    ("多智能体", "multi-agent"),
    ("人工智能", "artificial intelligence"),
    ("机器学习", "machine learning"),
    ("深度学习", "deep learning"),
    ("入侵检测", "intrusion detection"),
    ("入侵防御", "intrusion prevention"),
    ("网络安全", "cybersecurity"),
    ("网络攻击", "network attack"),
    ("恶意流量", "malicious traffic"),
    ("威胁检测", "threat detection"),
    ("防火墙", "firewall"),
    ("安全", "security"),
    ("检测", "detection"),
    ("结合", "integration"),
)

_QUERY_NOISE = re.compile(
    r"(?:帮我|请|找一下|查一下|搜索一下|检索一下|相关的|相关|论文|文章|"
    r"研究一下|介绍一下|与|和|的|一下)"
)


def normalize_search_query(query: str) -> str:
    """Turn common Chinese research requests into arXiv-friendly keywords."""
    normalized = query.strip()
    for source, target in _TERM_TRANSLATIONS:
        normalized = normalized.replace(source, f" {target} ")
    normalized = _QUERY_NOISE.sub(" ", normalized)
    normalized = re.sub(r"[，。,.：:；;！!？?、]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def rank_search_candidates(
    candidates: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """Stable rank by query-term matches, with title matches weighted higher."""
    terms = [
        term.casefold()
        for term in re.findall(r"[a-zA-Z][a-zA-Z0-9-]*", query)
        if len(term) > 1
    ]
    if not terms:
        return candidates

    scored: list[tuple[int, int, dict[str, Any]]] = []
    for position, candidate in enumerate(candidates):
        title = str(candidate.get("title") or "").casefold()
        abstract = str(candidate.get("abstract") or "").casefold()
        score = sum(3 for term in terms if term in title) + sum(
            1 for term in terms if term in abstract
        )
        enriched = dict(candidate)
        enriched["relevance_score"] = round(
            min(1.0, score / max(1, len(terms) * 3)),
            4,
        )
        scored.append((score, -position, enriched))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored]

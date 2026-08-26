from __future__ import annotations

import math
from typing import Iterable


def recall_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    if k <= 0 or not relevant:
        return 0.0
    return len(set(list(retrieved)[:k]) & relevant) / len(relevant)


def reciprocal_rank(retrieved: Iterable[str], relevant: set[str]) -> float:
    for index, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at_k(
    retrieved: Iterable[str],
    relevance: dict[str, float],
    k: int,
) -> float:
    if k <= 0 or not relevance:
        return 0.0
    values = [relevance.get(item, 0.0) for item in list(retrieved)[:k]]
    dcg = sum(
        (2**value - 1) / math.log2(index + 2)
        for index, value in enumerate(values)
    )
    ideal = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum(
        (2**value - 1) / math.log2(index + 2)
        for index, value in enumerate(ideal)
    )
    return dcg / idcg if idcg else 0.0

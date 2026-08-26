from __future__ import annotations

import json
import re
from typing import Any, Optional, TYPE_CHECKING

from ..llm import BaseLLM, LLMMessage, MessageRole
from ..models.terminology import TerminologyEntry, TerminologyTranslation
from .search_query import _TERM_TRANSLATIONS

if TYPE_CHECKING:
    from ..persistence.terminology_store import TerminologyStore


class LLMTermTranslator:
    """Translate one OOV academic term into a validated structured result."""

    def __init__(self, llm: BaseLLM):
        self.llm = llm

    async def extract_terms(
        self,
        query: str,
        *,
        candidates: list[str],
    ) -> Optional[list[dict[str, Any]]]:
        """Classify candidate spans before sending any term to translation."""
        prompt = (
            "Extract useful academic topic terms from a Chinese paper search query. "
            "Classify only the supplied candidate terms; do not add new terms. "
            "Mark query instructions, politeness, grammatical words, and generic "
            "search words as useful=false. Return JSON only with key terms, whose "
            "items have source_term, useful, role, confidence. "
            f"query={query!r}; candidates={candidates!r}"
        )
        try:
            response = await self.llm.agenerate(
                messages=[
                    LLMMessage(
                        role=MessageRole.SYSTEM,
                        content="You are an academic search term extraction expert.",
                    ),
                    LLMMessage(role=MessageRole.USER, content=prompt),
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("terms"), list):
                return None

            candidate_set = set(candidates)
            extracted = []
            for item in data["terms"]:
                if not isinstance(item, dict):
                    continue
                source_term = item.get("source_term")
                if not isinstance(source_term, str) or source_term not in candidate_set:
                    continue
                try:
                    confidence = float(item.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                extracted.append(
                    {
                        "source_term": source_term,
                        "useful": bool(item.get("useful", False)),
                        "role": str(item.get("role", "")),
                        "confidence": max(0.0, min(1.0, confidence)),
                    }
                )
            return extracted
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            return None

    async def translate(
        self,
        source_term: str,
        *,
        context: str = "",
    ) -> Optional[dict[str, Any]]:
        prompt = (
            "Translate one academic term from Chinese to English for scholarly "
            "information retrieval. Return JSON only with keys: source_term, "
            "translations (list of {term, confidence, usage, is_preferred}), "
            "domain, ambiguity. Do not invent explanations outside JSON. "
            f"source_term={source_term!r}; context={context!r}"
        )
        try:
            response = await self.llm.agenerate(
                messages=[
                    LLMMessage(role=MessageRole.SYSTEM, content="You are a terminology expert."),
                    LLMMessage(role=MessageRole.USER, content=prompt),
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
            data = json.loads(raw)
            if not isinstance(data, dict):
                return None
            translations = [
                TerminologyTranslation.model_validate(item)
                for item in data.get("translations", [])
                if isinstance(item, dict)
            ][:5]
            if not translations:
                return None
            return {
                "source_term": source_term,
                "translations": translations,
                "domain": data.get("domain", ""),
                "ambiguity": bool(data.get("ambiguity", False)),
            }
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            return None


class TerminologyService:
    """Resolve known terms and cache LLM discoveries as pending entries."""

    _CHINESE_TERM_PATTERN = re.compile(r"[\u3400-\u9fff]{2,}")
    _NOISE = (
        "一些关于",
        "用英文关键词",
        "找一下",
        "查一下",
        "搜索一下",
        "检索一下",
        "相关的",
        "相关",
        "论文",
        "文章",
        "研究一下",
        "方向",
        "与",
        "和",
        "的",
    )

    def __init__(
        self,
        store: TerminologyStore,
        translator: Optional[LLMTermTranslator] = None,
        *,
        max_oov_terms: int = 3,
        load_seed_terms: bool = True,
    ):
        self.store = store
        self.translator = translator
        self.max_oov_terms = max_oov_terms
        if load_seed_terms:
            self._ensure_seed_terms()

    def _ensure_seed_terms(self) -> None:
        for source_term, target_term in _TERM_TRANSLATIONS:
            if self.store.lookup(source_term) is None:
                self.store.upsert(
                    TerminologyEntry(
                        term_id=f"seed-{source_term}",
                        source_term=source_term,
                        target_terms=[
                            TerminologyTranslation(
                                term=target_term,
                                confidence=1.0,
                                is_preferred=True,
                            )
                        ],
                        source="seed_dictionary",
                        confidence=1.0,
                        status="verified",
                    )
                )

    def _extract_terms(self, query: str) -> list[str]:
        """Split Chinese query text at noise words and known term boundaries."""
        text = query.strip()
        for noise in sorted(self._NOISE, key=len, reverse=True):
            text = text.replace(noise, " ")

        known_terms = {
            source_term
            for source_term, _target_term in _TERM_TRANSLATIONS
        }
        known_terms.update(
            entry.source_term
            for entry in self.store.list_entries()
        )
        known_terms.update(
            alias
            for entry in self.store.list_entries()
            for alias in entry.aliases
        )
        known_terms = {term for term in known_terms if len(term) >= 2}
        pattern = re.compile(r"[\u3400-\u9fff]{2,}")
        terms: list[str] = []
        for match in pattern.finditer(text):
            chunk = match.group(0)
            index = 0
            while index < len(chunk):
                matches = [
                    term for term in known_terms
                    if chunk.startswith(term, index)
                ]
                if matches:
                    term = max(matches, key=len)
                    terms.append(term)
                    index += len(term)
                    continue
                next_boundary = [
                    chunk.find(term, index + 1)
                    for term in known_terms
                    if chunk.find(term, index + 1) >= 0
                ]
                end = min(next_boundary) if next_boundary else len(chunk)
                unknown = chunk[index:end].strip()
                if len(unknown) >= 2:
                    terms.append(unknown)
                index = max(end, index + 1)
        return list(dict.fromkeys(terms))

    async def expand_query(self, query: str) -> tuple[str, list[TerminologyEntry]]:
        queries, discovered = await self.expand_queries(query)
        return (
            " ".join(queries)
            if len(queries) > 1
            else queries[0] if queries else query,
            discovered,
        )

    async def expand_queries(
        self,
        query: str,
        *,
        max_queries: int = 3,
    ) -> tuple[list[str], list[TerminologyEntry]]:
        discovered: list[TerminologyEntry] = []
        if not self.translator:
            return [query], discovered

        candidate_terms = self._extract_terms(query)
        unknown_candidates = [
            term for term in candidate_terms if self.store.lookup(term) is None
        ][: self.max_oov_terms]
        if not unknown_candidates:
            return [query], discovered

        classified = await self.translator.extract_terms(
            query,
            candidates=candidate_terms,
        )
        if classified is None:
            useful_terms = unknown_candidates
        else:
            useful_terms = [
                item["source_term"]
                for item in classified
                if item["useful"] and item["source_term"] in unknown_candidates
            ]
        for source_term in useful_terms[: self.max_oov_terms]:
            result = await self.translator.translate(source_term, context=query)
            if not result:
                continue
            entry = self.store.add_pending(
                source_term,
                result["translations"],
                domain=[result["domain"]] if result["domain"] else [],
                context=query,
                confidence=max(
                    translation.confidence for translation in result["translations"]
                ),
            )
            discovered.append(entry)

        expansions = [
            translation.term
            for entry in discovered
            for translation in entry.target_terms
            if translation.is_preferred or translation.confidence >= 0.8
        ]
        expansions = list(dict.fromkeys(expansions))
        queries = [query]
        for expansion in expansions:
            if len(queries) >= max_queries:
                break
            queries.append(f"{query} {expansion}")
        return queries, discovered

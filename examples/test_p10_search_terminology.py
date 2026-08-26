"""P10 terminology and query expansion tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from paper_agent.common.capabilities import (
    ExecutionContext,
    LLMTermTranslator,
    PaperSearchAdapter,
    TerminologyService,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from paper_agent.common.llm import LLMResponse
from paper_agent.common.models.terminology import (
    TerminologyEntry,
    TerminologyTranslation,
)
from paper_agent.common.persistence import TerminologyStore
from paper_agent.common.tools import ToolResult


class FakeLLM:
    def __init__(self, content: str):
        self.content = content
        self.calls = 0

    async def agenerate(self, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=self.content)


class FakeTools:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        self.calls.append({"tool_name": tool_name, **kwargs})
        return ToolResult.ok(data={"results": []})


def test_llm_term_translation_is_structured_and_cached_as_pending(tmp_path: Path):
    class TwoStageLLM(FakeLLM):
        async def agenerate(self, **kwargs: Any) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content='{"terms":[{"source_term":"联邦学习","useful":true,'
                    '"role":"topic","confidence":0.99}]}'
                )
            return LLMResponse(
                content='{"source_term":"联邦学习","translations":[{"term":'
                '"federated learning","confidence":0.94,'
                '"usage":"privacy-preserving ML","is_preferred":true}],'
                '"domain":"machine_learning","ambiguity":false}'
            )

    llm = TwoStageLLM("")
    store = TerminologyStore(tmp_path)
    service = TerminologyService(store, LLMTermTranslator(llm))

    query, entries = asyncio.run(service.expand_query("联邦学习"))

    assert "federated learning" in query
    assert len(entries) == 1
    assert entries[0].status == "pending"
    assert entries[0].source_term == "联邦学习"
    assert store.lookup("联邦学习").status == "pending"
    assert llm.calls == 2


def test_known_term_does_not_call_llm(tmp_path: Path):
    llm = FakeLLM("{}")
    store = TerminologyStore(tmp_path)
    store.add_pending(
        "防火墙",
        [TerminologyTranslation(term="firewall", confidence=1.0)],
    )
    service = TerminologyService(store, LLMTermTranslator(llm))

    query, entries = asyncio.run(service.expand_query("防火墙"))

    assert query == "防火墙"
    assert entries == []
    assert llm.calls == 0


def test_empty_store_can_disable_seed_loading(tmp_path: Path):
    store = TerminologyStore(tmp_path)
    TerminologyService(store, load_seed_terms=False)

    assert store.list_entries() == []


def test_invalid_llm_translation_degrades_to_original_query(tmp_path: Path):
    llm = FakeLLM("not-json")
    service = TerminologyService(
        TerminologyStore(tmp_path),
        LLMTermTranslator(llm),
    )

    query, entries = asyncio.run(service.expand_query("联邦学习"))

    assert query == "联邦学习"
    assert entries == []
    assert llm.calls == 2


def test_sentence_is_split_into_independent_academic_terms(tmp_path: Path):
    llm = FakeLLM(
        '{"translations":[{"term":"artificial intelligence",'
        '"confidence":0.95,"is_preferred":true}]}'
    )
    service = TerminologyService(
        TerminologyStore(tmp_path),
        LLMTermTranslator(llm),
        load_seed_terms=False,
    )

    terms = service._extract_terms("找一下与人工智能相关的防火墙论文")

    assert terms == ["人工智能", "防火墙"]


def test_sentence_translation_calls_llm_once_per_unknown_term(tmp_path: Path):
    class MultiTermLLM(FakeLLM):
        async def agenerate(self, **kwargs: Any) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                content = (
                    '{"terms":[{"source_term":"人工智能","useful":true,'
                    '"role":"topic","confidence":0.99},'
                    '{"source_term":"防火墙","useful":true,'
                    '"role":"topic","confidence":0.99}]}'
                )
            elif self.calls == 2:
                content = (
                    '{"translations":[{"term":"artificial intelligence",'
                    '"confidence":0.95,"is_preferred":true}]}'
                )
            else:
                content = (
                    '{"translations":[{"term":"firewall",'
                    '"confidence":0.95,"is_preferred":true}]}'
                )
            return LLMResponse(content=content)

    llm = MultiTermLLM("")
    service = TerminologyService(
        TerminologyStore(tmp_path),
        LLMTermTranslator(llm),
        load_seed_terms=False,
    )

    query, entries = asyncio.run(
        service.expand_query("找一下与人工智能相关的防火墙论文")
    )

    assert llm.calls == 3
    assert {entry.source_term for entry in entries} == {"人工智能", "防火墙"}
    assert "artificial intelligence" in query
    assert "firewall" in query


def test_llm_filters_generic_candidate_before_translation(tmp_path: Path):
    class FilteringLLM(FakeLLM):
        async def agenerate(self, **kwargs: Any) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content='{"terms":[{"source_term":"联邦学习","useful":true,'
                    '"role":"topic","confidence":0.99},'
                    '{"source_term":"方法","useful":false,'
                    '"role":"generic_modifier","confidence":0.98}]}'
                )
            return LLMResponse(
                content='{"translations":[{"term":"federated learning",'
                '"confidence":0.95,"is_preferred":true}]}'
            )

    llm = FilteringLLM("")
    service = TerminologyService(
        TerminologyStore(tmp_path),
        LLMTermTranslator(llm),
        load_seed_terms=False,
    )

    query, entries = asyncio.run(
        service.expand_query("找一下联邦学习与方法的论文")
    )

    assert llm.calls == 2
    assert [entry.source_term for entry in entries] == ["联邦学习"]
    assert query.count("federated learning") == 1


def test_search_adapter_uses_expansion_and_exposes_discovered_terms(tmp_path: Path):
    llm = FakeLLM(
        '{"source_term":"联邦学习","translations":[{"term":"federated '
        'learning","confidence":0.94,"is_preferred":true}]}'
    )
    service = TerminologyService(
        TerminologyStore(tmp_path),
        LLMTermTranslator(llm),
    )
    tools = FakeTools()
    adapter = PaperSearchAdapter(tools, service)  # type: ignore[arg-type]

    result = asyncio.run(
        adapter.execute(ExecutionContext(), {"query": "联邦学习"})
    )

    assert result.success is True
    assert [call["query"] for call in tools.calls] == [
        "联邦学习",
        "联邦学习 federated learning",
    ]
    assert result.data["discovered_terms"][0]["status"] == "pending"


def test_terminology_lookup_prefers_matching_domain(tmp_path: Path):
    store = TerminologyStore(tmp_path)
    store.upsert(
        TerminologyEntry(
            term_id="term-carrier",
            source_term="载体",
            target_terms=[TerminologyTranslation(term="carrier", confidence=0.9)],
            domain=["drug_delivery"],
            source="human",
            confidence=0.9,
            status="verified",
        )
    )
    store.upsert(
        TerminologyEntry(
            term_id="term-vector",
            source_term="载体",
            target_terms=[TerminologyTranslation(term="vector", confidence=0.95)],
            domain=["machine_learning"],
            source="human",
            confidence=0.95,
            status="verified",
        )
    )

    assert store.lookup("载体", domain="machine_learning").target_terms[0].term == "vector"
    assert store.lookup("载体", domain="drug_delivery").target_terms[0].term == "carrier"


def test_search_metrics_are_bounded_and_reproducible():
    retrieved = ["paper-b", "paper-a", "paper-c"]
    assert recall_at_k(retrieved, {"paper-a", "paper-c"}, 2) == 0.5
    assert reciprocal_rank(retrieved, {"paper-a"}) == 0.5
    assert 0.0 <= ndcg_at_k(retrieved, {"paper-a": 2, "paper-c": 1}, 3) <= 1.0

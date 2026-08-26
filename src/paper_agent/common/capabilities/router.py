from __future__ import annotations

import re
from typing import Any

from ..models.conversation import ConversationContext, ConversationMessage
from .intent_schema import IntentDecision
from .registry import CapabilityRegistry
from .search_query import normalize_search_query

class DeterministicIntentRouter:
    """Route explicit paper-capability requests without an LLM."""

    _SEARCH_TERMS = (
        "检索",
        "搜索",
        "查找",
        "找论文",
        "论文",
        "search",
        "find papers",
        "find paper",
        "papers about",
    )
    _ARXIV_PATTERN = re.compile(r"(?<!\d)(\d{4}\.\d{4,5}(?:v\d+)?)(?!\d)")
    _ARXIV_URL_PATTERN = re.compile(
        r"https?://arxiv\.org/(?:abs|pdf)/(?P<identifier>\d{4}\.\d{4,5}(?:v\d+)?)(?:\.pdf)?",
        re.IGNORECASE,
    )
    _MAX_RESULTS_PATTERN = re.compile(r"(?:前|top|top\s*)?(\d+)\s*(?:篇|papers?)", re.IGNORECASE)
    _ARTIFACT_PATTERN = re.compile(
        r"(?P<path>(?:[\w.-]+/)*[\w.-]+\.json)",
        re.IGNORECASE,
    )
    _CAPABILITY_INTENTS = (
        (
            "process_selected_paper",
            "process_selected_paper",
            (
                "处理这篇论文",
                "完整处理论文",
                "处理选中的论文",
                "process selected paper",
                "process the paper",
            ),
            "请先选择一篇论文，才能启动完整论文处理流程。",
            ["selected_paper"],
        ),
        (
            "paper_download",
            "download_paper",
            ("下载", "download paper", "download the paper", "get the pdf"),
            "请先选择一篇论文或提供 arXiv ID。",
            ["selected_paper"],
        ),
        (
            "paper_parse",
            "parse_paper",
            ("解析", "提取章节", "parse paper", "parse the paper"),
            "请提供 PaperArtifact JSON 路径，例如 papers/paper.json。",
            ["artifact_path"],
        ),
        (
            "paper_glossary",
            "generate_paper_glossary",
            ("生成术语表", "提取术语", "术语表", "paper glossary", "glossary"),
            "请提供 PaperArtifact 路径和术语候选。",
            ["artifact_path", "terms"],
        ),
        (
            "paper_translate",
            "translate_paper",
            ("翻译", "translate paper", "translate the paper"),
            "请提供 PaperArtifact 路径和各章节译文。",
            ["artifact_path", "translations"],
        ),
        (
            "paper_summary",
            "summarize_paper",
            ("总结", "概括论文", "summarize paper", "paper summary"),
            "请提供 PaperArtifact 路径和带章节证据的总结。",
            ["artifact_path", "summary"],
        ),
    )

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        normalize_queries: bool = True,
    ):
        self.registry = registry
        self.normalize_queries = normalize_queries

    def route(
        self,
        message: ConversationMessage,
        context: ConversationContext,
    ) -> IntentDecision:
        if message.role != "user":
            return IntentDecision(
                matched=False,
                reason="Only user messages can be routed",
                clarification_question="请告诉我你想检索什么论文？",
            )

        content = message.content.strip()
        lowered = content.casefold()
        if not content:
            return IntentDecision(
                matched=False,
                reason="Unsupported intent in minimal chat",
                clarification_question="目前支持论文检索。请告诉我想检索的主题，例如“检索多智能体论文”。",
            )

        for capability_name, intent, terms, clarification, required_arguments in self._CAPABILITY_INTENTS:
            if any(term.casefold() in lowered for term in terms):
                return self._route_capability(
                    message=message,
                    context=context,
                    capability_name=capability_name,
                    intent=intent,
                    clarification_question=clarification,
                    required_arguments=required_arguments,
                )

        if not any(term.casefold() in lowered for term in self._SEARCH_TERMS):
            return IntentDecision(
                matched=False,
                reason="Unsupported intent in deterministic router",
                clarification_question="目前支持论文检索、下载、解析、术语表、翻译和总结。",
            )

        arxiv_match = self._ARXIV_PATTERN.search(content)
        max_match = self._MAX_RESULTS_PATTERN.search(content)
        arguments: dict[str, Any] = {}
        if arxiv_match:
            arguments["arxiv_id"] = arxiv_match.group(1)
        else:
            query = content
            if max_match:
                query = content[: max_match.start()] + content[max_match.end() :]
            for term in self._SEARCH_TERMS:
                query = re.sub(re.escape(term), " ", query, flags=re.IGNORECASE)
            query = re.sub(r"(?:前|top)\s*$", "", query, flags=re.IGNORECASE)
            query = re.sub(r"[，。,.：:；;！!？?]+", " ", query).strip()
            if not query:
                return IntentDecision(
                    matched=False,
                    intent="paper_search",
                    capability_name="paper_search",
                    missing_arguments=["query"],
                    reason="Search query is empty",
                    clarification_question="请补充论文检索主题。",
                )
            normalized_query = (
                normalize_search_query(query)
                if self.normalize_queries
                else query.strip()
            )
            if not normalized_query:
                return IntentDecision(
                    matched=False,
                    intent="paper_search",
                    capability_name="paper_search",
                    missing_arguments=["query"],
                    reason="Search query is empty after normalization",
                    clarification_question="请补充论文检索主题。",
                )
            arguments["query"] = normalized_query
            if max_match:
                arguments["max_results"] = int(max_match.group(1))

        try:
            self.registry.resolve("paper_search")
        except (KeyError, RuntimeError) as exc:
            return IntentDecision(
                matched=False,
                intent="paper_search",
                capability_name="paper_search",
                reason=str(exc),
                clarification_question="论文检索能力当前不可用。",
            )

        return IntentDecision(
            matched=True,
            intent="paper_search",
            capability_name="paper_search",
            confidence=0.95,
            arguments=arguments,
        )

    def _route_capability(
        self,
        *,
        message: ConversationMessage,
        context: ConversationContext,
        capability_name: str,
        intent: str,
        clarification_question: str,
        required_arguments: list[str],
    ) -> IntentDecision:
        execution_kind = (
            "workflow" if capability_name == "process_selected_paper" else "tool"
        )
        try:
            capability = self.registry.resolve(capability_name)
            execution_kind = capability.execution_kind
        except (KeyError, RuntimeError) as exc:
            return IntentDecision(
                matched=False,
                intent=intent,
                capability_name=capability_name,
                execution_kind=execution_kind,
                reason=str(exc),
                clarification_question=f"{capability_name} 能力当前不可用。",
            )

        content = message.content.strip()
        arguments: dict[str, Any] = {}
        artifact_match = self._ARTIFACT_PATTERN.search(content)
        if artifact_match:
            arguments["artifact_path"] = artifact_match.group("path")

        arxiv_match = self._ARXIV_PATTERN.search(content)
        arxiv_url_match = self._ARXIV_URL_PATTERN.search(content)
        if capability_name == "paper_download" and arxiv_match:
            arguments["arxiv_id"] = arxiv_match.group(1)
        if capability_name == "process_selected_paper":
            if arxiv_url_match:
                arguments["arxiv_id"] = arxiv_url_match.group("identifier")
                arguments["url"] = arxiv_url_match.group(0)
                if "/pdf/" in arxiv_url_match.group(0).casefold():
                    arguments["pdf_url"] = arxiv_url_match.group(0)
            elif arxiv_match:
                arguments["arxiv_id"] = arxiv_match.group(1)

        missing_arguments = [
            argument
            for argument in required_arguments
            if not self._has_route_argument(argument, arguments, context)
        ]
        if missing_arguments:
            return IntentDecision(
                matched=False,
                intent=intent,
                capability_name=capability_name,
                execution_kind=capability.execution_kind,
                confidence=0.9,
                arguments=arguments,
                missing_arguments=missing_arguments,
                reason="Required capability arguments are missing",
                clarification_question=clarification_question,
            )

        return IntentDecision(
            matched=True,
            intent=intent,
            capability_name=capability_name,
            execution_kind=capability.execution_kind,
            confidence=0.9,
            arguments=arguments,
        )

    @staticmethod
    def _has_route_argument(
        argument: str,
        arguments: dict[str, Any],
        context: ConversationContext,
    ) -> bool:
        if argument in arguments:
            return True
        if argument == "selected_paper":
            return bool(
                context.selected_paper
                or arguments.get("arxiv_id")
                or arguments.get("pdf_url")
            )
        return False

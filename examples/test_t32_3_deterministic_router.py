from __future__ import annotations

from typing import Any

from paper_agent.common.capabilities import (
    CapabilityAdapter,
    CapabilityRegistry,
    CapabilityResult,
    ExecutionContext,
    register_default_capabilities,
)
from paper_agent.common.capabilities.router import DeterministicIntentRouter
from paper_agent.common.models.conversation import ConversationContext, ConversationMessage


class DummyAdapter(CapabilityAdapter):
    def __init__(self, name: str):
        super().__init__(tool_registry=None)  # type: ignore[arg-type]
        self.name = name

    async def execute(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        return CapabilityResult.succeeded(data=arguments)


def router(*names: str) -> DeterministicIntentRouter:
    registry = CapabilityRegistry()
    for name in names:
        registry.register(DummyAdapter(name))
    return DeterministicIntentRouter(registry)


def message(content: str) -> ConversationMessage:
    return ConversationMessage(session_id="session-1", role="user", content=content)


def test_routes_search_with_existing_arguments():
    decision = router("paper_search").route(
        message("search papers about multi-agent systems, top 3 papers"),
        ConversationContext(),
    )

    assert decision.matched is True
    assert decision.intent == "paper_search"
    assert decision.capability_name == "paper_search"
    assert decision.arguments == {
        "query": "multi-agent systems",
        "max_results": 3,
    }


def test_normalizes_chinese_security_search_query():
    decision = router("paper_search").route(
        message("找一下与AI和防火墙结合的论文"),
        ConversationContext(),
    )

    assert decision.matched is True
    assert decision.arguments["query"] == (
        "AI firewall integration"
    )


def test_routes_download_with_arxiv_id():
    decision = router("paper_download").route(
        message("下载论文 2412.05449v1"),
        ConversationContext(),
    )

    assert decision.matched is True
    assert decision.intent == "download_paper"
    assert decision.arguments == {"arxiv_id": "2412.05449v1"}


def test_download_uses_selected_paper_from_context():
    decision = router("paper_download").route(
        message("下载这篇论文"),
        ConversationContext(
            selected_paper={"arxiv_id": "2412.05449v1", "title": "A paper"}
        ),
    )

    assert decision.matched is True
    assert decision.missing_arguments == []
    assert decision.arguments == {}


def test_process_selected_paper_routes_natural_language_to_workflow():
    decision = router("process_selected_paper").route(
        message("处理当前选中的论文"),
        ConversationContext(
            selected_paper={"arxiv_id": "2412.05449v1", "title": "A paper"}
        ),
    )

    assert decision.matched is True
    assert decision.intent == "process_selected_paper"
    assert decision.capability_name == "process_selected_paper"
    assert decision.execution_kind == "workflow"


def test_parse_requires_explicit_artifact_path():
    decision = router("paper_parse").route(
        message("解析论文"),
        ConversationContext(),
    )

    assert decision.matched is False
    assert decision.capability_name == "paper_parse"
    assert decision.missing_arguments == ["artifact_path"]


def test_parse_extracts_artifact_path():
    decision = router("paper_parse").route(
        message("解析 papers/2412.05449v1.json"),
        ConversationContext(),
    )

    assert decision.matched is True
    assert decision.arguments == {
        "artifact_path": "papers/2412.05449v1.json"
    }


def test_glossary_reports_missing_terms_without_inventing_them():
    decision = router("paper_glossary").route(
        message("根据 papers/paper.json 生成术语表"),
        ConversationContext(),
    )

    assert decision.matched is False
    assert decision.capability_name == "paper_glossary"
    assert decision.arguments == {"artifact_path": "papers/paper.json"}
    assert decision.missing_arguments == ["terms"]


def test_translate_and_summary_report_missing_content_arguments():
    translate = router("paper_translate").route(
        message("翻译 papers/paper.json"),
        ConversationContext(),
    )
    summary = router("paper_summary").route(
        message("总结 papers/paper.json"),
        ConversationContext(),
    )

    assert translate.matched is False
    assert translate.missing_arguments == ["translations"]
    assert summary.matched is False
    assert summary.missing_arguments == ["summary"]


def test_unsupported_intent_is_not_matched():
    decision = router(
        "paper_search",
        "paper_download",
        "paper_parse",
        "paper_glossary",
        "paper_translate",
        "paper_summary",
    ).route(message("你好"), ConversationContext())

    assert decision.matched is False
    assert decision.capability_name is None


def test_disabled_capability_cannot_be_routed():
    registry = CapabilityRegistry()
    registry.register(DummyAdapter("paper_parse"), enabled=False)
    decision = DeterministicIntentRouter(registry).route(
        message("解析 papers/paper.json"),
        ConversationContext(),
    )

    assert decision.matched is False
    assert decision.capability_name == "paper_parse"
    assert "disabled" in (decision.reason or "")


def test_default_registration_exposes_six_tools_and_two_workflows():
    registry = CapabilityRegistry()
    register_default_capabilities(registry, object())

    assert registry.list_names() == [
        "paper_search",
        "paper_download",
        "paper_parse",
        "paper_glossary",
        "paper_translate",
        "paper_summary",
        "process_selected_paper",
        "compare_papers",
    ]


if __name__ == "__main__":
    test_routes_search_with_existing_arguments()
    test_routes_download_with_arxiv_id()
    test_download_uses_selected_paper_from_context()
    test_parse_requires_explicit_artifact_path()
    test_parse_extracts_artifact_path()
    test_glossary_reports_missing_terms_without_inventing_them()
    test_translate_and_summary_report_missing_content_arguments()
    test_unsupported_intent_is_not_matched()
    test_disabled_capability_cannot_be_routed()
    test_default_registration_exposes_six_tools_and_two_workflows()
    print("10 passed")

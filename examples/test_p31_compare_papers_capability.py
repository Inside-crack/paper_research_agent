from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from paper_agent.common.capabilities.registry import (
    CapabilityRegistry,
    register_default_capabilities,
)
from paper_agent.common.conversation_application_service import (
    ConversationApplicationService,
)
from paper_agent.common.models.conversation import ConversationMessage
from paper_agent.common.models.conversation import ConversationContext
from paper_agent.common.models.paper_comparison import ComparisonSpec, PaperReference
from paper_agent.common.capabilities.router import DeterministicIntentRouter
from paper_agent.common.persistence import ConversationStore
from paper_agent.tools import get_default_registry


def test_compare_papers_router_extracts_two_arxiv_ids():
    registry = CapabilityRegistry()
    register_default_capabilities(registry, get_default_registry())
    router = DeterministicIntentRouter(registry, normalize_queries=False)
    decision = router.route(
        ConversationMessage(
            role="user",
            content="比较论文 2108.01343v3 和 2401.00001v1 的方法",
        ),
        ConversationContext(),
    )
    assert decision.matched is True
    assert decision.capability_name == "compare_papers"
    assert decision.execution_kind == "workflow"
    assert len(decision.arguments["paper_refs"]) == 2


def test_compare_papers_requires_confirmation():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversationStore(Path(tmpdir))
            registry = CapabilityRegistry()
            register_default_capabilities(registry, get_default_registry())
            service = ConversationApplicationService(
                store,
                registry,
                normalize_queries=False,
            )
            session = store.create_session()
            response = await service.handle_message(
                session.session_id,
                "比较论文 2108.01343v3 和 2401.00001v1",
            )
            assert response["status"] == "waiting_confirmation"
            assert response["confirmation_token"]
            saved = store.load_session(session.session_id)
            assert saved.context.pending_action is not None
            assert saved.context.pending_action.capability_name == "compare_papers"

    asyncio.run(scenario())


def test_comparison_spec_accepts_two_unique_references():
    spec = ComparisonSpec(
        user_query="compare",
        paper_refs=[
            PaperReference(arxiv_id="2108.01343v3"),
            PaperReference(arxiv_id="2401.00001v1"),
        ],
    )
    assert len(spec.paper_refs) == 2
    assert spec.comparison_dimensions

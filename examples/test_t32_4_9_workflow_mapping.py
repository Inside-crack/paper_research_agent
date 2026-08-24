from __future__ import annotations

import asyncio
from typing import Any

from paper_agent.common.capabilities import (
    CapabilityCatalog,
    CapabilityRegistry,
    CapabilityResult,
    ExecutionContext,
    PaperProcessingWorkflowAdapter,
    register_default_capabilities,
)
from paper_agent.common.capabilities.router import DeterministicIntentRouter
from paper_agent.common.models.conversation import ConversationContext, ConversationMessage


class FakeWorkflowRunner:
    def __init__(self):
        self.calls: list[tuple[ExecutionContext, dict[str, Any]]] = []

    async def run(
        self,
        context: ExecutionContext,
        arguments: dict[str, Any],
    ) -> CapabilityResult:
        self.calls.append((context, arguments))
        return CapabilityResult.succeeded(
            data={"workflow": "paper_processing", "task_id": context.task_id},
            next_actions=["等待处理结果"],
        )


def test_default_registration_exposes_workflow_metadata():
    registry = register_default_capabilities(CapabilityRegistry(), object())
    spec = registry.resolve("process_selected_paper")

    assert spec.execution_kind == "workflow"
    assert spec.confirmation_required is True
    assert spec.allowed_intents == ["process_selected_paper"]


def test_workflow_is_routed_only_when_selected_paper_exists():
    registry = register_default_capabilities(CapabilityRegistry(), object())
    router = DeterministicIntentRouter(registry)

    missing = router.route(
        ConversationMessage(role="user", content="处理这篇论文"),
        ConversationContext(),
    )
    ready = router.route(
        ConversationMessage(role="user", content="处理这篇论文"),
        ConversationContext(
            selected_paper={"arxiv_id": "2412.05449v1", "title": "A paper"}
        ),
    )

    assert missing.matched is False
    assert missing.capability_name == "process_selected_paper"
    assert missing.missing_arguments == ["selected_paper"]
    assert ready.matched is True
    assert ready.execution_kind == "workflow"


def test_unconfigured_workflow_never_fakes_success():
    adapter = PaperProcessingWorkflowAdapter()
    result = asyncio.run(
        adapter.execute(
            ExecutionContext(
                task_id="task-1",
                selected_paper={"arxiv_id": "2412.05449v1"},
            ),
            {},
        )
    )

    assert result.success is False
    assert result.status == "blocked"
    assert "not configured" in (result.error or "")


def test_workflow_adapter_delegates_to_injected_runner():
    runner = FakeWorkflowRunner()
    adapter = PaperProcessingWorkflowAdapter(runner)
    context = ExecutionContext(
        task_id="task-1",
        selected_paper={"arxiv_id": "2412.05449v1"},
    )

    result = asyncio.run(
        adapter.execute(
            context,
            {"translation_language": "zh-CN"},
        )
    )

    assert result.success is True
    assert runner.calls == [(context, {"translation_language": "zh-CN"})]


def test_workflow_adapter_requires_task_and_selected_paper():
    adapter = PaperProcessingWorkflowAdapter(FakeWorkflowRunner())

    no_task = asyncio.run(adapter.execute(ExecutionContext(), {}))
    no_paper = asyncio.run(
        adapter.execute(ExecutionContext(task_id="task-1"), {})
    )

    assert no_task.status == "blocked"
    assert no_paper.status == "blocked"


def test_catalog_does_not_expose_runner_instance():
    registry = register_default_capabilities(CapabilityRegistry(), object())
    entry = CapabilityCatalog.from_registry(registry).resolve(
        "process_selected_paper"
    )

    assert "adapter" not in entry.model_dump()
    assert "runner" not in entry.model_dump()


if __name__ == "__main__":
    for test in (
        test_default_registration_exposes_workflow_metadata,
        test_workflow_is_routed_only_when_selected_paper_exists,
        test_unconfigured_workflow_never_fakes_success,
        test_workflow_adapter_delegates_to_injected_runner,
        test_workflow_adapter_requires_task_and_selected_paper,
        test_catalog_does_not_expose_runner_instance,
    ):
        test()

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from paper_agent.common.capabilities import (
    CapabilityAdapter,
    CapabilityCatalog,
    CapabilityCatalogEntry,
    CapabilityRegistry,
    CapabilityResult,
    ExecutionContext,
    register_default_capabilities,
)


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


def test_default_catalog_contains_six_tools_and_one_workflow():
    registry = register_default_capabilities(CapabilityRegistry(), object())
    catalog = CapabilityCatalog.from_registry(registry)

    assert catalog.list_names() == [
        "paper_search",
        "paper_download",
        "paper_parse",
        "paper_glossary",
        "paper_translate",
        "paper_summary",
        "process_selected_paper",
    ]


def test_catalog_exposes_routing_metadata_without_adapter_details():
    registry = register_default_capabilities(CapabilityRegistry(), object())
    catalog = CapabilityCatalog.from_registry(registry)

    parse = catalog.resolve("paper_parse")
    assert parse.execution_kind == "tool"
    assert parse.required_arguments == ["artifact_path"]
    assert parse.input_schema["required"] == ["artifact_path"]
    assert parse.preconditions
    assert parse.allowed_intents == ["parse_paper"]
    assert "adapter" not in parse.model_dump()


def test_process_selected_paper_is_allowlisted_as_workflow():
    registry = register_default_capabilities(CapabilityRegistry(), object())
    workflow = CapabilityCatalog.from_registry(registry).resolve(
        "process_selected_paper"
    )

    assert workflow.execution_kind == "workflow"
    assert workflow.confirmation_required is True
    assert workflow.allowed_intents == ["process_selected_paper"]


def test_catalog_excludes_disabled_capabilities():
    registry = CapabilityRegistry()
    registry.register(DummyAdapter("paper_parse"), enabled=False)

    catalog = CapabilityCatalog.from_registry(registry)

    assert catalog.list_names() == []
    with pytest.raises(KeyError, match="not found"):
        catalog.resolve("paper_parse")


def test_catalog_preserves_custom_workflow_metadata():
    registry = CapabilityRegistry()
    registry.register(
        DummyAdapter("paper_processing"),
        execution_kind="workflow",
        input_schema={
            "type": "object",
            "additionalProperties": False,
        },
        required_arguments=["selected_paper"],
        preconditions=["selected_paper exists"],
        confirmation_required=True,
        allowed_intents=["process_selected_paper"],
    )

    entry = CapabilityCatalog.from_registry(registry).resolve(
        "paper_processing"
    )

    assert entry.execution_kind == "workflow"
    assert entry.confirmation_required is True
    assert entry.required_arguments == ["selected_paper"]


def test_prompt_schema_is_json_serializable_and_allowlisted():
    registry = register_default_capabilities(CapabilityRegistry(), object())
    catalog = CapabilityCatalog.from_registry(registry)

    prompt_schema = catalog.as_prompt_schema()

    assert isinstance(prompt_schema, list)
    assert all("name" in entry for entry in prompt_schema)
    assert all("input_schema" in entry for entry in prompt_schema)
    assert all("adapter" not in entry for entry in prompt_schema)


def test_unknown_catalog_entry_cannot_be_resolved():
    catalog = CapabilityCatalog(
        [
            CapabilityCatalogEntry(
                name="paper_parse",
                description="Parse a paper",
            )
        ]
    )

    with pytest.raises(KeyError, match="not found"):
        catalog.resolve("invented_capability")


def test_duplicate_catalog_names_are_rejected():
    entry = CapabilityCatalogEntry(name="paper_parse", description="Parse")

    with pytest.raises(ValueError, match="duplicate"):
        CapabilityCatalog([entry, entry])


def test_catalog_entry_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        CapabilityCatalogEntry(
            name="paper_parse",
            description="Parse",
            adapter="must-not-leak",
        )


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

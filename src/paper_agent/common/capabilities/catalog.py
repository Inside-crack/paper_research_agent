from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .registry import CapabilityRegistry


ExecutionKind = Literal["tool", "workflow"]


class CapabilityCatalogEntry(BaseModel):
    """LLM-safe metadata for one registered capability."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    execution_kind: ExecutionKind = "tool"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    required_arguments: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    confirmation_required: bool = False
    allowed_intents: list[str] = Field(default_factory=list)


class CapabilityCatalog:
    """Read-only, allowlisted view of capabilities for routing."""

    def __init__(self, entries: list[CapabilityCatalogEntry]):
        names = [entry.name for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("Capability Catalog cannot contain duplicate names")
        self._entries = {entry.name: entry for entry in entries}

    @classmethod
    def from_registry(
        cls,
        registry: CapabilityRegistry,
    ) -> "CapabilityCatalog":
        entries: list[CapabilityCatalogEntry] = []
        for spec in registry.list_enabled():
            entries.append(
                CapabilityCatalogEntry(
                    name=spec.name,
                    description=spec.description,
                    execution_kind=spec.execution_kind,
                    input_schema=spec.input_schema,
                    required_arguments=spec.required_arguments,
                    preconditions=spec.preconditions,
                    confirmation_required=spec.confirmation_required,
                    allowed_intents=spec.allowed_intents,
                )
            )
        return cls(entries)

    def resolve(self, name: str) -> CapabilityCatalogEntry:
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(f"Capability Catalog entry not found: {name}")
        return entry

    def list_entries(self) -> list[CapabilityCatalogEntry]:
        return list(self._entries.values())

    def list_names(self) -> list[str]:
        return list(self._entries)

    def as_prompt_schema(self) -> list[dict[str, Any]]:
        """Return only routing metadata suitable for an LLM request."""
        return [
            entry.model_dump(mode="json")
            for entry in self.list_entries()
        ]


DEFAULT_CAPABILITY_METADATA: dict[str, dict[str, Any]] = {
    "paper_search": {
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "arxiv_id": {"type": "string", "minLength": 1},
                "max_results": {"type": "integer", "minimum": 1},
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "sort_by": {"type": "string"},
                "sort_order": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "required_arguments": [],
        "preconditions": [],
        "confirmation_required": False,
        "allowed_intents": ["paper_search"],
    },
    "paper_download": {
        "input_schema": {
            "type": "object",
            "properties": {
                "arxiv_id": {"type": "string", "minLength": 1},
                "pdf_url": {"type": "string", "format": "uri"},
            },
            "additionalProperties": False,
        },
        "required_arguments": [],
        "preconditions": [
            "ExecutionContext.task_id exists",
            "selected_paper or arxiv_id/pdf_url exists",
        ],
        "confirmation_required": False,
        "allowed_intents": ["download_paper", "download_selected_paper"],
    },
    "paper_parse": {
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_path": {"type": "string", "minLength": 1},
            },
            "required": ["artifact_path"],
            "additionalProperties": False,
        },
        "required_arguments": ["artifact_path"],
        "preconditions": [
            "task_id exists",
            "PaperArtifact exists",
            "PaperArtifact.pdf_path exists and is readable",
        ],
        "confirmation_required": False,
        "allowed_intents": ["parse_paper"],
    },
    "paper_glossary": {
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_path": {"type": "string", "minLength": 1},
                "terms": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "required": ["artifact_path", "terms"],
            "additionalProperties": False,
        },
        "required_arguments": ["artifact_path", "terms"],
        "preconditions": [
            "task_id exists",
            "PaperArtifact.full_text_original is non-empty",
        ],
        "confirmation_required": False,
        "allowed_intents": ["generate_paper_glossary"],
    },
    "paper_translate": {
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_path": {"type": "string", "minLength": 1},
                "translations": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "required": ["artifact_path", "translations"],
            "additionalProperties": False,
        },
        "required_arguments": ["artifact_path", "translations"],
        "preconditions": [
            "task_id exists",
            "PaperArtifact.sections is non-empty",
            "PaperArtifact.glossary is available when required",
        ],
        "confirmation_required": False,
        "allowed_intents": ["translate_paper"],
    },
    "paper_summary": {
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_path": {"type": "string", "minLength": 1},
                "summary": {"type": "object"},
            },
            "required": ["artifact_path", "summary"],
            "additionalProperties": False,
        },
        "required_arguments": ["artifact_path", "summary"],
        "preconditions": [
            "task_id exists",
            "PaperArtifact.sections is non-empty",
            "summary evidence references existing sections",
        ],
        "confirmation_required": False,
        "allowed_intents": ["summarize_paper"],
    },
}


def metadata_for_capability(name: str) -> dict[str, Any]:
    """Return a defensive copy of the allowlisted metadata for one capability."""
    metadata = DEFAULT_CAPABILITY_METADATA.get(name)
    if metadata is None:
        return {}
    return deepcopy(metadata)

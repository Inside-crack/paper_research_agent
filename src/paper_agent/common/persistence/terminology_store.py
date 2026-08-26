from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from ..models.terminology import TerminologyEntry
from .manifest import atomic_write_json


class TerminologyStore:
    """Atomic JSON persistence for verified and pending terminology entries."""

    def __init__(self, base_dir: Path):
        self.path = Path(base_dir) / "terminology" / "terms.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_entries(self, *, include_rejected: bool = False) -> list[TerminologyEntry]:
        if not self.path.exists():
            return []
        import json

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt terminology store: {self.path}") from exc
        if not isinstance(data, list):
            raise ValueError(f"Invalid terminology store structure: {self.path}")
        entries = [TerminologyEntry.model_validate(item) for item in data]
        if include_rejected:
            return entries
        return [entry for entry in entries if entry.status not in {"rejected", "deprecated"}]

    def clear(self) -> None:
        """Remove all persisted terminology entries."""
        atomic_write_json(self.path, [])

    def lookup(
        self,
        source_term: str,
        *,
        domain: Optional[str] = None,
    ) -> Optional[TerminologyEntry]:
        normalized = source_term.strip().casefold()
        entries = self.list_entries()
        if domain:
            domain_entries = [
                entry for entry in entries if domain in entry.domain
            ]
            entries = domain_entries or entries
        candidates = []
        for entry in entries:
            names = [entry.source_term, *entry.aliases]
            if any(name.casefold() == normalized for name in names):
                candidates.append(entry)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda entry: (
                entry.status == "verified",
                entry.confidence,
                entry.usage_count,
            ),
        )

    def upsert(self, entry: TerminologyEntry) -> TerminologyEntry:
        entries = self.list_entries(include_rejected=True)
        replaced = False
        for index, current in enumerate(entries):
            if current.term_id == entry.term_id or (
                current.source_term.casefold() == entry.source_term.casefold()
                and current.status == entry.status
                and current.domain == entry.domain
            ):
                entries[index] = entry
                replaced = True
                break
        if not replaced:
            entries.append(entry)
        atomic_write_json(
            self.path,
            [item.model_dump(mode="json") for item in entries],
        )
        return entry

    def add_pending(
        self,
        source_term: str,
        target_terms,
        *,
        domain: Optional[list[str]] = None,
        context: str = "",
        confidence: float = 0.0,
    ) -> TerminologyEntry:
        entry = TerminologyEntry(
            term_id=f"term-{uuid.uuid4().hex}",
            source_term=source_term.strip(),
            target_terms=target_terms,
            domain=domain or [],
            context=context,
            source="llm",
            confidence=confidence,
            status="pending",
        )
        return self.upsert(entry)

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..capabilities.evaluation import (
    RoutingEvaluationItem,
    RoutingEvaluationReport,
)
from .manifest import atomic_write_json

_REPORT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class RoutingEvaluationReportStore:
    """Atomic JSON persistence and bounded queries for routing reports."""

    def __init__(self, base_dir: Path):
        self.evaluations_dir = Path(base_dir) / "routing" / "evaluations"
        if self.evaluations_dir.is_symlink():
            raise ValueError("Routing evaluation directory must not be a symlink")
        self.evaluations_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_report_id(report_id: str) -> None:
        if not isinstance(report_id, str) or not _REPORT_ID_PATTERN.fullmatch(report_id):
            raise ValueError(f"Invalid routing evaluation report_id: {report_id!r}")

    def _path(self, report_id: str) -> Path:
        self._validate_report_id(report_id)
        path = self.evaluations_dir / f"report_{report_id}.json"
        if path.is_symlink():
            raise ValueError(f"Routing evaluation report must not be a symlink: {path}")
        return path

    @staticmethod
    def _redact_report(report: RoutingEvaluationReport) -> dict:
        """Persist outcomes while excluding model arguments and context references."""
        items: list[RoutingEvaluationItem] = []
        for item in report.items:
            decision = item.decision.model_copy(
                update={"arguments": {}, "references": []}
            )
            items.append(
                RoutingEvaluationItem(
                    case_id=item.case_id,
                    passed=item.passed,
                    decision=decision,
                    failures=list(item.failures),
                )
            )
        return report.model_copy(update={"items": items}).model_dump(mode="json")

    def save(self, report: RoutingEvaluationReport) -> Path:
        if not isinstance(report, RoutingEvaluationReport):
            raise TypeError("report must be a RoutingEvaluationReport")
        path = self._path(report.report_id)
        atomic_write_json(path, self._redact_report(report))
        return path

    def load(self, report_id: str) -> Optional[RoutingEvaluationReport]:
        path = self._path(report_id)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return RoutingEvaluationReport.model_validate(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt routing evaluation report: {path}") from exc
        except OSError as exc:
            raise OSError(f"Failed to read routing evaluation report: {path}") from exc
        except ValueError as exc:
            raise ValueError(f"Invalid routing evaluation report: {path}") from exc

    def list_reports(
        self,
        *,
        suite_name: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[RoutingEvaluationReport]:
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
            raise ValueError("report limit must be an integer or None")
        if limit is not None and limit < 0:
            raise ValueError("report limit must be non-negative")
        reports: list[RoutingEvaluationReport] = []
        for path in sorted(self.evaluations_dir.glob("report_*.json")):
            report_id = path.stem.removeprefix("report_")
            report = self.load(report_id)
            if report is None:
                continue
            if suite_name is not None and report.suite_name != suite_name:
                continue
            if created_after is not None and report.created_at <= created_after:
                continue
            if created_before is not None and report.created_at >= created_before:
                continue
            reports.append(report)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return reports[:limit] if limit is not None else reports

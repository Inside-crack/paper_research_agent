from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..capabilities.evaluation import (
    RoutingEvaluationItem,
    RoutingEvaluationReport,
)
from .manifest import atomic_write_json

_REPORT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class RoutingEvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    suite_name: str
    created_at: datetime
    total: int
    passed: int
    failed: int
    accuracy: float
    clarification_count: int
    clarification_rate: float
    average_confidence: float


class RoutingEvaluationComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_name: Optional[str] = None
    reports: list[RoutingEvaluationMetrics] = Field(default_factory=list)
    accuracy_delta: Optional[float] = None
    failed_delta: Optional[int] = None
    clarification_rate_delta: Optional[float] = None
    average_confidence_delta: Optional[float] = None


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

    @staticmethod
    def _metrics(report: RoutingEvaluationReport) -> RoutingEvaluationMetrics:
        clarification_count = sum(
            not item.decision.matched for item in report.items
        )
        average_confidence = (
            sum(item.decision.confidence for item in report.items) / report.total
            if report.total
            else 0.0
        )
        return RoutingEvaluationMetrics(
            report_id=report.report_id,
            suite_name=report.suite_name,
            created_at=report.created_at,
            total=report.total,
            passed=report.passed,
            failed=report.failed,
            accuracy=report.accuracy,
            clarification_count=clarification_count,
            clarification_rate=(clarification_count / report.total)
            if report.total
            else 0.0,
            average_confidence=average_confidence,
        )

    def compare_reports(
        self,
        *,
        suite_name: Optional[str] = None,
        report_ids: Optional[list[str]] = None,
        limit: Optional[int] = None,
    ) -> RoutingEvaluationComparison:
        if report_ids is not None:
            reports = []
            for report_id in report_ids:
                report = self.load(report_id)
                if report is None:
                    raise FileNotFoundError(
                        f"Routing evaluation report does not exist: {report_id}"
                    )
                if suite_name is None or report.suite_name == suite_name:
                    reports.append(report)
        else:
            reports = self.list_reports(suite_name=suite_name, limit=limit)
        if limit is not None and report_ids is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise ValueError("report limit must be a non-negative integer or None")
            reports = sorted(
                reports,
                key=lambda item: item.created_at,
                reverse=True,
            )[:limit]

        metrics = sorted(
            (self._metrics(report) for report in reports),
            key=lambda item: item.created_at,
        )
        comparison_suite = suite_name
        if comparison_suite is None and metrics:
            suites = {item.suite_name for item in metrics}
            comparison_suite = next(iter(suites)) if len(suites) == 1 else None
        if not metrics:
            return RoutingEvaluationComparison(suite_name=comparison_suite)

        baseline = metrics[0]
        latest = metrics[-1]
        return RoutingEvaluationComparison(
            suite_name=comparison_suite,
            reports=metrics,
            accuracy_delta=latest.accuracy - baseline.accuracy,
            failed_delta=latest.failed - baseline.failed,
            clarification_rate_delta=(
                latest.clarification_rate - baseline.clarification_rate
            ),
            average_confidence_delta=(
                latest.average_confidence - baseline.average_confidence
            ),
        )

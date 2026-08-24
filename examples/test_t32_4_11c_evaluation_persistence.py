import asyncio
from pathlib import Path

import pytest

from paper_agent.common.capabilities import (
    CapabilityRegistry,
    RoutingEvaluationCase,
    evaluate_router,
)
from paper_agent.common.capabilities.router import DeterministicIntentRouter
from paper_agent.common.persistence import RoutingEvaluationReportStore


def make_router() -> DeterministicIntentRouter:
    return DeterministicIntentRouter(CapabilityRegistry())


def cases() -> list[RoutingEvaluationCase]:
    return [
        RoutingEvaluationCase(
            case_id="unsupported",
            content="你好",
            expected_matched=False,
            expected_clarification=True,
        ),
    ]


def test_evaluate_router_persists_report_and_query_reloads_redacted_result(
    tmp_path: Path,
):
    store = RoutingEvaluationReportStore(tmp_path)
    report = asyncio.run(
        evaluate_router(
            make_router(),
            cases(),
            report_store=store,
            suite_name="routing-smoke",
        )
    )

    path = tmp_path / "routing" / "evaluations" / f"report_{report.report_id}.json"
    assert path.exists()
    loaded = store.load(report.report_id)
    assert loaded is not None
    assert loaded.report_id == report.report_id
    assert loaded.suite_name == "routing-smoke"
    assert loaded.accuracy == 1.0
    assert loaded.items[0].decision.arguments == {}
    assert loaded.items[0].decision.references == []

    reports = store.list_reports(suite_name="routing-smoke")
    assert [item.report_id for item in reports] == [report.report_id]


def test_report_query_filters_and_limit(tmp_path: Path):
    store = RoutingEvaluationReportStore(tmp_path)
    first = asyncio.run(
        evaluate_router(
            make_router(),
            cases(),
            report_store=store,
            suite_name="suite-a",
        )
    )
    second = asyncio.run(
        evaluate_router(
            make_router(),
            cases(),
            report_store=store,
            suite_name="suite-b",
        )
    )

    assert store.list_reports(suite_name="suite-a")[0].report_id == first.report_id
    assert store.list_reports(suite_name="missing") == []
    assert len(store.list_reports(limit=1)) == 1
    assert second.report_id != first.report_id


def test_corrupt_report_fails_fast(tmp_path: Path):
    store = RoutingEvaluationReportStore(tmp_path)
    report_path = tmp_path / "routing" / "evaluations" / "report_corrupt.json"
    report_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="Corrupt routing evaluation report"):
        store.load("corrupt")

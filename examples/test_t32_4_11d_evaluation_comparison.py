import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_agent.common.capabilities import (
    CapabilityRegistry,
    RoutingEvaluationCase,
    evaluate_router,
)
from paper_agent.common.capabilities.router import DeterministicIntentRouter
from paper_agent.common.persistence import RoutingEvaluationReportStore


def test_compare_reports_returns_history_and_metric_deltas(tmp_path: Path):
    store = RoutingEvaluationReportStore(tmp_path)
    router = DeterministicIntentRouter(CapabilityRegistry())

    baseline = asyncio.run(
        evaluate_router(
            router,
            [
                RoutingEvaluationCase(
                    case_id="baseline",
                    content="你好",
                    expected_matched=False,
                )
            ],
            suite_name="routing-regression",
        )
    )
    latest = asyncio.run(
        evaluate_router(
            router,
            [
                RoutingEvaluationCase(
                    case_id="latest",
                    content="你好",
                    expected_matched=True,
                )
            ],
            suite_name="routing-regression",
        )
    )
    now = datetime.now(timezone.utc)
    store.save(baseline.model_copy(update={"created_at": now - timedelta(days=1)}))
    store.save(latest.model_copy(update={"created_at": now}))

    comparison = store.compare_reports(suite_name="routing-regression")

    assert [item.report_id for item in comparison.reports] == [
        baseline.report_id,
        latest.report_id,
    ]
    assert comparison.accuracy_delta == -1.0
    assert comparison.failed_delta == 1
    assert comparison.clarification_rate_delta == 0.0
    assert comparison.suite_name == "routing-regression"


def test_compare_reports_can_select_report_ids_and_limit(tmp_path: Path):
    store = RoutingEvaluationReportStore(tmp_path)
    router = DeterministicIntentRouter(CapabilityRegistry())
    reports = []
    for index in range(2):
        report = asyncio.run(
            evaluate_router(
                router,
                [
                    RoutingEvaluationCase(
                        case_id=f"case-{index}",
                        content="你好",
                        expected_matched=False,
                    )
                ],
                suite_name="selected",
            )
        )
        reports.append(report)
        store.save(
            report.model_copy(
                update={
                    "created_at": datetime(
                        2026,
                        1,
                        index + 1,
                        tzinfo=timezone.utc,
                    )
                }
            )
        )

    comparison = store.compare_reports(
        report_ids=[reports[0].report_id, reports[1].report_id],
        limit=1,
    )
    assert len(comparison.reports) == 1
    assert comparison.reports[0].report_id == reports[1].report_id


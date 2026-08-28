from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from paper_agent.common.comparison_export import PaperComparisonExporter
from paper_agent.common.models.paper_comparison import (
    ComparisonMatrixRow,
    ComparisonPaperFacts,
    PaperComparisonArtifact,
)


def make_artifact() -> PaperComparisonArtifact:
    return PaperComparisonArtifact(
        comparison_spec_id="comparison-1",
        papers=[
            ComparisonPaperFacts(paper_id="2108.01343", title="I3CL"),
            ComparisonPaperFacts(paper_id="2401.00001", title="Other"),
        ],
        dimensions=["核心方法", "实验结果"],
        comparison_matrix=[
            ComparisonMatrixRow(
                dimension="核心方法",
                values={
                    "2108.01343": "方法 A | 多模块",
                    "2401.00001": "unknown",
                },
            ),
            ComparisonMatrixRow(
                dimension="实验结果",
                values={
                    "2108.01343": "F1=86.9%",
                    "2401.00001": "F1=80.0%",
                },
            ),
        ],
        conclusion="<script>alert(1)</script>",
        missing_information=["2401.00001:training_strategy"],
    )


def test_export_writes_markdown_html_and_csv():
    with tempfile.TemporaryDirectory() as tmpdir:
        outputs = PaperComparisonExporter().export(
            make_artifact(),
            Path(tmpdir),
        )
        assert set(outputs) == {"markdown", "html", "csv"}
        assert (Path(tmpdir) / "paper_comparison.md").exists()
        assert (Path(tmpdir) / "paper_comparison.html").exists()
        assert (Path(tmpdir) / "paper_comparison.csv").exists()


def test_html_escapes_comparison_content_and_highlights_unknown():
    html = PaperComparisonExporter.render_html(make_artifact())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'class="unknown"' in html


def test_csv_contains_matrix_header_and_values():
    content = PaperComparisonExporter.render_csv(make_artifact())
    rows = list(csv.reader(content.splitlines()))
    assert rows[0] == ["dimension", "2108.01343", "2401.00001"]
    assert rows[1] == ["核心方法", "方法 A | 多模块", "unknown"]

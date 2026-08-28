from __future__ import annotations

import csv
import html
import io
import os
import tempfile
from pathlib import Path

from .models.paper_comparison import PaperComparisonArtifact


class PaperComparisonExporter:
    """Render a validated comparison artifact into portable display formats."""

    def export(
        self,
        artifact: PaperComparisonArtifact,
        output_dir: Path,
    ) -> dict[str, str]:
        if not isinstance(artifact, PaperComparisonArtifact):
            raise TypeError("artifact must be a PaperComparisonArtifact")
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs = {
            "markdown": output_dir / "paper_comparison.md",
            "html": output_dir / "paper_comparison.html",
            "csv": output_dir / "paper_comparison.csv",
        }
        contents = {
            "markdown": self.render_markdown(artifact),
            "html": self.render_html(artifact),
            "csv": self.render_csv(artifact),
        }
        for format_name, path in outputs.items():
            self._atomic_write(path, contents[format_name])
        return {name: path.name for name, path in outputs.items()}

    @staticmethod
    def render_markdown(artifact: PaperComparisonArtifact) -> str:
        paper_ids = [paper.paper_id for paper in artifact.papers]
        lines = [
            "# 多论文对比分析",
            "",
            f"- 对比任务：`{artifact.comparison_spec_id}`",
            f"- 论文数量：{len(artifact.papers)}",
            "",
            "| 对比维度 | " + " | ".join(paper_ids) + " |",
            "| --- | " + " | ".join("---" for _ in paper_ids) + " |",
        ]
        for row in artifact.comparison_matrix:
            values = [PaperComparisonExporter._markdown_cell(row.values.get(paper_id, "unknown"))
                      for paper_id in paper_ids]
            lines.append("| " + " | ".join([row.dimension, *values]) + " |")

        lines.extend(["", "## 共同点", ""])
        lines.extend(f"- {item}" for item in artifact.commonalities) or lines.append("- 暂无")
        lines.extend(["", "## 差异", ""])
        lines.extend(f"- {item}" for item in artifact.differences) or lines.append("- 暂无")
        lines.extend(["", "## 结论", "", artifact.conclusion or "暂无"])
        if artifact.missing_information:
            lines.extend(["", "## 缺失信息", ""])
            lines.extend(f"- `{item}`" for item in artifact.missing_information)
        if artifact.conflicts:
            lines.extend(["", "## 冲突记录", ""])
            lines.extend(
                f"- `{item.paper_id}:{item.field}`：{item.resolution}"
                for item in artifact.conflicts
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def render_html(artifact: PaperComparisonArtifact) -> str:
        paper_ids = [html.escape(paper.paper_id) for paper in artifact.papers]
        header = "".join(f"<th scope=\"col\">{paper_id}</th>" for paper_id in paper_ids)
        rows = []
        for row in artifact.comparison_matrix:
            cells = []
            for paper in artifact.papers:
                value = row.values.get(paper.paper_id, "unknown")
                css_class = "unknown" if value == "unknown" else "known"
                cells.append(
                    f'<td class="{css_class}">{html.escape(str(value))}</td>'
                )
            rows.append(
                f"<tr><th scope=\"row\">{html.escape(row.dimension)}</th>"
                + "".join(cells)
                + "</tr>"
            )
        missing = "".join(
            f"<li><code>{html.escape(item)}</code></li>"
            for item in artifact.missing_information
        ) or "<li>暂无</li>"
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>多论文对比分析</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; color: #202124; }}
table {{ border-collapse: collapse; width: 100%; min-width: 720px; }}
th, td {{ border: 1px solid #d9dce1; padding: .65rem; text-align: left; vertical-align: top; }}
thead th {{ background: #1f4b63; color: white; }}
tbody th {{ background: #eef3f5; white-space: nowrap; }}
td.unknown {{ color: #6b7280; background: #fafafa; font-style: italic; }}
td.known {{ background: #f8fbfc; }}
.matrix {{ overflow-x: auto; }}
</style>
</head>
<body>
<h1>多论文对比分析</h1>
<p>对比任务：<code>{html.escape(artifact.comparison_spec_id)}</code></p>
<div class="matrix"><table>
<thead><tr><th scope="col">对比维度</th>{header}</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>
<h2>结论</h2>
<p>{html.escape(artifact.conclusion or "暂无")}</p>
<h2>缺失信息</h2>
<ul>{missing}</ul>
</body>
</html>
"""

    @staticmethod
    def render_csv(artifact: PaperComparisonArtifact) -> str:
        paper_ids = [paper.paper_id for paper in artifact.papers]
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["dimension", *paper_ids])
        for row in artifact.comparison_matrix:
            writer.writerow(
                [row.dimension]
                + [row.values.get(paper_id, "unknown") for paper_id in paper_ids]
            )
        return output.getvalue()

    @staticmethod
    def _markdown_cell(value: str) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

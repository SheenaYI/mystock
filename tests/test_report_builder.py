from pathlib import Path

from research.contracts.experiment import FrozenExperiment
from research.report_builder import build_consolidated_report


def test_consolidated_report_renders_markdown_and_calendar_year_columns(tmp_path: Path) -> None:
    out_path = tmp_path / "report.html"
    continuous_path = tmp_path / "continuous.html"
    continuous_path.write_text("<html><body><h1>QuantStats</h1></body></html>", encoding="utf-8")
    report = build_consolidated_report(
        experiment=FrozenExperiment(),
        universe_size=300,
        trial_count=1,
        annual_metrics={
            "2024": {"Cumulative Return": 0.1, "Sharpe": 1.2, "Max Drawdown": -0.08},
            "2025": {"Cumulative Return": -0.02, "Sharpe": -0.1, "Max Drawdown": -0.12},
        },
        annual_notes={"2024": "- **相对收益** 为正。", "2025": "- 回撤需要关注。"},
        continuous_report_path=continuous_path,
        diagnostics_path=tmp_path / "diagnostics.html",
        analysis="## 结论\n\n- **这段 Markdown 应被渲染**。",
        phase_status={"continuous_2021_2025": {"run_status": "complete"}},
        out_path=out_path,
    )
    content = report.read_text(encoding="utf-8")
    assert "指标（按自然年计算）" in content
    assert "<th>2024</th>" in content
    assert "<strong>相对收益</strong>" in content
    assert "<h2>结论</h2>" in content
    assert "continuous.html" in content
    continuous = continuous_path.read_text(encoding="utf-8")
    assert "mystock-report-entry-banner" in continuous
    assert "年度白话表格与 AI 结果解读" in continuous


def test_consolidated_report_escapes_model_html(tmp_path: Path) -> None:
    out_path = tmp_path / "report.html"
    build_consolidated_report(
        experiment=FrozenExperiment(), universe_size=300, trial_count=1,
        annual_metrics={"2024": {}}, annual_notes={"2024": "- 正常"},
        continuous_report_path=tmp_path / "continuous.html",
        diagnostics_path=tmp_path / "diagnostics.html",
        analysis="<script>alert('not executable')</script>", out_path=out_path,
    )
    content = out_path.read_text(encoding="utf-8")
    assert "<script>alert" not in content
    assert "&lt;script&gt;" in content

"""Assembles the AI analysis, a metrics comparison table, and the
train/holdout QuantStats tearsheets into one consolidated HTML page.

QuantStatsReport already produces two standalone tearsheet files
(train, holdout); this module doesn't replace them, it wraps them so
there's a single entry point to open instead of three files (two
tearsheets plus a terminal-only analysis) that don't reference each
other.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from research.experiment import ExperimentDefinition

_METRIC_LABELS = [
    ("Cumulative Return", "累计收益", "pct"),
    ("CAGR﹪", "年化收益", "pct"),
    ("Sharpe", "夏普比率（收益/颠簸程度）", "num"),
    ("Sortino", "索提诺比率（收益/下跌颠簸）", "num"),
    ("Max Drawdown", "最大回撤（最惨亏多少）", "pct"),
    ("Longest DD Days", "最长回本天数", "days"),
    ("Volatility (ann.)", "年化波动率（涨跌颠簸幅度）", "pct"),
    ("Beta", "贝塔（跟大盘涨跌的敏感度）", "num"),
    ("Alpha", "阿尔法（扣除大盘影响后的超额收益）", "pct"),
    ("Information Ratio", "信息比率（跑赢大盘的稳定性）", "num"),
]


def _fmt(value, kind: str) -> str:
    if value is None:
        return "-"
    try:
        if kind == "pct":
            return f"{float(value):.0%}"
        if kind == "days":
            return f"{float(value):.0f} 天"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _metrics_table_html(train: dict, holdout: dict) -> str:
    rows = []
    for key, label, kind in _METRIC_LABELS:
        train_val = _fmt(train.get(key), kind)
        holdout_val = _fmt(holdout.get(key), kind)
        rows.append(
            f"<tr><td>{html.escape(label)}</td>"
            f"<td>{html.escape(train_val)}</td>"
            f"<td>{html.escape(holdout_val)}</td></tr>"
        )
    return (
        "<table class='metrics'>"
        "<tr><th>指标</th><th>训练期</th><th>验证期</th></tr>"
        f"{''.join(rows)}</table>"
    )


def _analysis_html(analysis_text: str) -> str:
    paragraphs = [p.strip() for p in analysis_text.split("\n\n") if p.strip()]
    return "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)


def build_consolidated_report(
    experiment: ExperimentDefinition,
    universe_size: int,
    trial_count: int,
    train_metrics: dict,
    holdout_metrics: dict,
    train_report_path: Path,
    holdout_report_path: Path,
    analysis: str,
    out_path: Path,
) -> Path:
    """Write the single-file report and return its path."""
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>mystock 研究报告 - {html.escape(experiment.factor)}</title>
<style>
  body {{
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei",
      sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 24px;
    color: #222;
    line-height: 1.7;
  }}
  h1 {{ font-size: 22px; }}
  h2 {{
    font-size: 18px;
    margin-top: 36px;
    border-bottom: 1px solid #ddd;
    padding-bottom: 6px;
  }}
  .meta {{ color: #666; font-size: 14px; }}
  .analysis {{
    background: #f7f7f5;
    border-left: 4px solid #a37f4c;
    padding: 4px 20px;
    border-radius: 4px;
  }}
  table.metrics {{
    border-collapse: collapse;
    width: 100%;
    font-size: 14px;
  }}
  table.metrics th, table.metrics td {{
    border: 1px solid #ddd;
    padding: 8px 12px;
    text-align: left;
  }}
  table.metrics th {{ background: #f0f0ee; }}
  iframe {{
    width: 100%;
    height: 1800px;
    border: 1px solid #ddd;
    margin-top: 8px;
  }}
</style>
</head>
<body>
<h1>mystock 研究报告</h1>
<p class="meta">
  因子: {html.escape(experiment.factor)} ·
  universe: {universe_size} 只股票 ·
  调仓周期: {experiment.rebalance_days} 天 ·
  Top {experiment.top_pct:.0%} ·
  手续费: {experiment.fee_rate:.2%} ·
  第 {trial_count} 次实验 ·
  生成于 {generated_at}
</p>

<h2>AI 分析</h2>
<div class="analysis">
{_analysis_html(analysis)}
</div>

<h2>关键指标对比（训练期 vs 验证期）</h2>
{_metrics_table_html(train_metrics, holdout_metrics)}

<h2>训练期完整图表</h2>
<iframe src="{train_report_path.name}"></iframe>

<h2>验证期完整图表</h2>
<iframe src="{holdout_report_path.name}"></iframe>

</body>
</html>
"""
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path

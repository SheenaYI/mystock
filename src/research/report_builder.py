"""Build the human-facing research report around one continuous ledger.

The QuantStats tearsheet remains the detailed chart source.  This module adds
the research context that a tearsheet lacks: calendar-year metrics, plain
Chinese annotations, the selector narrative, and explicit execution status.
"""

from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path

import markdown

from research.contracts.experiment import FrozenExperiment

_METRIC_LABELS = [
    ("Cumulative Return", "累计收益", "pct"),
    ("CAGR﹪", "年化收益", "pct"),
    ("Sharpe", "夏普比率（收益相对波动）", "num"),
    ("Sortino", "索提诺比率（收益相对下行波动）", "num"),
    ("Max Drawdown", "最大回撤（阶段内峰值到低点）", "pct"),
    ("Longest DD Days", "最长回本天数", "days"),
    ("Volatility (ann.)", "年化波动率", "pct"),
    ("Beta", "贝塔（相对沪深300的敏感度）", "num"),
    ("Alpha", "阿尔法（扣除大盘影响后的超额）", "pct"),
    ("Information Ratio", "信息比率（超额收益稳定性）", "num"),
]


def _fmt(value, kind: str) -> str:
    if value is None:
        return "-"
    try:
        if kind == "pct":
            return f"{float(value):.1%}"
        if kind == "days":
            return f"{float(value):.0f} 天"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _year_metrics_table_html(annual_metrics: dict[str, dict]) -> str:
    years = list(annual_metrics)
    rows = []
    for key, label, kind in _METRIC_LABELS:
        values = "".join(
            f"<td>{html.escape(_fmt(annual_metrics[year].get(key), kind))}</td>"
            for year in years
        )
        rows.append(f"<tr><td>{html.escape(label)}</td>{values}</tr>")
    headers = "".join(f"<th>{html.escape(year)}</th>" for year in years)
    return (
        "<table class='metrics'><tr><th>指标（按自然年计算）</th>"
        f"{headers}</tr>{''.join(rows)}</table>"
    )


def _year_notes_html(annual_notes: dict[str, str]) -> str:
    cards = []
    for year, note in annual_notes.items():
        cards.append(
            "<section class='year-note'><h3>" + html.escape(year) + " 年怎么看</h3>"
            + markdown.markdown(html.escape(note), extensions=["extra", "sane_lists"])
            + "</section>"
        )
    return "".join(cards)


def _analysis_html(analysis_text: str) -> str:
    """Render LLM Markdown rather than displaying its syntax literally."""
    # The narration is model output, not trusted HTML.  Escape it first, then
    # let Markdown render only its formatting syntax.
    return markdown.markdown(html.escape(analysis_text), extensions=["extra", "sane_lists"])


def build_consolidated_report(
    experiment: FrozenExperiment,
    universe_size: int,
    trial_count: int,
    annual_metrics: dict[str, dict],
    annual_notes: dict[str, str],
    continuous_report_path: Path,
    diagnostics_path: Path,
    analysis: str,
    out_path: Path,
    phase_status: dict[str, dict[str, object]] | None = None,
) -> Path:
    """Write one calendar-year report for a continuous selected-year run."""
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    continuous_relative_path = os.path.relpath(continuous_report_path, out_path.parent)
    diagnostics_relative_path = os.path.relpath(diagnostics_path, out_path.parent)
    years = list(annual_metrics)
    selected_period = f"{years[0]}–{years[-1]}" if years else "所选年份"

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>mystock 研究报告 - {html.escape(experiment.factor_name)}</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
          max-width: 1100px; margin: 0 auto; padding: 24px; color: #222; line-height: 1.7; }}
  h1 {{ font-size: 24px; }} h2 {{ font-size: 19px; margin-top: 36px;
          border-bottom: 1px solid #ddd; padding-bottom: 6px; }}
  h3 {{ margin: 0 0 6px; font-size: 16px; }}
  .meta {{ color: #666; font-size: 14px; }}
  .notice {{ color: #694f20; background: #fff7e7; border-left: 4px solid #d6a441;
             padding: 10px 16px; border-radius: 4px; }}
  .analysis {{ background: #f7f7f5; border-left: 4px solid #a37f4c;
               padding: 8px 20px; border-radius: 4px; }}
  .year-notes {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
  .year-note {{ background: #f7f9fb; border: 1px solid #e1e7ec; border-radius: 6px; padding: 12px 16px; }}
  .year-note p {{ margin: 4px 0; }}
  table.metrics {{ border-collapse: collapse; width: 100%; font-size: 14px; overflow-x: auto; display: block; }}
  table.metrics th, table.metrics td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: right; white-space: nowrap; }}
  table.metrics th:first-child, table.metrics td:first-child {{ text-align: left; }}
  table.metrics th {{ background: #f0f0ee; }}
  iframe {{ width: 100%; height: 1900px; border: 1px solid #ddd; margin-top: 8px; }}
  pre {{ background: #f7f7f7; padding: 12px; white-space: pre-wrap; word-break: break-word; }}
</style>
</head>
<body>
<h1>mystock 研究报告</h1>
<p class="meta">
  因子方案: {html.escape(experiment.factor_name)} · Universe: {universe_size} 只股票 ·
  预测窗口: {experiment.protocol.horizon} 个交易日 · 调仓: {experiment.protocol.rebalance_days} 个交易日 ·
  模型重训: {experiment.protocol.model_retrain_days} 个交易日 · 因子决策: {experiment.protocol.factor_decision_days} 个交易日 ·
  TopK: {experiment.portfolio.top_k} · n_drop: {experiment.portfolio.n_drop} ·
  合同: {experiment.contract_hash[:12]} · 第 {trial_count} 次实验 · 生成于 {generated_at}
</p>
<p class="notice">本页的 {html.escape(selected_period)} 图表来自同一条连续的现金、持仓和收盘估值账本；年度表仅是按自然年切片汇总，不是把每年重新从初始资金开始回测。历史回测不代表未来收益保证。</p>
{("<p class='notice'>S4 使用了实时联网文献索引辅助，因此属于探索性、非 PIT 实验；不得作为正式历史验证或锁定窗结论。</p>" if experiment.profile in {"s4", "s4_n2"} else "")}

<h2>年度关键指标</h2>
{_year_metrics_table_html(annual_metrics)}

<h2>年度白话批注</h2>
<div class="year-notes">{_year_notes_html(annual_notes)}</div>

<h2>AI 结果解读</h2>
<div class="analysis">{_analysis_html(analysis)}</div>

<h2>运行质量状态</h2>
<pre>{html.escape(str(phase_status or {}))}</pre>

<h2>分数与相对基准诊断</h2>
<p><a href="{html.escape(diagnostics_relative_path)}">打开 RankIC/ICIR、状态、分位数组合收益、相对净值与滚动 Beta 诊断</a></p>

<h2>{html.escape(selected_period)} 连续完整图表</h2>
<p>图表中的策略净值和沪深300基准使用同一“下一交易日开盘成交、当日收盘估值”的时钟。年度表帮助定位某一年的表现；此图用于判断连续路径、跨年回撤和相对表现。</p>
<iframe src="{html.escape(continuous_relative_path)}"></iframe>
</body>
</html>
"""
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path

"""Render a compact S0/S1/S2 comparison from append-only run logs."""

from __future__ import annotations

import html
import json
from pathlib import Path


def build_s012_comparison(log_path: Path, output: Path) -> Path:
    latest = {}
    for line in Path(log_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        experiment = record.get("experiment", {})
        profile = experiment.get("profile")
        if record.get("phase") == "full_run" and profile in {"s0", "s1", "s2"}:
            latest[profile] = record
    missing = {"s0", "s1", "s2"} - set(latest)
    if missing:
        raise ValueError(f"missing completed profiles: {sorted(missing)}")
    labels = {"s0": "S0 固定七因子", "s1": "S1 确定性扩展", "s2": "S2 状态条件化"}
    metrics = [
        ("Cumulative Return", "累计收益"), ("CAGR﹪", "年化收益"),
        ("Sharpe", "夏普"), ("Max Drawdown", "最大回撤"),
        ("Information Ratio", "信息比率"), ("Beta", "Beta"),
        ("run_status", "运行状态"),
    ]
    rows = []
    for key, label in metrics:
        cells = [f"<td>{html.escape(label)}</td>"]
        for profile in ("s0", "s1", "s2"):
            phases = latest[profile]["metrics"]
            values = []
            for phase in ("train", "holdout", "locked_2025"):
                phase_metrics = phases.get(phase, {})
                value = phase_metrics.get(key, "-")
                # Run quality is recorded per phase, alongside that phase's
                # metrics.  Keep the comparison report aligned with the
                # single-group reports instead of looking for a top-level key.
                if key == "run_status" and value == "-":
                    value = phase_metrics.get("run_status", "complete")
                values.append(str(value))
            cells.append(f"<td>{html.escape(' / '.join(values))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = """<!doctype html><html lang='zh-CN'><meta charset='utf-8'>
<title>S0/S1/S2 对照报告</title><style>
body{font-family:-apple-system,"PingFang SC",sans-serif;max-width:1100px;margin:30px auto;line-height:1.6}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background:#f5f5f5}
.note{color:#666}</style><body><h1>S0/S1/S2 统一对照报告</h1>
<p class='note'>每个单元依次为：2021–2023 开发 / 2024 验证 / 2025 锁定窗。合同在开发期确定后冻结，验证与锁定窗均按同一合同机械执行；结果只在合同、数据清单和运行日志一并保存后解读。</p>
<table><tr><th>指标</th><th>S0 固定七因子</th><th>S1 确定性扩展</th><th>S2 状态条件化</th></tr>""" + "".join(rows) + """</table>
<h2>单组网页报告</h2><ul>
<li><a href='report_technical_baseline_7.html'>S0 固定七因子</a></li>
<li><a href='report_technical_s1_deterministic.html'>S1 确定性扩展</a></li>
<li><a href='report_technical_s2_state_mapping.html'>S2 状态条件化</a></li>
</ul></body></html>"""
    output.write_text(doc, encoding="utf-8")
    return output

#!/usr/bin/env python3
"""Generate a read-only S3/S3-next factor-gate audit from cached evidence."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.audit import (
    action_diff,
    factor_gate_rows,
    find_evidence_cache,
    load_calls,
    summarise_by_state,
    summarise_factor_gates,
)


ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "data" / "warehouse"
LOG = WAREHOUSE / "llm_calls.jsonl"
EVIDENCE_ROOT = WAREHOUSE / "cache" / "evidence"
OUT = WAREHOUSE / "audits" / "s3_factor_gate_audit"
DISPLAY = WAREHOUSE / "reports" / "comparisons" / "factor_gate_audit.html"
S3_VERSION = "react_factor_selector_v1.5.0"
NEXT_VERSION = "react_factor_selector_s3_next_v1.0.0"


def _html_table(frame, *, rows: int | None = None) -> str:
    view = frame if rows is None else frame.head(rows)
    return view.to_html(index=False, border=0, classes="audit-table")


def main() -> None:
    s3_calls = load_calls(LOG, S3_VERSION)
    next_calls = load_calls(LOG, NEXT_VERSION)
    s3_rows = factor_gate_rows(
        profile="S3", evidence_dir=find_evidence_cache(EVIDENCE_ROOT, S3_VERSION), calls=s3_calls,
    )
    next_rows = factor_gate_rows(
        profile="S3-next", evidence_dir=find_evidence_cache(EVIDENCE_ROOT, NEXT_VERSION), calls=next_calls,
    )
    rows = pd.concat([s3_rows, next_rows], ignore_index=True)
    factor_summary = summarise_factor_gates(rows)
    state_summary = summarise_by_state(rows)
    diff = action_diff(s3_calls, next_calls)

    OUT.mkdir(parents=True, exist_ok=True)
    rows.to_csv(OUT / "factor_gate_audit.csv", index=False)
    factor_summary.to_csv(OUT / "factor_audit_summary.csv", index=False)
    state_summary.to_csv(OUT / "state_factor_audit.csv", index=False)
    diff.to_csv(OUT / "s3_s3_next_action_diff.csv", index=False)

    same_actions = int(diff["same_action"].sum())
    same_extensions = int(diff["same_extensions"].sum())
    selected = factor_summary[factor_summary["selected_count"] > 0]
    DISPLAY.parent.mkdir(parents=True, exist_ok=True)
    DISPLAY.write_text(
        """<!doctype html><html lang='zh-CN'><meta charset='utf-8'>
<title>S3 因子门槛审计</title><style>
body{font-family:-apple-system,'PingFang SC',sans-serif;max-width:1200px;margin:30px auto;line-height:1.6;color:#222}
table{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0 32px}th,td{border:1px solid #ddd;padding:7px;text-align:left}th{background:#f5f5f5}.note{color:#666}
</style><body><h1>S3 / S3-next 因子门槛审计</h1>
<p>本页只读取缓存的证据快照和调用日志；未训练新模型、未调用 LLM、未改动回测结果。</p>"""
        + f"<p><b>动作对照：</b>24 个决策日中，动作相同 {same_actions} 次，扩展因子相同 {same_extensions} 次。</p>"
        + "<h2>实际被选择的因子</h2>" + _html_table(selected)
        + "<h2>按因子汇总</h2>" + _html_table(factor_summary)
        + "<p class='note'>directional_gate_note 表示该因子中位 RankIC 为负、且被当前仅接受正 RankIC 的稳定性门槛挡住；"
          "这不是该因子必然无效，而是需要单独复核的实现/设计矛盾。</p>"
        + "<h2>按市场状态汇总</h2>" + _html_table(state_summary)
        + "<h2>S3 与 S3-next 动作逐日对照</h2>" + _html_table(diff)
        + "<p class='note'>完整逐日×逐因子数据见 data/warehouse/audits/s3_factor_gate_audit/。</p></body></html>",
        encoding="utf-8",
    )
    print(f"审计数据: {OUT}")
    print(f"审计网页: {DISPLAY}")


if __name__ == "__main__":
    main()

"""Convert provider snapshots into supported company-action records."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from research.backtest.corporate_actions import CorporateAction


def load_snapshot_actions(path: Path) -> tuple[CorporateAction, ...]:
    """Parse supported dividend/share-ratio fields from provider snapshots."""
    actions: list[CorporateAction] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        evidence_id = str(record.get("payload_sha256", ""))
        symbol_code = str(record.get("request", {}).get("symbol", ""))
        if not evidence_id or not symbol_code or "response_rows" not in record:
            continue
        symbol = symbol_code + (".SH" if symbol_code.startswith("6") else ".SZ")
        for row in record["response_rows"]:
            ex_text = row.get("除权除息日")
            announced_text = row.get("预案公告日")
            if not ex_text or not announced_text:
                continue
            try:
                ex_date = date.fromisoformat(str(ex_text))
                announced = datetime.combine(
                    date.fromisoformat(str(announced_text)), time(15, 30),
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                )
            except ValueError:
                continue
            ratio = row.get("送转股份-送转总比例")
            if ratio is not None and float(ratio) > 0:
                actions.append(CorporateAction(
                    action_id=f"{evidence_id}:share:{ex_date}", symbol=symbol,
                    action_type="share_ratio_adjustment", announced_at=announced,
                    ex_date=ex_date, share_ratio=1.0 + float(ratio) / 10.0,
                    evidence_id=evidence_id,
                ))
            desc = str(row.get("现金分红-现金分红比例描述") or "")
            match = re.search(r"10派([0-9]+(?:\.[0-9]+)?)", desc)
            if match:
                actions.append(CorporateAction(
                    action_id=f"{evidence_id}:cash:{ex_date}", symbol=symbol,
                    action_type="cash_dividend", announced_at=announced,
                    ex_date=ex_date, payment_date=ex_date,
                    cash_per_share=float(match.group(1)) / 10.0,
                    evidence_id=evidence_id,
                ))
    return tuple(sorted(actions, key=lambda item: (item.ex_date, item.symbol, item.action_id)))


def apply_action_overlay(
    returns, weights, close, actions: tuple[CorporateAction, ...]
):
    """Apply held-position cash/share effects to daily portfolio returns.

    This is an auditable relative-PIT overlay.  It is deliberately separate
    from raw execution prices and records unsupported evidence upstream.
    """
    result = returns.copy()
    for action in actions:
        if action.ex_date not in result.index or action.symbol not in weights.columns:
            continue
        previous = weights.loc[:action.ex_date].iloc[:-1]
        if previous.empty:
            continue
        held_weight = float(previous.iloc[-1].get(action.symbol, 0.0))
        if held_weight <= 0:
            continue
        price = float(close.loc[:action.ex_date].iloc[-1].get(action.symbol, 0.0))
        if price <= 0:
            continue
        contribution = held_weight * (
            (action.cash_per_share or 0.0) / price
            if action.action_type == "cash_dividend"
            else max((action.share_ratio or 1.0) - 1.0, 0.0)
        )
        result.loc[action.ex_date] = result.loc[action.ex_date] + contribution
    return result

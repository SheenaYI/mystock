from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from research.backtest.corporate_action_ledger import LedgerState, apply_close_actions, apply_open_actions
from research.backtest.corporate_actions import CorporateAction


def _dividend():
    return CorporateAction(
        action_id="cash-1", symbol="600000.SH", action_type="cash_dividend",
        announced_at=datetime(2024, 1, 1, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        ex_date=date(2024, 1, 3), payment_date=date(2024, 1, 5), cash_per_share=0.5,
        evidence_id="fixture-1",
    )


def test_dividend_is_receivable_on_ex_date_then_cash_on_payment_date():
    action = _dividend()
    opened, open_records = apply_open_actions(
        LedgerState(shares=1_000, cash=0), symbol=action.symbol, event_date=action.ex_date,
        actions=(action,), record_date_positions={action.action_id: 1_000},
    )
    assert (opened.cash, opened.dividend_receivable, open_records[0].phase) == (0, 500, "ex_date_open")
    settled, close_records = apply_close_actions(opened, symbol=action.symbol, event_date=action.payment_date, actions=(action,))
    assert (settled.cash, settled.dividend_receivable, close_records[0].phase) == (500, 0, "payment_date_close")


def test_non_integral_share_change_fails_instead_of_creating_fractional_shares():
    action = CorporateAction(
        action_id="ratio-1", symbol="600000.SH", action_type="share_ratio_adjustment",
        announced_at=datetime(2024, 1, 1, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        ex_date=date(2024, 1, 3), share_ratio=1.25, evidence_id="fixture-2",
    )
    with pytest.raises(ValueError, match="non_integral_share_result"):
        apply_open_actions(LedgerState(shares=101, cash=0), symbol=action.symbol, event_date=action.ex_date, actions=(action,), record_date_positions={})

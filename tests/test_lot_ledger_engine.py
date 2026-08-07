"""End-to-end guards for integer-lot, next-open formal execution."""

import pandas as pd

from research.backtest.engine import MarketPrices
from research.backtest.lot_ledger_engine import LotLedgerEngine
from research.portfolio.costs import CostModel


def test_lot_ledger_executes_only_whole_100_share_lots_at_next_open():
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    opens = pd.DataFrame({"AAA": [10.0, 10.0, 10.0]}, index=index)
    closes = pd.DataFrame({"AAA": [10.0, 11.0, 11.0]}, index=index)
    signals = pd.DataFrame({"AAA": [0.505, float("nan"), float("nan")]}, index=index)

    result = LotLedgerEngine(init_cash=10_000).run(
        MarketPrices(execution_open=opens, valuation_close=closes), signals, CostModel(commission=0, transfer_fee=0, sell_stamp_duty=0, slippage=0),
    )

    buys = result.trades[result.trades["kind"] == "buy"]
    assert int(buys.iloc[0]["shares"]) == 500
    assert result.value.iloc[1] == 10_500

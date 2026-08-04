"""VectorBT-backed backtest engine."""

from __future__ import annotations

import vectorbt as vbt

from research.engine import BacktestEngine, BacktestResult


class VectorBTEngine(BacktestEngine):
    """Executes a target-weight matrix as a single grouped portfolio."""

    def __init__(self, init_cash: float = 1_000_000.0) -> None:
        self.init_cash = init_cash

    def run(self, prices, weights, fee_rate: float) -> BacktestResult:
        prices = prices.ffill()
        portfolio = vbt.Portfolio.from_orders(
            close=prices,
            size=weights,
            size_type="targetpercent",
            fees=fee_rate,
            freq="1D",
            group_by=True,
            cash_sharing=True,
            init_cash=self.init_cash,
        )
        return BacktestResult(
            returns=portfolio.returns(),
            value=portfolio.value(),
            trades=portfolio.trades.records_readable,
        )

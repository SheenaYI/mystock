"""VectorBT-backed execution using next-session tradable prices."""

from __future__ import annotations

import numpy as np
import pandas as pd
import vectorbt as vbt

from research.backtest.engine import BacktestEngine, BacktestResult, MarketPrices
from research.portfolio.costs import CostModel


class ExecutionDataError(ValueError):
    """Raised when a requested order cannot be executed at a real price."""


def next_open_orders(signal_weights: pd.DataFrame, open_prices: pd.DataFrame,
                     *, reject_invalid: bool = True) -> pd.DataFrame:
    """Move close-derived targets to the following session's open.

    A finite target emitted on decision day *t* becomes an order only on the
    next row, *t+1*.  There is intentionally no forward filling: a requested
    order with absent/zero opening price is an explicit data failure.
    """
    if not signal_weights.index.equals(open_prices.index):
        raise ExecutionDataError("signal and execution panels must have the same sessions")
    if not signal_weights.columns.equals(open_prices.columns):
        raise ExecutionDataError("signal and execution panels must have the same symbols")
    orders = signal_weights.shift(1)
    targeted = orders.notna()
    invalid = targeted & (~np.isfinite(open_prices) | open_prices.le(0))
    if reject_invalid and invalid.to_numpy().any():
        session, symbol = invalid.stack()[lambda value: value].index[0]
        raise ExecutionDataError(
            f"cannot execute requested order: missing/invalid open for {symbol} on {session.date()}"
        )
    return orders


class VectorBTEngine(BacktestEngine):
    """Execute target weights at next-session opens without price imputation."""

    def __init__(self, init_cash: float = 1_000_000.0) -> None:
        self.init_cash = init_cash

    def run(self, prices: MarketPrices, weights: pd.DataFrame, costs: CostModel) -> BacktestResult:
        orders = next_open_orders(weights, prices.execution_open)
        portfolio = vbt.Portfolio.from_orders(
            close=prices.valuation_close,
            price=prices.execution_open,
            # Target percentages must be sized using information available at
            # the open, not the same day's as-yet-unknown closing valuation.
            val_price=prices.execution_open,
            size=orders,
            size_type="targetpercent",
            fees=costs.fee_schedule(weights),
            slippage=costs.slippage,
            freq="1D",
            group_by=True,
            cash_sharing=True,
            init_cash=self.init_cash,
            ffill_val_price=False,
        )
        return BacktestResult(
            returns=portfolio.returns(), value=portfolio.value(),
            trades=portfolio.trades.records_readable,
        )

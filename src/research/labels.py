"""Leakage-safe forward-return labels for cross-sectional stock selection."""

from __future__ import annotations

import pandas as pd


def forward_excess_return(
    stock_open: pd.DataFrame, benchmark_open: pd.Series, horizon: int = 20
) -> pd.DataFrame:
    """Return the decision-day label for a next-open, ``horizon``-day trade.

    A signal observed at close of ``t`` enters at open ``t+1`` and exits at
    open ``t+1+horizon``.  The corresponding benchmark return is subtracted.
    Thus the final ``horizon + 1`` decision rows are unavailable and must not
    enter model fitting or evaluation.
    """
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if not stock_open.index.equals(benchmark_open.index):
        raise ValueError("stock and benchmark opens must share the same sessions")
    entry = stock_open.shift(-1)
    exit_ = stock_open.shift(-(horizon + 1))
    stock_return = exit_.div(entry).sub(1.0)
    benchmark_return = benchmark_open.shift(-(horizon + 1)).div(benchmark_open.shift(-1)).sub(1.0)
    return stock_return.sub(benchmark_return, axis=0)


def forward_excess_return_20d(
    stock_open: pd.DataFrame, benchmark_open: pd.Series, horizon: int = 20
) -> pd.DataFrame:
    """Backward-compatible name for :func:`forward_excess_return`.

    The original implementation has always accepted an arbitrary horizon; new
    protocols should use the neutral name so a five-day label is not described
    as a twenty-day label.
    """
    return forward_excess_return(stock_open, benchmark_open, horizon=horizon)


def mature_labels_as_of(labels: pd.DataFrame, *, as_of: pd.Timestamp, horizon: int = 20) -> pd.DataFrame:
    """Keep only labels whose next-open holding period was complete by ``as_of``."""
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if as_of not in labels.index:
        raise ValueError("as_of must be a trading session in the label panel")
    pos = labels.index.get_loc(as_of)
    final_mature_pos = pos - horizon - 1
    if final_mature_pos < 0:
        return labels.iloc[0:0]
    return labels.iloc[: final_mature_pos + 1]

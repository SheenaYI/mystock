"""Benchmark returns aligned to the strategy's first open execution."""

from __future__ import annotations

import pandas as pd


def aligned_close_benchmark_returns(
    *, benchmark_open: pd.Series, benchmark_close: pd.Series, signal_weights: pd.DataFrame
) -> pd.Series:
    """Buy the benchmark at the strategy's first execution open, then mark close.

    Before the strategy has any order both paths remain at initial cash.  On the
    first execution date the benchmark earns close/open; later it earns daily
    close/previous-close, matching the portfolio's close-valued NAV clock.
    """
    if not benchmark_open.index.equals(benchmark_close.index) or not benchmark_open.index.equals(signal_weights.index):
        raise ValueError("benchmark and strategy sessions must match")
    order_dates = signal_weights.notna().any(axis=1).to_numpy().nonzero()[0]
    returns = pd.Series(0.0, index=benchmark_close.index, name="benchmark")
    if len(order_dates) == 0 or order_dates[0] + 1 >= len(returns):
        return returns
    entry_pos = order_dates[0] + 1
    returns.iloc[entry_pos] = benchmark_close.iloc[entry_pos] / benchmark_open.iloc[entry_pos] - 1.0
    returns.iloc[entry_pos + 1 :] = benchmark_close.pct_change().iloc[entry_pos + 1 :]
    return returns

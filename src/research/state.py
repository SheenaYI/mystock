"""Deterministic market-state features used by the constrained selector."""

from __future__ import annotations

import pandas as pd


def classify_market_state(benchmark_close: pd.Series) -> str:
    """Classify trend, stress, and range states from information visible then."""
    returns = benchmark_close.pct_change()
    ret20 = benchmark_close.pct_change(20).iloc[-1]
    ret60 = benchmark_close.pct_change(60).iloc[-1]
    vol20 = returns.rolling(20).std().iloc[-1]
    drawdown60 = benchmark_close.div(benchmark_close.rolling(60).max()).sub(1.0).iloc[-1]
    calibration = benchmark_close.loc[:"2021-06-30"]
    calibration_vol = calibration.pct_change().rolling(20).std().dropna()
    calibration_drawdown = calibration.div(calibration.rolling(60).max()).sub(1.0).dropna()
    if any(pd.isna(value) for value in (ret20, ret60, vol20, drawdown60)) or calibration_vol.empty or calibration_drawdown.empty:
        return "S0_insufficient_evidence"
    if vol20 >= calibration_vol.quantile(0.80) or drawdown60 <= calibration_drawdown.quantile(0.20):
        return "S2_stress"
    if ret60 > 0 and ret20 > 0:
        return "S1_trend"
    return "S3_range_or_uncertain"

"""Deterministic market-state features used by the constrained selector."""

from __future__ import annotations

import pandas as pd
import numpy as np


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


def market_state_snapshot(
    *, benchmark_close: pd.Series, stock_close: pd.DataFrame | None = None,
    as_of: pd.Timestamp | None = None,
) -> dict[str, object]:
    """Build deterministic state variables visible at one decision date.

    The classifier remains the single state authority.  Cross-sectional
    statistics enrich the evidence sent to the selector; they never let the
    LLM redefine the state or alter trading rules.
    """
    benchmark = benchmark_close.sort_index()
    if as_of is not None:
        benchmark = benchmark.loc[:pd.Timestamp(as_of)]
    if benchmark.empty:
        return {"state": "S0_insufficient_evidence", "evidence_status": "insufficient_evidence"}
    date = pd.Timestamp(benchmark.index[-1])
    returns = benchmark.pct_change()
    return20 = benchmark.pct_change(20).iloc[-1]
    return60 = benchmark.pct_change(60).iloc[-1]
    vol20 = returns.rolling(20).std().iloc[-1]
    drawdown60 = benchmark.div(benchmark.rolling(60).max()).sub(1.0).iloc[-1]
    snapshot: dict[str, object] = {
        "as_of": str(date.date()),
        "benchmark_return_20": None if pd.isna(return20) else float(return20),
        "benchmark_return_60": None if pd.isna(return60) else float(return60),
        "benchmark_volatility_20": None if pd.isna(vol20) else float(vol20),
        "benchmark_drawdown_60": None if pd.isna(drawdown60) else float(drawdown60),
    }
    if stock_close is not None:
        stocks = stock_close.sort_index().loc[:date]
        if not stocks.empty:
            latest = stocks.iloc[-1]
            ma20 = stocks.rolling(20).mean().iloc[-1]
            above = latest.div(ma20).sub(1.0).dropna()
            stock_ret20 = stocks.pct_change(20).iloc[-1].dropna()
            snapshot["breadth_above_ma20"] = float((above > 0).mean()) if len(above) else None
            snapshot["cross_sectional_return_dispersion_20"] = float(stock_ret20.std(ddof=1)) if len(stock_ret20) > 1 else None
            returns20 = stocks.pct_change().tail(20).dropna(axis=1, how="all")
            corr = returns20.corr(method="pearson") if returns20.shape[0] >= 10 else pd.DataFrame()
            if not corr.empty and len(corr) > 1:
                # The diagonal is excluded explicitly; missing pairs do not
                # become artificial zero-correlation evidence.
                diagonal = pd.DataFrame(
                    np.eye(len(corr), dtype=bool), index=corr.index, columns=corr.columns,
                )
                values = corr.where(~diagonal)
                snapshot["median_pairwise_correlation_20"] = float(values.stack().median()) if not values.stack().empty else None
            else:
                snapshot["median_pairwise_correlation_20"] = None
    state = classify_market_state(benchmark)
    snapshot["state"] = state
    snapshot["evidence_status"] = "ok" if state != "S0_insufficient_evidence" else "insufficient_evidence"
    return snapshot

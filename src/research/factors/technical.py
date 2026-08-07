"""Deterministic technical feature panels for the fixed seven-factor baseline."""

from __future__ import annotations

import pandas as pd


def baseline_seven_features(
    *, close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, volume: pd.DataFrame
) -> pd.DataFrame:
    """Build the frozen seven-factor panel indexed by (datetime, instrument)."""
    panels = (high, low, volume)
    if any(not close.index.equals(panel.index) or not close.columns.equals(panel.columns) for panel in panels):
        raise ValueError("OHLCV factor panels must have identical sessions and symbols")
    features = {
        "return_5": close.pct_change(5),
        "return_20": close.pct_change(20),
        "return_60": close.pct_change(60),
        "ma_gap_20": close.div(close.rolling(20).mean()).sub(1.0),
        "volatility_20": close.pct_change().rolling(20).std(),
        "volume_ratio_20": volume.div(volume.rolling(20).mean()).sub(1.0),
        "intraday_range": high.sub(low).div(close),
    }
    wide = pd.concat(features, axis=1)
    wide.columns.names = ["feature", "instrument"]
    result = wide.stack("instrument", future_stack=True)
    result.index.names = ["datetime", "instrument"]
    return result.reindex(columns=list(features))

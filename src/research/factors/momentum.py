"""N-day price momentum factor."""

from __future__ import annotations

import pandas as pd

from research.factor import Factor


class MomentumFactor(Factor):
    """Score = trailing `lookback`-day return. Higher = more momentum."""

    name = "momentum_20d"

    def __init__(self, lookback: int = 20) -> None:
        self.lookback = lookback

    def compute(self, panel: pd.DataFrame) -> pd.DataFrame:
        return panel.pct_change(self.lookback)

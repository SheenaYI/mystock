"""Top-percentile, equal-weight, periodic-rebalance strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.portfolio.strategy import Strategy


class TopPctStrategy(Strategy):
    """On each rebalance date, equal-weight the top `top_pct` scores.

    Symbols dropped from the picks get an explicit 0.0 target on the
    rebalance date they're dropped, so the engine actually sells them
    instead of holding forever (NaN means "hold", not "flatten").
    """

    def __init__(self, top_pct: float = 0.10) -> None:
        self.top_pct = top_pct

    def build_weights(
        self, scores: pd.DataFrame, rebalance_days: int
    ) -> pd.DataFrame:
        dates = scores.index
        weights = pd.DataFrame(np.nan, index=dates, columns=scores.columns)
        prev_picks: set[str] = set()

        for i in range(0, len(dates), rebalance_days):
            row = scores.loc[dates[i]].dropna()
            if row.empty:
                continue

            n_select = max(1, int(len(row) * self.top_pct))
            picks = set(row.nlargest(n_select).index)

            for symbol in prev_picks - picks:
                weights.loc[dates[i], symbol] = 0.0
            for symbol in picks:
                weights.loc[dates[i], symbol] = 1.0 / len(picks)

            prev_picks = picks

        return weights

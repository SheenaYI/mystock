"""TopK equal-weight selection with bounded turnover via n_drop."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.portfolio.strategy import Strategy


class TopKDropoutStrategy(Strategy):
    """Hold TopK names, replacing at most ``n_drop`` incumbents per rebalance."""

    def __init__(self, top_k: int = 10, n_drop: int = 5) -> None:
        if top_k <= 0 or n_drop <= 0 or n_drop > top_k:
            raise ValueError("require 0 < n_drop <= top_k")
        self.top_k = top_k
        self.n_drop = n_drop

    def build_weights(self, scores: pd.DataFrame, rebalance_days: int) -> pd.DataFrame:
        if rebalance_days <= 0:
            raise ValueError("rebalance_days must be positive")
        weights = pd.DataFrame(np.nan, index=scores.index, columns=scores.columns)
        holdings: set[str] = set()
        # The model already emits scores only on its frozen decision dates.
        # Selecting every Nth row after a phase slice can miss those sparse
        # dates (especially at the 2024/2025 boundary), producing a false
        # zero-trade holdout.  Rebalance on actual score-bearing sessions.
        decision_sessions = scores.index[scores.notna().any(axis=1)]
        for session in decision_sessions:
            ranked = scores.loc[session].dropna().sort_values(ascending=False)
            # Warm-up dates have no 60-day factor yet; they are not a failed
            # rebalance because no prior position exists to change.
            if ranked.empty and not holdings:
                continue
            if len(ranked) < self.top_k:
                if not holdings:
                    # Some profiles have a longer factor warm-up (for
                    # example return_120).  Wait for a complete initial
                    # universe instead of treating the warm-up as a trade
                    # failure.
                    continue
                raise ValueError(f"fewer than TopK valid scores on {session.date()}")
            if not holdings:
                picks = set(ranked.head(self.top_k).index)
            else:
                eligible_holdings = holdings & set(ranked.index)
                survivor_count = max(0, min(len(eligible_holdings), self.top_k - self.n_drop))
                survivors = set(ranked.loc[list(eligible_holdings)].nlargest(survivor_count).index)
                replacements = [symbol for symbol in ranked.index if symbol not in survivors]
                picks = survivors | set(replacements[: self.top_k - len(survivors)])
            for symbol in holdings - picks:
                weights.loc[session, symbol] = 0.0
            weights.loc[session, list(picks)] = 1.0 / self.top_k
            holdings = picks
        return weights

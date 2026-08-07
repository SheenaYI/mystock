"""Base interface for portfolio-construction strategies.

A strategy turns factor scores into a target-weight matrix (date x
symbol). It owns rebalance timing and position sizing — the Factor
layer only scores, the BacktestEngine only executes.
"""

from __future__ import annotations

import pandas as pd


class Strategy:
    """Base class for all strategies."""

    def build_weights(
        self, scores: pd.DataFrame, rebalance_days: int
    ) -> pd.DataFrame:
        """Turn factor scores into a sparse target-weight matrix.

        Non-rebalance dates should be NaN, meaning "no order, hold
        current position". Must be implemented by subclasses.
        """
        raise NotImplementedError

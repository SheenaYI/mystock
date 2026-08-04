"""Base interface for backtest engines."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestResult:
    """Output of a single backtest run."""

    returns: pd.Series
    value: pd.Series
    trades: pd.DataFrame


class BacktestEngine:
    """Base class for all backtest engines."""

    def run(
        self, prices: pd.DataFrame, weights: pd.DataFrame, fee_rate: float
    ) -> BacktestResult:
        """Execute `weights` (a target-weight matrix) against `prices`.

        Must be implemented by subclasses.
        """
        raise NotImplementedError

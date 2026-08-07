"""Base interface for backtest engines."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from research.portfolio.costs import CostModel


@dataclass
class BacktestResult:
    """Output of a single backtest run."""

    returns: pd.Series
    value: pd.Series
    trades: pd.DataFrame


@dataclass(frozen=True)
class MarketPrices:
    """Separate tradable opens from end-of-session valuation closes."""

    execution_open: pd.DataFrame
    valuation_close: pd.DataFrame
    tradability: dict[str, pd.DataFrame] | None = None

    def __post_init__(self) -> None:
        if not self.execution_open.index.equals(self.valuation_close.index):
            raise ValueError("open and close panels must have identical sessions")
        if not self.execution_open.columns.equals(self.valuation_close.columns):
            raise ValueError("open and close panels must have identical symbols")
        if self.tradability is not None:
            for name, panel in self.tradability.items():
                if not self.execution_open.index.equals(panel.index) or not self.execution_open.columns.equals(panel.columns):
                    raise ValueError(f"tradability panel {name} must align with price panels")


class BacktestEngine:
    """Base class for all backtest engines."""

    def run(
        self, prices: MarketPrices, weights: pd.DataFrame, costs: CostModel
    ) -> BacktestResult:
        """Execute `weights` at opens and value the portfolio at closes.

        Must be implemented by subclasses.
        """
        raise NotImplementedError

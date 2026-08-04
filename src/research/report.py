"""Base interface for research report generators."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.engine import BacktestResult


class ReportGenerator:
    """Base class for all report generators."""

    def build(
        self, result: BacktestResult, benchmark: pd.Series, out_path: Path
    ) -> Path:
        """Write an HTML report to `out_path`. Returns `out_path`."""
        raise NotImplementedError

    def metrics(
        self, result: BacktestResult, benchmark: pd.Series
    ) -> dict:
        """Return a flat dict of performance metrics for LLM summarizing."""
        raise NotImplementedError

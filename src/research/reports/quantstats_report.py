"""QuantStats-backed report generator: HTML tearsheet + metrics dict."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import pandas as pd
import quantstats as qs

from research.engine import BacktestResult
from research.report import ReportGenerator

warnings.filterwarnings("ignore")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)


class QuantStatsReport(ReportGenerator):
    """Generates a QuantStats HTML tearsheet vs. a benchmark series."""

    def __init__(self, title: str = "mystock Research Report") -> None:
        self.title = title

    def build(
        self, result: BacktestResult, benchmark: pd.Series, out_path: Path
    ) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        qs.reports.html(
            result.returns,
            benchmark=benchmark,
            output=str(out_path),
            title=self.title,
        )
        return out_path

    def metrics(
        self, result: BacktestResult, benchmark: pd.Series
    ) -> dict:
        table = qs.reports.metrics(
            result.returns, benchmark=benchmark, mode="full", display=False
        )
        return table["Strategy"].to_dict()

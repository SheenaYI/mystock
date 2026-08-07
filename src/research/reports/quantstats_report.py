"""QuantStats-backed report generator: HTML tearsheet + metrics dict."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import pandas as pd
import quantstats as qs

from research.backtest.engine import BacktestResult
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
        try:
            qs.reports.html(
                result.returns,
                benchmark=benchmark,
                output=str(out_path),
                title=self.title,
            )
        except Exception as exc:
            # QuantStats KDE plots fail for short/constant return samples.  A
            # deterministic table is preferable to losing the whole run.
            logging.getLogger(__name__).warning("quantstats chart fallback: %s", exc)
            frame = pd.concat(
                [result.returns.rename("strategy"), benchmark.rename("benchmark")], axis=1
            ).dropna(how="all")
            out_path.write_text(
                "<html><head><meta charset='utf-8'><title>"
                + self.title
                + "</title></head><body><h1>"
                + self.title
                + "</h1>"
                + frame.describe().to_html()
                + frame.tail(20).to_html()
                + "</body></html>",
                encoding="utf-8",
            )
        return out_path

    def metrics(
        self, result: BacktestResult, benchmark: pd.Series
    ) -> dict:
        table = qs.reports.metrics(
            result.returns, benchmark=benchmark, mode="full", display=False
        )
        return table["Strategy"].to_dict()

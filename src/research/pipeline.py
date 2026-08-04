"""End-to-end orchestration.

LLM intent -> universe -> factor -> strategy -> backtest (train and
holdout, run separately so the holdout number is a true out-of-sample
check) -> report -> LLM summary.

This is the only place that wires all research/ layers together. Each
layer stays swappable (new Factor, new BacktestEngine, ...) without
changing this file's shape — only the concrete classes instantiated
below change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from common.logger import PROJECT_ROOT, get_logger, load_settings
from data.akshare import AKShareProvider
from data.storage import ParquetStorage
from research.engines.vectorbt_engine import VectorBTEngine
from research.experiment import ExperimentDefinition, ExperimentLog
from research.llm import LLMClient
from research.registry import FACTOR_REGISTRY
from research.report_builder import build_consolidated_report
from research.reports.quantstats_report import QuantStatsReport
from research.strategies.top_pct import TopPctStrategy
from research.universe import build_clean_universe

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    """Everything a caller needs to report back to the user."""

    experiment: ExperimentDefinition
    universe_size: int
    train_metrics: dict
    holdout_metrics: dict
    train_report_path: Path
    holdout_report_path: Path
    consolidated_report_path: Path
    trial_count: int
    analysis: str


def _load_price_panel(
    symbols: list[str], start: str, end: str
) -> pd.DataFrame:
    raw_dir = PROJECT_ROOT / "data" / "raw" / "daily"
    con = duckdb.connect()
    symbols_sql = ",".join(f"'{s}'" for s in symbols)
    frame = con.execute(
        f"""
        SELECT date, symbol, close
        FROM read_parquet('{raw_dir.as_posix()}/*.parquet')
        WHERE symbol IN ({symbols_sql})
          AND date BETWEEN '{start}' AND '{end}'
        """
    ).df()
    panel = frame.pivot(index="date", columns="symbol", values="close")
    panel.index = pd.to_datetime(panel.index)
    return panel.sort_index()


def _load_benchmark(symbol: str, start: str, end: str) -> pd.Series:
    storage = ParquetStorage(PROJECT_ROOT / "data" / "raw" / "index")
    cached = storage.load(symbol)
    if cached is None:
        cached = AKShareProvider().fetch_index(symbol)
        storage.save(symbol, cached)
    cached = cached.set_index(pd.to_datetime(cached["date"])).sort_index()
    return cached.loc[start:end, "close"].pct_change()


def run(goal_text: str) -> PipelineResult:
    """Run the full research loop for one natural-language goal."""
    settings = load_settings().get("research", {})
    train_start = settings.get("train_start", "2015-01-01")
    train_end = settings.get("train_end", "2024-12-31")
    holdout_start = settings.get("holdout_start", "2025-01-01")
    holdout_end = pd.Timestamp.today().strftime("%Y-%m-%d")
    universe_cfg = settings.get("universe", {})
    report_dir = PROJECT_ROOT / settings.get(
        "report_dir", "data/warehouse/reports"
    )
    log_path = PROJECT_ROOT / "data" / "warehouse" / "experiments.jsonl"

    llm = LLMClient()
    experiment = llm.parse_intent(goal_text)
    logger.info("experiment: %s", experiment.model_dump())

    universe = build_clean_universe(
        top_n=universe_cfg.get("top_n", 800),
        min_history_days=universe_cfg.get("min_history_days", 250),
    )

    panel = _load_price_panel(universe, train_start, holdout_end)
    factor = FACTOR_REGISTRY[experiment.factor]["cls"]()
    scores = factor.compute(panel)
    strategy = TopPctStrategy(top_pct=experiment.top_pct)
    engine = VectorBTEngine()
    report_gen = QuantStatsReport()
    exp_log = ExperimentLog(log_path)

    def run_phase(phase: str, start: str, end: str) -> tuple[dict, Path]:
        weights = strategy.build_weights(
            scores.loc[start:end], experiment.rebalance_days
        )
        result = engine.run(
            panel.loc[start:end], weights, experiment.fee_rate
        )
        benchmark = _load_benchmark(experiment.benchmark, start, end)
        metrics = report_gen.metrics(result, benchmark)
        out_path = report_dir / f"{phase}_{experiment.factor}.html"
        report_gen.build(result, benchmark, out_path)
        return metrics, out_path

    train_metrics, train_report_path = run_phase(
        "train", train_start, train_end
    )
    holdout_metrics, holdout_report_path = run_phase(
        "holdout", holdout_start, holdout_end
    )

    # One record per full run (both phases), so trial-count reflects
    # "how many experiments have been tried", not "how many phases".
    exp_log.append(
        experiment,
        {"train": train_metrics, "holdout": holdout_metrics},
        phase="full_run",
    )
    trial_count = exp_log.count_trials()
    analysis = llm.summarize(
        {
            "train": train_metrics,
            "holdout": holdout_metrics,
            "trial_count_so_far": trial_count,
        },
        experiment,
    )

    consolidated_report_path = build_consolidated_report(
        experiment=experiment,
        universe_size=len(universe),
        trial_count=trial_count,
        train_metrics=train_metrics,
        holdout_metrics=holdout_metrics,
        train_report_path=train_report_path,
        holdout_report_path=holdout_report_path,
        analysis=analysis,
        out_path=report_dir / f"report_{experiment.factor}.html",
    )

    return PipelineResult(
        experiment=experiment,
        universe_size=len(universe),
        train_metrics=train_metrics,
        holdout_metrics=holdout_metrics,
        train_report_path=train_report_path,
        holdout_report_path=holdout_report_path,
        consolidated_report_path=consolidated_report_path,
        trial_count=trial_count,
        analysis=analysis,
    )

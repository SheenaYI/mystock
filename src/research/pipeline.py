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

from dataclasses import dataclass, replace
import json
from pathlib import Path

import duckdb
import pandas as pd

from common.logger import PROJECT_ROOT, get_logger, load_settings
from data.akshare import AKShareProvider
from data.storage import ParquetStorage
from research.data_contracts import amount_invalid_mask, load_ohlcv_contract, validate_amount_panel
from research.diagnostics import (
    relative_performance_diagnostics,
    score_diagnostics,
    write_diagnostics,
)
from research.portfolio.benchmark_clock import aligned_close_benchmark_returns
from research.portfolio.costs import CostModel
from research.backtest.engine import MarketPrices
from research.backtest.lot_ledger_engine import ExecutionPolicy, LotLedgerEngine
from research.backtest.corporate_action_adapter import load_snapshot_actions
from research.contracts.experiment import FrozenExperiment, build_evidence_contract
from research.experiment import ExperimentLog
from research.factors.extended import (
    select_high_coverage_low_redundancy,
    technical_20_features,
)
from research.labels import forward_excess_return_20d
from research.llm.report_explainer import ReportExplainer
from research.llm.react_lite import ReActLiteSelector
from research.llm.evidence import build_factor_evidence
from research.models.rolling import rolling_qlib_scores
from research.models.model_selection import select_model
from research.state import classify_market_state
from research.report_builder import build_consolidated_report
from research.reports.quantstats_report import QuantStatsReport
from research.portfolio.topk_dropout import TopKDropoutStrategy
from research.universe import load_historical_universe

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    """Everything a caller needs to report back to the user."""

    experiment: FrozenExperiment
    universe_size: int
    train_metrics: dict
    holdout_metrics: dict
    train_report_path: Path
    holdout_report_path: Path
    locked_metrics: dict
    locked_report_path: Path
    consolidated_report_path: Path
    diagnostics_path: Path
    trial_count: int
    analysis: str


BASE_FACTORS = (
    "return_5", "return_20", "return_60", "ma_gap_20", "volatility_20",
    "volume_ratio_20", "intraday_range",
)


def _profile_features(
    *, profile: str, features: pd.DataFrame, benchmark_prices: pd.DataFrame,
    decision_dates: pd.DatetimeIndex, base_factors: tuple[str, ...],
    labels: pd.DataFrame, llm_start: pd.Timestamp | None = None,
    llm_end: pd.Timestamp | None = None,
) -> dict[pd.Timestamp, tuple[str, ...]]:
    """Build one common date->factor mapping for S0/S1/S2/S3."""
    candidates = tuple(column for column in features.columns if column not in base_factors)
    def with_date_coverage(date: pd.Timestamp, selected: tuple[str, ...]) -> tuple[str, ...]:
        """Drop only low-coverage extensions for this decision date."""
        row = features.xs(date, level="datetime")
        eligible = row[list(base_factors)].notna().all(axis=1)
        if profile == "s3":
            # S3 actions are authoritative: a dropped/replaced baseline must
            # not be silently reintroduced by the warm-up guard used by S0-S2.
            return tuple(
                factor for factor in selected
                if factor in row.columns and row.loc[eligible, factor].notna().mean() >= 0.95
            )
        base = tuple(column for column in base_factors if row.loc[eligible, column].notna().mean() >= 0.95)
        extensions = tuple(
            column for column in selected if column not in base_factors
            and row.loc[eligible, column].notna().mean() >= 0.95
        )
        # Keep the frozen baseline contract intact during warm-up; a partial
        # baseline must wait for complete coverage rather than silently
        # changing the model's feature set.
        return (base_factors if len(base) < len(base_factors) else base) + extensions

    if profile == "m0":
        return {pd.Timestamp(date): ("return_20",) for date in decision_dates}
    if profile == "s0":
        return {pd.Timestamp(date): with_date_coverage(pd.Timestamp(date), base_factors) for date in decision_dates}
    if profile == "s1":
        extensions = select_high_coverage_low_redundancy(
            features, base_factors=base_factors, start="2021-01-01", end="2023-12-31",
        )
        selected = base_factors + extensions
        return {pd.Timestamp(date): with_date_coverage(pd.Timestamp(date), selected) for date in decision_dates}
    if profile == "s2":
        mapping = {
            "S1_trend": ("return_120", "trend_efficiency_60", "vol_adjusted_return_60"),
            "S2_stress": ("downside_volatility_20", "drawdown_60", "illiquidity_20"),
            "S0_insufficient_evidence": (),
            "S3_range_or_uncertain": (),
        }
        return {
            pd.Timestamp(date): with_date_coverage(
                pd.Timestamp(date), base_factors + mapping[classify_market_state(benchmark_prices.loc[:date, "close"])]
            )
            for date in decision_dates
        }
    if profile == "s3":
        selector = ReActLiteSelector(PROJECT_ROOT / "data" / "warehouse" / "llm_calls.jsonl")
        selected_by_date: dict[pd.Timestamp, tuple[str, ...]] = {}
        for date in decision_dates:
            # Smoke runs can restrict real LLM calls to a validation window;
            # dates outside it remain on the frozen seven-factor baseline.
            if ((llm_start is not None and pd.Timestamp(date) < llm_start)
                    or (llm_end is not None and pd.Timestamp(date) > llm_end)):
                selected_by_date[pd.Timestamp(date)] = with_date_coverage(
                    pd.Timestamp(date), tuple(base_factors)
                )
                continue
            # Each rebalance is an independent decision from the frozen
            # seven-factor baseline.  A previous period's add/drop/replace
            # recipe must not silently become the next period's baseline.
            current_recipe = tuple(base_factors)
            state = classify_market_state(benchmark_prices.loc[:date, "close"])
            row = features.xs(pd.Timestamp(date), level="datetime")
            coverage = {
                factor: round(float(row[factor].notna().mean()), 4)
                for factor in candidates
            }
            decision = selector.decide(
                decision_id=f"factor-selection-{date.date()}", state=state,
                evidence={
                    **build_factor_evidence(
                        features=features,
                        labels=labels,
                        benchmark_close=benchmark_prices["close"],
                        as_of=pd.Timestamp(date),
                        base_factors=base_factors,
                        candidates=candidates,
                    ),
                    "decision_date": str(date.date()),
                    "candidate_count": len(candidates),
                    "candidate_names": list(candidates),
                    "candidate_coverage": coverage,
                    "base_factors": list(base_factors),
                },
                candidates=candidates,
                current_factors=current_recipe,
            )
            current_recipe = decision.selected
            selected_by_date[pd.Timestamp(date)] = with_date_coverage(pd.Timestamp(date), current_recipe)
        return selected_by_date
    raise ValueError(f"unknown experiment profile: {profile}")


def _direct_momentum_scores(
    features: pd.DataFrame, decision_dates: pd.DatetimeIndex,
    sessions: pd.DatetimeIndex, instruments: pd.Index,
) -> pd.DataFrame:
    """Return direct 20-day momentum ranks only on frozen decision dates.

    M0 deliberately bypasses LightGBM: it is the like-for-like replacement
    for the original project's direct ``return_20`` ranking, while retaining
    the new universe and next-open execution contract.
    """
    wide = features["return_20"].unstack("instrument")
    scores = pd.DataFrame(float("nan"), index=sessions, columns=instruments)
    scores.loc[decision_dates] = wide.loc[decision_dates]
    return scores


def _load_price_panels(
    symbols: list[str], start: str, end: str, *, raw_root: Path
) -> dict[str, pd.DataFrame]:
    """Load unadjusted close inputs and next-open execution inputs.

    The raw-data manifest is validated by the data-contract layer before this
    function is allowed to serve a formal run.  This loader intentionally does
    not fill missing bars: an unavailable execution price must stop the run.
    """
    raw_dir = Path(raw_root) / "daily"
    con = duckdb.connect()
    symbols_sql = ",".join(f"'{s}'" for s in symbols)
    frame = con.execute(
        f"""
        SELECT date, symbol, open, high, low, close, volume, amount
        FROM read_parquet('{raw_dir.as_posix()}/*.parquet')
        WHERE symbol IN ({symbols_sql})
          AND date BETWEEN '{start}' AND '{end}'
        """
    ).df()
    panels = {}
    for field in ("open", "high", "low", "close", "volume", "amount"):
        panel = frame.pivot(index="date", columns="symbol", values=field)
        panel.index = pd.to_datetime(panel.index)
        panels[field] = panel.sort_index().reindex(columns=sorted(symbols))
    return panels


def _apply_historical_membership(
    panel: pd.DataFrame, *, universe, index_code: str
) -> pd.DataFrame:
    """Mask scores outside the constituents actually eligible on each date."""
    mask = pd.DataFrame(False, index=panel.index, columns=panel.columns)
    for session in panel.index:
        members = universe.require_members_on(index_code, session.date())
        mask.loc[session, [symbol for symbol in members if symbol in mask.columns]] = True
    return mask


def _load_benchmark_prices(symbol: str, start: str, end: str) -> pd.DataFrame:
    storage = ParquetStorage(PROJECT_ROOT / "data" / "raw" / "index")
    cached = storage.load(symbol)
    if cached is None:
        cached = AKShareProvider().fetch_index(symbol)
        storage.save(symbol, cached)
    cached = cached.set_index(pd.to_datetime(cached["date"])).sort_index()
    return cached.loc[start:end, ["open", "close"]]


def _load_tradability_panels(symbols: list[str], sessions: pd.DatetimeIndex,
                             *, root: Path) -> dict[str, pd.DataFrame]:
    """Load verified JoinQuant status panels aligned to the OHLCV sessions."""
    manifest = Path(root) / "manifests" / "tradability.json"
    if not manifest.is_file():
        raise ValueError(f"missing tradability manifest: {manifest}")
    raw_dir = Path(root) / "daily"
    con = duckdb.connect()
    symbols_sql = ",".join(f"'{s}'" for s in symbols)
    frame = con.execute(
        f"""
        SELECT date, symbol, paused, high_limit, low_limit, pre_close
        FROM read_parquet('{raw_dir.as_posix()}/*.parquet')
        WHERE symbol IN ({symbols_sql})
          AND date BETWEEN '{sessions.min().date()}' AND '{sessions.max().date()}'
        """
    ).df()
    panels: dict[str, pd.DataFrame] = {}
    for field in ("paused", "high_limit", "low_limit", "pre_close"):
        panel = frame.pivot(index="date", columns="symbol", values=field)
        panel.index = pd.to_datetime(panel.index)
        panels[field] = panel.reindex(index=sessions, columns=sorted(symbols))
    return panels


def run(
    profile: str = "s0", *, tradability_mode: str = "fail",
    llm_start: str | None = None, llm_end: str | None = None,
) -> PipelineResult:
    """Run the frozen technical-baseline contract; no LLM sets methodology."""
    settings = load_settings().get("research", {})
    preliminary_experiment = FrozenExperiment(profile=profile, tradability_mode=tradability_mode)
    train_start = preliminary_experiment.protocol.train_start
    train_end = "2023-12-31"
    holdout_start = preliminary_experiment.protocol.validation_start
    holdout_end = preliminary_experiment.protocol.validation_end
    locked_end = preliminary_experiment.protocol.locked_end
    universe_cfg = settings.get("universe", {})
    report_dir = PROJECT_ROOT / settings.get(
        "report_dir", "data/warehouse/reports"
    )
    execution_dir = PROJECT_ROOT / "data" / "warehouse" / "execution"
    execution_dir.mkdir(parents=True, exist_ok=True)
    log_path = PROJECT_ROOT / "data" / "warehouse" / "experiments.jsonl"
    raw_root = PROJECT_ROOT / settings.get(
        "raw_data_root", "data/raw/unadjusted_akshare"
    )
    action_path = PROJECT_ROOT / "data" / "raw" / "corporate_actions_akshare" / "observations.jsonl"
    membership_manifest = PROJECT_ROOT / "data" / "raw" / "membership" / "csi300" / "historical_index_membership_manifest.json"
    action_manifest = PROJECT_ROOT / "data" / "raw" / "corporate_actions_akshare" / "manifest.json"
    experiment = FrozenExperiment(
        profile=profile,
        tradability_mode=tradability_mode,
        evidence=build_evidence_contract(
            raw_root=raw_root, membership_manifest=membership_manifest,
            corporate_action_manifest=action_manifest,
            implementation_root=PROJECT_ROOT / "src" / "research",
        ),
    )
    experiment.require_resolved_evidence()
    actions = load_snapshot_actions(action_path) if action_path.exists() else ()

    # Prevent a forward-adjusted download from silently becoming a tradable
    # next-open execution series.  Factor adjustment is added later from the
    # company-action evidence archive, not by trusting a vendor's qfq series.
    load_ohlcv_contract(raw_root).require_execution_compatible()

    logger.info("frozen experiment: %s", experiment.contract_hash)

    cutoff = pd.Timestamp(f"2000-01-01 {universe_cfg.get('decision_cutoff_time', '15:30')}").time()
    universe = load_historical_universe(
        PROJECT_ROOT / universe_cfg["membership_path"],
        expected_index_code=universe_cfg.get("index_code", "000300.XSHG"),
        decision_cutoff_time=cutoff,
        timezone_name=universe_cfg.get("timezone", "Asia/Shanghai"),
    )
    index_code = universe_cfg.get("index_code", "000300.XSHG")
    symbols = sorted({row.symbol for row in universe.memberships})
    panels = _load_price_panels(symbols, train_start, locked_end, raw_root=raw_root)
    invalid_amount = amount_invalid_mask(panels["amount"])
    if invalid_amount.any().any():
        quality_dir = PROJECT_ROOT / "data" / "warehouse" / "quality"
        quality_dir.mkdir(parents=True, exist_ok=True)
        invalid_rows = (
            panels["amount"].where(invalid_amount)
            .stack()
            .rename("amount")
            .reset_index()
            .rename(columns={"level_0": "date", "level_1": "symbol"})
        )
        invalid_rows.to_csv(quality_dir / "invalid_amount_rows.csv", index=False)
        logger.warning(
            "quarantining %d invalid amount cells; see %s",
            len(invalid_rows),
            quality_dir / "invalid_amount_rows.csv",
        )
    validate_amount_panel(panels["amount"], ignore_mask=invalid_amount)
    close_panel = panels["close"]
    open_panel = panels["open"]
    membership_mask = _apply_historical_membership(
        close_panel, universe=universe, index_code=index_code
    )
    # A zero/missing turnover observation is not silently repaired.  It makes
    # that stock-date unavailable for selection and execution.
    membership_mask = membership_mask & ~invalid_amount
    features = technical_20_features(
        close=close_panel,
        high=panels["high"],
        low=panels["low"],
        volume=panels["volume"],
        amount=panels["amount"],
    )
    member_long = membership_mask.stack(future_stack=True)
    features = features.where(member_long, other=float("nan"))
    benchmark_prices = _load_benchmark_prices(experiment.protocol.benchmark, train_start, locked_end)
    benchmark_prices = benchmark_prices.reindex(close_panel.index)
    if benchmark_prices.isna().any().any():
        raise ValueError("benchmark OHLCV does not cover every strategy session")
    tradability_panels = _load_tradability_panels(
        symbols, close_panel.index, root=PROJECT_ROOT / "data" / "raw" / "tradability_joinquant"
    )
    labels = forward_excess_return_20d(open_panel, benchmark_prices["open"], horizon=experiment.protocol.horizon)
    # Select one LightGBM configuration using development folds only.  The
    # selected configuration is then shared by S0--S3 and later windows.
    selected_model, model_selection_table, selected_model_name = select_model(
        features=features[list(BASE_FACTORS)], labels=labels, base_config=experiment.model
    )
    experiment = replace(experiment, model=selected_model)
    selection_dir = PROJECT_ROOT / "data" / "warehouse" / "model_selection"
    selection_dir.mkdir(parents=True, exist_ok=True)
    model_selection_table.to_csv(selection_dir / f"{profile}_m1_m6_development.csv", index=False)
    decision_dates = close_panel.index[::experiment.protocol.rebalance_days]
    selected_by_date = _profile_features(
        profile=profile, features=features, benchmark_prices=benchmark_prices,
        decision_dates=decision_dates, base_factors=BASE_FACTORS, labels=labels,
        llm_start=pd.Timestamp(llm_start) if llm_start else None,
        llm_end=pd.Timestamp(llm_end) if llm_end else None,
    )
    if profile == "m0":
        scores = _direct_momentum_scores(
            features, decision_dates, close_panel.index, close_panel.columns
        )
    else:
        scores = rolling_qlib_scores(
            features=features, labels=labels, decision_dates=decision_dates,
            train_start=train_start, horizon=experiment.protocol.horizon, model_config=selected_model,
            selected_features_by_date=selected_by_date,
        )
    if not scores.notna().any().any():
        raise ValueError(
            f"profile {profile} produced no valid scores; check factor coverage and warm-up"
        )
    states = pd.Series(
        {date: classify_market_state(benchmark_prices.loc[:date, "close"]) for date in decision_dates},
        name="state",
    )
    fold_summary, state_summary, quantiles, rank_ic = score_diagnostics(
        scores=scores, labels=labels, states=states
    )
    strategy = TopKDropoutStrategy(top_k=experiment.portfolio.top_k, n_drop=experiment.portfolio.n_drop)
    engine = LotLedgerEngine(
        init_cash=experiment.portfolio.initial_cash,
        policy=ExecutionPolicy(
            unknown_tradability=tradability_mode,
            missing_valuation="carry_last" if tradability_mode == "block" else "fail",
        ),
    )
    report_gen = QuantStatsReport()
    exp_log = ExperimentLog(log_path)

    phase_diagnostics: dict[str, tuple[pd.DataFrame, dict[str, float | None]]] = {}
    phase_status: dict[str, dict[str, object]] = {}

    def run_phase(phase: str, start: str, end: str) -> tuple[dict, Path]:
        weights = strategy.build_weights(
            scores.loc[start:end], experiment.protocol.rebalance_days
        )
        result = engine.run(
            MarketPrices(
                execution_open=open_panel.loc[start:end],
                valuation_close=close_panel.loc[start:end],
                tradability={name: panel.loc[start:end] for name, panel in tradability_panels.items()},
            ), weights, experiment.execution, actions=actions
        )
        kinds = result.trades.get("kind", pd.Series(dtype=str)).dropna().astype(str)
        quarantine_kinds = sorted({kind for kind in kinds if kind.startswith("blocked_")})
        phase_status[phase] = {
            "run_status": "complete_with_quarantines" if quarantine_kinds else "complete",
            "quarantine_kinds": quarantine_kinds,
            "quarantine_records": int(kinds.str.startswith("blocked_").sum()),
        }
        # The return series alone cannot reconstruct whether a change came
        # from a buy, sell, dividend, or corporate action.  Persist the ledger
        # next to the run under its immutable contract identifier.
        ledger_path = execution_dir / f"{experiment.contract_hash}_{phase}_ledger.csv"
        result.trades.to_csv(ledger_path, index=False)
        (execution_dir / f"{experiment.contract_hash}_{phase}_ledger.json").write_text(
            json.dumps(
                {
                    "contract_hash": experiment.contract_hash,
                    "phase": phase,
                    "ledger_csv": ledger_path.name,
                    "record_count": len(result.trades),
                    "execution_clock": "signal_close_to_next_open; close_valuation",
                    "lot_size": 100,
                    "run_status": phase_status.get(phase, {}).get("run_status"),
                    "quarantine_kinds": phase_status.get(phase, {}).get("quarantine_kinds", []),
                },
                ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        benchmark = aligned_close_benchmark_returns(
            benchmark_open=benchmark_prices.loc[start:end, "open"],
            benchmark_close=benchmark_prices.loc[start:end, "close"],
            signal_weights=weights,
        )
        metrics = report_gen.metrics(result, benchmark)
        metrics["run_status"] = phase_status[phase]["run_status"]
        phase_diagnostics[phase] = relative_performance_diagnostics(result.returns, benchmark)
        out_path = report_dir / f"{phase}_{experiment.factor_name}.html"
        report_gen.build(result, benchmark, out_path)
        return metrics, out_path

    train_metrics, train_report_path = run_phase(
        "train", train_start, train_end
    )
    holdout_metrics, holdout_report_path = run_phase(
        "holdout", holdout_start, holdout_end
    )
    locked_metrics, locked_report_path = run_phase(
        "locked_2025", experiment.protocol.locked_start, locked_end
    )
    diagnostics_path = write_diagnostics(
        out_dir=PROJECT_ROOT / "data" / "warehouse" / "diagnostics",
        profile=experiment.factor_name,
        fold_summary=fold_summary,
        state_summary=state_summary,
        quantiles=quantiles,
        rank_ic=rank_ic,
        phases=phase_diagnostics,
    )

    # One record per full run (both phases), so trial-count reflects
    # "how many experiments have been tried", not "how many phases".
    exp_log.append(
        experiment,
        {"train": train_metrics, "holdout": holdout_metrics, "locked_2025": locked_metrics},
        phase="full_run",
    )
    trial_count = exp_log.count_trials()
    analysis = ReportExplainer().explain(
        metrics={
            "train": train_metrics,
            "holdout": holdout_metrics,
            "trial_count_so_far": trial_count,
        },
        method_summary=f"{experiment.factor_name}; fixed contract {experiment.contract_hash}; Qlib LightGBM; TopK={experiment.portfolio.top_k}; n_drop={experiment.portfolio.n_drop}",
    )

    consolidated_report_path = build_consolidated_report(
        experiment=experiment,
        universe_size=len(symbols),
        trial_count=trial_count,
        train_metrics=train_metrics,
        holdout_metrics=holdout_metrics,
        train_report_path=train_report_path,
        holdout_report_path=holdout_report_path,
        diagnostics_path=diagnostics_path,
        analysis=analysis,
        phase_status=phase_status,
        out_path=report_dir / f"report_{experiment.factor_name}.html",
    )

    return PipelineResult(
        experiment=experiment,
        universe_size=len(symbols),
        train_metrics=train_metrics,
        holdout_metrics=holdout_metrics,
        train_report_path=train_report_path,
        holdout_report_path=holdout_report_path,
        locked_metrics=locked_metrics,
        locked_report_path=locked_report_path,
        consolidated_report_path=consolidated_report_path,
        diagnostics_path=diagnostics_path,
        trial_count=trial_count,
        analysis=analysis,
    )

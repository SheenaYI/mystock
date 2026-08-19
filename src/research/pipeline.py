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
from research.backtest.engine import BacktestResult, MarketPrices
from research.backtest.lot_ledger_engine import ExecutionPolicy, LotLedgerEngine
from research.backtest.corporate_action_adapter import load_snapshot_actions
from research.contracts.experiment import (
    FrozenExperiment, ProtocolContract,
    PortfolioContract,
    build_evidence_contract,
)
from research.experiment import ExperimentLog
from research.factors.extended import (
    select_high_coverage_low_redundancy,
    technical_25_features,
)
from research.factors.catalog import BASE_FACTORS
from research.labels import forward_excess_return
from research.llm.report_explainer import ReportExplainer
from research.llm.react_lite import (
    PROMPT_VERSION, S3_NEXT_PROMPT_VERSION, S4_PROMPT_VERSION, ReActLiteSelector,
)
from research.llm.live_literature import retrieve_live_literature
from research.llm.evidence import build_factor_evidence
from research.llm.evidence_cache import EvidenceCache
from research.llm.historical_context import load_context_as_of
from research.llm.literature_registry import retrieve_literature_as_of
from research.models.rolling import rolling_qlib_scores
from research.models.model_selection import select_model
from research.state import classify_market_state, market_state_snapshot
from research.report_builder import build_consolidated_report
from research.reports.quantstats_report import QuantStatsReport
from research.reports.paths import profile_diagnostics_dir, profile_report_dir
from research.portfolio.topk_dropout import TopKDropoutStrategy
from research.universe import load_historical_universe

logger = get_logger(__name__)


def _format_metric(value: object, kind: str) -> str:
    """Format one report annotation metric without failing a completed run."""
    try:
        return f"{float(value):.1%}" if kind == "pct" else f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "暂无有效值"


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
    continuous_report_path: Path
    consolidated_report_path: Path
    diagnostics_path: Path
    trial_count: int
    analysis: str


def _factor_selection_namespace(experiment: FrozenExperiment) -> str:
    """Return a cache key for factor decisions, independent of S4 turnover.

    S4-W1-n2 and S4-W1-n5 are a paired portfolio experiment.  Their LLM
    decisions must be identical; otherwise the two return series would mix
    turnover with a second stochastic factor-selection draw.
    """
    if experiment.profile in {"s4", "s4_n2"}:
        return replace(
            experiment, profile="s4", portfolio=PortfolioContract(),
        ).contract_hash
    return experiment.contract_hash


def _profile_features(
    *, profile: str, features: pd.DataFrame, benchmark_prices: pd.DataFrame,
    stock_close: pd.DataFrame,
    decision_dates: pd.DatetimeIndex, base_factors: tuple[str, ...],
    labels: pd.DataFrame, llm_start: pd.Timestamp | None = None,
    llm_end: pd.Timestamp | None = None, cache_namespace: str | None = None,
    model_config=None, horizon: int = 20, factor_decision_days: int = 20,
    rebalance_days: int = 20,
) -> dict[pd.Timestamp, tuple[str, ...]]:
    """Build one common date->factor mapping for S0/S1/S2/S3."""
    candidates = tuple(column for column in features.columns if column not in base_factors)
    def with_date_coverage(date: pd.Timestamp, selected: tuple[str, ...]) -> tuple[str, ...]:
        """Drop only low-coverage extensions for this decision date."""
        row = features.xs(date, level="datetime")
        eligible = row[list(base_factors)].notna().all(axis=1)
        if profile in {"s3", "s3_next", "s4", "s4_n2"}:
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
    if profile in {"s3", "s3_next", "s4", "s4_n2"}:
        is_challenger = profile == "s3_next"
        is_s4 = profile in {"s4", "s4_n2"}
        if factor_decision_days % rebalance_days:
            raise ValueError("factor_decision_days must be a whole number of rebalance intervals")
        action_dates = decision_dates[:: factor_decision_days // rebalance_days]
        selector = ReActLiteSelector(
            PROJECT_ROOT / "data" / "warehouse" / "llm_calls.jsonl",
            prompt_version=(S4_PROMPT_VERSION if is_s4 else S3_NEXT_PROMPT_VERSION if is_challenger else PROMPT_VERSION),
            # S3-next is the literature-constrained challenger.  S4 may use
            # retrieved literature as supporting context, but an empty local
            # archive must not turn a valid market-state decision into an
            # artificial failure.
            require_literature_refs=is_challenger,
            enforce_marginal_evidence=not is_s4,
            require_economic_rationales=is_s4,
        )
        evidence_namespace = f"{cache_namespace or 'uncached'}-{selector.prompt_version}"
        evidence_cache = EvidenceCache(
            PROJECT_ROOT / "data" / "warehouse" / "cache" / "evidence",
            evidence_namespace,
        )
        # Prompt/action contract changes must never replay decisions produced
        # under an older selector protocol.  Keep the old cache for audit, but
        # put new decisions in a versioned namespace.
        decision_namespace = evidence_namespace
        decision_cache_root = PROJECT_ROOT / "data" / "warehouse" / "cache" / "decisions" / decision_namespace
        decision_cache_root.mkdir(parents=True, exist_ok=True)
        selected_on_action_date: dict[pd.Timestamp, tuple[str, ...]] = {}
        for date in action_dates:
            # Smoke runs can restrict real LLM calls to a validation window;
            # dates outside it remain on the frozen seven-factor baseline.
            if ((llm_start is not None and pd.Timestamp(date) < llm_start)
                    or (llm_end is not None and pd.Timestamp(date) > llm_end)):
                selected_on_action_date[pd.Timestamp(date)] = with_date_coverage(
                    pd.Timestamp(date), tuple(base_factors)
                )
                continue
            # Each rebalance is an independent decision from the frozen
            # seven-factor baseline.  A previous period's add/drop/replace
            # recipe must not silently become the next period's baseline.
            current_recipe = tuple(base_factors)
            state_snapshot = market_state_snapshot(
                benchmark_close=benchmark_prices["close"],
                stock_close=stock_close,
                as_of=pd.Timestamp(date),
            )
            state = str(state_snapshot["state"])
            row = features.xs(pd.Timestamp(date), level="datetime")
            base_eligible = row[list(base_factors)].notna().all(axis=1)
            coverage = {
                factor: round(float(row.loc[base_eligible, factor].notna().mean()), 4)
                for factor in candidates
            }
            evidence = evidence_cache.get_or_build(
                str(pd.Timestamp(date).date()),
                lambda: {
                    **build_factor_evidence(
                        features=features,
                        labels=labels,
                        benchmark_close=benchmark_prices["close"],
                        as_of=pd.Timestamp(date),
                        base_factors=base_factors,
                        candidates=candidates,
                        state_snapshot=state_snapshot,
                        historical_context=load_context_as_of(
                            PROJECT_ROOT / "data" / "raw" / "historical_context.jsonl",
                            cutoff_date=pd.Timestamp(date),
                        ),
                        model_config=model_config,
                        horizon=horizon,
                        include_portfolio_marginal=not is_s4,
                    ),
                    "decision_date": str(date.date()),
                    "candidate_count": len(candidates),
                    "candidate_names": list(candidates),
                    "candidate_coverage": coverage,
                    "base_factors": list(base_factors),
                    "frozen_literature": retrieve_literature_as_of(
                        as_of=pd.Timestamp(date), state=state, candidates=candidates,
                    ) if is_challenger else [],
                    "live_literature": retrieve_live_literature(
                        as_of=str(pd.Timestamp(date).date()), state=state,
                        cache_root=PROJECT_ROOT / "data" / "warehouse" / "cache" / "live_literature",
                    ) if is_s4 else [],
                },
            )
            decision_id = f"factor-selection-{date.date()}"
            decision_path = decision_cache_root / f"{date.date()}.json"
            if decision_path.is_file():
                from research.llm.react_lite import SelectionDecision
                cached_decision = json.loads(decision_path.read_text(encoding="utf-8"))
                decision = SelectionDecision(
                    decision_id=decision_id, state=state,
                    selected=tuple(cached_decision["selected"]),
                    action=cached_decision["action"],
                    rounds=int(cached_decision["rounds"]),
                    reason=cached_decision.get("reason", "cached"),
                )
            else:
                decision = selector.decide(
                    decision_id=decision_id, state=state, evidence=evidence,
                    candidates=candidates, current_factors=current_recipe,
                )
                decision_path.write_text(json.dumps({
                    "selected": list(decision.selected), "action": decision.action,
                    "rounds": decision.rounds, "reason": decision.reason,
                }, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            current_recipe = decision.selected
            selected_on_action_date[pd.Timestamp(date)] = with_date_coverage(pd.Timestamp(date), current_recipe)
        action_index = pd.DatetimeIndex(selected_on_action_date)
        return {
            pd.Timestamp(date): selected_on_action_date[action_index[action_index <= date][-1]]
            for date in decision_dates
        }
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
    is_s4_weekly = profile in {"s4", "s4_n2"}
    protocol = (
        ProtocolContract(horizon=5, rebalance_days=5, model_retrain_days=20, factor_decision_days=20)
        if is_s4_weekly else ProtocolContract()
    )
    portfolio = PortfolioContract(n_drop=2) if profile in {"s3_next", "s4_n2"} else PortfolioContract()
    preliminary_experiment = FrozenExperiment(
        profile=profile, protocol=protocol, tradability_mode=tradability_mode, portfolio=portfolio,
    )
    train_start = preliminary_experiment.protocol.train_start
    train_end = "2023-12-31"
    holdout_start = preliminary_experiment.protocol.validation_start
    holdout_end = preliminary_experiment.protocol.validation_end
    locked_end = preliminary_experiment.protocol.locked_end
    universe_cfg = settings.get("universe", {})
    report_root = PROJECT_ROOT / settings.get(
        "report_dir", "data/warehouse/reports"
    )
    report_dir = profile_report_dir(report_root, profile)
    report_dir.mkdir(parents=True, exist_ok=True)
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
        profile=profile, protocol=protocol, portfolio=portfolio,
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
    benchmark_prices = _load_benchmark_prices(experiment.protocol.benchmark, train_start, locked_end)
    benchmark_prices = benchmark_prices.reindex(close_panel.index)
    if benchmark_prices.isna().any().any():
        raise ValueError("benchmark OHLCV does not cover every strategy session")
    features = technical_25_features(
        close=close_panel,
        high=panels["high"],
        low=panels["low"],
        volume=panels["volume"],
        amount=panels["amount"],
        benchmark_close=benchmark_prices["close"],
    )
    member_long = membership_mask.stack(future_stack=True)
    features = features.where(member_long, other=float("nan"))
    tradability_panels = _load_tradability_panels(
        symbols, close_panel.index, root=PROJECT_ROOT / "data" / "raw" / "tradability_joinquant"
    )
    labels = forward_excess_return(open_panel, benchmark_prices["open"], horizon=experiment.protocol.horizon)
    # Select one LightGBM configuration using development folds only.  The
    # selected configuration is then shared by S0--S3 and later windows.
    selected_model, model_selection_table, selected_model_name = select_model(
        features=features[list(BASE_FACTORS)], labels=labels, base_config=experiment.model,
        horizon=experiment.protocol.horizon,
    )
    experiment = replace(experiment, model=selected_model)
    selection_dir = PROJECT_ROOT / "data" / "warehouse" / "model_selection"
    selection_dir.mkdir(parents=True, exist_ok=True)
    model_selection_table.to_csv(selection_dir / f"{profile}_m1_m6_development.csv", index=False)
    evaluation_start = (
        experiment.protocol.validation_start if is_s4_weekly else experiment.protocol.train_start
    )
    decision_dates = close_panel.index[::experiment.protocol.rebalance_days]
    decision_dates = decision_dates[decision_dates >= pd.Timestamp(evaluation_start)]
    selected_by_date = _profile_features(
        profile=profile, features=features, benchmark_prices=benchmark_prices,
        stock_close=close_panel,
        decision_dates=decision_dates, base_factors=BASE_FACTORS, labels=labels,
        llm_start=pd.Timestamp(llm_start) if llm_start else None,
        llm_end=pd.Timestamp(llm_end) if llm_end else None,
        cache_namespace=_factor_selection_namespace(experiment),
        model_config=selected_model,
        horizon=experiment.protocol.horizon,
        factor_decision_days=experiment.protocol.factor_decision_days,
        rebalance_days=experiment.protocol.rebalance_days,
    )
    if profile == "m0":
        scores = _direct_momentum_scores(
            features, decision_dates, close_panel.index, close_panel.columns
        )
    else:
        scores = rolling_qlib_scores(
            features=features, labels=labels, decision_dates=decision_dates,
            train_start=train_start, horizon=experiment.protocol.horizon, model_config=selected_model,
            retrain_days=experiment.protocol.model_retrain_days,
            rebalance_days=experiment.protocol.rebalance_days,
            selected_features_by_date=selected_by_date,
            cache_root=PROJECT_ROOT / "data" / "warehouse" / "cache" / "matrices",
            cache_namespace=experiment.contract_hash,
        )
    # S4 evaluates only 2024–2025.  The feature/label panels still contain
    # 2021–2023 so the expanding LightGBM window has mature training data,
    # but no earlier S4 trading or LLM decision is generated.
    if is_s4_weekly:
        scores = scores.loc[evaluation_start:locked_end]
    if not scores.notna().any().any():
        raise ValueError(
            f"profile {profile} produced no valid scores; check factor coverage and warm-up"
        )
    # Diagnostics must use the same evaluation panel as the scores.  S4 keeps
    # the full label history for PIT-safe model training, but its score panel is
    # intentionally restricted to 2024–2025.
    diagnostic_labels = labels.reindex(index=scores.index, columns=scores.columns)
    states = pd.Series(
        {date: classify_market_state(benchmark_prices.loc[:date, "close"]) for date in decision_dates},
        name="state",
    )
    fold_summary, state_summary, quantiles, rank_ic = score_diagnostics(
        scores=scores, labels=diagnostic_labels, states=states
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

    # Build positions and execute the ledger once over the selected evaluation
    # years.  Training history is deliberately not an invested period here.
    # The former implementation restarted both cash and TopK holdings at the
    # 2024/2025 boundaries.  That made phase reports useful as diagnostics,
    # but unsuitable as a single continuous investment path.  One full run is
    # now the source of truth; phase/year views below are slices of it.
    all_weights = strategy.build_weights(scores, experiment.protocol.rebalance_days)
    execution_open = open_panel.loc[all_weights.index]
    valuation_close = close_panel.loc[all_weights.index]
    execution_tradability = {
        name: panel.loc[all_weights.index] for name, panel in tradability_panels.items()
    }
    continuous_result = engine.run(
        MarketPrices(
            execution_open=execution_open,
            valuation_close=valuation_close,
            tradability=execution_tradability,
        ), all_weights, experiment.execution, actions=actions,
    )
    continuous_benchmark = aligned_close_benchmark_returns(
        benchmark_open=benchmark_prices.loc[all_weights.index, "open"],
        benchmark_close=benchmark_prices.loc[all_weights.index, "close"],
        signal_weights=all_weights,
    )

    phase_diagnostics: dict[str, tuple[pd.DataFrame, dict[str, float | None]]] = {}
    phase_status: dict[str, dict[str, object]] = {}
    if profile in {"s4", "s4_n2"}:
        phase_status["research_scope"] = {
            "classification": "exploratory_non_pit",
            "reason": "LLM received live Crossref index results; outputs are not formal historical evidence.",
        }

    def result_slice(start: str, end: str) -> BacktestResult:
        mask = (continuous_result.returns.index >= pd.Timestamp(start)) & (continuous_result.returns.index <= pd.Timestamp(end))
        trades = continuous_result.trades
        if not trades.empty and "date" in trades:
            trade_dates = pd.to_datetime(trades["date"])
            trades = trades.loc[(trade_dates >= pd.Timestamp(start)) & (trade_dates <= pd.Timestamp(end))].copy()
        return BacktestResult(
            returns=continuous_result.returns.loc[mask],
            value=continuous_result.value.loc[mask],
            trades=trades,
        )

    def record_view(phase: str, start: str, end: str) -> tuple[dict, Path]:
        result = result_slice(start, end)
        benchmark = continuous_benchmark.loc[result.returns.index]
        kinds = result.trades.get("kind", pd.Series(dtype=str)).dropna().astype(str)
        quarantine_kinds = sorted({kind for kind in kinds if kind.startswith("blocked_")})
        phase_status[phase] = {
            "run_status": "complete_with_quarantines" if quarantine_kinds else "complete",
            "quarantine_kinds": quarantine_kinds,
            "quarantine_records": int(kinds.str.startswith("blocked_").sum()),
            "ledger_origin": f"continuous_{pd.Timestamp(evaluation_start).year}_{pd.Timestamp(locked_end).year}",
        }
        ledger_path = execution_dir / f"{experiment.contract_hash}_{phase}_ledger.csv"
        result.trades.to_csv(ledger_path, index=False)
        (execution_dir / f"{experiment.contract_hash}_{phase}_ledger.json").write_text(
            json.dumps(
                {
                    "contract_hash": experiment.contract_hash,
                    "phase": phase,
                    "ledger_csv": ledger_path.name,
                    "record_count": len(result.trades),
                    "ledger_origin": f"continuous_{pd.Timestamp(evaluation_start).year}_{pd.Timestamp(locked_end).year}",
                    "execution_clock": "signal_close_to_next_open; close_valuation",
                    "lot_size": 100,
                    "run_status": phase_status[phase]["run_status"],
                    "quarantine_kinds": quarantine_kinds,
                }, ensure_ascii=False, indent=2,
            ) + "\n", encoding="utf-8",
        )
        metrics = report_gen.metrics(result, benchmark)
        metrics["run_status"] = phase_status[phase]["run_status"]
        phase_diagnostics[phase] = relative_performance_diagnostics(result.returns, benchmark)
        out_path = report_dir / f"{phase}_{experiment.factor_name}.html"
        report_gen.build(result, benchmark, out_path)
        return metrics, out_path

    if is_s4_weekly:
        train_metrics, train_report_path = ({"run_status": "not_evaluated_for_s4_window"}, report_dir / "not_evaluated.html")
    else:
        train_metrics, train_report_path = record_view("train", train_start, train_end)
    holdout_metrics, holdout_report_path = record_view("holdout", holdout_start, holdout_end)
    locked_metrics, locked_report_path = record_view("locked_2025", experiment.protocol.locked_start, locked_end)
    full_phase = f"continuous_{pd.Timestamp(evaluation_start).year}_{pd.Timestamp(locked_end).year}"
    full_metrics, continuous_report_path = record_view(full_phase, evaluation_start, locked_end)

    annual_metrics: dict[str, dict] = {}
    annual_notes: dict[str, str] = {}
    for year in range(pd.Timestamp(evaluation_start).year, pd.Timestamp(locked_end).year + 1):
        year_key = str(year)
        year_result = result_slice(f"{year}-01-01", f"{year}-12-31")
        year_benchmark = continuous_benchmark.loc[year_result.returns.index]
        metrics = report_gen.metrics(year_result, year_benchmark)
        annual_metrics[year_key] = metrics
        strategy_return = float((1.0 + year_result.returns).prod() - 1.0)
        benchmark_return = float((1.0 + year_benchmark).prod() - 1.0)
        excess = strategy_return - benchmark_return
        annual_notes[year_key] = (
            f"- 本策略累计收益 **{strategy_return:.1%}**，沪深300同期 **{benchmark_return:.1%}**，"
            f"相对差额 **{excess:+.1%}**。\n"
            f"- 年内最大回撤为 **{_format_metric(metrics.get('Max Drawdown'), 'pct')}**，"
            f"夏普为 **{_format_metric(metrics.get('Sharpe'), 'num')}**。\n"
            "- 这是该自然年的历史回测切片，用于解释路径；不能据此推断未来收益。"
        )
    diagnostics_path = write_diagnostics(
        out_dir=profile_diagnostics_dir(
            PROJECT_ROOT / "data" / "warehouse" / "diagnostics", profile,
        ),
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
        {"train": train_metrics, "holdout": holdout_metrics, "locked_2025": locked_metrics,
         full_phase: full_metrics, "annual": annual_metrics},
        phase="full_run",
    )
    trial_count = exp_log.count_trials()
    analysis = ReportExplainer().explain(
        metrics={"annual": annual_metrics, "full_period": full_metrics, "trial_count_so_far": trial_count},
        method_summary=f"{experiment.factor_name}; fixed contract {experiment.contract_hash}; Qlib LightGBM; TopK={experiment.portfolio.top_k}; n_drop={experiment.portfolio.n_drop}",
    )

    consolidated_report_path = build_consolidated_report(
        experiment=experiment,
        universe_size=len(symbols),
        trial_count=trial_count,
        annual_metrics=annual_metrics,
        annual_notes=annual_notes,
        continuous_report_path=continuous_report_path,
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
        continuous_report_path=continuous_report_path,
        consolidated_report_path=consolidated_report_path,
        diagnostics_path=diagnostics_path,
        trial_count=trial_count,
        analysis=analysis,
    )

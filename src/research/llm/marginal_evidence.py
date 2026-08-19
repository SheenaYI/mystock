"""PIT-safe, fold-level portfolio marginal evidence for S3 gating.

Candidate comparisons use the same local Qlib/LightGBM model family as the
main pipeline, followed by the same TopK ranking convention.  This remains a
development-fold screen rather than the final lot-level execution ledger, but
it no longer treats an equal-weight factor-rank proxy as proof of LightGBM
improvement.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from research.diagnostics import DEVELOPMENT_FOLDS, rank_ic_series
from research.labels import mature_labels_as_of
from research.models.qlib_lightgbm import LightGBMConfig, LocalPanelDataset, QlibLightGBMModel
from research.state import classify_market_state


_FOLD_SCORE_CACHE: dict[tuple[int, int, tuple[str, ...], str, int, LightGBMConfig], pd.DataFrame] = {}


def build_portfolio_marginal_evidence(
    *,
    features: pd.DataFrame,
    labels: pd.DataFrame,
    benchmark_close: pd.Series,
    as_of: pd.Timestamp,
    base_factors: tuple[str, ...],
    candidates: tuple[str, ...],
    horizon: int = 20,
    top_k: int = 10,
    min_folds: int = 2,
    current_state: str | None = None,
    min_state_observations: int = 20,
    model_config: LightGBMConfig = LightGBMConfig(),
) -> dict[str, dict[str, Any]]:
    """Return candidate eligibility evidence using only data mature at ``as_of``.

    A candidate qualifies only when at least ``min_folds`` development folds
    show a positive return and Sharpe delta versus the same LightGBM/TopK
    baseline, while turnover, drawdown and beta do not materially worsen.  If
    ``current_state`` is supplied, the same test must also pass on observations
    from that state in at least ``min_folds`` folds.
    """
    if horizon <= 0 or top_k <= 0 or min_folds <= 0:
        raise ValueError("horizon, top_k and min_folds must be positive")
    mature = mature_labels_as_of(labels, as_of=pd.Timestamp(as_of), horizon=horizon)
    if mature.empty:
        return {}
    available = set(features.columns)
    if not set(base_factors).issubset(available):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if candidate not in available:
            continue
        factor_stable, stable_folds = _factor_stability(
            features, mature, candidate, as_of, min_folds
        )
        state_factor_stable, state_stable_folds = _state_factor_stability(
            features, mature, candidate, benchmark_close, current_state,
            min_folds=min_folds, min_observations=min_state_observations,
        )
        fold_rows: list[dict[str, Any]] = []
        for fold_name, start, end in DEVELOPMENT_FOLDS:
            dates = mature.index[(mature.index >= pd.Timestamp(start)) & (mature.index <= pd.Timestamp(end))]
            if len(dates) < 20:
                continue
            baseline_frame = _lgbm_fold_scores(
                features, labels, base_factors, fold_name, start, end,
                horizon=horizon, model_config=model_config,
            )
            augmented_frame = _lgbm_fold_scores(
                features, labels, (*base_factors, candidate), fold_name, start, end,
                horizon=horizon, model_config=model_config,
            )
            if baseline_frame.empty or augmented_frame.empty:
                continue
            common = baseline_frame.index.intersection(augmented_frame.index)
            baseline_frame = baseline_frame.loc[common]
            augmented_frame = augmented_frame.loc[common]
            baseline, baseline_picks = _topk_returns(baseline_frame, top_k)
            augmented, augmented_picks = _topk_returns(augmented_frame, top_k)
            common_dates = baseline.index.intersection(augmented.index)
            baseline_metrics = _portfolio_metrics(
                baseline.loc[common_dates], benchmark_close, horizon, baseline_picks
            )
            augmented_metrics = _portfolio_metrics(
                augmented.loc[common_dates], benchmark_close, horizon, augmented_picks
            )
            delta = {
                key: _delta(augmented_metrics.get(key), baseline_metrics.get(key))
                for key in ("total_return", "sharpe", "max_drawdown", "turnover", "beta")
            }
            improved = bool(
                delta["total_return"] is not None and delta["total_return"] > 0
                and delta["sharpe"] is not None and delta["sharpe"] > 0
            )
            risk_cost_ok = bool(
                delta["turnover"] is not None and delta["turnover"] <= 0.20
                and delta["max_drawdown"] is not None and delta["max_drawdown"] >= -0.05
                and delta["beta"] is not None and delta["beta"] <= 0.15
            )
            state_baseline: dict[str, Any] = {}
            state_augmented: dict[str, Any] = {}
            state_delta: dict[str, Any] = {}
            state_improved = False
            state_risk_cost_ok = False
            state_observations = 0
            if current_state:
                states = _states_for_dates(benchmark_close, common_dates)
                state_dates = common_dates[states.reindex(common_dates).eq(current_state).fillna(False)]
                state_observations = len(state_dates)
                if state_observations >= min_state_observations:
                    state_baseline = _portfolio_metrics(
                        baseline.loc[state_dates], benchmark_close, horizon,
                        {date: baseline_picks[date] for date in state_dates if date in baseline_picks},
                    )
                    state_augmented = _portfolio_metrics(
                        augmented.loc[state_dates], benchmark_close, horizon,
                        {date: augmented_picks[date] for date in state_dates if date in augmented_picks},
                    )
                    state_delta = {
                        key: _delta(state_augmented.get(key), state_baseline.get(key))
                        for key in ("total_return", "sharpe", "max_drawdown", "turnover", "beta")
                    }
                    state_improved = bool(
                        state_delta.get("total_return") is not None
                        and state_delta["total_return"] > 0
                        and state_delta.get("sharpe") is not None
                        and state_delta["sharpe"] > 0
                    )
                    state_risk_cost_ok = bool(
                        state_delta.get("turnover") is not None
                        and state_delta["turnover"] <= 0.20
                        and state_delta.get("max_drawdown") is not None
                        and state_delta["max_drawdown"] >= -0.05
                        and state_delta.get("beta") is not None
                        and state_delta["beta"] <= 0.15
                    )
            fold_rows.append({
                "fold": fold_name,
                "baseline": baseline_metrics,
                "augmented": augmented_metrics,
                "delta": delta,
                "portfolio_marginal_improvement": improved,
                "risk_cost_ok": risk_cost_ok,
                "state_observations": state_observations,
                "state_baseline": state_baseline,
                "state_augmented": state_augmented,
                "state_delta": state_delta,
                "state_portfolio_marginal_improvement": state_improved,
                "state_risk_cost_ok": state_risk_cost_ok,
            })
        qualifying = sum(
            1 for row in fold_rows
            if row["portfolio_marginal_improvement"] and row["risk_cost_ok"]
        )
        state_qualifying = sum(
            1 for row in fold_rows
            if row["state_portfolio_marginal_improvement"] and row["state_risk_cost_ok"]
        )
        result[candidate] = {
            "evidence_method": "qlib_lightgbm_topk_fold_comparison",
            "factor_evidence_stable": factor_stable,
            "factor_stable_folds": stable_folds,
            "state": current_state,
            "state_factor_evidence_stable": state_factor_stable,
            "state_factor_stable_folds": state_stable_folds,
            "qualifying_folds": qualifying,
            "portfolio_marginal_improvement": qualifying >= min_folds,
            "risk_cost_ok": qualifying >= min_folds,
            "state_qualifying_folds": state_qualifying,
            "state_portfolio_marginal_improvement": state_qualifying >= min_folds,
            "state_risk_cost_ok": state_qualifying >= min_folds,
            "folds": fold_rows,
            "thresholds": {
                "min_folds": min_folds,
                "min_state_observations": min_state_observations,
                "max_turnover_delta": 0.20,
                "max_drawdown_worsening": 0.05,
                "max_beta_delta": 0.15,
            },
        }
    return result


def _factor_stability(features, mature, factor, as_of, min_folds):
    panel = features[factor].unstack("instrument").reindex(mature.index)
    ic = rank_ic_series(panel, mature)
    stable_folds = 0
    for _, start, end in DEVELOPMENT_FOLDS:
        values = ic.loc[start:end].dropna()
        if len(values) >= 20 and float(values.mean()) > 0:
            stable_folds += 1
    return stable_folds >= min_folds, stable_folds


def _state_factor_stability(
    features, mature, factor, benchmark_close, state, *, min_folds, min_observations
):
    if not state:
        return True, min_folds
    panel = features[factor].unstack("instrument").reindex(mature.index)
    ic = rank_ic_series(panel, mature)
    states = _states_for_dates(benchmark_close, ic.index)
    stable_folds = 0
    for _, start, end in DEVELOPMENT_FOLDS:
        values = ic.loc[start:end]
        values = values[states.reindex(values.index).eq(state).fillna(False)].dropna()
        if len(values) >= min_observations and float(values.mean()) > 0:
            stable_folds += 1
    return stable_folds >= min_folds, stable_folds


def _states_for_dates(benchmark_close: pd.Series, dates: pd.Index) -> pd.Series:
    return pd.Series(
        {
            pd.Timestamp(date): classify_market_state(benchmark_close.loc[:pd.Timestamp(date)])
            for date in dates
            if pd.Timestamp(date) in benchmark_close.index
        },
        dtype=object,
    )


def _lgbm_fold_scores(
    features, labels, factors, fold_name, start, end, *, horizon, model_config
):
    """Fit one actual LightGBM baseline/candidate model per development fold.

    The in-process cache is important: evidence is requested on every S3
    decision date, but the 2021--2023 development fold comparison is identical
    once its mature labels and frozen model configuration are fixed.
    """
    key = (id(features), id(labels), tuple(factors), fold_name, horizon, model_config)
    cached = _FOLD_SCORE_CACHE.get(key)
    if cached is not None:
        return cached
    valid_starts = {"F1": "2021-07-01", "F2": "2022-07-01", "F3": "2023-07-01"}
    train_ends = {"F1": "2021-06-30", "F2": "2022-06-30", "F3": "2023-06-30"}
    requested_valid_start = pd.Timestamp(valid_starts[fold_name])
    available_valid_starts = labels.index[labels.index >= requested_valid_start]
    if len(available_valid_starts) == 0:
        return pd.DataFrame(columns=["score", "label"])
    valid_start = pd.Timestamp(available_valid_starts[0])
    # The frozen development folds use an expanding training origin at
    # 2021-01-01; ``start`` is the validation start from DEVELOPMENT_FOLDS.
    train_start = pd.Timestamp("2021-01-01")
    train_end = pd.Timestamp(train_ends[fold_name])
    mature = mature_labels_as_of(labels, as_of=valid_start, horizon=horizon)
    train_dates = mature.index[(mature.index >= train_start) & (mature.index <= train_end)]
    valid_dates = labels.index[(labels.index >= valid_start) & (labels.index <= pd.Timestamp(end))]
    if len(train_dates) < 20 or len(valid_dates) == 0:
        return pd.DataFrame(columns=["score", "label"])
    label_long = labels.loc[train_dates].stack(future_stack=True).rename("label")
    label_long.index = label_long.index.set_names(["datetime", "instrument"])
    training = features[list(factors)].join(label_long, how="inner").dropna()
    valid_long = labels.loc[valid_dates].stack(future_stack=True).rename("label")
    valid_long.index = valid_long.index.set_names(["datetime", "instrument"])
    valid = features.loc[
        features.index.get_level_values("datetime").isin(valid_dates), list(factors)
    ].join(valid_long, how="inner").dropna()
    if training.empty or valid.empty:
        return pd.DataFrame(columns=["score", "label"])
    combined = pd.concat([training, valid]).sort_index()
    dataset = LocalPanelDataset(
        combined.drop(columns="label"), combined["label"],
        train=(str(train_start.date()), str(train_end.date())),
        valid=(str(valid_start.date()), str(pd.Timestamp(end).date())),
    )
    prediction = QlibLightGBMModel(model_config).fit(dataset).predict(valid[list(factors)])
    output = pd.DataFrame({"score": prediction, "label": valid["label"]}).dropna()
    _FOLD_SCORE_CACHE[key] = output
    return output


def _topk_returns(frame: pd.DataFrame, top_k: int):
    returns: dict[pd.Timestamp, float] = {}
    picks: dict[pd.Timestamp, set[str]] = {}
    for date, row in frame.groupby(level="datetime"):
        flat = row.droplevel("datetime")
        ranked = flat["score"].dropna().sort_values(ascending=False)
        selected = list(ranked.head(min(top_k, len(ranked))).index)
        realized = flat.loc[selected, "label"].dropna()
        if len(realized) >= min(top_k, 5):
            timestamp = pd.Timestamp(date)
            returns[timestamp] = float(realized.mean())
            picks[timestamp] = set(realized.index)
    return pd.Series(returns, dtype=float).sort_index(), picks


def _rank_portfolio_returns(features, labels, dates, factors, top_k):
    panels = [features[factor].unstack("instrument").reindex(dates) for factor in factors]
    score = sum(panel.rank(axis=1, pct=True) for panel in panels) / len(panels)
    returns = []
    for date in dates:
        # Historical membership is represented by NaN outside the eligible
        # universe.  We need only TopK valid names on a date, not complete
        # observations for every symbol in the all-time column union.
        row = score.loc[date].dropna().sort_values(ascending=False)
        picks = row.head(min(top_k, len(row))).index
        realized = labels.loc[date, labels.columns.intersection(picks)].dropna()
        if len(realized) >= min(top_k, 5):
            returns.append((date, float(realized.mean())))
    return pd.Series(dict(returns), dtype=float).sort_index()


def _portfolio_metrics(returns, benchmark_close, horizon, picks=None):
    returns = returns.dropna()
    if returns.empty:
        return {"total_return": None, "sharpe": None, "max_drawdown": None, "turnover": None, "beta": None}
    nav = (1.0 + returns).cumprod()
    drawdown = nav.div(nav.cummax()).sub(1.0)
    std = returns.std(ddof=1)
    sharpe = None if pd.isna(std) or std == 0 else float(returns.mean() / std * np.sqrt(252 / horizon))
    benchmark = benchmark_close.pct_change(horizon).reindex(returns.index)
    variance = benchmark.var(ddof=1)
    beta = None if pd.isna(variance) or variance == 0 else float(returns.cov(benchmark) / variance)
    if picks:
        ordered = [picks[date] for date in returns.index if date in picks]
        turnover = (
            float(np.mean([
                1.0 - len(current.intersection(previous)) / max(len(previous), 1)
                for previous, current in zip(ordered, ordered[1:])
            ]))
            if len(ordered) > 1 else 1.0
        )
    else:
        turnover = float(1.0 - 1.0 / len(returns)) if len(returns) > 1 else 1.0
    return {
        "total_return": float(nav.iloc[-1] - 1.0),
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "turnover": turnover,
        "beta": beta,
    }


def _delta(after, before):
    if after is None or before is None:
        return None
    return float(after - before)

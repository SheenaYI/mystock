"""Point-in-time factor evidence supplied to ReAct-lite.

All summaries are computed from observations whose forward labels have
finished by the decision date.  The module returns JSON-serialisable data so
the exact snapshot can be hashed and replayed from the LLM call log.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from research.diagnostics import _ic_summary, rank_ic_series
from research.factors.extended import strong_correlation_clusters
from research.labels import mature_labels_as_of
from research.llm.marginal_evidence import build_portfolio_marginal_evidence
from research.models.qlib_lightgbm import LightGBMConfig
from research.state import classify_market_state


def build_factor_evidence(
    *,
    features: pd.DataFrame,
    labels: pd.DataFrame,
    benchmark_close: pd.Series,
    as_of: pd.Timestamp,
    base_factors: tuple[str, ...],
    candidates: tuple[str, ...],
    correlation_threshold: float = 0.80,
    min_state_observations: int = 20,
    horizon: int = 20,
    include_portfolio_marginal: bool = True,
    state_snapshot: dict[str, Any] | None = None,
    historical_context: list[dict[str, Any]] | None = None,
    model_config: LightGBMConfig = LightGBMConfig(),
) -> dict[str, Any]:
    """Build the frozen historical evidence snapshot visible at ``as_of``.

    The latest usable feature/label date is determined by
    :func:`mature_labels_as_of`; no current or future outcome is included.
    ``min_state_observations`` prevents a tiny regime sample from looking like
    strong evidence.
    """
    as_of = pd.Timestamp(as_of)
    mature = mature_labels_as_of(labels, as_of=as_of, horizon=horizon)
    mature_dates = mature.index
    if len(mature_dates) == 0:
        return {
            "as_of": str(as_of.date()),
            "mature_through": None,
            "mature_observations": 0,
            "current_state": "S0_insufficient_evidence",
            "market_state_snapshot": state_snapshot or {
                "state": "S0_insufficient_evidence",
                "evidence_status": "insufficient_evidence",
            },
            "historical_context": historical_context or [],
            "factor_evidence": {},
            "state_evidence": {},
            "correlation_clusters": [],
            "portfolio_marginal_evidence": {},
            "evidence_status": "insufficient_evidence",
        }

    usable_features = features.loc[
        features.index.get_level_values("datetime").isin(mature_dates)
    ]
    factor_evidence: dict[str, Any] = {}
    state_by_date = pd.Series(
        {
            pd.Timestamp(date): classify_market_state(benchmark_close.loc[:date])
            for date in mature_dates
            if date in benchmark_close.index
        },
        name="state",
    )
    for factor in (*base_factors, *candidates):
        if factor not in features.columns:
            continue
        factor_panel = usable_features[factor].unstack("instrument").reindex(index=mature_dates)
        rank_ic = rank_ic_series(factor_panel, mature)
        current_panel = (
            features.xs(as_of, level="datetime")
            if as_of in features.index.get_level_values("datetime")
            else pd.DataFrame()
        )
        # Measure coverage within stocks where the base recipe can be
        # calculated today. A missing bar for a base-ineligible stock must not
        # make a usable extension look incomplete.
        base_eligible = (
            current_panel.reindex(columns=list(base_factors)).notna().all(axis=1)
            if not current_panel.empty else pd.Series(dtype=bool)
        )
        current_row = (
            current_panel.loc[base_eligible, factor]
            if factor in current_panel else pd.Series(dtype=float)
        )
        factor_evidence[factor] = {
            **_ic_summary(rank_ic),
            "coverage_current": round(float(current_row.notna().mean()), 4) if len(current_row) else 0.0,
            "eligible_universe_count": int(base_eligible.sum()),
            "state_rank_ic": _state_summaries(rank_ic, state_by_date, min_state_observations),
        }

    clusters = strong_correlation_clusters(
        usable_features[list((*base_factors, *candidates))].dropna(how="all"),
        threshold=correlation_threshold,
    )
    current_state = str((state_snapshot or {}).get("state") or classify_market_state(benchmark_close.loc[:as_of]))
    portfolio_marginal = (
        build_portfolio_marginal_evidence(
            features=features, labels=labels, benchmark_close=benchmark_close,
            as_of=as_of, base_factors=base_factors, candidates=candidates,
            current_state=current_state,
            min_state_observations=min_state_observations,
            model_config=model_config,
            horizon=horizon,
        ) if include_portfolio_marginal else {}
    )
    return {
        "as_of": str(as_of.date()),
        "mature_through": str(mature_dates.max().date()),
        "mature_observations": int(len(mature_dates)),
        "current_state": current_state,
        "market_state_snapshot": state_snapshot or {
            "state": current_state,
            "evidence_status": "legacy_snapshot_without_cross_sectional_metrics",
        },
        "historical_context": historical_context or [],
        "factor_evidence": factor_evidence,
        "state_evidence": _state_summaries(
            pd.Series(dtype=float), state_by_date, min_state_observations
        ),
        "correlation_clusters": [sorted(cluster) for cluster in clusters],
        "correlation_threshold": correlation_threshold,
        # Filled only by a separate PIT-safe fold evaluator.  Empty means
        # ReAct-lite must abstain rather than treating RankIC as a substitute.
        "portfolio_marginal_evidence": portfolio_marginal,
        "min_state_observations": min_state_observations,
        "evidence_status": "ok" if len(mature_dates) >= min_state_observations else "insufficient_evidence",
    }


def _state_summaries(
    rank_ic: pd.Series,
    states: pd.Series,
    min_observations: int,
) -> dict[str, dict[str, Any]]:
    """Summarise a RankIC series by the state visible on each date."""
    if rank_ic.empty:
        return {}
    aligned = states.reindex(rank_ic.index)
    result: dict[str, dict[str, Any]] = {}
    for state, values in rank_ic.groupby(aligned):
        summary = _ic_summary(values)
        summary["evidence_status"] = "ok" if summary["observations"] >= min_observations else "insufficient_evidence"
        result[str(state)] = summary
    return result

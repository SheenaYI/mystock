import numpy as np
import pandas as pd

from research.llm.evidence import build_factor_evidence
from research.llm.marginal_evidence import build_portfolio_marginal_evidence


def _panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    dates = pd.date_range("2021-01-01", periods=100, freq="D")
    instruments = [f"S{i:02d}" for i in range(25)]
    index = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    rng = np.random.default_rng(7)
    features = pd.DataFrame(
        rng.normal(size=(len(index), 3)),
        index=index,
        columns=["return_5", "volatility_20", "drawdown_60"],
    )
    labels = pd.DataFrame(rng.normal(size=(len(dates), len(instruments))), index=dates, columns=instruments)
    benchmark = pd.Series(100 + np.cumsum(rng.normal(size=len(dates))), index=dates)
    return features, labels, benchmark


def test_factor_evidence_uses_only_mature_labels() -> None:
    features, labels, benchmark = _panels()
    as_of = labels.index[-1]
    first = build_factor_evidence(
        features=features,
        labels=labels,
        benchmark_close=benchmark,
        as_of=as_of,
        base_factors=("return_5",),
        candidates=("volatility_20", "drawdown_60"),
    )
    labels.loc[labels.index > as_of - pd.Timedelta(days=21), :] = 999999
    second = build_factor_evidence(
        features=features,
        labels=labels,
        benchmark_close=benchmark,
        as_of=as_of,
        base_factors=("return_5",),
        candidates=("volatility_20", "drawdown_60"),
    )
    assert first["mature_through"] == second["mature_through"]
    assert first["factor_evidence"] == second["factor_evidence"]
    assert "correlation_clusters" in first


def test_current_coverage_uses_the_base_eligible_universe() -> None:
    features, labels, benchmark = _panels()
    as_of = labels.index[-1]
    # This stock cannot form the base recipe today, so it must not dilute an
    # extension's coverage presented to an S4 decision.
    features.loc[(as_of, "S00"), "return_5"] = np.nan
    features.loc[(as_of, "S00"), "drawdown_60"] = np.nan
    result = build_factor_evidence(
        features=features, labels=labels, benchmark_close=benchmark, as_of=as_of,
        base_factors=("return_5",), candidates=("drawdown_60",),
    )
    evidence = result["factor_evidence"]["drawdown_60"]
    assert evidence["coverage_current"] == 1.0
    assert evidence["eligible_universe_count"] == 24


def test_marginal_evidence_is_fail_closed_before_two_development_folds() -> None:
    features, labels, benchmark = _panels()
    result = build_portfolio_marginal_evidence(
        features=features,
        labels=labels,
        benchmark_close=benchmark,
        as_of=labels.index[-1],
        base_factors=("return_5",),
        candidates=("volatility_20",),
    )
    assert result["volatility_20"]["qualifying_folds"] == 0
    assert result["volatility_20"]["portfolio_marginal_improvement"] is False
    assert result["volatility_20"]["evidence_method"] == "qlib_lightgbm_topk_fold_comparison"
    assert result["volatility_20"]["state_portfolio_marginal_improvement"] is False

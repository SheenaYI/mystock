import numpy as np
import pandas as pd

from research.llm.evidence import build_factor_evidence


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

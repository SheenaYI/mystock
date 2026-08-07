import pandas as pd
import pytest

from research.diagnostics import rank_ic_series, relative_performance_diagnostics, score_diagnostics


def test_rank_ic_and_quantile_diagnostics_detect_perfect_ordering():
    dates = pd.to_datetime(["2021-07-01", "2021-07-29"])
    columns = [f"S{index}" for index in range(30)]
    scores = pd.DataFrame([list(range(30)) for _ in dates], index=dates, columns=columns)
    labels = pd.DataFrame([[index / 1000 for index in range(30)] for _ in dates], index=dates, columns=columns)
    rank_ic = rank_ic_series(scores, labels)
    assert rank_ic.tolist() == pytest.approx([1.0, 1.0])
    folds, states, quantiles, _ = score_diagnostics(scores=scores, labels=labels, states=pd.Series("S1_trend", index=dates))
    assert folds.loc[0, "median_rank_ic"] == pytest.approx(1.0)
    assert states.loc[0, "mean_rank_ic"] == pytest.approx(1.0)
    assert (quantiles["top_minus_bottom"] > 0).all()


def test_relative_diagnostics_calculates_active_metrics_and_beta():
    dates = pd.date_range("2024-01-02", periods=80, freq="B")
    benchmark = pd.Series([0.01 if index % 2 == 0 else -0.005 for index in range(80)], index=dates)
    strategy = benchmark * 1.2 + 0.001
    frame, metrics = relative_performance_diagnostics(strategy, benchmark)
    assert metrics["active_return"] > 0
    assert metrics["mean_rolling_beta_60"] == pytest.approx(1.2)
    assert frame["relative_drawdown"].min() == pytest.approx(0.0)

import numpy as np
import pandas as pd

from research.factors.extended import strong_correlation_clusters, technical_20_features, technical_25_features


def test_twenty_factor_panel_has_all_frozen_factor_names():
    dates = pd.date_range("2021-01-01", periods=140, freq="B")
    close = pd.DataFrame(np.arange(280).reshape(140, 2) + 100.0, index=dates, columns=["AAA", "BBB"])
    panel = technical_20_features(close=close, high=close + 1, low=close - 1, volume=close * 10, amount=close * 1000)
    assert len(panel.columns) == 20
    assert "return_120" in panel.columns
    assert "volume_price_corr_20" in panel.columns


def test_strong_correlation_clusters_are_deterministic():
    dates = pd.date_range("2021-01-01", periods=10, freq="B")
    idx = pd.MultiIndex.from_product([dates, ["A", "B", "C"]], names=["datetime", "instrument"])
    pattern = [1.0, 2.0, 3.0] * 10
    panel = pd.DataFrame({"a": pattern, "b": pattern, "c": [3.0, 1.0, 2.0] * 10}, index=idx)
    clusters = strong_correlation_clusters(panel)
    assert any({"a", "b"}.issubset(cluster) for cluster in clusters)


def test_downside_volatility_does_not_require_twenty_negative_days():
    dates = pd.date_range("2021-01-01", periods=40, freq="B")
    close = pd.DataFrame(
        {"AAA": [100.0 if pos % 2 == 0 else 99.0 for pos in range(40)]},
        index=dates,
    )
    panel = technical_20_features(
        close=close, high=close + 1, low=close - 1,
        volume=close * 10, amount=close * 1000,
    )
    assert panel["downside_volatility_20"].notna().any()


def test_five_family_panel_adds_relative_market_features():
    dates = pd.date_range("2021-01-01", periods=140, freq="B")
    close = pd.DataFrame(np.arange(280).reshape(140, 2) + 100.0, index=dates, columns=["AAA", "BBB"])
    benchmark = pd.Series(np.arange(140) + 100.0, index=dates)
    panel = technical_25_features(
        close=close, high=close + 1, low=close - 1,
        volume=close * 10, amount=close * 1000, benchmark_close=benchmark,
    )
    assert len(panel.columns) == 25
    assert {"beta_60", "market_corr_60", "idiosyncratic_return_20", "residual_volatility_60"}.issubset(panel.columns)

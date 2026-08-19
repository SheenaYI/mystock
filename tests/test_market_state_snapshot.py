import numpy as np
import pandas as pd

from research.state import market_state_snapshot


def test_market_state_snapshot_contains_deterministic_cross_sectional_metrics():
    dates = pd.date_range("2021-01-01", periods=100, freq="B")
    benchmark = pd.Series(np.linspace(100.0, 110.0, len(dates)), index=dates)
    stocks = pd.DataFrame({
        "AAA": np.linspace(10.0, 12.0, len(dates)),
        "BBB": np.linspace(20.0, 19.0, len(dates)),
        "CCC": np.linspace(15.0, 15.5, len(dates)),
    }, index=dates)
    snapshot = market_state_snapshot(
        benchmark_close=benchmark, stock_close=stocks, as_of=dates[-1],
    )
    assert snapshot["state"] in {"S0_insufficient_evidence", "S1_trend", "S2_stress", "S3_range_or_uncertain"}
    assert snapshot["breadth_above_ma20"] is not None
    assert snapshot["cross_sectional_return_dispersion_20"] is not None
    assert snapshot["median_pairwise_correlation_20"] is not None

import pandas as pd
import pytest

from research.portfolio.benchmark_clock import aligned_close_benchmark_returns


def test_benchmark_starts_at_the_strategy_first_open_execution():
    dates = pd.date_range("2024-01-02", periods=4, freq="B")
    open_ = pd.Series([100.0, 100.0, 110.0, 121.0], index=dates)
    close = pd.Series([100.0, 110.0, 121.0, 133.1], index=dates)
    signals = pd.DataFrame({"AAA": [1.0, float("nan"), float("nan"), float("nan")]}, index=dates)
    returns = aligned_close_benchmark_returns(benchmark_open=open_, benchmark_close=close, signal_weights=signals)
    assert returns.tolist() == pytest.approx([0.0, 0.1, 0.1, 0.1])

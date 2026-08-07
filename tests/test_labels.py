import pandas as pd

from research.labels import forward_excess_return_20d, mature_labels_as_of


def test_label_uses_next_open_entry_and_horizon_later_open_exit():
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    opens = pd.DataFrame({"600000.SH": [10, 11, 12, 13, 14]}, index=dates)
    benchmark = pd.Series([100, 110, 120, 130, 140], index=dates)
    labels = forward_excess_return_20d(opens, benchmark, horizon=2)
    # t0: stock 13/11 - 1 equals benchmark 130/110 - 1, so excess is zero.
    assert labels.iloc[0, 0] == 0
    assert pd.isna(labels.iloc[-3, 0])


def test_mature_as_of_excludes_unrealized_future_horizon():
    dates = pd.date_range("2024-01-02", periods=7, freq="B")
    labels = pd.DataFrame({"600000.SH": range(7)}, index=dates)
    mature = mature_labels_as_of(labels, as_of=dates[-1], horizon=2)
    assert list(mature.index) == list(dates[:4])

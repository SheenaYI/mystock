import numpy as np
import pandas as pd

from research.factors.technical import baseline_seven_features


def test_seven_baseline_features_have_expected_names_and_panel_index():
    dates = pd.date_range("2024-01-02", periods=65, freq="B")
    columns = ["AAA", "BBB"]
    close = pd.DataFrame(np.arange(130).reshape(65, 2) + 100.0, index=dates, columns=columns)
    features = baseline_seven_features(close=close, high=close + 1, low=close - 1, volume=close * 100)
    assert list(features.columns) == [
        "return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range",
    ]
    assert features.index.names == ["datetime", "instrument"]
    assert features.loc[(dates[60], "AAA"), "return_60"] == (close.loc[dates[60], "AAA"] / close.loc[dates[0], "AAA"] - 1)
    assert features.loc[(dates[60], "AAA"), "volume_ratio_20"] == (
        (close.loc[dates[60], "AAA"] / close.loc[dates[41:61], "AAA"].mean()) - 1
    )

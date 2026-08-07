import numpy as np
import pandas as pd

from research.models.qlib_lightgbm import LightGBMConfig
from research.models.rolling import rolling_qlib_scores


def test_rolling_model_uses_only_a_date_mature_label_cutoff():
    dates = pd.date_range("2021-01-01", periods=120, freq="B")
    instruments = ["AAA", "BBB", "CCC"]
    index = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    features = pd.DataFrame({"return_5": np.arange(len(index), dtype=float), "volatility_20": 1.0}, index=index)
    labels = pd.DataFrame(0.01, index=dates, columns=instruments)
    scores = rolling_qlib_scores(
        features=features, labels=labels, decision_dates=pd.DatetimeIndex([dates[110]]),
        train_start="2021-01-01", horizon=20, validation_sessions=60,
        model_config=LightGBMConfig(num_leaves=3, max_depth=2, min_data_in_leaf=2, num_boost_round=4, early_stopping_rounds=2),
    )
    assert scores.loc[dates[110]].notna().all()
    # At t=110 only labels through t-21 are mature, so the later values
    # cannot be needed to make the current cross-sectional score.
    assert scores.loc[dates[111:]].isna().all().all()


def test_selected_features_are_filtered_before_dropna():
    dates = pd.date_range("2021-01-01", periods=120, freq="B")
    instruments = ["AAA", "BBB", "CCC"]
    index = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    features = pd.DataFrame(
        {"return_5": 1.0, "unselected_broken_factor": float("nan")}, index=index
    )
    labels = pd.DataFrame(0.01, index=dates, columns=instruments)
    scores = rolling_qlib_scores(
        features=features, labels=labels, decision_dates=pd.DatetimeIndex([dates[110]]),
        train_start="2021-01-01", horizon=20, validation_sessions=60,
        selected_features_by_date={dates[110]: ("return_5",)},
        model_config=LightGBMConfig(num_leaves=3, max_depth=2, min_data_in_leaf=2, num_boost_round=4, early_stopping_rounds=2),
    )
    assert scores.loc[dates[110]].notna().all()

"""Small Qlib-compatible adapter for a local feature panel and LightGBM."""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import pandas as pd
from qlib.contrib.model.gbdt import LGBModel


@dataclass(frozen=True)
class LightGBMConfig:
    """Frozen candidate configuration; tuning is handled outside this class."""

    num_leaves: int = 31
    max_depth: int = 5
    min_data_in_leaf: int = 500
    lambda_l2: float = 10.0
    learning_rate: float = 0.03
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    bagging_freq: int = 1
    num_boost_round: int = 1_000
    early_stopping_rounds: int = 50
    seed: int = 20260805

    def qlib_parameters(self) -> dict[str, object]:
        return {
            "num_leaves": self.num_leaves, "max_depth": self.max_depth,
            "min_data_in_leaf": self.min_data_in_leaf, "lambda_l2": self.lambda_l2,
            "learning_rate": self.learning_rate, "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction, "bagging_freq": self.bagging_freq,
            "seed": self.seed, "feature_fraction_seed": self.seed, "bagging_seed": self.seed,
        }


class LocalPanelDataset:
    """The narrow Qlib dataset protocol needed by ``LGBModel``.

    It lets research use Qlib's LightGBM wrapper without converting the local
    AKShare archive into Qlib's binary data format.  ``features`` and
    ``labels`` use a MultiIndex ordered as ``(datetime, instrument)``.
    """

    def __init__(self, features: pd.DataFrame, labels: pd.Series, *, train: tuple[str, str], valid: tuple[str, str]) -> None:
        if not isinstance(features.index, pd.MultiIndex) or features.index.names[:2] != ["datetime", "instrument"]:
            raise ValueError("features must use a (datetime, instrument) MultiIndex")
        if not features.index.equals(labels.index):
            raise ValueError("features and labels must have identical indexes")
        self._features = features
        self._labels = labels.rename("label")
        self.segments = {"train": train, "valid": valid}

    def prepare(self, segment, col_set=None, data_key=None):
        if isinstance(segment, str):
            segment = self.segments[segment]
        start, end = (pd.Timestamp(value) for value in segment)
        dates = self._features.index.get_level_values("datetime")
        selected = (dates >= start) & (dates <= end)
        feature = self._features.loc[selected]
        label = self._labels.loc[selected].to_frame()
        # Qlib's LGBModel accesses df["feature"] and df["label"].
        return pd.concat({"feature": feature, "label": label}, axis=1)


class _LocalQlibLGBModel(LGBModel):
    """Qlib's LGBModel without its optional MLflow-recorder side effect."""

    def fit(self, dataset, num_boost_round=None, early_stopping_rounds=None, verbose_eval=False, **kwargs):
        datasets = self._prepare_data(dataset)
        values, names = list(zip(*datasets))
        callbacks = [lgb.early_stopping(
            self.early_stopping_rounds if early_stopping_rounds is None else early_stopping_rounds
        )]
        if verbose_eval:
            callbacks.append(lgb.log_evaluation(period=20))
        self.model = lgb.train(
            self.params, values[0],
            num_boost_round=self.num_boost_round if num_boost_round is None else num_boost_round,
            valid_sets=values, valid_names=names, callbacks=callbacks, **kwargs,
        )


class QlibLightGBMModel:
    """Fit/predict Qlib's LightGBM model on a local, leakage-safe panel."""

    def __init__(self, config: LightGBMConfig = LightGBMConfig()) -> None:
        self.config = config
        self.model = _LocalQlibLGBModel(
            loss="mse", early_stopping_rounds=config.early_stopping_rounds,
            num_boost_round=config.num_boost_round, **config.qlib_parameters(),
        )

    def fit(self, dataset: LocalPanelDataset) -> "QlibLightGBMModel":
        self.model.fit(dataset, verbose_eval=False)
        return self

    def predict(self, features: pd.DataFrame) -> pd.Series:
        if not isinstance(features.index, pd.MultiIndex):
            raise ValueError("features must use a (datetime, instrument) MultiIndex")
        if self.model.model is None:
            raise RuntimeError("model has not been fitted")
        return pd.Series(self.model.model.predict(features), index=features.index, name="score")

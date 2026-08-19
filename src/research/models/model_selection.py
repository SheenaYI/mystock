"""Pre-registered LightGBM candidates and development-fold selection.

This module never reads validation or locked-window returns.  It evaluates the
six frozen candidates only on the three 2021--2023 development folds.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from research.labels import mature_labels_as_of
from research.models.qlib_lightgbm import LightGBMConfig, LocalPanelDataset, QlibLightGBMModel


@dataclass(frozen=True)
class ModelCandidate:
    name: str
    config: LightGBMConfig


@dataclass(frozen=True)
class DevelopmentFold:
    name: str
    train_start: str
    train_end: str
    valid_start: str
    valid_end: str


FOLDS = (
    DevelopmentFold("F1", "2021-01-01", "2021-06-30", "2021-07-01", "2021-12-31"),
    DevelopmentFold("F2", "2021-01-01", "2022-06-30", "2022-07-01", "2022-12-31"),
    DevelopmentFold("F3", "2021-01-01", "2023-06-30", "2023-07-01", "2023-12-31"),
)


def registered_candidates(base: LightGBMConfig = LightGBMConfig()) -> tuple[ModelCandidate, ...]:
    values = (("M1", 15, 4, 500, 10.0), ("M2", 15, 4, 200, 1.0),
              ("M3", 31, 5, 500, 10.0), ("M4", 31, 5, 200, 1.0),
              ("M5", 63, 6, 500, 10.0), ("M6", 63, 6, 200, 1.0))
    return tuple(ModelCandidate(name, replace(base, num_leaves=leaves,
                                               max_depth=depth,
                                               min_data_in_leaf=min_leaf,
                                               lambda_l2=l2))
                 for name, leaves, depth, min_leaf, l2 in values)


def _long_labels(labels: pd.DataFrame) -> pd.Series:
    long = labels.stack(future_stack=True).rename("label")
    long.index = long.index.set_names(["datetime", "instrument"])
    return long


def _rank_ic(prediction: pd.Series, label: pd.Series) -> pd.Series:
    frame = pd.concat([prediction.rename("score"), label.rename("label")], axis=1).dropna()
    if frame.empty:
        return pd.Series(dtype=float)
    return frame.groupby(level="datetime").apply(
        lambda row: row["score"].corr(row["label"], method="spearman")
    ).dropna()


def select_model(
    *, features: pd.DataFrame, labels: pd.DataFrame,
    base_config: LightGBMConfig = LightGBMConfig(),
    folds: tuple[DevelopmentFold, ...] = FOLDS,
    horizon: int = 20,
) -> tuple[LightGBMConfig, pd.DataFrame, str]:
    """Select one candidate by three-fold median RankIC, then ICIR.

    The returned table is an auditable development artifact.  It is the
    caller's responsibility to persist it and include its hash in a contract.
    """
    if not isinstance(features.index, pd.MultiIndex):
        raise ValueError("features must use a datetime/instrument MultiIndex")
    labels_long = _long_labels(labels)
    rows = []
    for candidate in registered_candidates(base_config):
        fold_scores = []
        for fold in folds:
            requested_start = pd.Timestamp(fold.valid_start)
            available = labels.index[labels.index >= requested_start]
            if len(available) == 0:
                fold_scores.append(np.nan)
                continue
            valid_start = available[0]
            mature = mature_labels_as_of(labels, as_of=valid_start, horizon=horizon)
            train_mask = (mature.index >= pd.Timestamp(fold.train_start)) & (mature.index <= pd.Timestamp(fold.train_end))
            train_labels = mature.loc[train_mask]
            train_long = _long_labels(train_labels)
            training = features.join(train_long, how="inner").dropna()
            valid = features.join(labels_long, how="inner")
            valid = valid.loc[(valid.index.get_level_values("datetime") >= pd.Timestamp(fold.valid_start)) &
                              (valid.index.get_level_values("datetime") <= pd.Timestamp(fold.valid_end))].dropna()
            if training.empty or valid.empty:
                fold_scores.append(np.nan)
                continue
            dataset_frame = pd.concat([training, valid], axis=0).sort_index()
            dataset = LocalPanelDataset(
                dataset_frame.drop(columns="label"), dataset_frame["label"],
                train=(fold.train_start, fold.train_end),
                valid=(fold.valid_start, fold.valid_end),
            )
            prediction = QlibLightGBMModel(candidate.config).fit(dataset).predict(valid.drop(columns="label"))
            ic = _rank_ic(prediction, valid["label"])
            fold_scores.append(float(ic.mean()) if not ic.empty else np.nan)
        rows.append({"candidate": candidate.name, **{fold.name: score for fold, score in zip(folds, fold_scores)}})
    table = pd.DataFrame(rows)
    fold_cols = [fold.name for fold in folds]
    table["rank_ic_median"] = table[fold_cols].median(axis=1)
    table["rank_ic_mean"] = table[fold_cols].mean(axis=1)
    table["icir_proxy"] = table[fold_cols].mean(axis=1) / table[fold_cols].std(axis=1).replace(0, np.nan)
    table = table.sort_values(["rank_ic_median", "icir_proxy"], ascending=False, na_position="last")
    if table.empty or pd.isna(table.iloc[0]["rank_ic_median"]):
        raise ValueError("model selection produced no valid development-fold evidence")
    selected_name = str(table.iloc[0]["candidate"])
    selected = next(item.config for item in registered_candidates(base_config) if item.name == selected_name)
    return selected, table.reset_index(drop=True), selected_name

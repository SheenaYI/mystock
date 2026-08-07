"""Point-in-time rolling Qlib scores for scheduled portfolio decisions."""

from __future__ import annotations

import pandas as pd

from research.labels import mature_labels_as_of
from research.models.qlib_lightgbm import LightGBMConfig, LocalPanelDataset, QlibLightGBMModel


def rolling_qlib_scores(
    *,
    features: pd.DataFrame,
    labels: pd.DataFrame,
    decision_dates: pd.DatetimeIndex,
    train_start: str,
    horizon: int = 20,
    validation_sessions: int = 60,
    model_config: LightGBMConfig = LightGBMConfig(),
    selected_features_by_date: dict[pd.Timestamp, tuple[str, ...]] | None = None,
) -> pd.DataFrame:
    """Score each decision date using only labels mature at that date.

    This is expanding-window fitting: at decision date ``t``, labels whose
    next-open holding period has not ended are excluded, then the most recent
    ``validation_sessions`` mature dates are reserved for early stopping.
    Dates without enough history intentionally yield no score and become the
    strategy warm-up period.
    """
    if not features.index.names[:2] == ["datetime", "instrument"]:
        raise ValueError("features must use a (datetime, instrument) MultiIndex")
    if not features.index.get_level_values("datetime").unique().equals(labels.index):
        raise ValueError("feature and label sessions must match")
    if validation_sessions <= 0:
        raise ValueError("validation_sessions must be positive")
    columns = features.index.get_level_values("instrument").unique().sort_values()
    scores = pd.DataFrame(index=labels.index, columns=columns, dtype=float)
    feature_dates = features.index.get_level_values("datetime")
    start = pd.Timestamp(train_start)

    for as_of in decision_dates:
        mature = mature_labels_as_of(labels, as_of=as_of, horizon=horizon)
        if len(mature.index) <= validation_sessions:
            continue
        label_long = mature.stack(future_stack=True).rename("label")
        label_long.index = label_long.index.set_names(["datetime", "instrument"])
        training = features.join(label_long, how="inner")
        selected = None if selected_features_by_date is None else selected_features_by_date.get(pd.Timestamp(as_of))
        if selected:
            selected = [column for column in selected if column in training.columns]
            if not selected:
                raise ValueError(f"no registered features for decision date {as_of.date()}")
            training = training[selected + ["label"]]
        training = training.loc[training.index.get_level_values("datetime") >= start].dropna()
        if training.empty:
            # Early decision dates can legitimately be part of the factor
            # warm-up period (for example return_120).  They produce no
            # score; the caller performs a final non-empty-score check.
            continue
        unique_dates = training.index.get_level_values("datetime").unique().sort_values()
        if len(unique_dates) <= validation_sessions:
            continue
        valid_start = unique_dates[-validation_sessions]
        dataset = LocalPanelDataset(
            training.drop(columns="label"), training["label"],
            train=(start.isoformat(), (valid_start - pd.Timedelta(days=1)).isoformat()),
            valid=(valid_start.isoformat(), unique_dates[-1].isoformat()),
        )
        current = features.loc[feature_dates == as_of]
        if selected:
            current = current[selected]
        current = current.dropna()
        if current.empty:
            continue
        prediction = QlibLightGBMModel(model_config).fit(dataset).predict(current)
        scores.loc[as_of, prediction.index.get_level_values("instrument")] = prediction.to_numpy()
    return scores

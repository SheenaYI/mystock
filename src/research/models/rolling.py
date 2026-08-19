"""Point-in-time rolling Qlib scores for scheduled portfolio decisions."""

from __future__ import annotations

import pandas as pd

from research.labels import mature_labels_as_of
from research.models.qlib_lightgbm import LightGBMConfig, LocalPanelDataset, QlibLightGBMModel
from research.models.matrix_cache import MatrixCache


def rolling_qlib_scores(
    *,
    features: pd.DataFrame,
    labels: pd.DataFrame,
    decision_dates: pd.DatetimeIndex,
    train_start: str,
    horizon: int = 20,
    retrain_days: int | None = None,
    rebalance_days: int = 20,
    validation_sessions: int = 60,
    model_config: LightGBMConfig = LightGBMConfig(),
    selected_features_by_date: dict[pd.Timestamp, tuple[str, ...]] | None = None,
    cache_root=None,
    cache_namespace: str | None = None,
) -> pd.DataFrame:
    """Score each decision date using only labels mature at that date.

    This is expanding-window fitting.  The model is fitted every
    ``retrain_days`` and scores every scheduled decision date in between with
    the last fitted model.  At each fitting date, labels whose next-open
    holding period has not ended are excluded and the most recent
    ``validation_sessions`` mature dates are reserved for early stopping.
    """
    if not features.index.names[:2] == ["datetime", "instrument"]:
        raise ValueError("features must use a (datetime, instrument) MultiIndex")
    if not features.index.get_level_values("datetime").unique().equals(labels.index):
        raise ValueError("feature and label sessions must match")
    if validation_sessions <= 0:
        raise ValueError("validation_sessions must be positive")
    retrain_days = retrain_days or rebalance_days
    if retrain_days <= 0 or rebalance_days <= 0:
        raise ValueError("retrain_days and rebalance_days must be positive")
    if retrain_days % rebalance_days:
        raise ValueError("retrain_days must be a whole number of rebalance intervals")
    columns = features.index.get_level_values("instrument").unique().sort_values()
    scores = pd.DataFrame(index=labels.index, columns=columns, dtype=float)
    feature_dates = features.index.get_level_values("datetime")
    start = pd.Timestamp(train_start)
    matrix_cache = (
        MatrixCache(cache_root, cache_namespace)
        if cache_root is not None and cache_namespace
        else None
    )

    decision_stride = retrain_days // rebalance_days
    active_model = None
    active_features: tuple[str, ...] = ()

    for position, as_of in enumerate(decision_dates):
        selected = None if selected_features_by_date is None else selected_features_by_date.get(pd.Timestamp(as_of))
        selected_tuple = tuple(selected or ())
        should_retrain = active_model is None or position % decision_stride == 0
        if active_model is not None and active_features != selected_tuple:
            should_retrain = True
        if should_retrain:
            mature = mature_labels_as_of(labels, as_of=as_of, horizon=horizon)
            if len(mature.index) <= validation_sessions:
                continue
            cached = matrix_cache.load(str(pd.Timestamp(as_of).date())) if matrix_cache else None
            if cached is not None and tuple(cached[1].get("selected_features", ())) == selected_tuple:
                training = cached[0]
            else:
                label_long = mature.stack(future_stack=True).rename("label")
                label_long.index = label_long.index.set_names(["datetime", "instrument"])
                training = features.join(label_long, how="inner")
                if selected:
                    selected = [column for column in selected if column in training.columns]
                    if not selected:
                        raise ValueError(f"no registered features for decision date {as_of.date()}")
                    training = training[selected + ["label"]]
                training = training.loc[training.index.get_level_values("datetime") >= start].dropna()
                if matrix_cache and not training.empty:
                    matrix_cache.save(
                        str(pd.Timestamp(as_of).date()), training,
                        {"selected_features": list(selected_tuple), "mature_through": str(mature.index.max().date())},
                    )
            if training.empty:
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
            active_model = QlibLightGBMModel(model_config).fit(dataset)
            active_features = selected_tuple
        current = features.loc[feature_dates == as_of]
        if active_features:
            current = current[list(active_features)]
        current = current.dropna()
        if current.empty or active_model is None:
            continue
        prediction = active_model.predict(current)
        scores.loc[as_of, prediction.index.get_level_values("instrument")] = prediction.to_numpy()
    return scores

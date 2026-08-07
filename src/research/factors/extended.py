"""The complete frozen 20-factor technical menu and correlation clusters."""

from __future__ import annotations

import pandas as pd

from research.factors.technical import baseline_seven_features


def technical_20_features(*, close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, volume: pd.DataFrame, amount: pd.DataFrame) -> pd.DataFrame:
    """Return the seven baseline plus thirteen deterministic extensions."""
    daily = close.pct_change()
    base = baseline_seven_features(close=close, high=high, low=low, volume=volume)
    ret_1 = close.pct_change(1)
    ret_5 = close.pct_change(5)
    ret_20 = close.pct_change(20)
    ret_60 = close.pct_change(60)
    vol_20 = daily.rolling(20).std()
    vol_60 = daily.rolling(60).std()
    high_60 = high.rolling(60).max()
    low_60 = low.rolling(60).min()
    extended = {
        "return_120": close.pct_change(120),
        "return_1": ret_1,
        "reversal_5": -ret_5,
        "ma_gap_5": close.div(close.rolling(5).mean()).sub(1.0),
        # Positive returns are intentionally excluded, but a window does not
        # need to contain twenty negative sessions.  Requiring the default
        # twenty non-null observations made this factor entirely NaN for
        # ordinary price paths and removed every training row downstream.
        "downside_volatility_20": daily.where(daily < 0).rolling(20, min_periods=5).std(),
        "drawdown_60": close.div(close.rolling(60).max()).sub(1.0),
        "volume_trend_20": volume.rolling(5).mean().div(volume.rolling(20).mean()).sub(1.0),
        "volume_price_corr_20": daily.rolling(20).corr(volume.pct_change()),
        "illiquidity_20": daily.abs().div(amount).rolling(20).mean(),
        "trend_efficiency_60": ret_60.abs().div(daily.abs().rolling(60).sum()),
        "vol_adjusted_return_60": ret_60.div(vol_60),
        "high_low_position_60": close.sub(low_60).div(high_60.sub(low_60)),
        "return_skewness_20": daily.rolling(20).skew(),
    }
    # Build extensions with the same (date, instrument) layout.
    ext = pd.concat(extended, axis=1)
    ext.columns.names = ["feature", "instrument"]
    ext = ext.stack("instrument", future_stack=True)
    ext.index.names = ["datetime", "instrument"]
    return pd.concat([base, ext], axis=1).sort_index(axis=1)


def strong_correlation_clusters(features: pd.DataFrame, threshold: float = 0.80) -> tuple[frozenset[str], ...]:
    """Group factors whose daily cross-sectional Spearman correlation is strong."""
    if not isinstance(features.index, pd.MultiIndex):
        raise ValueError("features must use a (datetime, instrument) MultiIndex")
    corr = features.groupby(level="datetime").corr(method="spearman")
    factors = list(features.columns)
    parent = {factor: factor for factor in factors}

    def root(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    for left_pos, left in enumerate(factors):
        for right in factors[left_pos + 1:]:
            pair = corr.loc[(slice(None), left), right].abs().median()
            if pd.notna(pair) and pair >= threshold:
                parent[root(left)] = root(right)
    groups: dict[str, set[str]] = {}
    for factor in factors:
        groups.setdefault(root(factor), set()).add(factor)
    return tuple(frozenset(group) for group in groups.values())


def select_high_coverage_low_redundancy(
    features: pd.DataFrame,
    *,
    base_factors: tuple[str, ...],
    start: str,
    end: str,
    threshold: float = 0.80,
    max_extensions: int = 3,
    min_coverage: float = 0.95,
) -> tuple[str, ...]:
    """Select a frozen deterministic extension set for S1.

    Coverage is measured only on the development period.  Candidates are
    ranked by coverage and then name, and a candidate is accepted only when
    its median daily cross-sectional Spearman correlation with every already
    selected factor is below ``threshold``.  This is deliberately a small,
    deterministic rule; it is not the real-LLM selector.
    """
    if max_extensions < 0:
        raise ValueError("max_extensions must be non-negative")
    subset = features.loc[
        (features.index.get_level_values("datetime") >= pd.Timestamp(start))
        & (features.index.get_level_values("datetime") <= pd.Timestamp(end))
    ]
    candidates = [column for column in features.columns if column not in base_factors]
    eligible = subset[list(base_factors)].notna().all(axis=1)
    eligible_count = eligible.groupby(level="datetime").sum()
    candidate_count = subset[candidates].notna().where(eligible).groupby(level="datetime").sum()
    denominator = eligible_count.where(eligible_count > 0)
    coverage = candidate_count.div(denominator, axis=0).median()
    ordered = sorted(
        (column for column in candidates if coverage.get(column, 0.0) >= min_coverage),
        key=lambda column: (-float(coverage[column]), column),
    )
    selected = list(base_factors)
    for candidate in ordered:
        if len(selected) >= len(base_factors) + max_extensions:
            break
        redundant = False
        for existing in selected:
            pair = []
            for _, day in subset[[candidate, existing]].dropna().groupby(level="datetime"):
                if day[ candidate].nunique() > 1 and day[existing].nunique() > 1:
                    pair.append(day[candidate].corr(day[existing], method="spearman"))
            if pair and abs(float(pd.Series(pair).median())) >= threshold:
                redundant = True
                break
        if not redundant:
            selected.append(candidate)
    return tuple(selected[len(base_factors):])

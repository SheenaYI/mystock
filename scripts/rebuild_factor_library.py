"""Rebuild the five-family technical factor audit for the development period.

This is an analysis-only command.  It reads the frozen unadjusted archive and
writes coverage, daily median Spearman correlation, clusters, and mature-label
RankIC evidence without changing the research pipeline or source data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common.logger import PROJECT_ROOT
from research.factors.catalog import FACTOR_CATEGORIES, TECHNICAL_FACTOR_MENU
from research.factors.extended import strong_correlation_clusters, technical_25_features
from research.labels import forward_excess_return_20d, mature_labels_as_of
from research.pipeline import _apply_historical_membership, _load_benchmark_prices, _load_price_panels
from research.diagnostics import rank_ic_series, _ic_summary
from research.diagnostics import DEVELOPMENT_FOLDS
from research.state import classify_market_state
from research.universe import load_historical_universe


def _median_cross_sectional_corr(features: pd.DataFrame) -> pd.DataFrame:
    values: list[pd.DataFrame] = []
    for _, day in features.groupby(level="datetime"):
        wide = day.droplevel("datetime").reindex(columns=list(TECHNICAL_FACTOR_MENU))
        if len(wide) >= 20:
            values.append(wide.corr(method="spearman"))
    if not values:
        return pd.DataFrame(index=TECHNICAL_FACTOR_MENU, columns=TECHNICAL_FACTOR_MENU, dtype=float)
    return pd.concat(values).groupby(level=0).median().reindex(index=TECHNICAL_FACTOR_MENU, columns=TECHNICAL_FACTOR_MENU)


def run() -> Path:
    raw_root = PROJECT_ROOT / "data" / "raw" / "unadjusted_akshare"
    output = PROJECT_ROOT / "data" / "warehouse" / "factor_library_rebuild"
    output.mkdir(parents=True, exist_ok=True)
    universe = load_historical_universe(
        PROJECT_ROOT / "data" / "raw" / "membership" / "csi300",
        expected_index_code="000300.XSHG",
        decision_cutoff_time=pd.Timestamp("2000-01-01 15:30").time(),
        timezone_name="Asia/Shanghai",
    )
    symbols = sorted({row.symbol for row in universe.memberships})
    panels = _load_price_panels(symbols, "2021-01-01", "2023-12-31", raw_root=raw_root)
    close = panels["close"]
    benchmark = _load_benchmark_prices("000300.SH", "2021-01-01", "2023-12-31")
    benchmark = benchmark.reindex(close.index)
    features = technical_25_features(
        close=close, high=panels["high"], low=panels["low"],
        volume=panels["volume"], amount=panels["amount"],
        benchmark_close=benchmark["close"],
    )
    membership = _apply_historical_membership(close, universe=universe, index_code="000300.XSHG")
    amount_ok = panels["amount"].apply(pd.to_numeric, errors="coerce").gt(0)
    eligible = membership & amount_ok
    eligible_long = eligible.stack(future_stack=True)
    eligible_long.index.names = ["datetime", "instrument"]
    features = features.where(eligible_long, other=float("nan"))

    denominator = eligible.sum(axis=1).replace(0, pd.NA)
    coverage_rows = []
    for factor in TECHNICAL_FACTOR_MENU:
        daily = features[factor].notna().groupby(level="datetime").sum()
        coverage = daily.div(denominator).dropna()
        # Do not punish a 60/120-day lookback for its intentional warm-up.
        # Coverage thresholds apply from the first date on which the factor
        # has a normal cross-section, not from the beginning of the archive.
        active = coverage[coverage > 0]
        first_valid = active.index[0] if len(active) else None
        post_warmup = coverage.loc[first_valid:] if first_valid is not None else coverage.iloc[0:0]
        coverage_rows.append({
            "factor": factor,
            "category": FACTOR_CATEGORIES[factor],
            "median_coverage": float(coverage.median()) if not coverage.empty else None,
            "min_daily_coverage": float(coverage.min()) if not coverage.empty else None,
            "first_valid_date": str(first_valid.date()) if first_valid is not None else None,
            "days_at_or_above_95pct": int((post_warmup >= 0.95).sum()),
            "coverage_days_after_warmup": int(len(post_warmup)),
            "share_days_at_or_above_95pct_after_warmup": (
                float((post_warmup >= 0.95).mean()) if len(post_warmup) else None
            ),
        })
    pd.DataFrame(coverage_rows).to_csv(output / "coverage.csv", index=False)

    corr = _median_cross_sectional_corr(features)
    corr.to_csv(output / "median_daily_spearman.csv")
    clusters = [sorted(cluster) for cluster in strong_correlation_clusters(features, threshold=0.80)]
    (output / "correlation_clusters.json").write_text(
        json.dumps({"threshold": 0.80, "clusters": clusters}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    labels = forward_excess_return_20d(panels["open"], benchmark["open"], horizon=20)
    labels = labels.where(membership & amount_ok)
    mature = mature_labels_as_of(labels, as_of=pd.Timestamp("2023-12-29"), horizon=20)
    state_benchmark = _load_benchmark_prices("000300.SH", "2015-01-01", "2023-12-31")
    states = pd.Series(
        {date: classify_market_state(state_benchmark.loc[:date, "close"])
         for date in mature.index},
        name="state",
    )
    evidence_rows = []
    state_rows = []
    for factor in TECHNICAL_FACTOR_MENU:
        scores = features[factor].unstack("instrument").reindex(index=mature.index, columns=mature.columns)
        ic = rank_ic_series(scores, mature)
        evidence_rows.append({"factor": factor, "category": FACTOR_CATEGORIES[factor], **_ic_summary(ic)})
        for fold_name, fold_start, fold_end in DEVELOPMENT_FOLDS:
            fold_summary = _ic_summary(ic.loc[fold_start:fold_end])
            evidence_rows[-1][f"{fold_name}_mean_rank_ic"] = fold_summary["mean_rank_ic"]
            evidence_rows[-1][f"{fold_name}_icir"] = fold_summary["icir"]
            evidence_rows[-1][f"{fold_name}_observations"] = fold_summary["observations"]
        aligned = states.reindex(ic.index)
        for state, values in ic.groupby(aligned):
            evidence_rows[-1][f"{state}_mean_rank_ic"] = _ic_summary(values)["mean_rank_ic"]
            evidence_rows[-1][f"{state}_icir"] = _ic_summary(values)["icir"]
            evidence_rows[-1][f"{state}_observations"] = _ic_summary(values)["observations"]
    pd.DataFrame(evidence_rows).to_csv(output / "development_rank_ic.csv", index=False)
    (output / "summary.json").write_text(json.dumps({
        "schema_version": "mystock-factor-library-rebuild-v1",
        "period": {"start": "2021-01-01", "end": "2023-12-31"},
        "factor_count": len(TECHNICAL_FACTOR_MENU),
        "factor_categories": FACTOR_CATEGORIES,
        "mature_through": str(mature.index.max().date()) if len(mature.index) else None,
        "outputs": ["coverage.csv", "median_daily_spearman.csv", "correlation_clusters.json", "development_rank_ic.csv"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    print(run())

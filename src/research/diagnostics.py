"""Diagnostics that separate score quality from portfolio construction."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEVELOPMENT_FOLDS = (
    ("F1", "2021-07-01", "2021-12-31"),
    ("F2", "2022-07-01", "2022-12-31"),
    ("F3", "2023-07-01", "2023-12-31"),
)


def rank_ic_series(scores: pd.DataFrame, labels: pd.DataFrame) -> pd.Series:
    """Daily cross-sectional Spearman score/realized-label correlations."""
    if not scores.index.equals(labels.index) or not scores.columns.equals(labels.columns):
        raise ValueError("scores and labels must share the same date x instrument panel")
    values: dict[pd.Timestamp, float] = {}
    for date in scores.index[scores.notna().any(axis=1)]:
        sample = pd.concat([scores.loc[date].rename("score"), labels.loc[date].rename("label")], axis=1).dropna()
        if len(sample) >= 20 and sample["score"].nunique() > 1 and sample["label"].nunique() > 1:
            values[pd.Timestamp(date)] = sample["score"].corr(sample["label"], method="spearman")
    return pd.Series(values, name="rank_ic", dtype=float)


def _ic_summary(series: pd.Series) -> dict[str, float | int | None]:
    clean = series.dropna()
    if clean.empty:
        return {"observations": 0, "mean_rank_ic": None, "median_rank_ic": None, "icir": None}
    std = clean.std(ddof=1)
    return {
        "observations": int(len(clean)),
        "mean_rank_ic": float(clean.mean()),
        "median_rank_ic": float(clean.median()),
        "icir": None if pd.isna(std) or std == 0 else float(clean.mean() / std),
    }


def score_diagnostics(
    *, scores: pd.DataFrame, labels: pd.DataFrame, states: pd.Series
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    """Return fold/state RankIC and top/middle/bottom realized excess returns."""
    rank_ic = rank_ic_series(scores, labels)
    fold_rows = []
    for name, start, end in DEVELOPMENT_FOLDS:
        row = {"segment": name, **_ic_summary(rank_ic.loc[start:end])}
        fold_rows.append(row)
    state_rows = []
    aligned_states = states.reindex(rank_ic.index).rename("state")
    for state, group in rank_ic.groupby(aligned_states):
        state_rows.append({"state": state, **_ic_summary(group)})

    quantile_rows = []
    for date in rank_ic.index:
        sample = pd.concat([scores.loc[date].rename("score"), labels.loc[date].rename("excess_return")], axis=1).dropna()
        ranks = sample["score"].rank(pct=True, method="first")
        quantile_rows.append({
            "date": date,
            "state": states.get(date, "unknown"),
            "top_10_excess_return": float(sample.loc[ranks >= 0.90, "excess_return"].mean()),
            "middle_10_excess_return": float(sample.loc[(ranks >= 0.45) & (ranks <= 0.55), "excess_return"].mean()),
            "bottom_10_excess_return": float(sample.loc[ranks <= 0.10, "excess_return"].mean()),
        })
    quantiles = pd.DataFrame(quantile_rows).set_index("date") if quantile_rows else pd.DataFrame()
    if not quantiles.empty:
        quantiles["top_minus_bottom"] = quantiles["top_10_excess_return"] - quantiles["bottom_10_excess_return"]
        for column in ("top_10_excess_return", "middle_10_excess_return", "bottom_10_excess_return", "top_minus_bottom"):
            quantiles[f"{column}_nav"] = (1.0 + quantiles[column]).cumprod()
    return pd.DataFrame(fold_rows), pd.DataFrame(state_rows), quantiles, rank_ic


def relative_performance_diagnostics(
    strategy_returns: pd.Series, benchmark_returns: pd.Series, *, window: int = 60
) -> tuple[pd.DataFrame, dict[str, float | None]]:
    """Benchmark-relative NAV, drawdown, tracking error, IR, and rolling beta."""
    if not strategy_returns.index.equals(benchmark_returns.index):
        raise ValueError("strategy and benchmark returns must share an index")
    frame = pd.DataFrame({"strategy_return": strategy_returns, "benchmark_return": benchmark_returns}).fillna(0.0)
    frame["active_return"] = frame["strategy_return"] - frame["benchmark_return"]
    strategy_nav = (1.0 + frame["strategy_return"]).cumprod()
    benchmark_nav = (1.0 + frame["benchmark_return"]).cumprod()
    frame["relative_nav"] = strategy_nav.div(benchmark_nav)
    frame["relative_drawdown"] = frame["relative_nav"].div(frame["relative_nav"].cummax()).sub(1.0)
    variance = frame["benchmark_return"].rolling(window).var()
    frame["rolling_beta_60"] = frame["strategy_return"].rolling(window).cov(frame["benchmark_return"]).div(variance.where(variance != 0))
    tracking_error = frame["active_return"].std(ddof=1) * np.sqrt(252)
    active_return_annualized = frame["active_return"].mean() * 252
    metrics: dict[str, float | None] = {
        "active_return": float(frame["relative_nav"].iloc[-1] - 1.0),
        "relative_max_drawdown": float(frame["relative_drawdown"].min()),
        "tracking_error": float(tracking_error),
        "information_ratio": None if tracking_error == 0 or pd.isna(tracking_error) else float(active_return_annualized / tracking_error),
        "mean_rolling_beta_60": None if frame["rolling_beta_60"].dropna().empty else float(frame["rolling_beta_60"].mean()),
    }
    return frame, metrics


def write_diagnostics(
    *, out_dir: Path, profile: str, fold_summary: pd.DataFrame, state_summary: pd.DataFrame,
    quantiles: pd.DataFrame, rank_ic: pd.Series, phases: dict[str, tuple[pd.DataFrame, dict[str, float | None]]],
) -> Path:
    """Persist replayable tables and a compact HTML page with two key charts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / profile
    rank_ic.rename("rank_ic").to_csv(prefix.with_name(f"{profile}_rank_ic.csv"))
    fold_summary.to_csv(prefix.with_name(f"{profile}_fold_rank_ic.csv"), index=False)
    state_summary.to_csv(prefix.with_name(f"{profile}_state_rank_ic.csv"), index=False)
    quantiles.to_csv(prefix.with_name(f"{profile}_quantile_returns.csv"))
    phase_metrics = {}
    images = []
    for phase, (frame, metrics) in phases.items():
        frame.to_csv(prefix.with_name(f"{profile}_{phase}_relative_performance.csv"))
        phase_metrics[phase] = metrics
        fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
        axes[0].plot(frame.index, frame["relative_nav"], label="strategy / benchmark")
        axes[0].axhline(1.0, color="black", linewidth=0.8)
        axes[0].set_title(f"{profile} {phase}: relative NAV")
        axes[0].legend()
        axes[1].plot(frame.index, frame["rolling_beta_60"], label="60d beta")
        axes[1].axhline(1.0, color="black", linewidth=0.8)
        axes[1].set_title("rolling beta")
        axes[1].legend()
        fig.tight_layout()
        image_path = prefix.with_name(f"{profile}_{phase}_relative.png")
        fig.savefig(image_path, dpi=140)
        plt.close(fig)
        images.append(image_path.name)
    payload = {"profile": profile, "phase_metrics": phase_metrics}
    prefix.with_name(f"{profile}_diagnostics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    page = prefix.with_name(f"{profile}_diagnostics.html")
    image_html = "".join(f'<h2>{name}</h2><img src="{name}" style="max-width:100%">' for name in images)
    page.write_text(
        "<html><head><meta charset='utf-8'><title>score diagnostics</title></head><body>"
        f"<h1>{profile} score and portfolio diagnostics</h1>"
        "<h2>Development-fold RankIC / ICIR</h2>" + fold_summary.to_html(index=False) +
        "<h2>State RankIC / ICIR</h2>" + state_summary.to_html(index=False) +
        "<h2>Quantile realized excess returns</h2>" + quantiles.tail(30).to_html() +
        "<h2>Relative-performance metrics</h2>" + pd.DataFrame(phase_metrics).T.to_html() + image_html +
        "</body></html>", encoding="utf-8",
    )
    return page

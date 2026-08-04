"""Builds the research universe: a liquid, non-ST symbol list.

Fixed for the whole backtest period rather than re-selected at each
rebalance — a deliberate MVP simplification. It ranks symbols by
full-period average liquidity, which leaks a small amount of future
information into universe *selection* (not into the factor signal
itself). Acceptable for validating the pipeline; revisit before
trusting absolute performance numbers.
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb
import pandas as pd

from common.logger import PROJECT_ROOT, get_logger, load_settings
from data.akshare import AKShareProvider

logger = get_logger(__name__)

_SYMBOL_MASTER_PATH = PROJECT_ROOT / "data" / "raw" / "symbols.parquet"
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0


def _raw_daily_dir() -> Path:
    settings = load_settings()
    raw_path = settings.get("data", {}).get("raw_path", "data/raw")
    return PROJECT_ROOT / raw_path / "daily"


def _load_symbol_master() -> pd.DataFrame:
    """Return a cached `symbol, name` table, fetching it once if absent."""
    if _SYMBOL_MASTER_PATH.exists():
        return pd.read_parquet(_SYMBOL_MASTER_PATH)

    provider = AKShareProvider()
    master = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            master = provider.list_symbol_master()
            break
        except Exception as exc:
            logger.warning(
                "list_symbol_master attempt=%d/%d failed: %s",
                attempt, _RETRY_ATTEMPTS, exc,
            )
            time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
    if master is None:
        raise RuntimeError("failed to fetch symbol master after retries")

    _SYMBOL_MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    master.to_parquet(_SYMBOL_MASTER_PATH, index=False)
    return master


def build_clean_universe(
    top_n: int = 800, min_history_days: int = 250
) -> list[str]:
    """Return up to `top_n` liquid, non-ST symbols with enough history."""
    raw_dir = _raw_daily_dir()
    con = duckdb.connect()
    stats = con.execute(
        f"""
        SELECT symbol, count(*) AS n_days, avg(amount) AS avg_amount
        FROM read_parquet('{raw_dir.as_posix()}/*.parquet')
        GROUP BY symbol
        """
    ).df()

    master = _load_symbol_master()
    merged = stats.merge(master, on="symbol", how="inner")
    is_st = merged["name"].str.contains("ST", na=False)
    eligible = merged[(merged["n_days"] >= min_history_days) & ~is_st]

    universe = (
        eligible.sort_values("avg_amount", ascending=False)
        .head(top_n)["symbol"]
        .tolist()
    )
    logger.info(
        "universe: %d/%d eligible, %d selected",
        len(eligible), len(merged), len(universe),
    )
    return universe

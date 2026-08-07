"""Non-overwriting OHLCV repair helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data.akshare import AKShareProvider


def repair_symbols(symbols: list[str], *, raw_root: Path, start_date: str, end_date: str) -> dict:
    """Retry selected symbols and append only absent OHLCV rows.

    Existing rows are never replaced. A conflicting observation is reported
    and left untouched for manual review.
    """
    provider = AKShareProvider()
    daily = Path(raw_root) / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    summary = {"requested": len(symbols), "repaired_rows": 0, "empty_symbols": [], "conflicts": []}
    fields = ["open", "high", "low", "close", "volume", "amount"]
    for symbol in symbols:
        frame = provider.fetch(symbol, start_date=start_date)
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        frame = frame[(frame["date"] >= start_date) & (frame["date"] <= end_date)]
        if frame.empty:
            summary["empty_symbols"].append(symbol)
            continue
        path = daily / f"{symbol}.parquet"
        existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["symbol", "date", *fields])
        existing["date"] = existing["date"].astype(str)
        old = existing.set_index(["symbol", "date"])
        new = frame.set_index(["symbol", "date"])
        overlap = old.index.intersection(new.index)
        for key in overlap:
            for field in fields:
                left, right = old.loc[key, field], new.loc[key, field]
                if pd.notna(left) and pd.notna(right) and float(left) != float(right):
                    summary["conflicts"].append({"symbol": key[0], "date": key[1], "field": field})
        absent = new.loc[~new.index.isin(old.index)].reset_index()
        if len(absent):
            pd.concat([existing, absent], ignore_index=True).sort_values("date").to_parquet(
                path, index=False, compression="zstd"
            )
            summary["repaired_rows"] += len(absent)
    return summary

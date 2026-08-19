"""Provider-neutral normalization and source comparison for OHLCV supplements."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


OHLCV_FIELDS = ("open", "high", "low", "close", "volume", "amount")
STANDARD_COLUMNS = ("symbol", "date", *OHLCV_FIELDS, "outstanding_share", "turnover")


def normalize_ohlcv(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    """Normalize a provider frame without silently inventing market fields."""
    aliases = {
        "datetime": "date", "time": "date", "日期": "date",
        "开盘": "open", "最高": "high", "最低": "low", "收盘": "close",
        "成交量": "volume", "成交额": "amount", "vol": "volume",
    }
    data = frame.rename(columns={key: value for key, value in aliases.items()}).copy()
    if "date" not in data or not set(OHLCV_FIELDS).issubset(data.columns):
        missing = [field for field in ("date", *OHLCV_FIELDS) if field not in data]
        raise ValueError(f"supplement frame lacks standard fields: {missing}")
    data["symbol"] = symbol
    data["date"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d")
    for field in OHLCV_FIELDS:
        data[field] = pd.to_numeric(data[field], errors="coerce")
    for field in ("outstanding_share", "turnover"):
        if field not in data:
            data[field] = pd.NA
    result = data[list(STANDARD_COLUMNS)].dropna(subset=list(OHLCV_FIELDS))
    return result.drop_duplicates(["symbol", "date"], keep="last").sort_values("date")


def compare_with_primary(
    supplement: pd.DataFrame,
    *,
    primary_file: Path,
    report_root: Path,
    source_name: str,
    price_tolerance: float = 1e-8,
    relative_tolerance: float = 1e-6,
) -> dict:
    """Compare a normalized supplement with the canonical primary archive.

    No rows are merged or overwritten here.  The report is reusable for any
    future provider and separates missing rows from same-key field conflicts.
    """
    report_root = Path(report_root)
    report_root.mkdir(parents=True, exist_ok=True)
    primary = pd.read_parquet(primary_file) if Path(primary_file).exists() else pd.DataFrame()
    primary = (
        normalize_ohlcv(primary, symbol=str(supplement["symbol"].iloc[0]))
        if not primary.empty
        else pd.DataFrame(columns=STANDARD_COLUMNS)
    )
    key = ["symbol", "date"]
    missing = supplement.merge(primary[key], on=key, how="left", indicator=True)
    missing = missing.loc[missing["_merge"] == "left_only", supplement.columns].copy()
    common = supplement.merge(primary, on=key, how="inner", suffixes=("_supplement", "_primary"))
    conflicts: list[dict] = []
    for _, row in common.iterrows():
        for field in OHLCV_FIELDS:
            left, right = row[f"{field}_supplement"], row[f"{field}_primary"]
            if pd.isna(left) or pd.isna(right):
                continue
            scale = max(abs(float(left)), abs(float(right)), 1.0)
            if abs(float(left) - float(right)) > max(price_tolerance, relative_tolerance * scale):
                conflicts.append({
                    "symbol": row["symbol"], "date": row["date"], "field": field,
                    "primary": float(right), "supplement": float(left),
                })
    stem = f"{source_name.lower().replace('-', '_')}_{supplement['symbol'].iloc[0]}"
    missing_path = report_root / f"{stem}_missing.csv"
    conflict_path = report_root / f"{stem}_conflicts.csv"
    missing.to_csv(missing_path, index=False)
    pd.DataFrame(conflicts, columns=["symbol", "date", "field", "primary", "supplement"]).to_csv(conflict_path, index=False)
    payload = {
        "schema_version": "mystock-source-comparison-v1",
        "source_name": source_name,
        "symbol": str(supplement["symbol"].iloc[0]),
        "primary_file": str(primary_file),
        "supplement_rows": int(len(supplement)),
        "common_rows": int(len(common)),
        "missing_rows": int(len(missing)),
        "conflict_fields": int(len(conflicts)),
        "missing_csv": str(missing_path),
        "conflicts_csv": str(conflict_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    report_path = report_root / f"{stem}.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload | {"report": str(report_path)}


def iter_source_comparisons(
    frames: Iterable[pd.DataFrame], *, primary_root: Path, report_root: Path, source_name: str
) -> list[dict]:
    """Run the same comparison contract for any future provider adapter."""
    reports = []
    for frame in frames:
        if frame.empty:
            continue
        symbol = str(frame["symbol"].iloc[0])
        reports.append(compare_with_primary(
            normalize_ohlcv(frame, symbol=symbol),
            primary_file=Path(primary_root) / f"{symbol}.parquet",
            report_root=report_root, source_name=source_name,
        ))
    return reports

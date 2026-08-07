"""JoinQuant historical tradability fields.

This provider deliberately stores only execution-status evidence.  It never
replaces the AKShare OHLCV archive: ``paused`` and daily limit prices are
joined later by ``symbol`` and ``date``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from common.logger import PROJECT_ROOT, get_logger

logger = get_logger(__name__)
FIELDS = ["paused", "high_limit", "low_limit", "pre_close"]
SCHEMA_VERSION = "mystock-tradability-manifest-v1"


def jq_symbol(symbol: str) -> str:
    code, exchange = symbol.split(".")
    return f"{code}.{ 'XSHG' if exchange == 'SH' else 'XSHE' }"


def local_symbol(code: str) -> str:
    code = str(code)
    exchange = "SH" if code.endswith("XSHG") else "SZ"
    return f"{code.split('.')[0]}.{exchange}"


class JoinQuantTradabilityProvider:
    """Authenticated, read-only JoinQuant daily status client."""

    def __init__(self, username: str | None = None, password: str | None = None) -> None:
        load_dotenv(PROJECT_ROOT / ".env")
        self.username = username or os.getenv("JQ_USERNAME", "").strip()
        self.password = password or os.getenv("JQ_PASSWORD", "").strip()
        if not self.username or not self.password:
            raise ValueError("JQ_USERNAME and JQ_PASSWORD are required")
        try:
            import jqdatasdk as jq
        except ImportError as exc:
            raise RuntimeError("install jqdatasdk to fetch JoinQuant tradability data") from exc
        self.jq = jq
        try:
            self.jq.auth(self.username, self.password)
        except Exception as exc:
            raise RuntimeError(
                "JoinQuant authentication failed; check JQ_USERNAME/JQ_PASSWORD "
                "and whether the account has JQData SDK access"
            ) from exc

    def fetch(self, symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        jq_symbols = [jq_symbol(symbol) for symbol in symbols]
        frame = self.jq.get_price(
            jq_symbols,
            start_date=start_date,
            end_date=end_date,
            frequency="daily",
            fields=FIELDS,
            skip_paused=False,
            fq=None,
            panel=False,
            fill_paused=False,
        )
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["symbol", "date", *FIELDS])
        frame = frame.rename(columns={"code": "jq_code", "time": "date"})
        if "jq_code" not in frame.columns or "date" not in frame.columns:
            raise ValueError("JoinQuant response lacks code/time columns")
        frame["symbol"] = frame["jq_code"].map(local_symbol)
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        missing = [field for field in FIELDS if field not in frame.columns]
        if missing:
            raise ValueError(f"JoinQuant response lacks fields: {missing}")
        result = frame[["symbol", "date", *FIELDS]].copy()
        result["paused"] = result["paused"].astype("boolean")
        return result.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"])


def _symbol_path(root: Path, symbol: str) -> Path:
    return Path(root) / "daily" / f"{symbol}.parquet"


def save_tradability(root: Path, frame: pd.DataFrame) -> int:
    """Merge provider rows into the separate archive, never touching OHLCV."""
    count = 0
    daily = Path(root) / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    for symbol, rows in frame.groupby("symbol", sort=True):
        path = _symbol_path(root, symbol)
        existing = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        merged = pd.concat([existing, rows], ignore_index=True)
        merged = merged.drop_duplicates(["symbol", "date"], keep="last").sort_values("date")
        merged.to_parquet(path, index=False, compression="zstd")
        count += len(rows)
    return count


def update_tradability(symbols: list[str], *, start_date: str, end_date: str,
                       root: Path, chunk_size: int = 50) -> dict:
    """Fetch in resumable chunks and write a content-addressed manifest."""
    provider = JoinQuantTradabilityProvider()
    succeeded: list[str] = []
    failed: dict[str, str] = {}
    for offset in range(0, len(symbols), chunk_size):
        chunk = symbols[offset:offset + chunk_size]
        try:
            frame = provider.fetch(chunk, start_date, end_date)
            save_tradability(root, frame)
            succeeded.extend(chunk)
            logger.info("JoinQuant tradability: %d/%d symbols", min(offset + len(chunk), len(symbols)), len(symbols))
        except Exception as exc:
            logger.warning("JoinQuant chunk failed (%s): %s", chunk[:2], exc)
            failed.update({symbol: repr(exc) for symbol in chunk})
    write_tradability_manifest(root, start_date=start_date, end_date=end_date,
                               symbols=symbols, failed=failed)
    return {"total": len(symbols), "succeeded": len(succeeded), "failed": failed}


def write_tradability_manifest(root: Path, *, start_date: str, end_date: str,
                               symbols: list[str], failed: dict[str, str]) -> Path:
    root = Path(root)
    files = sorted((root / "daily").glob("*.parquet"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_name": "JoinQuant",
        "retrieved_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "start_date": start_date,
        "end_date": end_date,
        "symbol_count": len(symbols),
        "file_count": len(files),
        "files_sha256": digest.hexdigest(),
        "failed_symbols": failed,
        "research_status": "development_only_not_strict_pit",
    }
    path = root / "manifests" / "tradability.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def import_export(export_root: Path, canonical_root: Path) -> dict:
    """Verify the downloaded CSV export and normalize it to per-symbol Parquet."""
    export_root = Path(export_root)
    manifest_path = export_root / "tradability_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"missing JoinQuant export manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {item["file"]: item["sha256"] for item in manifest.get("files", [])}
    frames: list[pd.DataFrame] = []
    for name, digest in expected.items():
        path = export_root / name
        if not path.is_file():
            raise ValueError(f"missing JoinQuant export file: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"JoinQuant export hash mismatch: {name}")
        frame = pd.read_csv(path)
        required = {"symbol", "date", *FIELDS}
        if not required.issubset(frame.columns):
            raise ValueError(f"JoinQuant export missing fields: {name}")
        frames.append(frame[["symbol", "date", *FIELDS]])
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    duplicate_mask = combined.duplicated(["symbol", "date"], keep=False)
    if duplicate_mask.any():
        duplicates = combined.loc[duplicate_mask].sort_values(["symbol", "date"])
        if duplicates.drop_duplicates(["symbol", "date", *FIELDS]).duplicated(["symbol", "date"], keep=False).any():
            raise ValueError("conflicting duplicate JoinQuant tradability observations")
        combined = combined.drop_duplicates(["symbol", "date"], keep="first")
    combined["date"] = pd.to_datetime(combined["date"]).dt.strftime("%Y-%m-%d")
    combined["paused"] = combined["paused"].astype("boolean")
    canonical_root = Path(canonical_root)
    (canonical_root / "daily").mkdir(parents=True, exist_ok=True)
    for symbol, rows in combined.groupby("symbol", sort=True):
        rows.to_parquet(canonical_root / "daily" / f"{symbol}.parquet", index=False, compression="zstd")
    canonical_manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_name": "JoinQuant",
        "source_export_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "file_count": int(combined["symbol"].nunique()),
        "row_count": int(len(combined)),
        "symbol_count": int(combined["symbol"].nunique()),
        "date_min": str(combined["date"].min()) if not combined.empty else None,
        "date_max": str(combined["date"].max()) if not combined.empty else None,
        "research_status": "development_only_not_strict_pit",
    }
    manifest_out = canonical_root / "manifests" / "tradability.json"
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(canonical_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return canonical_manifest


def audit_tradability_coverage(
    canonical_root: Path,
    membership_csv: Path,
    *,
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
) -> dict:
    """Check status evidence against PIT membership intervals.

    Missing status values are reported, never inferred from OHLCV. This keeps
    a partial manual export from being mistaken for a complete execution
    archive.
    """
    import duckdb

    membership = pd.read_csv(membership_csv, dtype=str)
    required = {"symbol", "effective_from", "effective_to"}
    if not required.issubset(membership.columns):
        raise ValueError("membership archive lacks effective_from/effective_to fields")
    membership["effective_from"] = pd.to_datetime(membership["effective_from"], errors="coerce")
    membership["effective_to"] = pd.to_datetime(membership["effective_to"], errors="coerce")
    if membership[["effective_from", "effective_to"]].isna().any().any():
        raise ValueError("membership archive contains invalid effective interval")

    root = Path(canonical_root)
    daily = root / "daily"
    if not any(daily.glob("*.parquet")):
        raise ValueError(f"missing canonical tradability files: {daily}")
    con = duckdb.connect()
    dates = pd.to_datetime(con.execute(
        f"SELECT DISTINCT date FROM read_parquet('{daily.as_posix()}/*.parquet') "
        f"WHERE date BETWEEN '{start_date}' AND '{end_date}' ORDER BY date"
    ).df()["date"])
    expected_parts: list[pd.DataFrame] = []
    for row in membership.itertuples(index=False):
        active = dates[(dates >= row.effective_from) & (dates <= row.effective_to)]
        if len(active):
            expected_parts.append(pd.DataFrame({"symbol": row.symbol, "date": active}))
    expected = pd.concat(expected_parts, ignore_index=True) if expected_parts else pd.DataFrame(columns=["symbol", "date"])
    observed = con.execute(
        f"SELECT symbol, date, paused, high_limit, low_limit, pre_close "
        f"FROM read_parquet('{daily.as_posix()}/*.parquet') "
        f"WHERE date BETWEEN '{start_date}' AND '{end_date}'"
    ).df()
    observed["date"] = pd.to_datetime(observed["date"])
    merged = expected.merge(observed, on=["symbol", "date"], how="left", indicator=True)
    fields = ["paused", "high_limit", "low_limit", "pre_close"]
    incomplete = merged[merged["_merge"].eq("both") & merged[fields].isna().any(axis=1)]
    missing = merged[merged["_merge"].eq("left_only")]
    report = {
        "schema_version": "mystock-tradability-coverage-v1",
        "canonical_manifest": str(root / "manifests" / "tradability.json"),
        "membership_csv": str(membership_csv),
        "window": {"start": start_date, "end": end_date},
        "expected_membership_days": int(len(expected)),
        "complete_membership_days": int(len(merged) - len(missing) - len(incomplete)),
        "missing_rows": int(len(missing)),
        "incomplete_rows": int(len(incomplete)),
        "missing_symbols": sorted(missing["symbol"].dropna().unique().tolist()),
        "incomplete_symbols": sorted(incomplete["symbol"].dropna().unique().tolist()),
        "status": "complete_for_membership_window" if missing.empty and incomplete.empty else "incomplete",
        "research_status": "development_only_not_strict_pit",
    }
    output = root / "manifests" / "tradability_coverage.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Keep the exact repair target as a small, reviewable artifact.  It is
    # intentionally not merged into the canonical archive automatically.
    repair_rows = pd.concat(
        [missing[["symbol", "date"]], incomplete[["symbol", "date"]]],
        ignore_index=True,
    ).sort_values(["symbol", "date"])
    repair_rows.to_csv(root / "manifests" / "incomplete_rows.csv", index=False)
    return report


def merge_supplement(supplement_root: Path, canonical_root: Path) -> dict:
    """Merge manually repaired CSV rows without overwriting conflicts."""
    files = sorted(Path(supplement_root).rglob("*.csv"))
    if not files:
        raise ValueError(f"no supplement CSV files found: {supplement_root}")
    incoming = []
    for path in files:
        frame = pd.read_csv(path)
        required = {"symbol", "date", *FIELDS}
        if not required.issubset(frame.columns):
            raise ValueError(f"supplement missing fields: {path}")
        incoming.append(frame[["symbol", "date", *FIELDS]])
    incoming = pd.concat(incoming, ignore_index=True)
    # JoinQuant uses XSHE/XSHG; the canonical archive uses SZ/SH, matching
    # the OHLCV and historical-universe symbols.
    incoming["symbol"] = incoming["symbol"].map(local_symbol)
    incoming["date"] = pd.to_datetime(incoming["date"]).dt.strftime("%Y-%m-%d")
    incoming["paused"] = incoming["paused"].astype("boolean")
    incomplete_mask = incoming[FIELDS].isna().any(axis=1)
    incomplete_rows = int(incomplete_mask.sum())
    # A full-range JoinQuant export can legitimately include pre-listing rows
    # with no status evidence. They are not repairs; keep them out of the
    # canonical merge and let the PIT audit decide whether any active interval
    # remains incomplete.
    incoming = incoming.loc[~incomplete_mask].copy()
    if incoming.empty:
        return {"supplement_files": len(files), "merged_rows": 0, "skipped_incomplete_rows": incomplete_rows}
    if incoming.duplicated(["symbol", "date"], keep=False).any():
        dup = incoming[incoming.duplicated(["symbol", "date"], keep=False)]
        if dup.drop_duplicates(["symbol", "date", *FIELDS]).duplicated(["symbol", "date"], keep=False).any():
            raise ValueError("conflicting duplicate rows inside supplement")
        incoming = incoming.drop_duplicates(["symbol", "date"], keep="last")
    merged_rows = 0
    root = Path(canonical_root)
    for symbol, rows in incoming.groupby("symbol", sort=True):
        path = root / "daily" / f"{symbol}.parquet"
        existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["symbol", "date", *FIELDS])
        combined = pd.concat([existing, rows], ignore_index=True)
        dup = combined[combined.duplicated(["symbol", "date"], keep=False)]
        if not dup.empty:
            values = dup.drop_duplicates(["symbol", "date", *FIELDS])
            if values.duplicated(["symbol", "date"], keep=False).any():
                raise ValueError(f"supplement conflicts with canonical row: {symbol}")
        combined = combined.drop_duplicates(["symbol", "date"], keep="last").sort_values("date")
        combined.to_parquet(path, index=False, compression="zstd")
        merged_rows += len(rows)
    return {"supplement_files": len(files), "merged_rows": merged_rows, "skipped_incomplete_rows": incomplete_rows}

"""Build reproducible manifests for archived daily OHLCV files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "mystock-ohlcv-manifest-v1"


def _files_digest(files: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def build_ohlcv_manifest(
    raw_root: Path,
    *,
    price_adjustment: str,
    source_name: str,
    retrieved_at: str | None = None,
    amount_unit: str = "CNY",
) -> dict:
    """Build a manifest; adjustment is required and never inferred."""
    if price_adjustment not in {"unadjusted", "qfq", "hfq"}:
        raise ValueError("price_adjustment must be unadjusted, qfq, or hfq")
    if not source_name.strip():
        raise ValueError("source_name must not be empty")
    root = Path(raw_root)
    files = sorted((root / "daily").glob("*.parquet"))
    if not files:
        raise ValueError("no daily Parquet files found")
    return {
        "schema_version": SCHEMA_VERSION,
        "price_adjustment": price_adjustment,
        "source_name": source_name.strip(),
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(),
        "amount_unit": amount_unit,
        "file_count": len(files),
        "files_sha256": _files_digest(files, root),
    }


def write_ohlcv_manifest(raw_root: Path, manifest: dict) -> Path:
    path = Path(raw_root) / "manifests" / "ohlcv.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

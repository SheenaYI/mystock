"""Data-evidence contracts for reproducible historical research."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


_SCHEMA_VERSION = "mystock-ohlcv-manifest-v1"


@dataclass(frozen=True)
class OhlcvContract:
    """Declared price meanings for one archived OHLCV data set."""

    price_adjustment: str
    source_name: str
    retrieved_at: str
    amount_unit: str = "CNY"

    def require_execution_compatible(self) -> None:
        if self.price_adjustment != "unadjusted":
            raise ValueError(
                "formal research requires unadjusted OHLCV for next-open execution; "
                f"got {self.price_adjustment!r}"
            )


def amount_invalid_mask(amount: pd.DataFrame) -> pd.DataFrame:
    """Return cells that cannot be interpreted as positive traded turnover."""
    numeric = amount.apply(pd.to_numeric, errors="coerce")
    return numeric.isna() | (numeric <= 0)


def validate_amount_panel(
    amount: pd.DataFrame, *, ignore_mask: pd.DataFrame | None = None
) -> None:
    """Reject invalid turnover, except cells explicitly quarantined by the caller."""
    if amount.empty:
        raise ValueError("amount panel must not be empty")
    numeric = amount.apply(pd.to_numeric, errors="coerce")
    if ignore_mask is not None:
        if not ignore_mask.index.equals(numeric.index) or not ignore_mask.columns.equals(numeric.columns):
            raise ValueError("amount ignore_mask must align with amount panel")
        numeric = numeric.mask(ignore_mask)
        numeric = numeric.stack(future_stack=True).dropna().to_frame("amount")
    if numeric.isna().any().any():
        raise ValueError("amount panel contains missing or non-numeric values")
    if (numeric < 0).any().any():
        raise ValueError("amount panel contains invalid values")
    if (numeric <= 0).any().any():
        raise ValueError("amount panel contains zero turnover")


def load_ohlcv_contract(raw_root: Path) -> OhlcvContract:
    """Load the immutable OHLCV manifest; no manifest means no formal run."""
    path = Path(raw_root) / "manifests" / "ohlcv.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing OHLCV data manifest: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unexpected OHLCV data manifest schema_version")
    adjustment = str(payload.get("price_adjustment", "")).strip()
    if adjustment not in {"unadjusted", "qfq", "hfq"}:
        raise ValueError("OHLCV manifest price_adjustment must be unadjusted, qfq, or hfq")
    source_name = str(payload.get("source_name", "")).strip()
    retrieved_at = str(payload.get("retrieved_at", "")).strip()
    if not source_name or not retrieved_at:
        raise ValueError("OHLCV manifest requires source_name and retrieved_at")
    return OhlcvContract(adjustment, source_name, retrieved_at, str(payload.get("amount_unit", "CNY")))

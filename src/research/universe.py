"""Point-in-time historical index-universe contracts.

The research pipeline must not infer a past stock pool from the full price
history.  Instead it consumes a local, versioned CSI 300 membership archive.
Missing or unverifiable evidence is a hard error, never a fallback to a
present-day or full-period universe.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd


_CSV_NAME = "historical_index_membership.csv"
_MANIFEST_NAME = "historical_index_membership_manifest.json"
_SCHEMA_VERSION = "mystock-historical-universe-v1"


@dataclass(frozen=True)
class UniverseMembership:
    """One member interval whose announcement was visible before use."""

    index_code: str
    symbol: str
    effective_from: date
    effective_to: date
    announced_at: datetime
    source_name: str
    source_reference: str


@dataclass(frozen=True)
class HistoricalUniverse:
    """A validated, time-varying index membership table."""

    memberships: tuple[UniverseMembership, ...]
    input_sha256: str
    source_archive_sha256: str
    source_archive_reference: str
    retrieved_at: datetime

    def members_on(self, index_code: str, as_of: date) -> tuple[str, ...]:
        """Return only constituents publicly known by the decision cutoff."""
        return tuple(
            sorted(
                row.symbol
                for row in self.memberships
                if row.index_code == index_code
                and row.effective_from <= as_of <= row.effective_to
            )
        )

    def require_members_on(self, index_code: str, as_of: date) -> tuple[str, ...]:
        """Return the date's universe or stop before any model work begins."""
        members = self.members_on(index_code, as_of)
        if not members:
            raise ValueError(
                f"historical universe coverage failed for {index_code} on {as_of.isoformat()}"
            )
        return members


def _text(value: object, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} must not be blank")
    return result


def _timestamp(value: object, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, field))
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return result


def _day(value: object, field: str) -> date:
    try:
        return date.fromisoformat(_text(value, field))
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc


def _sha256(value: object, field: str) -> str:
    result = _text(value, field)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")
    return result


def _load_manifest(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing historical universe manifest: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unexpected historical universe manifest schema_version")
    return payload


def _first_visible_session(
    *, effective_from: date, effective_to: date, announced_at: datetime,
    decision_cutoff_time: time, timezone_name: str,
) -> tuple[date, date] | None:
    sessions = tuple(
        stamp.date()
        for stamp in xcals.get_calendar("XSHG").sessions_in_range(
            pd.Timestamp(effective_from), pd.Timestamp(effective_to)
        )
    )
    if not sessions:
        raise ValueError("membership interval does not contain an XSHG session")
    zone = ZoneInfo(timezone_name)
    first_visible = next(
        (
            session for session in sessions
            if datetime.combine(session, decision_cutoff_time, tzinfo=zone) >= announced_at
        ),
        None,
    )
    return None if first_visible is None else (first_visible, sessions[-1])


def load_historical_universe(
    input_root: Path,
    *,
    expected_index_code: str = "000300.XSHG",
    decision_cutoff_time: time = time(15, 30),
    timezone_name: str = "Asia/Shanghai",
) -> HistoricalUniverse:
    """Load a locally archived, hash-verified historical index universe.

    Required files are ``historical_index_membership.csv`` and its manifest
    under ``data/raw/membership/csi300/``.  The CSV is deliberately required:
    the loader never queries a live endpoint or substitutes a full-period pool.
    """
    if decision_cutoff_time.tzinfo is not None:
        raise ValueError("decision_cutoff_time must not include timezone")
    ZoneInfo(timezone_name)
    root = Path(input_root)
    csv_path = root / _CSV_NAME
    manifest = _load_manifest(root / _MANIFEST_NAME)
    actual_hash = sha256(csv_path.read_bytes()).hexdigest()
    if actual_hash != _sha256(manifest.get("csv_sha256"), "csv_sha256"):
        raise ValueError("membership CSV hash does not match manifest")
    retrieved_at = _timestamp(manifest.get("retrieved_at"), "retrieved_at")
    if _text(manifest.get("timezone"), "timezone") != timezone_name:
        raise ValueError("manifest timezone must match timezone_name")

    required = {
        "index_code", "symbol", "announced_at", "effective_from", "effective_to",
        "source_name", "source_reference",
    }
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or set(reader.fieldnames) != required:
            raise ValueError("membership CSV must contain exactly the required columns")
        memberships: list[UniverseMembership] = []
        for row in reader:
            if _text(row.get("index_code"), "index_code") != expected_index_code:
                raise ValueError("unexpected membership index code")
            start = _day(row.get("effective_from"), "effective_from")
            end = _day(row.get("effective_to"), "effective_to")
            if end < start:
                raise ValueError("effective_to must not be before effective_from")
            announced_at = _timestamp(row.get("announced_at"), "announced_at")
            visible = _first_visible_session(
                effective_from=start, effective_to=end, announced_at=announced_at,
                decision_cutoff_time=decision_cutoff_time, timezone_name=timezone_name,
            )
            if visible is not None:
                memberships.append(UniverseMembership(
                    index_code=expected_index_code, symbol=_text(row.get("symbol"), "symbol"),
                    effective_from=visible[0], effective_to=visible[1], announced_at=announced_at,
                    source_name=_text(row.get("source_name"), "source_name"),
                    source_reference=_text(row.get("source_reference"), "source_reference"),
                ))
    if not memberships:
        raise ValueError("membership CSV does not contain visible intervals")
    memberships.sort(key=lambda row: (row.symbol, row.effective_from, row.effective_to))
    for earlier, later in zip(memberships, memberships[1:]):
        if earlier.symbol == later.symbol and later.effective_from <= earlier.effective_to:
            raise ValueError("overlapping membership intervals")
    return HistoricalUniverse(
        memberships=tuple(memberships), input_sha256=actual_hash,
        source_archive_sha256=_sha256(manifest.get("source_archive_sha256"), "source_archive_sha256"),
        source_archive_reference=_text(manifest.get("source_archive_reference"), "source_archive_reference"),
        retrieved_at=retrieved_at,
    )

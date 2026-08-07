"""Convert archived membership snapshots into the research universe contract."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo


SNAPSHOT_COLUMNS = {"as_of", "index_code", "provider", "symbol"}
UNIVERSE_COLUMNS = (
    "index_code", "symbol", "announced_at", "effective_from", "effective_to",
    "source_name", "source_reference",
)


def _digest(paths: list[Path]) -> str:
    h = sha256()
    for path in sorted(paths):
        h.update(path.name.encode())
        h.update(b"\0")
        h.update(path.read_bytes())
    return h.hexdigest()


def convert_snapshot_archive(
    source_root: Path,
    output_root: Path,
    *,
    index_code: str = "000300.XSHG",
    timezone_name: str = "Asia/Shanghai",
    retrieved_at: datetime | None = None,
) -> Path:
    """Convert daily snapshots into non-overlapping relative-PIT intervals.

    The snapshot timestamp is used as the earliest visible evidence time and
    is explicitly labelled as a JoinQuant snapshot, not an official notice.
    """
    source_root = Path(source_root)
    files = sorted(
        path for path in source_root.glob("csi300_membership_*.csv")
        if not path.name.endswith("_manifest.csv")
    )
    if not files:
        raise ValueError(f"no membership snapshots found under {source_root}")
    rows: dict[date, set[str]] = {}
    providers: set[str] = set()
    for path in files:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if set(reader.fieldnames or ()) != SNAPSHOT_COLUMNS:
                raise ValueError(f"unexpected snapshot columns: {path}")
            for row in reader:
                if row["index_code"] != index_code:
                    continue
                as_of = date.fromisoformat(row["as_of"])
                rows.setdefault(as_of, set()).add(_normalise_symbol(row["symbol"]))
                providers.add(row["provider"])
    dates = sorted(rows)
    if not dates:
        raise ValueError("snapshot archive has no rows for requested index")
    zone = ZoneInfo(timezone_name)
    intervals: list[dict[str, str]] = []
    active: dict[str, date] = {}
    previous: set[str] = set()
    for current in dates:
        members = rows[current]
        for symbol in sorted(previous - members):
            intervals.append(_interval(index_code, symbol, active.pop(symbol), current - timedelta(days=1), zone))
        for symbol in sorted(members - previous):
            active[symbol] = current
        previous = members
    for symbol, start in sorted(active.items()):
        intervals.append(_interval(index_code, symbol, start, dates[-1], zone))

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "historical_index_membership.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=UNIVERSE_COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(intervals, key=lambda row: (row["symbol"], row["effective_from"])))
    source_hash = _digest(files)
    manifest = {
        "schema_version": "mystock-historical-universe-v1",
        "csv_sha256": sha256(csv_path.read_bytes()).hexdigest(),
        "retrieved_at": (retrieved_at or datetime.now(zone)).isoformat(),
        "source_archive_sha256": source_hash,
        "source_archive_reference": f"joinquant-snapshot://{source_root}",
        "timezone": timezone_name,
        "evidence_type": "relative_pit_snapshot",
        "provider_names": sorted(providers),
    }
    (output_root / "historical_index_membership_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_root


def _interval(index_code: str, symbol: str, start: date, end: date, zone: ZoneInfo) -> dict[str, str]:
    return {
        "index_code": index_code,
        "symbol": symbol,
        "announced_at": datetime.combine(start, time(15, 30), tzinfo=zone).isoformat(),
        "effective_from": start.isoformat(),
        "effective_to": end.isoformat(),
        "source_name": "joinquant_snapshot",
        "source_reference": f"joinquant://csi300_membership/{start.isoformat()}",
    }


def _normalise_symbol(symbol: str) -> str:
    """Use the same exchange suffix as the AKShare daily archive."""
    return symbol.replace(".XSHE", ".SZ").replace(".XSHG", ".SH")

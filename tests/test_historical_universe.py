"""Regression tests for the historical CSI 300 universe contract."""

import csv
import json
from datetime import date, time
from hashlib import sha256

import pytest

from research.universe import load_historical_universe


def _input(tmp_path, rows):
    root = tmp_path / "csi300"
    root.mkdir()
    csv_path = root / "historical_index_membership.csv"
    fields = (
        "index_code", "symbol", "announced_at", "effective_from", "effective_to",
        "source_name", "source_reference",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    root.joinpath("historical_index_membership_manifest.json").write_text(
        json.dumps({
            "schema_version": "mystock-historical-universe-v1",
            "csv_sha256": sha256(csv_path.read_bytes()).hexdigest(),
            "source_archive_sha256": "a" * 64,
            "source_archive_reference": "fixture://csi300",
            "retrieved_at": "2026-08-05T09:00:00+08:00",
            "timezone": "Asia/Shanghai",
        }), encoding="utf-8",
    )
    return root


def _row(announced_at):
    return {
        "index_code": "000300.XSHG", "symbol": "600000.SH",
        "announced_at": announced_at, "effective_from": "2024-01-02",
        "effective_to": "2024-01-05", "source_name": "fixture",
        "source_reference": "fixture://csi300/2024-01",
    }


def test_membership_is_not_usable_until_its_announcement_is_visible(tmp_path):
    universe = load_historical_universe(
        _input(tmp_path, [_row("2024-01-02T16:00:00+08:00")]),
        decision_cutoff_time=time(15, 30),
    )
    assert universe.members_on("000300.XSHG", date(2024, 1, 2)) == ()
    assert universe.members_on("000300.XSHG", date(2024, 1, 3)) == ("600000.SH",)


def test_missing_date_coverage_stops_the_research_run(tmp_path):
    universe = load_historical_universe(_input(tmp_path, [_row("2024-01-01T12:00:00+08:00")]))
    with pytest.raises(ValueError, match="coverage failed"):
        universe.require_members_on("000300.XSHG", date(2024, 1, 8))


def test_manifest_hash_mismatch_is_rejected(tmp_path):
    root = _input(tmp_path, [_row("2024-01-01T12:00:00+08:00")])
    root.joinpath("historical_index_membership.csv").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash does not match"):
        load_historical_universe(root)

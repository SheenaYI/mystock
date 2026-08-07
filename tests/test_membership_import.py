import csv
import json

from data.membership_import import convert_snapshot_archive
from research.universe import load_historical_universe


def test_snapshot_archive_converts_to_relative_pit_contract(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with (source / "csi300_membership_2021.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["as_of", "index_code", "provider", "symbol"])
        writer.writeheader()
        writer.writerows([
            {"as_of": "2021-01-04", "index_code": "000300.XSHG", "provider": "joinquant", "symbol": "AAA"},
            {"as_of": "2021-02-01", "index_code": "000300.XSHG", "provider": "joinquant", "symbol": "BBB"},
        ])
    output = tmp_path / "output"
    convert_snapshot_archive(source, output)
    manifest = json.loads((output / "historical_index_membership_manifest.json").read_text())
    assert manifest["evidence_type"] == "relative_pit_snapshot"
    universe = load_historical_universe(output)
    assert universe.require_members_on("000300.XSHG", __import__("datetime").date(2021, 1, 20)) == ("AAA",)

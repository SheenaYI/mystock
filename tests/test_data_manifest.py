import json

import pytest

from data.manifest import build_ohlcv_manifest, write_ohlcv_manifest


def test_manifest_requires_explicit_adjustment(tmp_path):
    daily = tmp_path / "daily"
    daily.mkdir()
    (daily / "AAA.parquet").write_bytes(b"fixture")
    with pytest.raises(ValueError, match="price_adjustment"):
        build_ohlcv_manifest(tmp_path, price_adjustment="unknown", source_name="AKShare")


def test_manifest_hashes_files_and_is_written(tmp_path):
    daily = tmp_path / "daily"
    daily.mkdir()
    (daily / "AAA.parquet").write_bytes(b"fixture")
    payload = build_ohlcv_manifest(
        tmp_path, price_adjustment="unadjusted", source_name="AKShare", retrieved_at="2026-08-05T00:00:00Z"
    )
    path = write_ohlcv_manifest(tmp_path, payload)
    loaded = json.loads(path.read_text())
    assert loaded["file_count"] == 1
    assert loaded["files_sha256"] == payload["files_sha256"]

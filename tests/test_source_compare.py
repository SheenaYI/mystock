from pathlib import Path
import hashlib

import pandas as pd

from data.source_compare import compare_with_primary, normalize_ohlcv


def _frame(close_values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": ["2025-01-02", "2025-01-03"],
        "open": close_values,
        "high": [x + 1 for x in close_values],
        "low": [x - 1 for x in close_values],
        "close": close_values,
        "volume": [100, 110],
        "amount": [10000, 11000],
    })


def test_normalize_ohlcv_is_explicit_and_deduplicated() -> None:
    normalized = normalize_ohlcv(pd.concat([_frame([10, 11]), _frame([10, 11])]), symbol="600000.SH")
    assert list(normalized.columns) == [
        "symbol", "date", "open", "high", "low", "close", "volume", "amount",
        "outstanding_share", "turnover",
    ]
    assert len(normalized) == 2


def test_compare_reports_missing_and_conflicts_without_overwrite(tmp_path: Path) -> None:
    primary = normalize_ohlcv(_frame([10, 11]), symbol="600000.SH")
    primary.to_parquet(tmp_path / "600000.SH.parquet")
    before = hashlib.sha256((tmp_path / "600000.SH.parquet").read_bytes()).hexdigest()
    supplement = normalize_ohlcv(
        pd.DataFrame({
            "date": ["2025-01-02", "2025-01-03", "2025-01-06"],
            "open": [10, 12, 13], "high": [11, 13, 14], "low": [9, 11, 12],
            "close": [10, 12, 13], "volume": [100, 110, 120], "amount": [10000, 11000, 12000],
        }),
        symbol="600000.SH",
    )
    report = compare_with_primary(
        supplement, primary_file=tmp_path / "600000.SH.parquet",
        report_root=tmp_path / "reports", source_name="test-source",
    )
    assert report["missing_rows"] == 1
    assert report["conflict_fields"] >= 1
    after = hashlib.sha256((tmp_path / "600000.SH.parquet").read_bytes()).hexdigest()
    assert before == after


def test_compare_treats_missing_primary_archive_as_all_missing(tmp_path: Path) -> None:
    supplement = normalize_ohlcv(_frame([10, 11]), symbol="000001.SZ")
    report = compare_with_primary(
        supplement,
        primary_file=tmp_path / "not-downloaded.parquet",
        report_root=tmp_path / "reports",
        source_name="future-source",
    )
    assert report["common_rows"] == 0
    assert report["missing_rows"] == 2
    assert report["conflict_fields"] == 0

import json

import pytest

import pandas as pd

from research.data_contracts import amount_invalid_mask, load_ohlcv_contract, validate_amount_panel


def _manifest(tmp_path, adjustment):
    root = tmp_path / "raw" / "manifests"
    root.mkdir(parents=True)
    root.joinpath("ohlcv.json").write_text(json.dumps({
        "schema_version": "mystock-ohlcv-manifest-v1",
        "price_adjustment": adjustment,
        "source_name": "fixture", "retrieved_at": "2026-08-05T00:00:00+08:00",
    }), encoding="utf-8")
    return root.parent


def test_unadjusted_series_is_required_for_execution(tmp_path):
    load_ohlcv_contract(_manifest(tmp_path, "unadjusted")).require_execution_compatible()


def test_forward_adjusted_series_cannot_be_used_as_execution_prices(tmp_path):
    with pytest.raises(ValueError, match="requires unadjusted OHLCV"):
        load_ohlcv_contract(_manifest(tmp_path, "qfq")).require_execution_compatible()


def test_missing_manifest_stops_a_formal_run(tmp_path):
    with pytest.raises(ValueError, match="missing OHLCV data manifest"):
        load_ohlcv_contract(tmp_path)


def test_amount_panel_rejects_zero_turnover():
    with pytest.raises(ValueError, match="zero turnover"):
        validate_amount_panel(pd.DataFrame({"AAA": [100.0, 0.0]}))


def test_amount_panel_rejects_missing_values():
    with pytest.raises(ValueError, match="missing"):
        validate_amount_panel(pd.DataFrame({"AAA": [100.0, float("nan")]}))


def test_quarantined_amount_cells_are_excluded_but_not_repaired():
    amount = pd.DataFrame({"AAA": [100.0, 0.0, 120.0]})
    invalid = amount_invalid_mask(amount)
    validate_amount_panel(amount, ignore_mask=invalid)
    assert invalid["AAA"].tolist() == [False, True, False]
    assert amount.loc[1, "AAA"] == 0.0

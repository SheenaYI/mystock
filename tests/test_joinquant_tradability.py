import pandas as pd

from data.joinquant_tradability import jq_symbol, local_symbol, save_tradability


def test_joinquant_symbol_round_trip():
    assert jq_symbol("600000.SH") == "600000.XSHG"
    assert jq_symbol("000001.SZ") == "000001.XSHE"
    assert local_symbol("600000.XSHG") == "600000.SH"
    assert local_symbol("000001.XSHE") == "000001.SZ"


def test_tradability_is_stored_in_its_own_archive(tmp_path):
    frame = pd.DataFrame({
        "symbol": ["000001.SZ"], "date": ["2021-01-04"],
        "paused": [False], "high_limit": [10.0],
        "low_limit": [8.0], "pre_close": [9.0],
    })
    assert save_tradability(tmp_path, frame) == 1
    assert (tmp_path / "daily" / "000001.SZ.parquet").exists()
    assert not (tmp_path / "000001.SZ.parquet").exists()

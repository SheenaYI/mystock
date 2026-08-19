"""a-stock-data market supplement adapter.

The upstream project is a multi-source collection of endpoint recipes.  This
adapter uses its recommended unadjusted daily K-line path through mootdx when
installed, and stores the result separately from the AKShare archive.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from data.provider import DataProvider
from data.source_compare import normalize_ohlcv


class AStockDataProvider(DataProvider):
    """Fetch unadjusted daily bars from the a-stock-data/mootdx route."""

    def __init__(self) -> None:
        try:
            from mootdx.quotes import Quotes
        except ImportError as exc:
            raise RuntimeError(
                "a-stock-data supplement requires mootdx; install requirements.txt first"
            ) from exc
        self._quotes = Quotes
        try:
            self._client = Quotes.factory(market="std", bestip=True)
        except Exception as exc:
            raise RuntimeError("mootdx market connection failed; a-stock-data supplement unavailable") from exc

    def fetch(self, symbol: str, start_date: str = "1990-01-01", end_date: str = "2099-12-31") -> pd.DataFrame:
        code = symbol.split(".", 1)[0]
        try:
            raw = self._client.bars(symbol=code, frequency=9, offset=800)
        except Exception as exc:
            raise RuntimeError(f"a-stock-data K-line request failed for {symbol}") from exc
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"])
        data = raw.reset_index() if isinstance(raw.index, pd.DatetimeIndex) else raw.copy()
        if "date" not in data and "datetime" not in data:
            for candidate in ("time", "index"):
                if candidate in data:
                    data = data.rename(columns={candidate: "date"})
                    break
        data = normalize_ohlcv(data, symbol=symbol)
        dates = pd.to_datetime(data["date"])
        return data.loc[(dates >= pd.Timestamp(start_date)) & (dates <= pd.Timestamp(end_date))].reset_index(drop=True)

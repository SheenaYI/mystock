"""AKShare-backed data provider.

Fetches the full A-share symbol list and per-symbol daily OHLCV
history. Uses AKShare's Sina-backed `stock_zh_a_daily`, not its
Eastmoney-backed `stock_zh_a_hist` — the latter's host is unreachable
from this environment's network, while Sina's is not.
"""

from __future__ import annotations

import akshare as ak
import pandas as pd

from data.provider import DataProvider

_OUTPUT_COLUMNS = [
    "symbol", "date", "open", "high", "low", "close",
    "volume", "amount", "outstanding_share", "turnover",
]


def _infer_exchange(code: str) -> str:
    """Guess the listing exchange suffix from a 6-digit A-share code."""
    if code.startswith("6"):
        return "SH"
    if code.startswith(("4", "8", "92")):
        return "BJ"
    return "SZ"


class AKShareProvider(DataProvider):
    """Fetches the A-share symbol universe and daily OHLCV via AKShare."""

    def list_symbols(self) -> list[str]:
        """Return every symbol as `<code>.<exchange>`, e.g. '600000.SH'."""
        codes = ak.stock_info_a_code_name()["code"]
        return sorted(f"{code}.{_infer_exchange(code)}" for code in codes)

    def list_symbol_master(self) -> pd.DataFrame:
        """Return a `symbol, name` table for every A-share symbol."""
        info = ak.stock_info_a_code_name()
        symbol = info["code"].apply(
            lambda code: f"{code}.{_infer_exchange(code)}"
        )
        return pd.DataFrame({"symbol": symbol, "name": info["name"]})

    def fetch_index(
        self,
        symbol: str,
        start_date: str = "1990-01-01",
        end_date: str = "2099-12-31",
    ) -> pd.DataFrame:
        """Fetch daily OHLCV history for an index, e.g. '000300.SH'."""
        code, exchange = symbol.split(".")
        sina_symbol = f"{exchange.lower()}{code}"
        data = ak.stock_zh_index_daily(symbol=sina_symbol)
        data["date"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d")
        data = data[(data["date"] >= start_date) & (data["date"] <= end_date)]
        data.insert(0, "symbol", symbol)
        columns = ["symbol", "date", "open", "high", "low", "close", "volume"]
        return data[columns]

    def fetch(
        self,
        symbol: str,
        start_date: str = "1990-01-01",
        end_date: str = "2099-12-31",
    ) -> pd.DataFrame:
        """Fetch forward-adjusted daily OHLCV history for one symbol."""
        code, exchange = symbol.split(".")
        sina_symbol = f"{exchange.lower()}{code}"
        data = ak.stock_zh_a_daily(
            symbol=sina_symbol,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="qfq",
        )
        data.insert(0, "symbol", symbol)
        return data[_OUTPUT_COLUMNS]

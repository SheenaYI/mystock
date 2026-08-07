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
        """Fetch unadjusted daily OHLCV for factor evidence and execution.

        Company-action adjustment is an auditable research operation. A vendor
        forward-adjusted series cannot be used as a next-open execution price.
        """
        code, exchange = symbol.split(".")
        sina_symbol = f"{exchange.lower()}{code}"
        try:
            data = ak.stock_zh_a_daily(
                symbol=sina_symbol,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="",
            )
        except Exception:
            # Sina has no rows for some delisted/legacy symbols.  Eastmoney's
            # historical endpoint is an explicit fallback with the same
            # unadjusted price contract; failures still propagate to the
            # downloader's retry/failure ledger.
            fallback = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="",
            )
            data = fallback.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
                "最低": "low", "成交量": "volume", "成交额": "amount",
            })
            if "date" in data:
                data["date"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d")
            data = data[["date", "open", "high", "low", "close", "volume", "amount"]]
            data["outstanding_share"] = pd.NA
            data["turnover"] = pd.NA
        data.insert(0, "symbol", symbol)
        return data[_OUTPUT_COLUMNS]

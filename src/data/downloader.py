"""Download pipeline: Provider -> Downloader -> Storage.

Fetches per-symbol OHLCV history from a DataProvider and persists it
via a Storage backend, with retries, rate limiting, and resumability
so a multi-thousand-symbol run can be safely interrupted and re-run.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd

from common.logger import get_logger
from data.provider import DataProvider
from data.storage import Storage

logger = get_logger(__name__)

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0
REQUEST_INTERVAL_SECONDS = 0.3


class Downloader:
    """Coordinates a DataProvider and a Storage backend."""

    def __init__(self, provider: DataProvider, storage: Storage) -> None:
        self.provider = provider
        self.storage = storage

    def _fetch_with_retry(
        self, symbol: str, start_date: str
    ) -> pd.DataFrame | None:
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                return self.provider.fetch(symbol, start_date=start_date)
            except Exception as exc:
                logger.warning(
                    "symbol=%s attempt=%d/%d failed: %s",
                    symbol, attempt, RETRY_ATTEMPTS, exc,
                )
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        return None

    def run(
        self,
        symbols: list[str],
        start_date: str = "1990-01-01",
        incremental: bool = False,
        force: bool = False,
    ) -> dict:
        """Fetch and store OHLCV history for `symbols`.

        Non-incremental runs skip symbols that already have stored
        data unless `force` is set, so an interrupted full backfill
        can resume. Incremental runs fetch only the days after each
        symbol's last stored date and append to its existing history.
        """
        skip_existing = not incremental and not force
        existing_symbols = (
            set(self.storage.known_symbols()) if skip_existing else set()
        )
        succeeded: list[str] = []
        failed: list[str] = []
        total = len(symbols)

        for i, symbol in enumerate(symbols, start=1):
            if symbol in existing_symbols:
                succeeded.append(symbol)
                continue

            symbol_start = start_date
            if incremental:
                last = self.storage.last_date(symbol)
                if last is not None:
                    next_day = date.fromisoformat(last) + timedelta(days=1)
                    symbol_start = next_day.isoformat()
                    if symbol_start > date.today().isoformat():
                        succeeded.append(symbol)
                        continue

            fetched = self._fetch_with_retry(symbol, symbol_start)
            time.sleep(REQUEST_INTERVAL_SECONDS)

            if fetched is None:
                failed.append(symbol)
                continue
            if fetched.empty:
                succeeded.append(symbol)
                continue

            if incremental:
                existing = self.storage.load(symbol)
                if existing is not None:
                    fetched = pd.concat(
                        [existing, fetched], ignore_index=True
                    )

            self.storage.save(symbol, fetched)
            succeeded.append(symbol)

            if i % 100 == 0 or i == total:
                logger.info(
                    "progress: %d/%d (succeeded=%d failed=%d)",
                    i, total, len(succeeded), len(failed),
                )

        return {"total": total, "succeeded": len(succeeded), "failed": failed}

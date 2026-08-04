"""Storage interface and a Parquet-backed implementation.

Each symbol's OHLCV history is stored as a single Parquet file under a
base directory, keyed by symbol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


class Storage:
    """Base class for all storage backends."""

    def save(self, key: str, data: Any) -> None:
        """Persist data under `key`. Must be implemented by subclasses."""
        raise NotImplementedError

    def load(self, key: str) -> Any:
        """Load data stored under `key`. Must be implemented by subclasses."""
        raise NotImplementedError


class ParquetStorage(Storage):
    """One Parquet file per symbol, under `base_dir`."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.base_dir / f"{symbol}.parquet"

    def save(self, symbol: str, data: pd.DataFrame) -> None:
        """Write `data` for `symbol`, sorted and deduped by date."""
        data = data.sort_values("date")
        data = data.drop_duplicates(subset="date", keep="last")
        data.to_parquet(
            self._path(symbol),
            engine="pyarrow",
            index=False,
            compression="zstd",
        )

    def load(self, symbol: str) -> pd.DataFrame | None:
        """Return the stored history for `symbol`, or None if absent."""
        path = self._path(symbol)
        if not path.exists():
            return None
        return pd.read_parquet(path, engine="pyarrow")

    def last_date(self, symbol: str) -> str | None:
        """Return the most recent stored date for `symbol`, or None."""
        data = self.load(symbol)
        if data is None or data.empty:
            return None
        return str(data["date"].max())

    def known_symbols(self) -> list[str]:
        """List symbols that already have a stored Parquet file."""
        return sorted(p.stem for p in self.base_dir.glob("*.parquet"))

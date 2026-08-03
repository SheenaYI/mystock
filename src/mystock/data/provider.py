"""Base interface for data providers.

Concrete providers (AKShare, Tushare, ...) implement fetch() to return
raw market data. No provider is implemented yet.
"""

from __future__ import annotations

from typing import Any


class DataProvider:
    """Base class for all data providers."""

    def fetch(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch raw data from the provider. Must be implemented by subclasses."""
        raise NotImplementedError

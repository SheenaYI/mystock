"""Base interface for local data storage.

Concrete backends (Parquet, DuckDB, ...) implement save() and load().
No backend is implemented yet.
"""

from __future__ import annotations

from typing import Any


class Storage:
    """Base class for all storage backends."""

    def save(self, data: Any) -> None:
        """Persist data to the storage backend. Must be implemented by subclasses."""
        raise NotImplementedError

    def load(self) -> Any:
        """Load data from the storage backend. Must be implemented by subclasses."""
        raise NotImplementedError

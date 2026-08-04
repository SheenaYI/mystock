"""Download pipeline placeholder: Provider -> Downloader -> Storage.

Wires a DataProvider to a Storage backend. No download logic is
implemented yet — this only defines the shape of the pipeline.
"""

from __future__ import annotations

from mystock.data.provider import DataProvider
from mystock.data.storage import Storage


class Downloader:
    """Coordinates a DataProvider and a Storage backend."""

    def __init__(self, provider: DataProvider, storage: Storage) -> None:
        self.provider = provider
        self.storage = storage

    def run(self, *args, **kwargs) -> None:
        """Fetch data from the provider and save it via storage. Not implemented yet."""
        raise NotImplementedError

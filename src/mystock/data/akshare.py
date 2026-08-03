"""AKShare data provider placeholder.

Not implemented in this phase. Reserved for a future AKShareProvider
that implements the DataProvider interface using the akshare package.
"""

from __future__ import annotations

from mystock.data.provider import DataProvider


class AKShareProvider(DataProvider):
    """Placeholder for a future AKShare-backed data provider."""

    def fetch(self, *args, **kwargs):
        raise NotImplementedError("AKShare integration is not implemented yet.")

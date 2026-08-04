"""Base interface for research factors.

A factor turns a wide price panel into a same-shaped panel of scores
(higher = more attractive). No ranking, selection, or trading logic
lives here — that's the Strategy layer's job.
"""

from __future__ import annotations

import pandas as pd


class Factor:
    """Base class for all factors."""

    name: str = "factor"

    def compute(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Compute factor scores.

        `panel` is indexed by date, columned by symbol, valued by
        close price. Returns a same-shaped DataFrame of scores. Must
        be implemented by subclasses.
        """
        raise NotImplementedError

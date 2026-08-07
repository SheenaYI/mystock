"""Single source of truth for which factors are implemented.

`ExperimentDefinition` validation, the LLM intent-parsing prompt, and
the `mystock research factors` CLI command all read from
`FACTOR_REGISTRY` instead of each keeping their own copy of "what's
supported" — that duplication is exactly how a factor ends up
selectable in one place but not actually wired up in another.
"""

from __future__ import annotations

from research.factors.momentum_legacy import MomentumFactor

FACTOR_REGISTRY = {
    "momentum_20d": {
        "cls": MomentumFactor,
        "description": "20日动量：买入过去20个交易日涨幅最高的股票",
    },
}


class UnsupportedFactorError(Exception):
    """Raised when a request names a factor that isn't implemented."""

    def __init__(self, requested: str) -> None:
        self.requested = requested
        self.supported = list(FACTOR_REGISTRY)
        super().__init__(
            f"unsupported factor {requested!r}; "
            f"supported: {', '.join(self.supported)}"
        )

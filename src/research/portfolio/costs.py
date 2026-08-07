"""Explicit A-share transaction-friction assumptions."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CostModel:
    """Rates as decimal fractions; stamp duty applies only when selling."""

    commission: float = 0.0003
    transfer_fee: float = 0.00001
    sell_stamp_duty: float = 0.0005
    slippage: float = 0.0005

    def __post_init__(self) -> None:
        if any(value < 0 for value in (self.commission, self.transfer_fee, self.sell_stamp_duty, self.slippage)):
            raise ValueError("cost rates must be non-negative")

    @property
    def buy_fee(self) -> float:
        return self.commission + self.transfer_fee

    @property
    def sell_fee(self) -> float:
        return self.buy_fee + self.sell_stamp_duty

    def fee_schedule(self, signal_weights: pd.DataFrame) -> pd.DataFrame:
        """Assign buy/sell fees from each scheduled target-weight change."""
        targets = signal_weights.ffill().fillna(0.0)
        changes = targets.sub(targets.shift(1).fillna(0.0))
        scheduled = signal_weights.notna()
        return pd.DataFrame(
            np.where(changes.ge(0.0), self.buy_fee, self.sell_fee),
            index=signal_weights.index, columns=signal_weights.columns,
        ).where(scheduled).shift(1)

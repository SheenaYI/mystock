"""Validated company-action evidence used by factor and accounting layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite


@dataclass(frozen=True)
class CorporateAction:
    """A supported action with evidence visible before its use.

    Only cash dividends and share-ratio changes are supported in v1.  An
    unsupported or incomplete action must be rejected by the data adapter;
    inventing an adjustment would corrupt both factors and portfolio value.
    """

    action_id: str
    symbol: str
    action_type: str
    announced_at: datetime
    ex_date: date
    payment_date: date | None = None
    cash_per_share: float | None = None
    share_ratio: float | None = None
    evidence_id: str = ""

    def __post_init__(self) -> None:
        if not self.action_id or not self.symbol or not self.evidence_id:
            raise ValueError("action_id, symbol, and evidence_id are required")
        if self.announced_at.tzinfo is None or self.announced_at.utcoffset() is None:
            raise ValueError("announced_at must include timezone")
        if self.action_type == "cash_dividend":
            if self.payment_date is None or self.payment_date < self.ex_date:
                raise ValueError("cash dividend needs a payment date on/after ex-date")
            if self.cash_per_share is None or not isfinite(self.cash_per_share) or self.cash_per_share < 0:
                raise ValueError("cash dividend needs a finite non-negative cash_per_share")
            if self.share_ratio is not None:
                raise ValueError("cash dividend cannot have a share_ratio")
        elif self.action_type == "share_ratio_adjustment":
            if self.payment_date is not None or self.cash_per_share is not None:
                raise ValueError("share ratio action cannot have dividend fields")
            if self.share_ratio is None or not isfinite(self.share_ratio) or self.share_ratio <= 0:
                raise ValueError("share ratio action needs a positive share_ratio")
        else:
            raise ValueError("unsupported corporate action type")

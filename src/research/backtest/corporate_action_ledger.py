"""Auditable, fail-closed accounting transitions for supported company actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isclose
from typing import Literal, Mapping, Sequence

from research.backtest.corporate_actions import CorporateAction


@dataclass(frozen=True)
class CorporateActionRecord:
    action_id: str
    event_date: date
    phase: Literal["ex_date_open", "payment_date_close"]
    symbol: str
    status: Literal["applied", "rejected"]
    reason: str | None
    shares_before: int
    shares_after: int
    cash_before: float
    cash_after: float
    receivable_before: float
    receivable_after: float


@dataclass(frozen=True)
class LedgerState:
    """One-symbol state; shares are deliberately integer-only in v1."""

    shares: int
    cash: float
    receivables: Mapping[str, float] = field(default_factory=dict)
    opened_action_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.shares, bool) or not isinstance(self.shares, int) or self.shares < 0:
            raise ValueError("shares must be a non-negative integer")
        if self.cash < 0:
            raise ValueError("cash must be non-negative")
        if any(amount < 0 for amount in self.receivables.values()):
            raise ValueError("receivables must be non-negative")

    @property
    def dividend_receivable(self) -> float:
        return sum(self.receivables.values())


def apply_open_actions(
    state: LedgerState, *, symbol: str, event_date: date,
    actions: Sequence[CorporateAction], record_date_positions: Mapping[str, int],
) -> tuple[LedgerState, tuple[CorporateActionRecord, ...]]:
    """Apply share changes and establish dividend receivables before trading."""
    current = state
    records: list[CorporateActionRecord] = []
    for action in sorted((a for a in actions if a.symbol == symbol and a.ex_date == event_date), key=lambda a: a.action_id):
        before = current
        if action.action_id in current.opened_action_ids:
            records.append(_record(action, event_date, "ex_date_open", "rejected", "duplicate_action_id", before, current))
            continue
        receivables = dict(current.receivables)
        if action.action_type == "share_ratio_adjustment":
            assert action.share_ratio is not None
            shares = current.shares * action.share_ratio
            if not isclose(shares, round(shares), rel_tol=0.0, abs_tol=1e-9):
                raise ValueError("non_integral_share_result")
            current = LedgerState(int(round(shares)), current.cash, receivables, current.opened_action_ids | {action.action_id})
        else:
            position = record_date_positions.get(action.action_id)
            if isinstance(position, bool) or not isinstance(position, int) or position < 0:
                raise ValueError("cash dividend requires a non-negative integer record-date position")
            assert action.cash_per_share is not None
            receivables[action.action_id] = position * action.cash_per_share
            current = LedgerState(current.shares, current.cash, receivables, current.opened_action_ids | {action.action_id})
        records.append(_record(action, event_date, "ex_date_open", "applied", None, before, current))
    return current, tuple(records)


def apply_close_actions(
    state: LedgerState, *, symbol: str, event_date: date, actions: Sequence[CorporateAction],
) -> tuple[LedgerState, tuple[CorporateActionRecord, ...]]:
    """Settle only a dividend that was already recorded at its ex-date."""
    current = state
    records: list[CorporateActionRecord] = []
    for action in sorted((a for a in actions if a.symbol == symbol and a.payment_date == event_date), key=lambda a: a.action_id):
        before = current
        if action.action_id not in current.receivables:
            raise ValueError("unrecognized_dividend_receivable")
        receivables = dict(current.receivables)
        amount = receivables.pop(action.action_id)
        current = LedgerState(current.shares, current.cash + amount, receivables, current.opened_action_ids)
        records.append(_record(action, event_date, "payment_date_close", "applied", None, before, current))
    return current, tuple(records)


def _record(action, event_date, phase, status, reason, before, after) -> CorporateActionRecord:
    return CorporateActionRecord(
        action_id=action.action_id, event_date=event_date, phase=phase, symbol=action.symbol,
        status=status, reason=reason, shares_before=before.shares, shares_after=after.shares,
        cash_before=before.cash, cash_after=after.cash,
        receivable_before=before.dividend_receivable, receivable_after=after.dividend_receivable,
    )

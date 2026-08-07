"""Fail-closed A-share execution ledger for the formal research path.

This intentionally small engine is used instead of a percentage-only vector
backtest when the research contract requires auditable cash and integer-share
states.  It models target weights at the next open and values the resulting
positions at that day's close.  It is not a claim to reproduce exchange order
books: missing/invalid tradability evidence is rejected rather than filled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd

from research.backtest.corporate_actions import CorporateAction
from research.backtest.engine import BacktestEngine, BacktestResult, MarketPrices
from research.backtest.vectorbt_engine import ExecutionDataError, next_open_orders
from research.portfolio.costs import CostModel


@dataclass(frozen=True)
class ExecutionPolicy:
    """Frozen execution constraints supported by the available daily data."""

    lot_size: int = 100
    reject_missing_open: bool = True
    unknown_tradability: str = "fail"
    missing_valuation: str = "fail"

    def __post_init__(self) -> None:
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")
        if self.unknown_tradability not in {"fail", "block"}:
            raise ValueError("unknown_tradability must be 'fail' or 'block'")
        if self.missing_valuation not in {"fail", "carry_last"}:
            raise ValueError("missing_valuation must be 'fail' or 'carry_last'")


class LotLedgerEngine(BacktestEngine):
    """Next-open, close-valued, integer-lot cash and position ledger."""

    def __init__(self, *, init_cash: float = 1_000_000.0,
                 policy: ExecutionPolicy = ExecutionPolicy()) -> None:
        self.init_cash = init_cash
        self.policy = policy

    def run(self, prices: MarketPrices, weights: pd.DataFrame, costs: CostModel,
            actions: Sequence[CorporateAction] = ()) -> BacktestResult:
        orders = next_open_orders(
            weights, prices.execution_open,
            reject_invalid=self.policy.unknown_tradability == "fail",
        )
        open_prices = prices.execution_open
        close_prices = prices.valuation_close
        tradability = prices.tradability
        if not weights.index.equals(open_prices.index) or not weights.columns.equals(open_prices.columns):
            raise ExecutionDataError("weights and price panels must align")

        actions_by_date: dict[date, list[CorporateAction]] = {}
        for action in actions:
            actions_by_date.setdefault(action.ex_date, []).append(action)

        cash = float(self.init_cash)
        shares = {symbol: 0 for symbol in weights.columns}
        receivables: dict[str, float] = {}
        records: list[dict] = []
        values: list[float] = []
        last_close: dict[str, float] = {}

        for session in weights.index:
            today = pd.Timestamp(session).date()
            # Ex-date changes occur before this session's open.  Dividends
            # require an explicit payment date; their record-date proxy is
            # the prior close position because current source evidence lacks a
            # separate record-date field.  This limitation is documented in
            # the contract and is not used to make factor prices adjusted.
            for action in actions_by_date.get(today, []):
                if action.announced_at.date() > today:
                    raise ExecutionDataError(f"company action announced after ex-date: {action.action_id}")
                before = shares[action.symbol]
                if action.action_type == "share_ratio_adjustment":
                    changed = before * float(action.share_ratio)
                    if not np.isclose(changed, round(changed)):
                        raise ExecutionDataError(f"non-integral company-action shares: {action.action_id}")
                    shares[action.symbol] = int(round(changed))
                    records.append({"date": session, "symbol": action.symbol, "kind": "corporate_action",
                                    "action_id": action.action_id, "shares": shares[action.symbol], "cash": 0.0})
                else:
                    receivables[action.action_id] = before * float(action.cash_per_share)

            # The available action adapter only permits payment >= ex-date.
            for action in actions:
                if action.action_type == "cash_dividend" and action.payment_date == today:
                    amount = receivables.pop(action.action_id, None)
                    if amount is None:
                        raise ExecutionDataError(f"unrecognized dividend receivable: {action.action_id}")
                    cash += amount
                    records.append({"date": session, "symbol": action.symbol, "kind": "dividend_payment",
                                    "action_id": action.action_id, "shares": shares[action.symbol], "cash": amount})

            targets = orders.loc[session]
            if targets.notna().any():
                opening_value = cash + sum(
                    shares[s] * (
                        float(open_prices.loc[session, s])
                        if pd.notna(open_prices.loc[session, s]) and np.isfinite(open_prices.loc[session, s])
                        else last_close.get(s, np.nan)
                    )
                    for s in shares if shares[s] > 0
                )
                # Sell first; each target is an absolute portfolio fraction.
                desired = {}
                for symbol, target in targets.dropna().items():
                    raw_price = open_prices.loc[session, symbol]
                    if pd.isna(raw_price) or not np.isfinite(raw_price) or float(raw_price) <= 0:
                        if self.policy.unknown_tradability == "fail":
                            raise ExecutionDataError(
                                f"cannot execute requested order: missing/invalid open for {symbol} on {today}"
                            )
                        records.append({"date": session, "symbol": symbol,
                                        "kind": "blocked_missing_open", "shares": 0,
                                        "cash": 0.0})
                        continue
                    price = float(raw_price)
                    desired[symbol] = int(np.floor((opening_value * float(target)) / price / self.policy.lot_size)) * self.policy.lot_size
                for symbol, target_shares in desired.items():
                    delta = target_shares - shares[symbol]
                    if delta == 0:
                        continue
                    if tradability is not None:
                        paused = tradability["paused"].loc[session, symbol]
                        high_limit = tradability["high_limit"].loc[session, symbol]
                        low_limit = tradability["low_limit"].loc[session, symbol]
                        if pd.isna(paused) or pd.isna(high_limit) or pd.isna(low_limit):
                            if self.policy.unknown_tradability == "fail":
                                raise ExecutionDataError(
                                    f"missing tradability evidence for {symbol} on {today}"
                                )
                            records.append({"date": session, "symbol": symbol,
                                            "kind": "blocked_missing_tradability", "shares": abs(delta),
                                            "cash": 0.0})
                            continue
                        if bool(paused):
                            records.append({"date": session, "symbol": symbol,
                                            "kind": "blocked_paused", "shares": abs(delta),
                                            "cash": 0.0})
                            continue
                        price = float(open_prices.loc[session, symbol])
                        if delta > 0 and np.isclose(price, float(high_limit), rtol=0.0, atol=1e-6):
                            records.append({"date": session, "symbol": symbol,
                                            "kind": "blocked_limit_up", "shares": delta,
                                            "cash": 0.0})
                            continue
                        if delta < 0 and np.isclose(price, float(low_limit), rtol=0.0, atol=1e-6):
                            records.append({"date": session, "symbol": symbol,
                                            "kind": "blocked_limit_down", "shares": -delta,
                                            "cash": 0.0})
                            continue
                    if delta >= 0:
                        continue
                    price = float(open_prices.loc[session, symbol]) * (1.0 - costs.slippage)
                    proceeds = (-delta) * price * (1.0 - costs.sell_fee)
                    cash += proceeds
                    shares[symbol] = target_shares
                    records.append({"date": session, "symbol": symbol, "kind": "sell", "shares": -delta,
                                    "price": price, "cash": proceeds})
                for symbol, target_shares in desired.items():
                    delta = target_shares - shares[symbol]
                    if delta <= 0:
                        continue
                    price = float(open_prices.loc[session, symbol]) * (1.0 + costs.slippage)
                    spend = delta * price * (1.0 + costs.buy_fee)
                    # A target derived before realised sell costs may exceed
                    # cash by a few yuan.  Buy the largest valid whole-lot
                    # amount; do not create margin or fractional shares.
                    affordable = int(np.floor(cash / (price * (1.0 + costs.buy_fee)) / self.policy.lot_size)) * self.policy.lot_size
                    filled = min(delta, max(0, affordable))
                    if filled:
                        outlay = filled * price * (1.0 + costs.buy_fee)
                        cash -= outlay
                        shares[symbol] += filled
                        records.append({"date": session, "symbol": symbol, "kind": "buy", "shares": filled,
                                        "price": price, "cash": -outlay})
            close_row = close_prices.loc[session]
            held = [symbol for symbol, quantity in shares.items() if quantity > 0]
            invalid_held = [
                symbol for symbol in held
                if pd.isna(close_row[symbol]) or not np.isfinite(close_row[symbol]) or float(close_row[symbol]) <= 0
            ]
            if invalid_held:
                if self.policy.missing_valuation == "fail":
                    raise ExecutionDataError(
                        f"cannot value held position: missing/invalid close for {invalid_held[0]} on {today}"
                    )
                for symbol in invalid_held:
                    if symbol not in last_close:
                        raise ExecutionDataError(
                            f"cannot conservatively value position without prior close for {symbol} on {today}"
                        )
                    records.append({"date": session, "symbol": symbol,
                                    "kind": "blocked_missing_valuation", "shares": shares[symbol],
                                    "valuation_price": last_close[symbol], "cash": 0.0})
            for symbol in held:
                if symbol not in invalid_held:
                    last_close[symbol] = float(close_row[symbol])
            values.append(cash + sum(
                shares[s] * (last_close[s] if s in invalid_held else float(close_row[s]))
                for s in held
            ))

        value = pd.Series(values, index=weights.index, name="value")
        returns = value.pct_change().fillna(0.0)
        return BacktestResult(returns=returns, value=value, trades=pd.DataFrame(records))

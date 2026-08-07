"""Regression tests that prevent same-close execution and price filling."""

import numpy as np
import pandas as pd
import pytest

from research.backtest.vectorbt_engine import ExecutionDataError, next_open_orders


def _frame(values):
    return pd.DataFrame(values, index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]), columns=["600000.SH"])


def test_close_signal_is_sent_to_the_following_open_only():
    signals = _frame([[1.0], [np.nan], [0.0]])
    opens = _frame([[10.0], [10.2], [10.4]])
    orders = next_open_orders(signals, opens)
    assert pd.isna(orders.iloc[0, 0])
    assert orders.iloc[1, 0] == 1.0
    assert pd.isna(orders.iloc[2, 0])


def test_missing_next_open_is_a_failure_not_a_forward_fill():
    signals = _frame([[1.0], [np.nan], [np.nan]])
    opens = _frame([[10.0], [np.nan], [10.4]])
    with pytest.raises(ExecutionDataError, match="cannot execute requested order"):
        next_open_orders(signals, opens)

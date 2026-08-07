import pandas as pd

from research.portfolio.costs import CostModel


def test_cost_model_charges_stamp_duty_only_on_a_target_sell():
    signals = pd.DataFrame({"AAA": [1.0, float("nan"), 0.0, float("nan")]}, index=pd.date_range("2024-01-02", periods=4, freq="B"))
    fees = CostModel().fee_schedule(signals)
    assert fees.iloc[1, 0] == CostModel().buy_fee
    assert fees.iloc[3, 0] == CostModel().sell_fee

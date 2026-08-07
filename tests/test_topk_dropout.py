import pandas as pd

from research.portfolio.topk_dropout import TopKDropoutStrategy


def test_topk_dropout_replaces_at_most_n_drop_incumbents():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    scores = pd.DataFrame(
        [[10, 9, 8, 7, 6, 5], [1, 2, 3, 4, 10, 9]],
        index=dates, columns=list("ABCDEF"),
    )
    weights = TopKDropoutStrategy(top_k=4, n_drop=2).build_weights(scores, rebalance_days=1)
    first = set(weights.loc[dates[0]].dropna()[lambda x: x > 0].index)
    second = set(weights.loc[dates[1]].dropna()[lambda x: x > 0].index)
    assert first == set("ABCD")
    assert second == set("CDEF")
    assert weights.loc[dates[1], "A"] == 0
    assert weights.loc[dates[1], "B"] == 0


def test_topk_dropout_skips_empty_warmup_before_first_position():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    scores = pd.DataFrame([[float("nan")] * 10, range(10)], index=dates, columns=[f"S{i}" for i in range(10)])
    weights = TopKDropoutStrategy().build_weights(scores, rebalance_days=1)
    assert weights.loc[dates[0]].isna().all()
    assert (weights.loc[dates[1]].dropna() == 0.1).all()

import pandas as pd

from research.llm.literature_registry import retrieve_literature_as_of


def test_retrieval_is_date_bounded_and_state_relevant():
    results = retrieve_literature_as_of(
        as_of=pd.Timestamp("2024-01-20"),
        state="S2_stress",
        candidates=("drawdown_60", "illiquidity_20", "market_corr_60"),
    )
    assert results
    assert all(pd.Timestamp(item["published_on"]) <= pd.Timestamp("2024-01-20") for item in results)
    assert any("risk" in item["supported_categories"] for item in results)
    assert all(item["registry_version"] == "s3-next-literature-v1" for item in results)


def test_retrieval_does_not_require_a_live_network_call():
    assert retrieve_literature_as_of(
        as_of=pd.Timestamp("2024-01-20"),
        state="S3_range_or_uncertain",
        candidates=("reversal_5",),
    )

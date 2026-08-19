from pathlib import Path

from research.llm.historical_context import HistoricalContext, append_context, load_context_as_of, search_queries


def test_context_archive_filters_after_cutoff(tmp_path: Path):
    path = tmp_path / "historical_context.jsonl"
    append_context(path, [
        HistoricalContext(
            title="before", url="https://example.test/before",
            published_at="2024-01-10T10:00:00+08:00", source="fixture",
        ),
        HistoricalContext(
            title="after", url="https://example.test/after",
            published_at="2024-01-11T10:00:00+08:00", source="fixture",
        ),
    ])
    records = load_context_as_of(path, cutoff_date="2024-01-10")
    assert [item["title"] for item in records] == ["before"]


def test_context_query_batch_has_a_frozen_limit():
    class Stub:
        def search(self, query, *, cutoff_date):
            return []

    try:
        search_queries(Stub(), ["a", "b", "c"], cutoff_date="2024-01-10")
    except ValueError as exc:
        assert "at most 2" in str(exc)
    else:
        raise AssertionError("query limit was not enforced")

import json

from research.llm import live_literature


def test_live_literature_snapshots_result_and_replays_cache(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_fetch(url: str, *, timeout_seconds: float = 12.0):
        calls.append(url)
        return {
            "message": {"items": [{
                "title": ["Momentum and volatility"],
                "DOI": "10.1234/example",
                "issued": {"date-parts": [[2020, 3, 1]]},
            }]}
        }

    monkeypatch.setattr(live_literature, "_fetch_json", fake_fetch)
    first = live_literature.retrieve_live_literature(
        as_of="2024-01-05", state="S2_stress", cache_root=tmp_path,
    )
    second = live_literature.retrieve_live_literature(
        as_of="2024-01-05", state="S2_stress", cache_root=tmp_path,
    )
    snapshot = json.loads((tmp_path / "2024-01-05_S2_stress.json").read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert first == second
    assert first[0]["source_id"] == "crossref:10.1234/example"
    assert snapshot["non_pit_notice"]
    assert snapshot["snapshot_sha256"]


def test_live_literature_records_failure_without_blocking(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        live_literature, "_fetch_json",
        lambda url, *, timeout_seconds=12.0: (_ for _ in ()).throw(TimeoutError("offline")),
    )
    result = live_literature.retrieve_live_literature(
        as_of="2024-01-05", state="S1_trend", cache_root=tmp_path,
    )
    snapshot = json.loads((tmp_path / "2024-01-05_S1_trend.json").read_text(encoding="utf-8"))
    assert result == []
    assert "TimeoutError" in snapshot["error"]

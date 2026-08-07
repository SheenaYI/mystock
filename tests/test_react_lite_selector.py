from pathlib import Path

import pytest

from research.llm.react_lite import ReActLiteSelector


def test_offline_fixture_is_bounded_and_logged(tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    selector = ReActLiteSelector(log, use_llm=False, max_rounds=3)
    decision = selector.decide(
        decision_id="fixture-1",
        state="S0_insufficient_evidence",
        evidence={"decision_date": "2025-01-02"},
        candidates=("drawdown_60", "illiquidity_20"),
        current_factors=("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range"),
    )
    assert decision.action == "abstain"
    assert decision.rounds == 1
    record = log.read_text(encoding="utf-8").strip().splitlines()[0]
    assert '"decision_id": "fixture-1"' in record
    assert '"consumes_trial_id": false' in record


def test_invalid_real_outputs_fail_after_frozen_round_limit(tmp_path: Path, monkeypatch) -> None:
    selector = ReActLiteSelector(tmp_path / "calls.jsonl", use_llm=False, max_rounds=2)
    monkeypatch.setattr(selector, "_chat", lambda prompt: '{"action":"bad"}')
    selector.use_llm = True
    with pytest.raises(RuntimeError, match="selection_failed"):
        selector.decide(
            decision_id="fixture-failed",
            state="S1_trend",
            evidence={"decision_date": "2025-01-02"},
            candidates=("drawdown_60",),
            current_factors=("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range"),
        )
    lines = (tmp_path / "calls.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert all('"output_kind": "failure"' in line for line in lines[:2])
    assert '"output_kind": "selection_failed"' in lines[-1]


def test_add_drop_replace_actions_apply_to_current_recipe(tmp_path: Path, monkeypatch) -> None:
    selector = ReActLiteSelector(tmp_path / "calls.jsonl", use_llm=False)
    base = ("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range")
    monkeypatch.setattr(
        selector, "_chat",
        lambda prompt: '{"action":"replace","replace":[{"drop":"ma_gap_20","add":"drawdown_60"}],"reason":"互补证据"}',
    )
    selector.use_llm = True
    decision = selector.decide(
        decision_id="replace-1", state="S2_stress", evidence={"correlation_clusters": []},
        candidates=("drawdown_60",), current_factors=base,
    )
    assert "ma_gap_20" not in decision.selected
    assert "drawdown_60" in decision.selected
    assert len(decision.selected) == 7


def test_baseline_cluster_is_grandfathered_but_new_conflict_is_rejected(tmp_path: Path) -> None:
    selector = ReActLiteSelector(tmp_path / "calls.jsonl", use_llm=False)
    base = ("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range")
    selector._validate_recipe(
        base,
        {"base_factors": list(base), "correlation_clusters": [["ma_gap_20", "return_20"]]},
    )
    with pytest.raises(ValueError, match="correlation cluster"):
        selector._validate_recipe(
            base + ("reversal_5",),
            {"base_factors": list(base), "correlation_clusters": [["return_5", "reversal_5"]]},
        )

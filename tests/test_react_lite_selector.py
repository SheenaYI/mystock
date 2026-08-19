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
    evidence = {
        "portfolio_marginal_evidence": {
            "drawdown_60": {
                "factor_evidence_stable": True,
                "state_factor_evidence_stable": True,
                "qualifying_folds": 2,
                "state_qualifying_folds": 2,
                "portfolio_marginal_improvement": True,
                "risk_cost_ok": True,
                "state_portfolio_marginal_improvement": True,
                "state_risk_cost_ok": True,
            }
        }
    }
    with pytest.raises(RuntimeError, match="selection_failed"):
        selector.decide(
            decision_id="fixture-failed",
            state="S1_trend",
            evidence={"decision_date": "2025-01-02", **evidence},
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
    evidence = {
        "correlation_clusters": [],
        "portfolio_marginal_evidence": {
            "drawdown_60": {
                "factor_evidence_stable": True,
                "state_factor_evidence_stable": True,
                "qualifying_folds": 2,
                "state_qualifying_folds": 2,
                "portfolio_marginal_improvement": True,
                "risk_cost_ok": True,
                "state_portfolio_marginal_improvement": True,
                "state_risk_cost_ok": True,
            }
        },
    }
    decision = selector.decide(
        decision_id="replace-1", state="S2_stress", evidence=evidence,
        candidates=("drawdown_60",), current_factors=base,
    )
    assert "ma_gap_20" not in decision.selected
    assert "drawdown_60" in decision.selected
    assert len(decision.selected) == 7


def test_missing_portfolio_marginal_evidence_defaults_to_abstain(tmp_path: Path, monkeypatch) -> None:
    selector = ReActLiteSelector(tmp_path / "calls.jsonl", use_llm=False)
    monkeypatch.setattr(
        selector, "_chat",
        lambda prompt: '{"action":"add","add":["drawdown_60"],"reason":"正 IC"}',
    )
    selector.use_llm = True
    base = ("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range")
    decision = selector.decide(
        decision_id="gate-1", state="S1_trend", evidence={},
        candidates=("drawdown_60",), current_factors=base,
    )
    assert decision.action == "abstain"
    assert decision.selected == base
    assert decision.reason == "no_clear_portfolio_marginal_improvement"


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


def test_s3_next_requires_a_retrieved_literature_reference(tmp_path: Path, monkeypatch) -> None:
    selector = ReActLiteSelector(
        tmp_path / "calls.jsonl", use_llm=False,
        prompt_version="react_factor_selector_s3_next_v1.0.0",
        require_literature_refs=True,
    )
    monkeypatch.setattr(
        selector, "_chat",
        lambda prompt: '{"action":"add","add":["drawdown_60"],"reason":"组合改善","literature_refs":["amihud_2002"]}',
    )
    selector.use_llm = True
    base = ("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range")
    evidence = {
        "frozen_literature": [{"source_id": "amihud_2002"}],
        "correlation_clusters": [],
        "portfolio_marginal_evidence": {
            "drawdown_60": {
                "factor_evidence_stable": True, "state_factor_evidence_stable": True,
                "qualifying_folds": 2, "state_qualifying_folds": 2,
                "portfolio_marginal_improvement": True, "risk_cost_ok": True,
                "state_portfolio_marginal_improvement": True, "state_risk_cost_ok": True,
            }
        },
    }
    decision = selector.decide(
        decision_id="s3-next-1", state="S2_stress", evidence=evidence,
        candidates=("drawdown_60",), current_factors=base,
    )
    assert decision.action == "add"
    assert '"prompt_version": "react_factor_selector_s3_next_v1.0.0"' in (tmp_path / "calls.jsonl").read_text()


def test_s4_requires_coverage_and_economic_rationale(tmp_path: Path, monkeypatch) -> None:
    selector = ReActLiteSelector(
        tmp_path / "calls.jsonl", use_llm=False,
        enforce_marginal_evidence=False, require_economic_rationales=True,
        require_literature_refs=False,
    )
    monkeypatch.setattr(
        selector, "_chat",
        lambda prompt: (
            '{"action":"add","add":["drawdown_60"],"reason":"压力期风险压力",'
            '"factor_rationales":[{"factor":"drawdown_60","economic_meaning":"回撤压力",'
            '"state_relevance":"高风险状态","coverage":"100%","non_redundancy":"不同于趋势"}]}'
        ),
    )
    selector.use_llm = True
    base = ("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range")
    evidence = {
        "factor_evidence": {"drawdown_60": {"coverage_current": 1.0}},
        "correlation_clusters": [],
    }
    decision = selector.decide(
        decision_id="s4-1", state="S2_stress", evidence=evidence,
        candidates=("drawdown_60",), current_factors=base,
    )
    assert decision.action == "add"
    prompt = selector._prompt(
        evidence=evidence, state="S2_stress", candidates=("drawdown_60",), current_factors=base,
    )
    assert "经济意义" in prompt
    assert "覆盖率不低于 95%" in prompt
    assert "强相关簇" in prompt


def test_s4_allows_drop_without_literature_or_marginal_gate(tmp_path: Path, monkeypatch) -> None:
    """S4 can test a leaner recipe; S3's strict drop gate remains elsewhere."""
    selector = ReActLiteSelector(
        tmp_path / "calls.jsonl", use_llm=False,
        enforce_marginal_evidence=False, require_economic_rationales=True,
        require_literature_refs=False,
    )
    monkeypatch.setattr(
        selector, "_chat",
        lambda prompt: '{"action":"drop","drop":["ma_gap_20"],"reason":"当前状态下减少与动量重复的均线偏离"}',
    )
    selector.use_llm = True
    base = ("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range")
    decision = selector.decide(
        decision_id="s4-drop", state="S3_range_or_uncertain",
        evidence={"factor_evidence": {"drawdown_60": {"coverage_current": 1.0}}, "correlation_clusters": []},
        candidates=("drawdown_60",), current_factors=base,
    )
    assert decision.action == "drop"
    assert "ma_gap_20" not in decision.selected


def test_optional_live_literature_reference_must_be_from_snapshot(tmp_path: Path, monkeypatch) -> None:
    selector = ReActLiteSelector(
        tmp_path / "calls.jsonl", use_llm=False, enforce_marginal_evidence=False,
    )
    monkeypatch.setattr(
        selector, "_chat",
        lambda prompt: '{"action":"add","add":["drawdown_60"],"reason":"风险互补",'
        '"literature_refs":["not-in-snapshot"]}',
    )
    selector.use_llm = True
    base = ("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range")
    with pytest.raises(RuntimeError, match="selection_failed"):
        selector.decide(
            decision_id="s4-web-invalid-ref", state="S2_stress",
            evidence={
                "factor_evidence": {"drawdown_60": {"coverage_current": 1.0}},
                "live_literature": [{"source_id": "crossref:real-result"}],
                "correlation_clusters": [],
            },
            candidates=("drawdown_60",), current_factors=base,
        )


def test_s4_abstains_when_candidate_is_not_covered(tmp_path: Path) -> None:
    selector = ReActLiteSelector(
        tmp_path / "calls.jsonl", use_llm=False, enforce_marginal_evidence=False,
    )
    base = ("return_5", "return_20", "return_60", "ma_gap_20", "volatility_20", "volume_ratio_20", "intraday_range")
    decision = selector.decide(
        decision_id="s4-coverage", state="S1_trend",
        evidence={"factor_evidence": {"drawdown_60": {"coverage_current": 0.94}}},
        candidates=("drawdown_60",), current_factors=base,
    )
    assert decision.action == "abstain"
    assert decision.reason == "no_candidate_with_95%_active_universe_coverage"

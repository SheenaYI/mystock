from research.audit import action_diff, factor_gate_rows, summarise_factor_gates


def _evidence():
    return {
        "decision_date": "2024-01-19", "current_state": "S2_stress",
        "candidate_names": ["drawdown_60"], "candidate_coverage": {"drawdown_60": 1.0},
        "base_factors": ["return_5"], "correlation_clusters": [],
        "factor_evidence": {"drawdown_60": {"mean_rank_ic": 0.02, "state_rank_ic": {"S2_stress": {"mean_rank_ic": 0.03}}}},
        "portfolio_marginal_evidence": {"drawdown_60": {
            "factor_evidence_stable": True, "state_factor_evidence_stable": True,
            "qualifying_folds": 2, "state_qualifying_folds": 2,
            "portfolio_marginal_improvement": True, "risk_cost_ok": True,
            "state_portfolio_marginal_improvement": True, "state_risk_cost_ok": True,
        }},
    }


def test_gate_audit_expands_evidence_and_summarises(tmp_path):
    (tmp_path / "2024-01-19.json").write_text(__import__("json").dumps(_evidence()), encoding="utf-8")
    calls = {"factor-selection-2024-01-19": {"output_kind": "add", "output": {"add": ["drawdown_60"]}}}
    rows = factor_gate_rows(profile="S3", evidence_dir=tmp_path, calls=calls)
    assert rows.loc[0, "gate_eligible"]
    assert rows.loc[0, "llm_selected"]
    summary = summarise_factor_gates(rows)
    assert summary.loc[0, "eligible_count"] == 1
    assert summary.loc[0, "selected_count"] == 1


def test_action_diff_marks_equal_recipes():
    left = {"factor-selection-2024-01-19": {"output_kind": "add", "output": {"add": ["drawdown_60"]}}}
    right = {"factor-selection-2024-01-19": {"output_kind": "add", "output": {"add": ["drawdown_60"], "literature_refs": ["source"]}}}
    diff = action_diff(left, right)
    assert diff.loc[0, "same_action"]
    assert diff.loc[0, "same_extensions"]

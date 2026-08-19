from dataclasses import replace

import json

import pytest

from research.contracts.experiment import (
    FrozenExperiment, PortfolioContract, ProtocolContract, build_evidence_contract,
)
from research.experiment import ExperimentLog
from research.pipeline import _factor_selection_namespace


def test_contract_hash_changes_when_a_method_parameter_changes():
    base = FrozenExperiment()
    changed = replace(base, portfolio=PortfolioContract(top_k=20, n_drop=5))
    assert base.contract_hash != changed.contract_hash
    assert len(base.contract_hash) == 64


def test_m0_has_a_distinct_frozen_profile_name():
    assert FrozenExperiment(profile="m0").factor_name == "technical_m0_return_20_direct"


def test_s3_next_has_a_distinct_challenger_profile_name():
    assert FrozenExperiment(profile="s3_next").factor_name == "technical_s3_next_literature_challenger"


def test_s4_has_a_distinct_exploratory_profile_name():
    assert FrozenExperiment(profile="s4").factor_name == "technical_s4_w1_economic_coverage_n5"
    assert FrozenExperiment(profile="s4_n2").factor_name == "technical_s4_w1_economic_coverage_n2"


def test_protocol_requires_independent_clocks_to_align_on_rebalances():
    weekly = ProtocolContract(horizon=5, rebalance_days=5, model_retrain_days=20, factor_decision_days=20)
    assert weekly.model_retrain_days == 20
    with pytest.raises(ValueError, match="whole number"):
        ProtocolContract(rebalance_days=5, model_retrain_days=12)


def test_weekly_s4_turnover_profiles_share_one_factor_selection_namespace():
    protocol = ProtocolContract(horizon=5, rebalance_days=5, model_retrain_days=20, factor_decision_days=20)
    n5 = FrozenExperiment(profile="s4", protocol=protocol)
    n2 = FrozenExperiment(profile="s4_n2", protocol=protocol, portfolio=PortfolioContract(n_drop=2))
    assert n5.contract_hash != n2.contract_hash
    assert _factor_selection_namespace(n5) == _factor_selection_namespace(n2)


def test_formal_experiment_rejects_unresolved_evidence():
    with pytest.raises(ValueError, match="unresolved evidence"):
        FrozenExperiment().require_resolved_evidence()


def test_evidence_contract_hashes_each_required_manifest(tmp_path):
    raw = tmp_path / "ohlcv"
    (raw / "manifests").mkdir(parents=True)
    ohlcv = raw / "manifests" / "ohlcv.json"
    membership = tmp_path / "membership.json"
    actions = tmp_path / "actions.json"
    implementation = tmp_path / "implementation"
    implementation.mkdir()
    (implementation / "pipeline.py").write_text("# fixture\n", encoding="utf-8")
    for path in (ohlcv, membership, actions):
        path.write_text(json.dumps({"fixture": path.name}), encoding="utf-8")
    evidence = build_evidence_contract(
        raw_root=raw, membership_manifest=membership,
        corporate_action_manifest=actions,
        implementation_root=implementation,
    )
    assert evidence.resolved
    assert len(evidence.ohlcv_manifest_sha256) == 64


def test_experiment_log_writes_replayable_contract_hash(tmp_path):
    log = ExperimentLog(tmp_path / "runs.jsonl")
    experiment = FrozenExperiment()
    log.append(experiment, {"fixture": True}, phase="test")
    record = json.loads(log.path.read_text(encoding="utf-8"))
    assert record["contract_hash"] == experiment.contract_hash

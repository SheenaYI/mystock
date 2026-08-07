from dataclasses import replace

import json

import pytest

from research.contracts.experiment import (
    FrozenExperiment, PortfolioContract, build_evidence_contract,
)
from research.experiment import ExperimentLog


def test_contract_hash_changes_when_a_method_parameter_changes():
    base = FrozenExperiment()
    changed = replace(base, portfolio=PortfolioContract(top_k=20, n_drop=5))
    assert base.contract_hash != changed.contract_hash
    assert len(base.contract_hash) == 64


def test_m0_has_a_distinct_frozen_profile_name():
    assert FrozenExperiment(profile="m0").factor_name == "technical_m0_return_20_direct"


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

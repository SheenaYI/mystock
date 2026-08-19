"""Read-only audits for cached factor-selection evidence."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from research.factors.catalog import FACTOR_CATEGORIES


GATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("factor_evidence_stable", "overall_factor_evidence"),
    ("state_factor_evidence_stable", "state_factor_evidence"),
    ("qualifying_folds", "overall_two_fold_portfolio"),
    ("state_qualifying_folds", "state_two_fold_portfolio"),
    ("portfolio_marginal_improvement", "overall_portfolio_improvement"),
    ("risk_cost_ok", "overall_risk_cost"),
    ("state_portfolio_marginal_improvement", "state_portfolio_improvement"),
    ("state_risk_cost_ok", "state_risk_cost"),
)


def find_evidence_cache(root: Path, prompt_version: str) -> Path:
    """Find the populated cache namespace for a frozen selector version."""
    candidates = [
        path for path in Path(root).glob(f"*{prompt_version}")
        if path.is_dir() and any(path.glob("*.json"))
    ]
    if not candidates:
        raise FileNotFoundError(f"no populated evidence cache for {prompt_version}")
    return max(candidates, key=lambda path: max(item.stat().st_mtime for item in path.glob("*.json")))


def load_calls(log_path: Path, prompt_version: str) -> dict[str, dict[str, Any]]:
    """Return one logged LLM output per decision id for a selector version."""
    records: dict[str, dict[str, Any]] = {}
    for line in Path(log_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("prompt_version") != prompt_version:
            continue
        if item.get("output_kind") in {"add", "drop", "replace", "abstain"}:
            records[str(item["decision_id"])] = item
    return records


def _changed_factors(output: dict[str, Any]) -> set[str]:
    changed = set(output.get("add") or [])
    for replacement in output.get("replace") or []:
        if isinstance(replacement, dict) and isinstance(replacement.get("add"), str):
            changed.add(replacement["add"])
    return changed


def _failed_gates(item: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    for field, label in GATE_FIELDS:
        value = item.get(field)
        passed = int(value or 0) >= 2 if field.endswith("qualifying_folds") else value is True
        if not passed:
            failed.append(label)
    return failed


def _base_cluster_conflict(candidate: str, evidence: dict[str, Any]) -> bool:
    base = set(evidence.get("base_factors", []))
    return any(candidate in cluster and bool(base.intersection(cluster)) for cluster in evidence.get("correlation_clusters", []))


def factor_gate_rows(
    *,
    profile: str,
    evidence_dir: Path,
    calls: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    """Expand each cached decision into one row per candidate factor."""
    rows: list[dict[str, Any]] = []
    for path in sorted(Path(evidence_dir).glob("*.json")):
        evidence = json.loads(path.read_text(encoding="utf-8"))
        date = str(evidence.get("decision_date") or path.stem)
        call = calls.get(f"factor-selection-{date}", {})
        output = call.get("output", {}) if isinstance(call.get("output"), dict) else {}
        changed = _changed_factors(output)
        marginal = evidence.get("portfolio_marginal_evidence", {})
        factor_data = evidence.get("factor_evidence", {})
        for factor in evidence.get("candidate_names", sorted(marginal)):
            item = marginal.get(factor, {})
            failures = _failed_gates(item) if item else ["missing_portfolio_evidence"]
            factor_evidence = factor_data.get(factor, {})
            state_evidence = factor_evidence.get("state_rank_ic", {}).get(evidence.get("current_state"), {})
            rows.append({
                "profile": profile,
                "decision_date": date,
                "state": evidence.get("current_state"),
                "factor": factor,
                "category": FACTOR_CATEGORIES.get(factor, "unregistered"),
                "coverage_current": evidence.get("candidate_coverage", {}).get(factor),
                "mean_rank_ic": factor_evidence.get("mean_rank_ic"),
                "state_mean_rank_ic": state_evidence.get("mean_rank_ic"),
                "factor_stable_folds": item.get("factor_stable_folds"),
                "state_factor_stable_folds": item.get("state_factor_stable_folds"),
                "qualifying_folds": item.get("qualifying_folds"),
                "state_qualifying_folds": item.get("state_qualifying_folds"),
                "portfolio_marginal_improvement": item.get("portfolio_marginal_improvement"),
                "state_portfolio_marginal_improvement": item.get("state_portfolio_marginal_improvement"),
                "risk_cost_ok": item.get("risk_cost_ok"),
                "state_risk_cost_ok": item.get("state_risk_cost_ok"),
                "base_cluster_conflict": _base_cluster_conflict(factor, evidence),
                "gate_eligible": not failures,
                "failed_gates": ";".join(failures),
                "llm_action": call.get("output_kind", "missing_log"),
                "llm_selected": factor in changed,
                "literature_refs": ";".join(output.get("literature_refs") or []),
            })
    return pd.DataFrame(rows)


def summarise_factor_gates(rows: pd.DataFrame) -> pd.DataFrame:
    """Summarise gate and selection outcomes by profile and factor."""
    records: list[dict[str, Any]] = []
    for (profile, factor, category), group in rows.groupby(["profile", "factor", "category"], sort=True):
        failures = Counter(
            failure for value in group["failed_gates"] for failure in str(value).split(";") if failure
        )
        record: dict[str, Any] = {
            "profile": profile,
            "factor": factor,
            "category": category,
            "evaluations": len(group),
            "eligible_count": int(group["gate_eligible"].sum()),
            "selected_count": int(group["llm_selected"].sum()),
            "median_coverage": group["coverage_current"].median(),
            "median_rank_ic": group["mean_rank_ic"].median(),
            "median_state_rank_ic": group["state_mean_rank_ic"].median(),
            "most_common_failure": failures.most_common(1)[0][0] if failures else "passed_all_gates",
        }
        record.update({f"fail_{name}": failures.get(name, 0) for _, name in GATE_FIELDS})
        record["fail_missing_portfolio_evidence"] = failures.get("missing_portfolio_evidence", 0)
        record["directional_gate_note"] = (
            "negative_mean_rank_ic_blocked_by_positive_only_gate"
            if record["median_rank_ic"] is not None
            and record["median_rank_ic"] < 0
            and failures.get("overall_factor_evidence", 0) > 0
            else ""
        )
        records.append(record)
    return pd.DataFrame(records).sort_values(["profile", "selected_count", "eligible_count", "factor"], ascending=[True, False, False, True])


def summarise_by_state(rows: pd.DataFrame) -> pd.DataFrame:
    """Show which factors can actually pass gates in each state."""
    result = (
        rows.groupby(["profile", "state", "factor", "category"], dropna=False)
        .agg(
            evaluations=("factor", "size"),
            eligible_count=("gate_eligible", "sum"),
            selected_count=("llm_selected", "sum"),
            median_state_rank_ic=("state_mean_rank_ic", "median"),
        )
        .reset_index()
    )
    return result.sort_values(["profile", "state", "selected_count", "eligible_count", "factor"], ascending=[True, True, False, False, True])


def action_diff(left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Compare final action and additions for two selector versions."""
    rows: list[dict[str, Any]] = []
    dates = sorted({key.removeprefix("factor-selection-") for key in set(left) | set(right)})
    for date in dates:
        left_item = left.get(f"factor-selection-{date}", {})
        right_item = right.get(f"factor-selection-{date}", {})
        left_output = left_item.get("output", {}) if isinstance(left_item.get("output"), dict) else {}
        right_output = right_item.get("output", {}) if isinstance(right_item.get("output"), dict) else {}
        left_changed = sorted(_changed_factors(left_output))
        right_changed = sorted(_changed_factors(right_output))
        rows.append({
            "decision_date": date,
            "s3_action": left_item.get("output_kind"),
            "s3_selected_extensions": ";".join(left_changed),
            "s3_next_action": right_item.get("output_kind"),
            "s3_next_selected_extensions": ";".join(right_changed),
            "s3_next_literature_refs": ";".join(right_output.get("literature_refs") or []),
            "same_action": left_item.get("output_kind") == right_item.get("output_kind"),
            "same_extensions": left_changed == right_changed,
        })
    return pd.DataFrame(rows)

"""Experiment definition schema and trial log.

`ExperimentDefinition` is the contract between the LLM intent-parsing
step and the deterministic pipeline: the LLM may only set the fields
below, each whitelisted or range-checked, so a hallucinated value
fails validation instead of reaching the backtest engine. Methodology
guardrails (train/holdout split, universe construction) are NOT part
of this schema — they come from config/settings.yaml and are not
user- or LLM-adjustable, on purpose.

`ExperimentLog` appends every run to a JSONL file, so the number of
trials attempted is always tracked from the first run, not bolted on
after someone starts trusting the numbers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from research.registry_legacy import FACTOR_REGISTRY, UnsupportedFactorError
from research.contracts.experiment import FrozenExperiment


class ExperimentDefinition(BaseModel):
    """LLM-controllable knobs for a single research run."""

    factor: str = "momentum_20d"
    top_pct: float = Field(0.10, gt=0, le=0.5)
    rebalance_days: int = Field(20, gt=0, le=120)
    fee_rate: float = Field(0.0025, ge=0, le=0.02)
    benchmark: str = "000300.SH"

    @field_validator("factor")
    @classmethod
    def _factor_must_be_registered(cls, value: str) -> str:
        if value not in FACTOR_REGISTRY:
            raise UnsupportedFactorError(value)
        return value


class ExperimentLog:
    """Append-only JSONL log of every backtest run."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self, experiment: FrozenExperiment | ExperimentDefinition, metrics: dict, phase: str
    ) -> None:
        """Record one run: its config, resulting metrics, and phase."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "experiment": experiment.model_dump() if hasattr(experiment, "model_dump") else asdict(experiment) if is_dataclass(experiment) else str(experiment),
            "contract_hash": getattr(experiment, "contract_hash", None),
            "metrics": metrics,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str))
            f.write("\n")

    def count_trials(self) -> int:
        """Return how many runs have been logged so far."""
        if not self.path.exists():
            return 0
        with self.path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)

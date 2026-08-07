"""Shared, auditable output schemas for bounded LLM roles."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCallAudit:
    decision_id: str
    prompt_version: str
    input_snapshot_hash: str
    output_kind: str

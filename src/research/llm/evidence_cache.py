"""Content-addressed cache for deterministic S3 evidence snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable


class EvidenceCache:
    """Persist one JSON evidence snapshot per contract and decision date."""

    def __init__(self, root: Path, namespace: str) -> None:
        self.root = Path(root) / namespace
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, decision_date: str) -> Path:
        safe = decision_date.replace("/", "-")
        return self.root / f"{safe}.json"

    def get_or_build(
        self, decision_date: str, builder: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        path = self.path_for(decision_date)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        value = builder()
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return value

    @staticmethod
    def snapshot_hash(value: dict[str, Any]) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

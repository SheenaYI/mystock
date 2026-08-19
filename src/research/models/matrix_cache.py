"""Cache metadata and prepared training matrices for rolling model runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


class MatrixCache:
    """Store one prepared matrix as parquet plus a small JSON manifest."""

    def __init__(self, root: Path, namespace: str) -> None:
        self.root = Path(root) / namespace
        self.root.mkdir(parents=True, exist_ok=True)

    def paths_for(self, decision_date: str) -> tuple[Path, Path]:
        safe = decision_date.replace("/", "-")
        return self.root / f"{safe}.parquet", self.root / f"{safe}.json"

    def load(self, decision_date: str) -> tuple[pd.DataFrame, dict[str, Any]] | None:
        data_path, meta_path = self.paths_for(decision_date)
        if not data_path.is_file() or not meta_path.is_file():
            return None
        return pd.read_parquet(data_path), json.loads(meta_path.read_text(encoding="utf-8"))

    def save(self, decision_date: str, frame: pd.DataFrame, metadata: dict[str, Any]) -> None:
        data_path, meta_path = self.paths_for(decision_date)
        frame.to_parquet(data_path)
        enriched = dict(metadata)
        enriched["rows"] = int(len(frame))
        enriched["columns"] = list(frame.columns)
        enriched["sha256"] = hashlib.sha256(frame.to_csv().encode("utf-8")).hexdigest()
        meta_path.write_text(json.dumps(enriched, ensure_ascii=False, sort_keys=True, default=str), encoding="utf-8")

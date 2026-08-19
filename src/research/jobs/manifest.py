"""Durable JSON manifests for local research worker jobs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid


@dataclass
class JobManifest:
    job_id: str
    profile: str
    status: str = "queued"
    llm_start: str | None = None
    llm_end: str | None = None
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def create(cls, profile: str, *, llm_start: str | None = None, llm_end: str | None = None) -> "JobManifest":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            job_id=f"{profile}-{uuid.uuid4().hex[:12]}", profile=profile,
            llm_start=llm_start, llm_end=llm_end, created_at=now, updated_at=now,
        )

    def save(self, root: Path) -> Path:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        path = root / f"{self.job_id}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "JobManifest":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

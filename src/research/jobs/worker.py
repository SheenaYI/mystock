"""Small foreground worker with durable status and resumable cache-backed runs."""

from __future__ import annotations

from pathlib import Path

from research.pipeline import PipelineResult, run
from research.jobs.manifest import JobManifest


def run_job(manifest: JobManifest, *, root: Path, tradability_mode: str = "block") -> PipelineResult | None:
    if manifest.status == "completed":
        return None
    manifest.status = "running"
    manifest.last_error = None
    manifest.save(root)
    try:
        result = run(
            profile=manifest.profile,
            tradability_mode=tradability_mode,
            llm_start=manifest.llm_start,
            llm_end=manifest.llm_end,
        )
    except Exception as exc:
        manifest.status = "failed"
        manifest.last_error = str(exc)
        manifest.save(root)
        raise
    manifest.status = "completed"
    manifest.save(root)
    return result

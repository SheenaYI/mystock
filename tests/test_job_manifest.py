from pathlib import Path

from research.jobs.manifest import JobManifest


def test_job_manifest_round_trip(tmp_path: Path) -> None:
    manifest = JobManifest.create("s3", llm_start="2024-01-01", llm_end="2025-12-31")
    path = manifest.save(tmp_path)
    loaded = JobManifest.load(path)
    assert loaded.job_id == manifest.job_id
    assert loaded.llm_start == "2024-01-01"

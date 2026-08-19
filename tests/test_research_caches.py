from pathlib import Path

import pandas as pd

from research.llm.evidence_cache import EvidenceCache
from research.models.matrix_cache import MatrixCache


def test_evidence_cache_builds_once(tmp_path: Path) -> None:
    cache = EvidenceCache(tmp_path, "contract")
    calls = []

    def build():
        calls.append(1)
        return {"value": 1}

    assert cache.get_or_build("2024-01-01", build) == {"value": 1}
    assert cache.get_or_build("2024-01-01", build) == {"value": 1}
    assert len(calls) == 1


def test_matrix_cache_round_trip(tmp_path: Path) -> None:
    cache = MatrixCache(tmp_path, "contract")
    frame = pd.DataFrame({"x": [1.0], "label": [0.2]})
    cache.save("2024-01-01", frame, {"selected_features": ["x"]})
    loaded = cache.load("2024-01-01")
    assert loaded is not None
    got, metadata = loaded
    assert got.equals(frame)
    assert metadata["selected_features"] == ["x"]

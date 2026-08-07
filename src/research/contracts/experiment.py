"""The immutable method contract for one formal research run."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

from research.models.qlib_lightgbm import LightGBMConfig
from research.portfolio.costs import CostModel


def _sha256_file(path: Path) -> str:
    """Return a content hash for one frozen evidence file."""
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_tree(root: Path) -> str:
    """Hash the formal research implementation without machine-local paths."""
    digest = sha256()
    files = sorted(path for path in Path(root).rglob("*.py") if "__pycache__" not in path.parts)
    if not files:
        raise ValueError(f"no Python source files under implementation root: {root}")
    for path in files:
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class ProtocolContract:
    universe_index: str = "000300.XSHG"
    benchmark: str = "000300.SH"
    train_start: str = "2021-01-01"
    validation_start: str = "2024-01-01"
    validation_end: str = "2024-12-31"
    locked_start: str = "2025-01-01"
    locked_end: str = "2025-12-31"
    horizon: int = 20
    rebalance_days: int = 20


@dataclass(frozen=True)
class PortfolioContract:
    top_k: int = 10
    n_drop: int = 5
    initial_cash: float = 1_000_000.0


@dataclass(frozen=True)
class EvidenceContract:
    ohlcv_manifest_sha256: str = "UNRESOLVED"
    membership_manifest_sha256: str = "UNRESOLVED"
    corporate_action_manifest_sha256: str = "UNRESOLVED"
    implementation_sha256: str = "UNRESOLVED"
    factor_version: str = "technical-baseline-v1"

    @property
    def resolved(self) -> bool:
        return all(
            value and value != "UNRESOLVED"
            for value in (
                self.ohlcv_manifest_sha256,
                self.membership_manifest_sha256,
                self.corporate_action_manifest_sha256,
                self.implementation_sha256,
            )
        )


def build_evidence_contract(*, raw_root: Path, membership_manifest: Path,
                            corporate_action_manifest: Path,
                            implementation_root: Path) -> EvidenceContract:
    """Bind one run to the exact archived input manifests it consumed.

    The files themselves are already content-addressed by their manifests.  We
    hash the manifests too, so a run record changes when source metadata,
    coverage, or the underlying archive digest changes.
    """
    ohlcv_manifest = Path(raw_root) / "manifests" / "ohlcv.json"
    required = (ohlcv_manifest, Path(membership_manifest), Path(corporate_action_manifest))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError("formal run requires evidence manifests: " + ", ".join(missing))
    return EvidenceContract(
        ohlcv_manifest_sha256=_sha256_file(ohlcv_manifest),
        membership_manifest_sha256=_sha256_file(Path(membership_manifest)),
        corporate_action_manifest_sha256=_sha256_file(Path(corporate_action_manifest)),
        implementation_sha256=_sha256_tree(Path(implementation_root)),
    )


@dataclass(frozen=True)
class FrozenExperiment:
    """Five contracts; changing any field yields a different experiment hash."""

    protocol: ProtocolContract = ProtocolContract()
    model: LightGBMConfig = LightGBMConfig()
    portfolio: PortfolioContract = PortfolioContract()
    execution: CostModel = CostModel()
    evidence: EvidenceContract = EvidenceContract()
    profile: str = "s0"
    tradability_mode: str = "fail"

    def __post_init__(self) -> None:
        if self.tradability_mode not in {"fail", "block"}:
            raise ValueError("tradability_mode must be 'fail' or 'block'")

    @property
    def contract_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()

    def require_resolved_evidence(self) -> None:
        if not self.evidence.resolved:
            raise ValueError("formal experiment cannot run with unresolved evidence hashes")

    @property
    def factor_name(self) -> str:
        names = {
            "m0": "technical_m0_return_20_direct",
            "s0": "technical_baseline_7",
            "s1": "technical_s1_deterministic",
            "s2": "technical_s2_state_mapping",
            "s3": "technical_s3_react_lite",
        }
        try:
            return names[self.profile]
        except KeyError as exc:
            raise ValueError(f"unknown experiment profile: {self.profile}") from exc

"""Stable, human-readable locations for research result groups."""

from __future__ import annotations

from pathlib import Path


PROFILE_REPORT_DIRECTORIES: dict[str, str] = {
    "m0": "M0_direct_momentum",
    "s0": "S0_fixed_7",
    "s1": "S1_deterministic",
    "s2": "S2_state_mapping",
    "s3": "S3_react_lite",
    "s3_next": "S3_next_literature",
    "s4": "S4_W1_n5",
    "s4_n2": "S4_W1_n2",
}


def profile_report_dir(root: Path, profile: str) -> Path:
    """Return the display folder for one current research profile."""
    try:
        return Path(root) / PROFILE_REPORT_DIRECTORIES[profile]
    except KeyError as exc:
        raise ValueError(f"no report directory registered for profile: {profile}") from exc


def profile_diagnostics_dir(root: Path, profile: str) -> Path:
    """Keep diagnostics beside their display group without mixing profiles."""
    return profile_report_dir(root, profile)

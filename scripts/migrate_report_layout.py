#!/usr/bin/env python3
"""Move existing rendered reports into the grouped display layout once.

The script intentionally fails if a destination already exists.  It never
overwrites a report, so rerunning after an interrupted migration is safe once
the conflicting file is inspected.
"""

from __future__ import annotations

from pathlib import Path
import os
import shutil


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "data" / "warehouse" / "reports"
DIAGNOSTICS = ROOT / "data" / "warehouse" / "diagnostics"


REPORT_GROUPS = {
    "legacy/technical_20": ("technical_20",),
    "legacy/m0_original": ("technical_m0_return_20",),
    "M0_direct_momentum": ("technical_m0_return_20_direct",),
    "S0_fixed_7": ("technical_baseline_7",),
    "S1_deterministic": ("technical_s1_deterministic",),
    "S2_state_mapping": ("technical_s2_state_mapping",),
    "S3_react_lite": ("technical_s3_react_lite",),
    "S3_next_literature": ("technical_s3_next_literature_challenger",),
}


def _move(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def migrate() -> None:
    # Longest prefix first: ``technical_m0_return_20_direct`` must be moved
    # before the shorter legacy ``technical_m0_return_20`` prefix can match it.
    groups = sorted(
        REPORT_GROUPS.items(),
        key=lambda item: max(len(prefix) for prefix in item[1]),
        reverse=True,
    )
    for group, prefixes in groups:
        for prefix in prefixes:
            for source in REPORTS.glob(f"*{prefix}*"):
                if source.is_file():
                    _move(source, REPORTS / group / source.name)
            for source in DIAGNOSTICS.glob(f"{prefix}*"):
                if source.is_file():
                    _move(source, DIAGNOSTICS / group / source.name)

    _move(
        REPORTS / "report_s012_comparison.html",
        REPORTS / "comparisons" / "report_s012_comparison.html",
    )
    _move(
        REPORTS / "s3_llm_analysis.txt",
        REPORTS / "S3_react_lite" / "s3_llm_analysis.txt",
    )
    _repair_consolidated_diagnostic_links()


def _repair_consolidated_diagnostic_links() -> None:
    """Make migrated summary reports point to their grouped diagnostics."""
    for group, prefixes in REPORT_GROUPS.items():
        report_dir = REPORTS / group
        diagnostic_dir = DIAGNOSTICS / group
        for prefix in prefixes:
            summary = report_dir / f"report_{prefix}.html"
            diagnostic = diagnostic_dir / f"{prefix}_diagnostics.html"
            if not summary.is_file() or not diagnostic.is_file():
                continue
            old_href = f'href="{diagnostic.name}"'
            new_href = f'href="{os.path.relpath(diagnostic, report_dir)}"'
            content = summary.read_text(encoding="utf-8")
            if old_href in content:
                summary.write_text(content.replace(old_href, new_href), encoding="utf-8")


if __name__ == "__main__":
    migrate()

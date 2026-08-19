from pathlib import Path

from research.reports.paths import profile_diagnostics_dir, profile_report_dir


def test_current_profiles_have_separate_human_readable_result_folders():
    root = Path("warehouse/reports")
    assert profile_report_dir(root, "s0") == root / "S0_fixed_7"
    assert profile_report_dir(root, "s3") == root / "S3_react_lite"
    assert profile_report_dir(root, "s3_next") == root / "S3_next_literature"
    assert profile_report_dir(root, "s4") == root / "S4_W1_n5"
    assert profile_report_dir(root, "s4_n2") == root / "S4_W1_n2"


def test_diagnostics_follow_the_same_group_names():
    root = Path("warehouse/diagnostics")
    assert profile_diagnostics_dir(root, "s2") == root / "S2_state_mapping"

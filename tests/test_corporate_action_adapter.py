import json
from datetime import date

from research.backtest.corporate_action_adapter import load_snapshot_actions


def test_snapshot_actions_are_normalized(tmp_path):
    path = tmp_path / "observations.jsonl"
    path.write_text(json.dumps({
        "payload_sha256": "a" * 64,
        "request": {"symbol": "000001"},
        "response_rows": [{
            "除权除息日": "2021-05-10", "预案公告日": "2021-04-01",
            "送转股份-送转总比例": 5.0,
            "现金分红-现金分红比例描述": "10派1.00元",
        }],
    }) + "\n", encoding="utf-8")
    actions = load_snapshot_actions(path)
    assert len(actions) == 2
    assert actions[0].ex_date == date(2021, 5, 10)

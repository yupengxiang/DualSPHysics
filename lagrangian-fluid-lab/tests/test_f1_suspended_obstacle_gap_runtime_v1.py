import json
from pathlib import Path

import pytest

from scripts.f1_suspended_obstacle_gap_runtime_v1 import _verify_root_review


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1"


def test_root_review_binds_the_prepared_anchor_and_runtime_code():
    review = _verify_root_review(BASE / "root-review-v1.json", BASE / "prepared.json")
    assert review["decision"] == "approved_for_runtime_smoke"
    assert review["matrix_submission"] is False
    assert review["authorization"]["registry_mutation"] is False


def test_root_review_rejects_a_changed_prepared_input(tmp_path):
    copied = tmp_path / "prepared.json"
    payload = json.loads((BASE / "prepared.json").read_text())
    payload["config"]["case_id"] += "_changed"
    copied.write_text(json.dumps(payload))
    with pytest.raises(SystemExit, match="prepared (hash|case)"):
        _verify_root_review(BASE / "root-review-v1.json", copied)

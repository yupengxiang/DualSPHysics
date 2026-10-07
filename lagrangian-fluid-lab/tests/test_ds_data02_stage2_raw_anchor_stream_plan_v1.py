from __future__ import annotations

import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_raw_anchor_stream_plan_v1 as stream_plan  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / (
    "campaigns/ds-data-02/stage2/lineage/v14/raw-anchor-plans/"
    "family-raw-anchor-plan-index-v1.json"
)


def test_seven_family_stream_plan_keeps_f2_ready_and_other_families_pending(tmp_path: Path) -> None:
    result = stream_plan.build(INDEX, tmp_path / "stream-plan.json")
    plan = json.loads(Path(result["path"]).read_text())
    assert plan["schema"] == "ds02.stage2.seven-family-raw-anchor-stream-plan.v1"
    assert len(plan["jobs"]) == 7
    assert [job["family_id"] for job in plan["jobs"]] == [f"F{i}" for i in range(1, 8)]
    assert plan["jobs"][1]["status"] == "F2_REQUEST_READY"
    assert all(job["status"] == "PLAN_ONLY_FAMILY_REQUEST_PENDING" for job in plan["jobs"] if job["family_id"] != "F2")
    assert plan["seven_family_execution_boundary"]["completed_raw_reconstructions"] == 0
    assert plan["stream_operator_contract"]["partout_runparts"] == "provenance only; never typed source arrays"
    assert plan["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_anchor_plan_rejects_changed_current_identity(tmp_path: Path) -> None:
    index = json.loads(INDEX.read_text())
    index["families"][1]["anchor_current_index"] = 79
    bad = tmp_path / "bad-index.json"
    bad.write_text(json.dumps(index))
    try:
        stream_plan.build(bad, tmp_path / "output.json")
    except stream_plan.RawAnchorStreamPlanError as error:
        assert "CURRENT index differs" in str(error)
    else:
        raise AssertionError("changed CURRENT identity must be rejected")

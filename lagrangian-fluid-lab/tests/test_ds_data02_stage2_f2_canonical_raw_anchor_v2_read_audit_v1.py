from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_canonical_raw_anchor_v2_read_audit_v1.py"
SPEC = importlib.util.spec_from_file_location("f2_v2_read_audit_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PLAN = (ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/"
        "canonical-f2-anchor-v2-source-only-002/f2-s1-canonical-raw-anchor-plan-v2.json")
OLD_PLANNER = ROOT / "scripts/ds_data02_stage2_f2_canonical_raw_anchor_v2.py"


@pytest.mark.skipif(not PLAN.is_file(), reason="historical v2 plan is not in this checkout")
def test_actual_v2_partout_and_auxiliary_read_facts_are_recorded_without_payload_open() -> None:
    report = MODULE.audit(plan_path=PLAN, planner_source_path=OLD_PLANNER)
    by_role = {item["role"]: item for item in report["observed_source_roles"]}
    assert by_role["native_partout"]["bytes"] == 7173
    assert by_role["native_partout"]["sha256"] == (
        "248ef327921332beda7efec30ded7612d0d2f6687882a96c40067a0ca04f7b97")
    assert by_role["native_partout"]["content_read_by_planner"] is True
    assert by_role["native_runparts"]["content_read_by_planner"] is True
    assert by_role["motion_dat"]["content_read_by_planner"] is True
    assert by_role["initial_csv"]["content_read_by_planner"] is False
    assert report["payload_opened_by_audit"] is False
    assert report["v2_request_claim"]["source_hashes_preverified_by_parent"] is True
    assert report["v2_request_claim"]["corrected_value"] is False


def test_audit_rejects_a_plan_that_changes_the_recorded_partout_sha(tmp_path: Path) -> None:
    if not PLAN.is_file():
        pytest.skip("historical v2 plan is not in this checkout")
    value = json.loads(PLAN.read_text(encoding="utf-8"))
    value["source_bindings"][-2]["sha256"] = "0" * 64
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MODULE.AuditError, match="native_partout.sha256"):
        MODULE.audit(plan_path=broken, planner_source_path=OLD_PLANNER)

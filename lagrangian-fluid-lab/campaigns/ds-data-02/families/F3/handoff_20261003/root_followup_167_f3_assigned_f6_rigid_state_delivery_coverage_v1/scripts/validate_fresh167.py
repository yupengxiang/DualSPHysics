#!/usr/bin/env python3
"""Static validator for fresh167; reads only this package's JSON/metadata."""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
coverage = json.loads((HERE / "metadata/f6-final48-rigid-state-coverage.json").read_text())
plan = json.loads((HERE / "metadata/full-time-floatinginfo-export-plan.json").read_text())
assert coverage["assignment"]["assigned_family"] == "F3"
assert coverage["assignment"]["actual_family_audited"] == "F6"
assert coverage["assignment"]["scientific_payload_read_or_hashed_by_this_package"] is False
assert coverage["assignment"]["jobs_started_by_this_package"] is False
assert coverage["assignment"]["shared_state_written_by_this_package"] is False
rows = coverage["cases"]
assert len(rows) == 48
assert len({r["physical_case_id"] for r in rows}) == 48
assert coverage["aggregate"]["state0_only_rows"] == 47
assert coverage["aggregate"]["full_time_rigid_state_verified_rows"] == 1
assert coverage["aggregate"]["state0_rows_examined_total"] == 94
assert coverage["aggregate"]["state0_frame_limits"] == [0, 1]
assert len(plan["cases_requiring_full_time_export"]) == 47
assert plan["status"].startswith("source_only_disabled")
assert plan["request_contract"]["disabled"] is True
assert plan["request_contract"]["cpu_task_kind"] == "audit"
assert plan["request_contract"]["cpu_threads"] == 2
assert plan["request_contract"]["registered_runner"]["registration_owner"] == "root"
assert plan["request_contract"]["registered_runner"]["entrypoint"].endswith("root_stage1_home_floor_inventory_dispatch_142/launch.py")
assert coverage["aggregate"]["accepted_rows_with_native_receipt_evidence"] == 47
assert plan["request_contract"]["frame_contract"] == {"first": 0, "last": 240, "expected_count": 241, "must_parse_all_rows": True, "bounded_prefix_is_rejected": True}
assert plan["future_outputs"]["receipt"] is None
assert plan["future_outputs"]["report"] is None
assert plan["future_outputs"]["output_sha256"] is None
for row in rows:
    rs = row["rigid_state_coverage"]
    if rs["classification"] == "full_time_rigid_state_verified":
        assert row["physical_case_id"] == "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE"
        assert rs["full_time_checks"]["total_frames"] == 241
        assert rs["full_time_checks"]["full_12s_window_complete"] is True
    else:
        s = rs["state0_evidence"]
        assert s["rows_examined"] == 2
        assert s["bounded_prefix_only"] is True
        assert s["frame_limits"] == {"first": 0, "last": 1}
        claim = (s["claim_boundary"] or "").lower()
        assert "state-zero" in claim or "state-0" in claim or "state0" in claim
        assert rs["full_time_export_evidence"] is None
        assert row["physical_case_id"] in plan["cases_requiring_full_time_export"]
# Every future output field in source plan is explicitly null; no payload file is packaged.
for p in HERE.rglob("*"):
    if p.is_file() and p.name != "package-integrity.json":
        assert p.suffix.lower() not in {".h5", ".bi4", ".dat", ".vtk", ".vtu", ".pvtu"}, p
print("fresh167 validator: PASS (48 rows; 47 state0-only; 1 full-time baseline; plan disabled)" )

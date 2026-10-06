#!/usr/bin/env python3
"""Validate fresh172's frozen Root951 queue observation without science I/O."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).parents[1]
META = PACKAGE / "metadata/queue-audit.json"

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    d = json.loads(META.read_text())
    assert d["schema"] == "ds02.f6.fresh172.root951-render-queue-audit.v1"
    assert d["fresh_id"] == "fresh172" and d["family_id"] == "F6"
    assert d["model"] == "gpt-5.6-luna" and d["reasoning_effort"] == "max"
    assert d["recursive_delegation"] is False
    c = d["controller"]
    assert c["pid"] == 4004579 and c["proc_start_ticks"] == "207142232"
    t = d["target"]
    assert t["outer_request_index"] == 35
    assert t["case_id"] == "F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025"
    assert t["request_sha256"] == "3950c121b37139711f5caabda2a6182efa995ee70039b0fd1b3b155734bc5754"
    assert t["request_bytes"] == 28216
    request = Path(t["request_path"])
    assert request.is_file() and request.stat().st_size == t["request_bytes"] and sha256(request) == t["request_sha256"]
    rq = json.loads(request.read_text())
    assert rq["case_id"] == t["case_id"] and rq["physical_case_id"] == t["physical_case_id"]
    assert rq["attempt_id"] == t["attempt_id"] and rq["attempt_root"] == t["attempt_root"]
    assert rq["disabled"] is False and rq["launch"] is True and rq["launch_allowed"] is True and rq["execution_allowed"] is True
    assert rq["expected_frames"] == 241 and rq["expected_particles"] == 417505
    assert rq["cpu_threads"] == 24 and rq["estimated_storage_bytes"] == 3221225472
    assert len(rq["input_files"]) == len(rq["input_sha256"]) == 45
    assert set(rq["input_files"]) == set(rq["input_sha256"])
    forbidden = {".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk"}
    nonscience = [Path(x) for x in rq["input_files"] if Path(x).suffix.lower() not in forbidden]
    assert len(nonscience) == 44 and all(x.is_file() for x in nonscience)
    assert t["manifest_path_is_absolute"] is True
    assert t["flags"] == {
        "disabled": False,
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "root_review_required": False,
        "source_only": False,
        "registered_nested_paraview_only_inside_shared_cpu_job": True,
        "full_time_and_native_identity_required": True,
    }
    closure = t["input_closure"]
    assert closure["input_files_count"] == closure["input_sha256_count"] == 45
    assert closure["input_key_sets_equal"] is True
    assert closure["non_science_input_count"] == 44 and closure["non_science_input_missing_count"] == 0
    assert closure["science_payload_opened_or_hashed"] is False
    state = t["attempt_state_at_observation"]
    assert all(state[k] is False for k in ("attempt_root_exists", "execution_receipt_exists", "render_output_exists", "result_row_exists", "visual_review_performed"))
    q = d["controller_queue_snapshot"]
    assert q["outer_request_count"] == 37 and q["result_rows"] == 36
    assert q["pending_not_submitted"] == 0 and q["target_absent_from_results"] is True
    sem = d["dispatch_semantics"]
    assert sem["effective_serial_conversion"] is False
    assert sem["lock_path_role"] == "stage1-fullnative-render-registration.lock"
    rs = sem["current_reservations"]
    assert len(rs) == 2 and [x["cpu_threads"] for x in rs] == [24, 24]
    cap = sem["capacity_inputs"]
    assert cap["reserved_cpu_threads"] == 48 and cap["renderer_count"] == 2
    fit = sem["fit_evaluation"]
    assert fit["cpu_fit"] is False and fit["renderer_cap_fit"] is False and fit["home_storage_fit"] is True
    assert fit["input_or_guard_failure"] is False and fit["qualification_failure"] is False
    assert fit["wait_class"] == "shared-render-capacity-and-cpu-headroom"
    assert d["safe_recovery"]["action"].startswith("leave the same Root951 controller future")
    print("fresh172 validation PASS: target outer_requests[35] is enabled and input-closed; no attempt/result; wait is shared renderer cap plus CPU headroom; no input or qualification failure")

if __name__ == "__main__":
    main()

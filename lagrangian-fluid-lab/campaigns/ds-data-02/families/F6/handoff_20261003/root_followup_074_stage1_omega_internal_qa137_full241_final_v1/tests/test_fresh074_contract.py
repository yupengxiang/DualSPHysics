#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ['F6_STAGE1_ANGULAR_RELEASE_OMEGA_S050_DP025', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S075_DP025', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S125_DP025', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S150_DP025', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S175_DP025']
CONDITIONS = {'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S050_DP025': '8586d081bd2d936c9ee8bb3e8830327cd465795c0ea911edadd29dd6bd88e534', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S075_DP025': 'aa72e1895f0da00dcfc3cf1008261c3d41cc6f4f10e96684c1540aaeadf340e5', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S125_DP025': 'c023e8728793929c773dbe3739c8f3f13061af6dfaba2e1f013180cf79d258b2', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S150_DP025': '669bf019915706bc3bea5d932453add414bcbd162c00775d5fb2d8392cdbaae3', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S175_DP025': 'effcb0dd816abf3babdf29a80744705150f9b41af8bbe5cba2e7d9f88d5e2e0b'}

def j(path):
    return json.loads(path.read_text())

def test_fresh074():
    qa = j(ROOT / "metadata/root137-initial-qa-binding.json")
    assert qa["execution_status"] == "completed" and qa["execution_returncode"] == 0
    assert qa["aggregate_pass"] is True and qa["all_cases_passed"] is True
    assert len(qa["cases"]) == 5
    for row in qa["cases"]:
        assert row["report_pass"] is True and row["physical_condition_sha256"] == CONDITIONS[row["case_id"]]
    owners = j(ROOT / "metadata/canonical-owner-binding.json")
    assert len(owners["cases"]) == 5
    for row in owners["cases"]:
        assert row["physical_condition_sha256"] == CONDITIONS[row["case_id"]]
        owner = j(Path(row["path"]))
        assert owner["physical_condition_sha256"] == row["physical_condition_sha256"]
    for case in CASES:
        req = j(ROOT / "full241-requests" / f"{case}-full241-native-request.json")
        assert req["launch"] is False and req["launch_allowed"] is False and req["execution_allowed"] is False
        assert req["physical_condition_sha256"] == CONDITIONS[case]
        assert "-genuine-gencase-069" in req["cwd"] and "prepared" not in req["cwd"]
        assert req["gencase_actual"] == {"dimension": 3, "fluid": 327680, "returncode": 0, "status": "completed", "total": 417505}
        assert req["actual_initial_qa"]["pass"] is True
        assert req["actual_initial_qa"]["report_sha256"] is not None
        assert req["future_outputs"]["solver_execution_receipt_sha256"] is None
        assert req["future_outputs"]["trajectory_h5_sha256"] is None
        assert req["future_outputs"]["floatinginfo_state0_audit_sha256"] is None
        assert req["future_outputs"]["typed_validation_receipt_sha256"] is None
        assert req["command"][-2:] == ["-tmax:12", "-tout:0.05"]
    state = j(ROOT / "floatinginfo/state0-binding.json")
    assert state["launch_allowed"] is False and len(state["cases"]) == 5
    assert all(row["solver_receipt_sha256"] is None and row["state0_audit_sha256"] is None for row in state["cases"])
    request = j(ROOT / "floatinginfo/state0-request.json")
    assert request["launch"] is False and request["execution_allowed"] is False
    assert request["future_outputs"]["summary_sha256"] is None

if __name__ == "__main__":
    test_fresh074()
    print("fresh074 contract: PASS")

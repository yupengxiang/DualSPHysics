#!/usr/bin/env python3
"""Metadata-only contract preflight for F5 fresh097.

This script reads request/gate/approval/receipt JSON and parses the local
builder AST. It does not open BI4, CSV, H5, VTK, or .dat artifacts, and it
never dispatches a job. ``--write-report`` writes only a small package JSON
summary.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
REQUESTS = PACKAGE / "requests"
GATE_PATH = PACKAGE / "metadata/full801-gate.json"
BUILDER = PACKAGE / "scripts/build_fresh097_requests.py"
BED_REPORT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-solid-fluid-recovery-short-native-bed-audit-321/audit-output/c082s1-short-event-bed-footprint-audit.json")
BED_RECEIPT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-solid-fluid-recovery-short-native-bed-audit-321/execution-receipt.json")
ROOT348 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actual_short51_bed_visual_full801_launch_approval_348/full801-root-launch-approval.json")
NATIVE349 = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-qualification-349/execution-receipt.json")
NATIVE_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-qualification-349"
TYPED_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-typed-nvme-350"
XMF_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-xmf-351"
RENDER_ATTEMPT = "root-stage1-f5-c082s1-solid-fluid-recovery-full801-native-render-352"
SCIENCE_SUFFIXES = {".dat", ".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu"}
EXPECTED_COUNTS = {
    "expected_particles": 194427,
    "expected_particle_axis": 194427,
    "expected_fixed_particles": 158559,
    "expected_moving_particles": 4210,
    "expected_floating_particles": 0,
    "expected_fluid_particles": 31658,
    "expected_dimension": 3,
    "expected_frames": 801,
}
REQUIRED = {
    "schema", "kind", "cpu_task_kind", "attempt_id", "depends_on_attempt",
    "command", "cwd", "worktree_root", "max_wall_seconds", "cpu_threads",
    "estimated_storage_bytes", "input_files", "input_sha256", "input_sha256_provenance",
    "execution_allowed", "launch", "launch_allowed", "disabled", "full16_authorized",
    "full801_authorized", "future_output_hashes", "full_event_gate",
}


def load(path: Path) -> dict:
    if not path.is_file():
        raise AssertionError(f"missing metadata file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"metadata root is not an object: {path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_request(name: str, expected_attempt: str, expected_kind: str, expected_task: str) -> dict:
    request = load(REQUESTS / name)
    missing = REQUIRED.difference(request)
    require(not missing, f"{name}: missing request keys {sorted(missing)}")
    require(request["schema"] == "ds02.runner-request.v2", f"{name}: schema mismatch")
    require(request["attempt_id"] == expected_attempt, f"{name}: attempt mismatch")
    require(request["kind"] == expected_kind, f"{name}: kind mismatch")
    require(request["cpu_task_kind"] == expected_task, f"{name}: cpu_task_kind mismatch")
    require(isinstance(request["command"], list) and request["command"], f"{name}: empty command")
    require(request["cwd"].startswith("/home/jade/"), f"{name}: cwd is not absolute")
    require(request["worktree_root"].endswith("/DualSPHysics"), f"{name}: worktree_root mismatch")
    require(int(request["max_wall_seconds"]) > 0, f"{name}: invalid max wall")
    require(int(request["cpu_threads"]) > 0, f"{name}: invalid CPU thread count")
    require(int(request["estimated_storage_bytes"]) > 0, f"{name}: invalid storage estimate")
    require(request["execution_allowed"] is False, f"{name}: execution unexpectedly enabled")
    require(request["launch"] is False and request["launch_allowed"] is False, f"{name}: launch unexpectedly enabled")
    require(request["disabled"] is True, f"{name}: disabled flag missing")
    require(request["full16_authorized"] is False and request["full801_authorized"] is False, f"{name}: promotion authorization unexpectedly true")
    require(request["future_output_hashes"] is None, f"{name}: future output hash is not null")
    files = request["input_files"]
    hashes = request["input_sha256"]
    require(isinstance(files, list) and files, f"{name}: no input files")
    require(set(hashes) == set(files), f"{name}: input file/hash closure mismatch")
    for raw in files:
        path = Path(raw)
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"{name}: science artifact registered as source input: {path}")
        require(path.is_file(), f"{name}: missing source input: {path}")
        value = hashes[raw]
        require(isinstance(value, str) and len(value) == 64, f"{name}: malformed input hash for {path}")
    for key, value in EXPECTED_COUNTS.items():
        require(request[key] == value, f"{name}: {key} mismatch")
    require(request["dp_m"] == 0.02 and request["save_interval_s"] == 0.02, f"{name}: DP/save interval mismatch")
    require(request["time_window_s"] == [0.0, 16.0] and request["motion_window_s"] == [0.0, 16.0], f"{name}: time window mismatch")
    gate = request["full_event_gate"]
    require(gate["bed_audit_attempt"] == "root-stage1-f5-c082s1-solid-fluid-recovery-short-native-bed-audit-321", f"{name}: bed dependency mismatch")
    require(gate["actual_bed_audit_completed_zero"] is True, f"{name}: actual bed gate not bound")
    require(gate["root348_launch_approval_sha256"] == digest(ROOT348), f"{name}: Root348 approval hash mismatch")
    require(gate["native349_receipt_sha256"] == digest(NATIVE349), f"{name}: native349 receipt hash mismatch")
    require(gate["audit_does_not_auto_authorize"] is True, f"{name}: audit gate became automatic")
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()

    gate = load(GATE_PATH)
    require(gate["schema"] == "ds02.f5.c082s1.full801-promotion-gate.fresh097.v1", "gate schema mismatch")
    require(gate["status"] == "downstream_disabled_after_actual_bed321_root348_and_native349", "gate status mismatch")
    bed = gate["bed_audit"]
    require(bed["receipt"] == str(BED_RECEIPT) and bed["report"] == str(BED_REPORT), "gate bed paths mismatch")
    require(bed["receipt_sha256"] == digest(BED_RECEIPT), "gate bed receipt hash mismatch")
    require(bed["report_sha256"] == digest(BED_REPORT), "gate bed report hash mismatch")
    require(bed["required_status"] == "completed/0", "bed receipt status requirement changed")
    require(bed["actual_frames"] == 51 and bed["actual_initial_fluid_uids"] == 31658, "bed frame/count evidence mismatch")
    require(bed["actual_max_missing_or_unexpected_uid"] == 0 and bed["actual_max_nonfinite_fluid_states"] == 0, "bed UID/finite evidence mismatch")
    require(bed["actual_max_gt_one_dp_02m_belowbed_count"] == 0 and bed["actual_max_gt_two_dp_04m_belowbed_count"] == 0, "bed penetration-bin evidence mismatch")
    require(bed["actual_bed_x_domain_m"] == [-0.2, 4.8] and bed["actual_bed_y_domain_m"] == [-0.22, 0.22], "bed profile domain mismatch")
    require(bed["actual_depth_tolerances_m"] == [0.02, 0.04], "bed diagnostic tolerances changed")
    require(bed["thresholds_remain_diagnostic_only"] is True, "bed thresholds became acceptance thresholds")

    approval = load(ROOT348)
    require(approval["status"] == "approved_to_run_full16s_native_for_stage1_validation", "Root348 status mismatch")
    require(approval["full801_launch_authorized"] is True, "Root348 launch permission missing")
    require(approval["complete_case_accepted"] is False, "Root348 incorrectly grants case acceptance")
    require(approval["q_n_status"] == "not_granted", "Root348 incorrectly grants Q-N")
    require(approval["independent_case_increment"] == 0, "Root348 incorrectly increments case count")

    native_receipt = load(NATIVE349)
    require(native_receipt["status"] == "completed" and native_receipt["returncode"] == 0, "native349 is not completed/0")
    require(native_receipt["output_root"].endswith(NATIVE_ATTEMPT), "native349 output root mismatch")
    require(native_receipt["request"]["attempt_id"] == NATIVE_ATTEMPT, "native349 nested request identity mismatch")
    require(native_receipt["request"]["expected_frames"] == 801, "native349 frame contract mismatch")
    require(native_receipt["request"]["tmax_s"] == 16.0 and native_receipt["request"]["tout_s"] == 0.02, "native349 time contract mismatch")

    native = check_request("full-native-801-request.json", NATIVE_ATTEMPT, "qualification", "solver")
    typed = check_request("full-typed-801-request.json", TYPED_ATTEMPT, "cpu", "conversion")
    xmf = check_request("full-xmf-801-request.json", XMF_ATTEMPT, "cpu", "audit")
    render = check_request("full-render-root023-801-request.json", RENDER_ATTEMPT, "cpu", "audit")
    require(native["actual_native_result"]["receipt_sha256"] == digest(NATIVE349), "native request actual receipt mismatch")
    require(native["actual_native_result"]["status"] == "completed/0", "native request actual status mismatch")
    require(typed["depends_on_attempt"] == NATIVE_ATTEMPT, "typed does not depend on native349")
    require(xmf["depends_on_attempt"] == TYPED_ATTEMPT, "XMF dependency mismatch")
    require(render["depends_on_attempt"] == XMF_ATTEMPT, "render dependency mismatch")
    require(str(NATIVE349) in typed["input_files"], "typed does not register native349 receipt")
    require(str(NATIVE349) in xmf["input_files"], "XMF does not register native349 receipt")
    require(str(ROOT348) in native["input_files"], "native does not register Root348 approval")
    require("-tmax:16.0" in native["command"] and "-tout:0.02" in native["command"], "native command time flags mismatch")
    require(any("ds_data02_nvme_convert_v1.py" in item for item in typed["command"]), "typed converter command missing")
    require(any(item.endswith("export_xmf_legacy_aware.py") for item in xmf["command"]), "legacy-aware XMF command missing")
    require(any(item.endswith("root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py") for item in render["command"]), "Root023 renderer command missing")

    tree = ast.parse(BUILDER.read_text(encoding="utf-8"), filename=str(BUILDER))
    forbidden = {"subprocess", "os.system", "Popen", "run_job"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    require(not (forbidden & names) and not (forbidden & attrs), "builder contains a job-dispatch primitive")

    summary = {
        "schema": "ds02.f5.c082s1.fresh097.metadata-preflight.v1",
        "status": "pass_disabled_downstream",
        "bed321": {"attempt_id": bed["attempt_id"], "frames": bed["actual_frames"], "below_1dp": bed["actual_max_gt_one_dp_02m_belowbed_count"], "below_2dp": bed["actual_max_gt_two_dp_04m_belowbed_count"], "uid_loss": bed["actual_max_missing_or_unexpected_uid"], "nonfinite": bed["actual_max_nonfinite_fluid_states"]},
        "root348": {"launch_permission": approval["full801_launch_authorized"], "complete_case_accepted": approval["complete_case_accepted"], "q_n_status": approval["q_n_status"]},
        "native349": {"status": native_receipt["status"], "returncode": native_receipt["returncode"], "receipt_sha256": digest(NATIVE349)},
        "downstream": {"typed": typed["attempt_id"], "xmf": xmf["attempt_id"], "render": render["attempt_id"], "all_execution_disabled": True, "future_hashes_null": True},
        "science_arrays_read_or_hashed_by_source_agent": False,
        "job_started_by_source_agent": False,
    }
    if args.write_report:
        (PACKAGE / "metadata/fresh097-preflight-report.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

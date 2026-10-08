#!/usr/bin/env python3
"""Prepare a strict JSON-only F7 17+3 observer join.

The three new native observations and the earlier 17 observations were
already decoded and independently verified.  This forward request consumes
those immutable JSON reports; it does not bind new BI4 files and does not
decode anything again.  The join remains a local output-sampling diagnostic:
all scientific qualification channels stay UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[5]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f7_s2_same_cfl_20frame_join_v4.py"
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py")
STRICT = DISPATCH.parent / "ds_data02_strict_dispatch_v8.py"
RUNTIME = DISPATCH.parent / "ds_data02_runtime_v8.py"
RAW_ROOT = Path("/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/data")
RUNPARTS = RAW_ROOT.parent / "RunPARTs.csv"
OVERLAY_XML = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/F7_OBSTACLE_QUINTIC_B08_A065_same_cfl_savedt.xml"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
CALIBRATION = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f7_s2_observer_calibration_contract_v3.json"
NEW_REPORT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_S2_A065_NEW3_SELECTED_NATIVE_OBSERVER_V4/f7-s2-a065-new3-selected-native-observer-v4-root-001-root-forward-030-001/observer/f7_s2_a065_new3_selected_native_observer_v4.json")
NEW_RECEIPT = NEW_REPORT.parents[1] / "execution-receipt.json"
NEW_REQUEST = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f7-new3-source-bound-root-042/f7_s2_a065_new3_selected_native_observer_v4_request.json")
NEW_MANIFEST = NEW_REQUEST.parent / "f7_s2_a065_new3_expected_source_manifest_v4.json"
NEW_PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F7_S2_THREE_NEW_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_042.json")
OLD_REPORT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_S2_SAME_CFL_TIME_OUTPUT_OBSERVER_V1/f7-s2-same_cfl-time-output-observer-v1-root-001-root-forward-029-001/observer/f7_s2_same_cfl_time_output_observer_v1.json")
OLD_RECEIPT = OLD_REPORT.parents[1] / "execution-receipt.json"
OLD_PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F7_SAME_CFL_SEVENTEEN_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_001.json")
SOURCE_RECEIPT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json")
SOURCE_REQUEST = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/f7-nvme-counterpart-v5-root-001/f7-s2-same-cfl-nvme-request-v5-001.json")
CURRENT_XML = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_OBSTACLE_QUINTIC_B08_A065/root-stage1-f7-angle065-genuine-gencase-085/prepared/F7_OBSTACLE_QUINTIC_B08_A065.xml")
OWNER = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_064_stage1_target_angle_full601_native099_nvme_typed_v1/owners/F7_OBSTACLE_QUINTIC_B08_A065.owner.json")
GENCASE_RECEIPT = CURRENT_XML.parents[1] / "execution-receipt.json"
MOTION = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/motion_obstacle_quintic.dat"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def assert_report(value: dict[str, Any], label: str, expected_frames: list[int]) -> None:
    if value.get("schema") != "ds02.stage2.native-physical-observer.v2":
        raise ValueError(f"{label} has unexpected observer schema")
    if value.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"{label} is not a completed selected-field report")
    frames = value.get("source", {}).get("selected_frames")
    if frames != expected_frames:
        raise ValueError(f"{label} frame list differs: {frames!r}")
    integrity = value.get("source_integrity", {})
    if integrity.get("status") != "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT":
        raise ValueError(f"{label} lacks complete source-integrity status")
    if integrity.get("hdf5_read") is not False or integrity.get("solver_launch") is not False:
        raise ValueError(f"{label} scope is not decode-only")


def build(output: Path) -> dict[str, Any]:
    all_paths = [
        WORKER, DISPATCH, STRICT, RUNTIME, PYTHON, DECODER, DECODER_SOURCE, CALIBRATION,
        RAW_ROOT.parent / "RunPARTs.csv", OVERLAY_XML, SOURCE_RECEIPT, SOURCE_REQUEST,
        CURRENT_XML, GENCASE_RECEIPT, OWNER, MOTION,
        NEW_REPORT, NEW_RECEIPT, NEW_REQUEST, NEW_MANIFEST, NEW_PROOF,
        OLD_REPORT, OLD_RECEIPT, OLD_PROOF,
    ]
    all_paths = list(dict.fromkeys(path.expanduser().resolve() for path in all_paths))
    for path in all_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    new_value = load(NEW_REPORT)
    old_value = load(OLD_REPORT)
    assert_report(new_value, "actual new3 observer", [302, 602, 902])
    assert_report(old_value, "actual old17 observer", [0, 1, 298, 299, 300, 301, 598, 599, 600, 601, 898, 899, 900, 901, 1198, 1199, 1200])
    proof = load(NEW_PROOF)
    if proof.get("status") != "PASS_ACTUAL_THREE_SELECTED_F7_NATIVE_OBSERVER_FIELDS":
        raise ValueError("new3 root proof is not the expected completed proof")
    if proof.get("report") != str(NEW_REPORT):
        raise ValueError("new3 root proof report path differs")
    if proof.get("report_sha256") != sha256(NEW_REPORT):
        raise ValueError("new3 root proof does not bind actual report bytes")
    frames = [0, 1, 298, 299, 300, 301, 302, 598, 599, 600, 601, 602, 898, 899, 900, 901, 902, 1198, 1199, 1200]
    output_name = "f7_s2_same_cfl_20frame_join_actual_new3_v1.json"
    input_hashes = {str(path): sha256(path) for path in all_paths}
    return {
        "schema": "ds02.request.v1", "family_id": "F7", "sentinel_id": "F7-S2",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "case_id": "F7_S2_SAME_CFL_20FRAME_JOIN_ACTUAL_NEW3_V1",
        "attempt_id": "f7-s2-same-cfl-20frame-join-actual-new3-v1-root-forward-001",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900,
        "worktree_root": str(REPO), "cwd": str(REPO),
        "command": [str(PYTHON), str(WORKER), "--same-observer", str(OLD_REPORT), "--neighbor-observer", str(NEW_REPORT), "--runparts", str(RUNPARTS), "--generated-xml", str(OVERLAY_XML), "--decoder", str(DECODER), "--decoder-source", str(DECODER_SOURCE), "--source-receipt", str(SOURCE_RECEIPT), "--raw-root", str(RAW_ROOT), "--calibration-contract", str(CALIBRATION), "--output", f"{{attempt_root}}/join/{output_name}"],
        "input_files": [str(path) for path in all_paths], "input_hashes": input_hashes,
        "deferred_input_files": [], "deferred_hash_policy": {"bi4_read": False, "decoder_launch": False, "old17_redecode": False, "new3_redecode": False, "json_only_join": True},
        "estimated_native_read_bytes": 0, "estimated_hdf5_read_bytes": 0, "estimated_storage_bytes": 64 << 20, "estimated_peak_memory_bytes": 256 << 20,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "hdf5_read": False, "bi4_decode": False,
        "output": {"path": f"{{attempt_root}}/join/{output_name}", "atomic": True, "refuse_overwrite": True, "frame_ids": frames, "field_interpolation": "FORBIDDEN"},
        "source_binding": {
            "raw_root": str(RAW_ROOT), "runparts": record(RUNPARTS), "overlay_xml": record(OVERLAY_XML), "source_solver_receipt": record(SOURCE_RECEIPT), "source_solver_request": record(SOURCE_REQUEST), "current_xml": record(CURRENT_XML), "gencase_receipt": record(GENCASE_RECEIPT), "owner": record(OWNER), "motion": record(MOTION), "calibration_contract": record(CALIBRATION),
            "old17": {"report": record(OLD_REPORT), "producer_receipt": record(OLD_RECEIPT), "independent_proof": record(OLD_PROOF), "frames": [0, 1, 298, 299, 300, 301, 598, 599, 600, 601, 898, 899, 900, 901, 1198, 1199, 1200]},
            "new3": {"request": record(NEW_REQUEST), "expected_manifest": record(NEW_MANIFEST), "report": record(NEW_REPORT), "producer_receipt": record(NEW_RECEIPT), "independent_proof": record(NEW_PROOF), "frames": [302, 602, 902]},
            "merged_frames": frames, "native_source_is_already_verified": True,
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "bi4_decode": "forbidden"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "same-run local output sampling join only; no spatial or integration truth"},
        "scope": {"old17_actual": True, "new3_actual": True, "new3_redecoded": False, "old17_redecoded": False, "json_only_join": True, "no_interpolation": True, "same_run_output_sampling_only": True},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    value = build(args.output)
    if args.self_test:
        print(json.dumps({"status": "PASS", "new3": value["source_binding"]["new3"]["report"], "merged_frames": value["source_binding"]["merged_frames"]}, ensure_ascii=False))
        return 0
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write(atomic_payload); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    print(json.dumps({"status": "PASS_REQUEST_READY", "output": str(args.output.resolve()), "merged_frames": value["source_binding"]["merged_frames"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

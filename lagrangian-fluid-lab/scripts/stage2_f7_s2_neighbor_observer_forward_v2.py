#!/usr/bin/env python3
"""Prepare the F7 17+3 selected-native observer and calibration chain.

The consumed neighbor builder selected only twelve frames.  This forward
builder uses the independently verified same-CFL and half-CFL seventeen-frame
reports as immutable producer evidence, schedules a three-frame same-CFL
observer for 302/602/902, and prepares a JSON-only join/calibration request.
The resulting same-CFL report has twenty frames.  Half-CFL remains seventeen
frames, so its radius-two/4x diagnostic stays explicitly UNKNOWN.

The builder reads only JSON/proof/RunPARTs metadata.  It never opens BI4 or
HDF5 and never launches a worker or solver.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
LAB_ROOT = SCRIPT_DIR.parent
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-02"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

SAME_OLD_PROOF = CAMPAIGN_ROOT / "stage2/checkpoints/F7_SAME_CFL_SEVENTEEN_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
HALF_OLD_PROOF = CAMPAIGN_ROOT / "stage2/checkpoints/F7_HALF_CFL_SEVENTEEN_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
SNAPSHOT_RESULT = DATA_ROOT / "families/F7/F7_S2_OUTPUT_NEIGHBOR_SNAPSHOT_V1/f7-s2-output-neighbor-snapshot-v1-root-001-root-forward-030-001/native_selected_source_snapshot_v2.json"
SNAPSHOT_RECEIPT = SNAPSHOT_RESULT.parent / "execution-receipt.json"
SNAPSHOT_PROOF = CAMPAIGN_ROOT / "stage2/checkpoints/F7_S2_THREE_MISSING_4X_NEIGHBOR_SNAPSHOT_ACTUAL_INDEPENDENT_VERIFICATION_001.json"

RAW_ROOT = Path("/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/data")
RUNPARTS = RAW_ROOT.parent / "RunPARTs.csv"
HALF_RUNPARTS = Path("/var/tmp/ds02-stage2/F7/F7_S2_HALF_CFL_SAVEDT_V7/f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/solver_output/RunPARTs.csv")
GENERATED_XML = CAMPAIGN_ROOT / "stage2/reference/stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/F7_OBSTACLE_QUINTIC_B08_A065_same_cfl_savedt.xml"
CURRENT_XML = DATA_ROOT / "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/root-stage1-f7-angle065-genuine-gencase-085/prepared/F7_OBSTACLE_QUINTIC_B08_A065.xml"
SOLVER_RECEIPT = DATA_ROOT / "families/F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json"
OWNER = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_064_stage1_target_angle_full601_native099_nvme_typed_v1/owners/F7_OBSTACLE_QUINTIC_B08_A065.owner.json")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = SCRIPT_DIR / "native/bi4_dump.cpp"
OBSERVER_WORKER = CAMPAIGN_ROOT / "stage2/reference/stage2_native_physical_observer_v2.py"
ENFORCER = CAMPAIGN_ROOT / "stage2/reference/stage2_native_physical_observer_enforcer_v2.py"
CALIBRATION = CAMPAIGN_ROOT / "stage2/reference/stage2_f7_s2_output_calibration_v2.py"
JOIN_WORKER = SCRIPT_DIR / "stage2_f7_s2_neighbor_calibration_join_v1.py"
CONTRACT = CAMPAIGN_ROOT / "stage2/reference/stage2_f7_s2_observer_calibration_contract_v3.json"
DISPATCH_V8 = LAB_ROOT / "scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_V8 = LAB_ROOT / "scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME_V8 = LAB_ROOT / "scripts/ds_data02_runtime_v8.py"
RUNTIME_V6 = LAB_ROOT / "scripts/ds_data02_runtime_v6.py"
RUNTIME_V2 = LAB_ROOT / "scripts/ds_data02_runtime_v2.py"
OUTPUT_DIR = CAMPAIGN_ROOT / "stage2/requests/stage2-f7-s2-neighbor-observer-v4"

SAME_OLD_FRAMES = (0, 1, 298, 299, 300, 301, 598, 599, 600, 601,
                   898, 899, 900, 901, 1198, 1199, 1200)
SAME_NEW_FRAMES = (302, 602, 902)
HALF_FRAMES = SAME_OLD_FRAMES
SAME_MERGED_FRAMES = tuple(sorted(set(SAME_OLD_FRAMES) | set(SAME_NEW_FRAMES)))
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, default=str).encode()).hexdigest()


def load(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"{label} is unavailable or symlinked: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildError(f"{label} must be a JSON object: {path}")
    return value


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"{label} is unavailable or symlinked: {path}")
    return path


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=SCRIPT_DIR.parent.parent,
                          check=True, capture_output=True, text=True).stdout.strip()


def parent_limits() -> dict[str, Any]:
    ledger_path = DATA_ROOT / "runtime/resource-ledger.json"
    ledger = load(ledger_path, "parent resource ledger")
    limits = ledger.get("limits", {})
    required = ("cpu_core_seconds", "gpu_seconds", "new_storage_bytes", "qualification_attempts",
                "production_attempts", "home_min_free_bytes", "home_path", "storage_policy")
    if any(key not in limits for key in required):
        raise BuildError("parent ledger lacks required live limits")
    return {"ledger_path": str(ledger_path), "data_root": str(DATA_ROOT),
            "campaign_id": ledger.get("campaign_id"), "deadline_utc": ledger.get("deadline_utc"),
            "ledger_reset": False, "no_new_data_root": True,
            "limits": {key: limits[key] for key in required}}


def _proof_report(proof_path: Path, label: str, expected_frames: tuple[int, ...]) -> tuple[dict[str, Any], Path]:
    proof = load(proof_path, label + " proof")
    if proof.get("status") != "PASS_ACTUAL_SELECTED_NATIVE_FIELDS":
        raise BuildError(f"{label} proof is not a successful selected-native proof")
    report_path = regular(Path(str(proof.get("report", ""))), label + " observer report")
    expected_sha = str(proof.get("report_sha256", ""))
    if len(expected_sha) != 64 or sha256_file(report_path) != expected_sha:
        raise BuildError(f"{label} report SHA does not match its independent proof")
    report = load(report_path, label + " observer report")
    if report.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise BuildError(f"{label} observer report is not successful")
    records = report.get("source", {}).get("selected_part_records", [])
    if not isinstance(records, list):
        raise BuildError(f"{label} report lacks selected source records")
    frames = tuple(int(Path(str(item["path"])).stem.split("_")[-1]) for item in records)
    if frames != expected_frames:
        raise BuildError(f"{label} report frames {frames} differ from the verified frame set")
    proof_frames = tuple(int(item["frame"]) for item in proof.get("native_sources", []))
    if proof_frames != expected_frames:
        raise BuildError(f"{label} proof native frame set differs from its report")
    for pitem, ritem in zip(proof.get("native_sources", []), records):
        if str(pitem.get("sha256")) != str(ritem.get("sha256")):
            raise BuildError(f"{label} proof/report source SHA differs at frame {pitem.get('frame')}")
    return proof, report_path


def _snapshot_records(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = snapshot.get("immutable_source_sha_list")
    if not isinstance(records, list) or tuple(int(item.get("frame", -1)) for item in records) != SAME_NEW_FRAMES:
        raise BuildError("new neighbor snapshot is not exactly frames 302/602/902")
    result = []
    for item in records:
        if not isinstance(item, Mapping):
            raise BuildError("new neighbor snapshot record is malformed")
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        if path.parent != RAW_ROOT.resolve() or path.name != f"Part_{int(item['frame']):04d}.bi4":
            raise BuildError(f"new snapshot frame/path is outside the bound raw root: {path}")
        if int(item.get("bytes", 0)) <= 0 or len(str(item.get("sha256", ""))) != 64:
            raise BuildError("new snapshot record lacks complete bytes/SHA")
        result.append({"frame": int(item["frame"]), "path": str(path),
                       "bytes": int(item["bytes"]), "sha256": str(item["sha256"])})
    return result


def _validate_snapshot_proof(snapshot: Mapping[str, Any], snapshot_sha: str) -> None:
    proof = load(SNAPSHOT_PROOF, "new neighbor snapshot proof")
    if proof.get("status") != "PASS_ACTUAL_THREE_SELECTED_F7_SOURCE_SNAPSHOTS_NO_DECODE":
        raise BuildError("new neighbor snapshot proof is not the actual no-decode PASS")
    if proof.get("root_BI4_content_read") is not False or proof.get("full_raw_scan") is not False:
        raise BuildError("new neighbor snapshot proof exceeds the selected-source scope")
    if proof.get("parent_actual_prepost_content_hashes_equal") is not True:
        raise BuildError("new neighbor snapshot proof lacks parent pre/post content closure")
    if proof.get("worker_stream_SHA_and_complete_prepost_stat_checked") is not True:
        raise BuildError("new neighbor snapshot proof lacks worker source integrity closure")
    report_path = Path(str(proof.get("report", ""))).expanduser().resolve()
    if report_path != SNAPSHOT_RESULT.resolve() or str(proof.get("report_sha256")) != snapshot_sha:
        raise BuildError("new neighbor snapshot proof does not bind the exact snapshot result")
    proof_records = proof.get("selected_native_records")
    snapshot_records = snapshot.get("immutable_source_sha_list")
    if not isinstance(proof_records, list) or not isinstance(snapshot_records, list):
        raise BuildError("new neighbor snapshot proof lacks selected source records")
    proof_by_frame = {int(item["frame"]): item for item in proof_records}
    for item in snapshot_records:
        frame = int(item["frame"])
        proof_item = proof_by_frame.get(frame)
        if proof_item is None or str(proof_item.get("declared_actual_worker_SHA")) != str(item.get("sha256")):
            raise BuildError(f"new snapshot proof/source SHA differs at frame {frame}")


def runparts_times(path: Path, frames: tuple[int, ...]) -> list[float]:
    """Read only the small RunPARTs timing table to make exact-frame queries."""
    values: dict[int, float] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.reader(stream, delimiter=";"):
            if not row or row[0] == "Part" or row[0].lstrip().startswith("#"):
                continue
            try:
                frame = int(row[0])
                time_s = float(row[1])
            except (ValueError, IndexError) as exc:
                raise BuildError(f"invalid RunPARTs timing row in {path}: {row[:2]}") from exc
            if frame in frames:
                values[frame] = time_s
    if tuple(sorted(values)) != frames:
        raise BuildError(f"RunPARTs lacks exact query frames {frames}: found {sorted(values)}")
    return [values[frame] for frame in frames]


def build_manifest(out: Path, snapshot: Mapping[str, Any], snapshot_sha: str,
                   same_old_proof: Path, half_old_proof: Path) -> dict[str, Any]:
    records = _snapshot_records(snapshot)
    value: dict[str, Any] = {
        "schema": "ds02.stage2.native-observer-source-manifest.v1",
        "status": "READY_PARENT_V8_NEW3_ONLY",
        "family_id": "F7", "sentinel_id": "F7-S2",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "raw_root": str(RAW_ROOT.resolve()), "selected_native_files": records,
        "selected_native_frame_ids": list(SAME_NEW_FRAMES),
        "producer_binding": {
            "snapshot_result": str(SNAPSHOT_RESULT.resolve()), "snapshot_result_sha256": snapshot_sha,
            "snapshot_receipt": str(SNAPSHOT_RECEIPT.resolve()), "snapshot_receipt_sha256": sha256_file(SNAPSHOT_RECEIPT),
            "snapshot_proof": str(SNAPSHOT_PROOF.resolve()), "snapshot_proof_sha256": sha256_file(SNAPSHOT_PROOF),
            "same_old_proof": str(same_old_proof.resolve()), "same_old_proof_sha256": sha256_file(same_old_proof),
            "half_old_proof": str(half_old_proof.resolve()), "half_old_proof_sha256": sha256_file(half_old_proof),
            "new_frames_only": list(SAME_NEW_FRAMES), "source_scope": "selected BI4 records only; no full tree hash",
        },
        "scope": {
            "selected_files_only": True, "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER",
            "full_raw_tree_scan": False, "hdf5_read": False, "bi4_decode": False,
            "solver_launch": False, "observer_decode_credit": "deferred parent worker only",
        },
    }
    value["sha256"] = canonical_sha(value)
    if out.exists():
        raise BuildError(f"refusing existing manifest: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def add_input(inputs: list[Path], hashes: dict[str, str], path: Path) -> None:
    path = regular(path, "request input")
    key = str(path)
    if key not in hashes:
        inputs.append(path)
        hashes[key] = sha256_file(path)


def build_observer_request(manifest_path: Path, manifest: Mapping[str, Any], output_dir: Path,
                           same_old_proof: Path, half_old_proof: Path,
                           query_times: list[float], launch_commit: str) -> tuple[dict[str, Any], Path]:
    output_root = DATA_ROOT / "families/F7/F7_S2_A065_NEW3_SELECTED_NATIVE_OBSERVER_V4/f7-s2-a065-new3-selected-native-observer-v4-root-001"
    command = [str(VENV_PYTHON), str(ENFORCER), "--observer-worker", str(OBSERVER_WORKER),
               "--expected-source-manifest", str(manifest_path.resolve()), "--raw-root", str(RAW_ROOT.resolve()),
               "--runparts", str(RUNPARTS.resolve()), "--generated-xml", str(GENERATED_XML.resolve()),
               "--decoder", str(DECODER.resolve()), "--decoder-source", str(DECODER_SOURCE.resolve()),
               "--output", "{attempt_root}/observer/f7_s2_a065_new3_selected_native_observer_v4.json",
               "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--cwd", str(SCRIPT_DIR.parent.parent),
               "--expected-frame-count", "1201", "--expected-final-time-s", "12.00003209155591",
               "--final-time-tolerance-s", "1e-12", "--frames", *[str(frame) for frame in SAME_NEW_FRAMES],
               "--query-times", *[format(value, ".17g") for value in query_times]]
    inputs: list[Path] = []
    hashes: dict[str, str] = {}
    for path in (OBSERVER_WORKER, ENFORCER, manifest_path, SNAPSHOT_RESULT, SNAPSHOT_RECEIPT, SNAPSHOT_PROOF,
                 DISPATCH_V8, STRICT_V8, RUNTIME_V8, RUNTIME_V6, RUNTIME_V2, DECODER, DECODER_SOURCE,
                 RUNPARTS, GENERATED_XML, CURRENT_XML, SOLVER_RECEIPT, OWNER, same_old_proof, half_old_proof,
                 CONTRACT):
        add_input(inputs, hashes, path)
    deferred = [str(item["path"]) for item in manifest["selected_native_files"]]
    value: dict[str, Any] = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F7", "sentinel_id": "F7-S2", "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "case_id": "F7_S2_A065_NEW3_SELECTED_NATIVE_OBSERVER_V4",
        "attempt_id": "f7-s2-a065-new3-selected-native-observer-v4-root-001",
        "command": command, "cwd": str(SCRIPT_DIR.parent.parent), "worktree_root": str(SCRIPT_DIR.parent.parent),
        "input_files": [str(path) for path in inputs], "input_hashes": hashes,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
        "estimated_input_read_bytes": sum(path.stat().st_size for path in inputs),
        "estimated_native_read_bytes": sum(int(item["bytes"]) for item in manifest["selected_native_files"]),
        "estimated_bi4_read_bytes": sum(int(item["bytes"]) for item in manifest["selected_native_files"]),
        "estimated_hdf5_read_bytes": 0, "estimated_storage_bytes": 1024**3,
        "estimated_peak_memory_bytes": 1024**3, "execution_allowed": True, "launch_disabled": False,
        "solver_started": False, "hdf5_read": False, "bi4_decode": True,
        "deferred_input_files": sorted(set(deferred)), "deferred_input_file_count": len(set(deferred)),
        "deferred_hash_policy": {
            "snapshot_result": str(SNAPSHOT_RESULT.resolve()), "snapshot_result_sha256": hashes[str(SNAPSHOT_RESULT.resolve())],
            "source_scope": "only Part_0302/0602/0902; no old17 re-decode; no full raw scan",
            "pre_post_complete_stat_required": True, "unknown_child_status": "FAILURE",
            "particle_field_interpolation": "NOT_PERFORMED_BY_WORKER",
        },
        "snapshot_binding": {"snapshot_result": str(SNAPSHOT_RESULT.resolve()),
                              "snapshot_result_sha256": hashes[str(SNAPSHOT_RESULT.resolve())],
                              "snapshot_receipt": str(SNAPSHOT_RECEIPT.resolve()),
                              "snapshot_receipt_sha256": hashes[str(SNAPSHOT_RECEIPT.resolve())],
                              "snapshot_proof": str(SNAPSHOT_PROOF.resolve()),
                              "snapshot_proof_sha256": hashes[str(SNAPSHOT_PROOF.resolve())],
                              "selected_new_frame_ids": list(SAME_NEW_FRAMES),
                              "selected_new_frame_records": list(manifest["selected_native_files"])},
        "source_binding": {"expected_manifest": str(manifest_path.resolve()),
                            "expected_manifest_sha256": sha256_file(manifest_path),
                            "raw_root": str(RAW_ROOT.resolve()), "selected_frame_ids": list(SAME_NEW_FRAMES),
                            "old_same_proof": str(same_old_proof.resolve()),
                            "old_half_proof": str(half_old_proof.resolve()),
                            "no_hdf5": True, "no_full_raw_tree_scan": True},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH_V8),
                            "strict": str(STRICT_V8), "runtime": str(RUNTIME_V8),
                            "runtime_v6_dependency": str(RUNTIME_V6), "launch_commit": launch_commit,
                            "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden"},
        "qualification": dict(UNKNOWN), "output_root": str(output_root),
        "manifest_path": str(manifest_path.resolve()), "launch_commit": launch_commit,
    }
    value["request_sha256"] = canonical_sha(value)
    path = output_dir / "f7_s2_a065_new3_selected_native_observer_v4_request.json"
    if path.exists():
        raise BuildError(f"refusing existing observer request: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value, path


def build_calibration_request(output_dir: Path, observer_request: Mapping[str, Any], observer_path: Path,
                              same_old_report: Path, half_old_report: Path, same_old_proof: Path,
                              half_old_proof: Path, launch_commit: str) -> tuple[dict[str, Any], Path]:
    new_output = DATA_ROOT / "families/F7/F7_S2_A065_NEW3_SELECTED_NATIVE_OBSERVER_V4/f7-s2-a065-new3-selected-native-observer-v4-root-001/observer/f7_s2_a065_new3_selected_native_observer_v4.json"
    output_root = DATA_ROOT / "families/F7/F7_S2_A065_MERGED20_CALIBRATION_V4/f7-s2-a065-merged20-calibration-v4-root-001"
    merged_same = Path("{attempt_root}/merged/f7_s2_a065_same_cfl_merged20_observer_v4.json")
    report_output = Path("{attempt_root}/report/f7_s2_a065_neighbor_output_calibration_v4.json")
    command = [str(VENV_PYTHON), str(JOIN_WORKER), "--run", "--same-old", str(same_old_report.resolve()),
               "--same-new", str(new_output), "--half-old", str(half_old_report.resolve()),
               "--merged-same", str(merged_same), "--merged-output", str(report_output),
               "--same-runparts", str(RUNPARTS.resolve()), "--half-runparts", str(HALF_RUNPARTS.resolve()),
               "--contract", str(CONTRACT.resolve()), "--calibration", str(CALIBRATION.resolve()),
               "--python", str(VENV_PYTHON), "--cwd", str(SCRIPT_DIR.parent.parent)]
    inputs: list[Path] = []
    hashes: dict[str, str] = {}
    for path in (JOIN_WORKER, CALIBRATION, VENV_PYTHON, DISPATCH_V8, STRICT_V8, RUNTIME_V8, RUNTIME_V6,
                 RUNTIME_V2, CONTRACT, same_old_report, half_old_report, RUNPARTS, HALF_RUNPARTS,
                 same_old_proof, half_old_proof, observer_path, SNAPSHOT_RESULT, SNAPSHOT_PROOF):
        add_input(inputs, hashes, path)
    value: dict[str, Any] = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F7", "sentinel_id": "F7-S2", "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "case_id": "F7_S2_A065_MERGED20_CALIBRATION_V4",
        "attempt_id": "f7-s2-a065-merged20-calibration-v4-root-001",
        "command": command, "cwd": str(SCRIPT_DIR.parent.parent), "worktree_root": str(SCRIPT_DIR.parent.parent),
        "input_files": [str(path) for path in inputs], "input_hashes": hashes,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900,
        "estimated_input_read_bytes": sum(path.stat().st_size for path in inputs),
        "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 128 * 1024**2, "estimated_peak_memory_bytes": 1024**3,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False,
        "hdf5_read": False, "bi4_decode": False,
        "deferred_input_files": [str(new_output)], "deferred_input_file_count": 1,
        "deferred_hash_policy": {
            "new3_observer_terminal_status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
            "new3_observer_source_integrity": "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT",
            "join_mode": "JSON_ONLY_OLD17_PLUS_NEW3_TO_SAME20",
            "half_mode": "KEEP_VERIFIED_HALF17",
            "half_radius_two_missing": [302, 602, 902],
            "four_x_status": "UNKNOWN_FOR_HALF_CFL",
            "particle_field_interpolation": "NOT_PERFORMED_BY_JOIN",
        },
        "source_binding": {
            "same_old_report": str(same_old_report.resolve()), "same_old_report_sha256": sha256_file(same_old_report),
            "half_old_report": str(half_old_report.resolve()), "half_old_report_sha256": sha256_file(half_old_report),
            "same_old_proof": str(same_old_proof.resolve()), "same_old_proof_sha256": sha256_file(same_old_proof),
            "half_old_proof": str(half_old_proof.resolve()), "half_old_proof_sha256": sha256_file(half_old_proof),
            "new3_observer_output": str(new_output), "new3_request": str(observer_path.resolve()),
            "same_frame_count": 20, "half_frame_count": 17,
            "same_frames": list(SAME_MERGED_FRAMES), "half_frames": list(HALF_FRAMES),
            "time_output_task_error_share": {"time": 0.25, "output": 0.25},
            "scientific_qualification": dict(UNKNOWN),
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH_V8),
                            "strict": str(STRICT_V8), "runtime": str(RUNTIME_V8),
                            "runtime_v6_dependency": str(RUNTIME_V6), "launch_commit": launch_commit,
                            "gpu": "none", "solver_launch": "forbidden", "bi4_read": "forbidden",
                            "hdf5_read": "forbidden"},
        "output": {"path": str(report_output), "merged_same_path": str(merged_same),
                   "atomic": True, "refuse_overwrite": True},
        "output_root": str(output_root), "qualification": dict(UNKNOWN), "launch_commit": launch_commit,
    }
    value["request_sha256"] = canonical_sha(value)
    path = output_dir / "f7_s2_a065_merged20_output_calibration_v4_request.json"
    if path.exists():
        raise BuildError(f"refusing existing calibration request: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value, path


def build(output_dir: Path = OUTPUT_DIR, *, launch_commit: str | None = None) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    launch_commit = launch_commit or git_commit()
    parent_limits()
    same_old_proof = regular(SAME_OLD_PROOF, "same-CFL old proof")
    half_old_proof = regular(HALF_OLD_PROOF, "half-CFL old proof")
    same_proof, same_report = _proof_report(same_old_proof, "same-CFL old", SAME_OLD_FRAMES)
    half_proof, half_report = _proof_report(half_old_proof, "half-CFL old", HALF_FRAMES)
    snapshot = load(SNAPSHOT_RESULT, "new 302/602/902 snapshot")
    if snapshot.get("status") != "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE":
        raise BuildError("new neighbor snapshot is not a stable PASS")
    snapshot_sha = sha256_file(SNAPSHOT_RESULT)
    for path, label in ((SNAPSHOT_RECEIPT, "new snapshot receipt"), (SNAPSHOT_PROOF, "new snapshot proof"),
                        (RUNPARTS, "same RunPARTs"), (HALF_RUNPARTS, "half RunPARTs"),
                        (GENERATED_XML, "generated XML"), (CURRENT_XML, "current XML"),
                        (SOLVER_RECEIPT, "same solver receipt"), (OWNER, "F7 owner"),
                        (OBSERVER_WORKER, "observer worker"), (ENFORCER, "observer enforcer"),
                        (CALIBRATION, "calibration worker"), (JOIN_WORKER, "join worker"),
                        (CONTRACT, "observer contract"), (DECODER, "decoder"), (DECODER_SOURCE, "decoder source"),
                        (DISPATCH_V8, "dispatch v8"), (STRICT_V8, "strict v8"), (RUNTIME_V8, "runtime v8"),
                        (RUNTIME_V6, "runtime v6"), (RUNTIME_V2, "runtime v2"), (VENV_PYTHON, "venv Python")):
        regular(path, label)
    _validate_snapshot_proof(snapshot, snapshot_sha)
    query_times = runparts_times(RUNPARTS, SAME_NEW_FRAMES)
    manifest_path = output_dir / "f7_s2_a065_new3_expected_source_manifest_v4.json"
    manifest = build_manifest(manifest_path, snapshot, snapshot_sha, same_old_proof, half_old_proof)
    observer_request, observer_path = build_observer_request(manifest_path, manifest, output_dir,
                                                              same_old_proof, half_old_proof,
                                                              query_times, launch_commit)
    calibration_request, calibration_path = build_calibration_request(output_dir, observer_request,
                                                                       observer_path, same_report, half_report,
                                                                       same_old_proof, half_old_proof,
                                                                       launch_commit)
    summary: dict[str, Any] = {
        "schema": "ds02.stage2.f7.neighbor-observer-forward.v2",
        "status": "READY_PARENT_V8_SEQUENTIAL_JSON_JOIN",
        "launch_commit": launch_commit,
        "manifest": str(manifest_path), "observer_request": str(observer_path),
        "calibration_request": str(calibration_path),
        "same_old_proof": str(same_old_proof), "same_old_report": str(same_report),
        "half_old_proof": str(half_old_proof), "half_old_report": str(half_report),
        "new_frames": list(SAME_NEW_FRAMES), "same_merged_frames": list(SAME_MERGED_FRAMES),
        "half_frames": list(HALF_FRAMES), "half_four_x_status": "UNKNOWN_MISSING_302_602_902",
        "no_raw_read_by_builder": True, "no_solver_launch": True,
        "scientific_qualification": dict(UNKNOWN),
    }
    summary["sha256"] = canonical_sha(summary)
    summary_path = output_dir / "f7_s2_neighbor_observer_forward_manifest_v2.json"
    if summary_path.exists():
        raise BuildError(f"refusing existing summary: {summary_path}")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--launch-commit")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            print("Use stage2_f7_s2_neighbor_calibration_join_v1.py --self-test for the JSON join self-test")
            return 0
        result = build(args.output_dir, launch_commit=args.launch_commit)
    except (BuildError, OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

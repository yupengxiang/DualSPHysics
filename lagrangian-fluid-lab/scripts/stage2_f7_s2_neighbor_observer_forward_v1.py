#!/usr/bin/env python3
"""Build the F7 3-neighbor observer and follow-on output calibration requests.

The parent has already produced an immutable three-file snapshot for frames
302/602/902.  This builder consumes that metadata only, combines it with the
previously verified nine-frame manifest, and emits two bounded CPU-v8 tasks:
the 12-frame enforcer/observer and a calibration task that must wait for its
terminal observer artifact.  It never opens a BI4/HDF5 payload and does not
launch a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
LAB_ROOT = SCRIPT_DIR.parent
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-02"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
RAW_ROOT = Path("/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/data")
RUNPARTS = RAW_ROOT.parent / "RunPARTs.csv"
GENERATED_XML = CAMPAIGN_ROOT / "stage2/reference/stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/F7_OBSTACLE_QUINTIC_B08_A065_same_cfl_savedt.xml"
CURRENT_XML = DATA_ROOT / "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/root-stage1-f7-angle065-genuine-gencase-085/prepared/F7_OBSTACLE_QUINTIC_B08_A065.xml"
SOLVER_RECEIPT = DATA_ROOT / "families/F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json"
OWNER = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_064_stage1_target_angle_full601_native099_nvme_typed_v1/owners/F7_OBSTACLE_QUINTIC_B08_A065.owner.json")
OLD_MANIFEST = CAMPAIGN_ROOT / "stage2/requests/stage2-f7-s2-native-observer-v2-root-prepared-001/f7_s2_a065_expected_source_manifest_v2.json"
OLD_TEMPLATE = CAMPAIGN_ROOT / "stage2/requests/stage2-f7-s2-native-observer-v2/f7_s2_a065_same_cfl_selected_native_observer_template_v2.json"
SNAPSHOT_RESULT = DATA_ROOT / "families/F7/F7_S2_OUTPUT_NEIGHBOR_SNAPSHOT_V1/f7-s2-output-neighbor-snapshot-v1-root-001-root-forward-030-001/native_selected_source_snapshot_v2.json"
SNAPSHOT_RECEIPT = SNAPSHOT_RESULT.parent / "execution-receipt.json"
SNAPSHOT_PROOF = CAMPAIGN_ROOT / "stage2/checkpoints/F7_S2_THREE_MISSING_4X_NEIGHBOR_SNAPSHOT_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics/lagrangian-fluid-lab/scripts/native/bi4_dump.cpp")
SNAPSHOT_WORKER = CAMPAIGN_ROOT / "stage2/reference/stage2_native_source_snapshot_v2.py"
OBSERVER_WORKER = CAMPAIGN_ROOT / "stage2/reference/stage2_native_physical_observer_v2.py"
ENFORCER = CAMPAIGN_ROOT / "stage2/reference/stage2_native_physical_observer_enforcer_v2.py"
CALIBRATION = CAMPAIGN_ROOT / "stage2/reference/stage2_f7_s2_output_calibration_v2.py"
CONTRACT = CAMPAIGN_ROOT / "stage2/reference/stage2_f7_s2_observer_calibration_contract_v3.json"
DISPATCH_V8 = LAB_ROOT / "scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_V8 = LAB_ROOT / "scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME_V8 = LAB_ROOT / "scripts/ds_data02_runtime_v8.py"
RUNTIME_V6 = LAB_ROOT / "scripts/ds_data02_runtime_v6.py"
RUNTIME_V2 = LAB_ROOT / "scripts/ds_data02_runtime_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
OUTPUT_DIR = CAMPAIGN_ROOT / "stage2/requests/stage2-f7-s2-neighbor-observer-v3"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
NEW_FRAMES = (302, 602, 902)
ALL_FRAMES = (0, 299, 300, 302, 599, 600, 602, 899, 900, 902, 1199, 1200)


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha(value: dict[str, Any]) -> str:
    body = {k: v for k, v in value.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, default=str).encode()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildError(f"JSON object required: {path}")
    return value


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise BuildError(f"required small input unavailable: {path}")
    return path


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=SCRIPT_DIR.parent.parent,
                          check=True, capture_output=True, text=True).stdout.strip()


def parent_limits() -> dict[str, Any]:
    ledger = load(DATA_ROOT / "runtime/resource-ledger.json")
    limits = ledger.get("limits", {})
    keys = ("cpu_core_seconds", "gpu_seconds", "new_storage_bytes", "qualification_attempts",
            "production_attempts", "home_min_free_bytes", "home_path", "storage_policy")
    if any(key not in limits for key in keys):
        raise BuildError("parent ledger lacks required live limits")
    return {"ledger_path": str(DATA_ROOT / "runtime/resource-ledger.json"),
            "data_root": str(DATA_ROOT), "campaign_id": ledger.get("campaign_id"),
            "deadline_utc": ledger.get("deadline_utc"), "ledger_reset": False,
            "no_new_data_root": True, "limits": {key: limits[key] for key in keys}}


def build_manifest(out: Path, snapshot: dict[str, Any], snapshot_sha: str) -> dict[str, Any]:
    old = load(OLD_MANIFEST)
    if old.get("schema") != "ds02.stage2.native-observer-source-manifest.v1":
        raise BuildError("old F7 observer manifest schema differs")
    records = list(old.get("selected_native_files", []))
    additions = snapshot.get("immutable_source_sha_list")
    if not isinstance(additions, list) or {int(item.get("frame", -1)) for item in additions} != set(NEW_FRAMES):
        raise BuildError("terminal neighbor snapshot lacks exactly frames 302/602/902")
    records.extend({"frame": int(item["frame"]), "path": str(item["path"]),
                    "bytes": int(item["bytes"]), "sha256": str(item["sha256"])} for item in additions)
    records.sort(key=lambda item: int(item["frame"]))
    if [int(item["frame"]) for item in records] != list(ALL_FRAMES):
        raise BuildError("combined selected frame list is not the registered 12-frame set")
    value = dict(old)
    value["case_id"] = "F7_S2_A065_SAME_CFL_SELECTED_NATIVE_OBSERVER_V3"
    value["observer_request"] = {"path": "PENDING_FORWARD_OBSERVER_REQUEST", "bytes": 0, "mtime_ns": 0, "sha256": "PENDING"}
    value["selected_native_frame_ids"] = list(ALL_FRAMES)
    value["selected_native_files"] = records
    value["selected_source_sha256"] = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    value["snapshot_binding"] = {
        "snapshot_result": str(SNAPSHOT_RESULT.resolve()), "snapshot_result_sha256": snapshot_sha,
        "snapshot_receipt": str(SNAPSHOT_RECEIPT.resolve()), "snapshot_receipt_sha256": sha256_file(SNAPSHOT_RECEIPT),
        "snapshot_proof": str(SNAPSHOT_PROOF.resolve()), "snapshot_proof_sha256": sha256_file(SNAPSHOT_PROOF),
        "new_frames": list(NEW_FRAMES), "worker_full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER",
    }
    contract = value.get("observer_calibration_contract", {})
    contract["status"] = "PRE_REGISTERED_BEFORE_FIELD_DIFFERENCES"
    contract["scientific_qualification"] = dict(UNKNOWN)
    contract.setdefault("alignment", {})["query_times_s"] = [0.0, 3.0, 6.0, 9.0, 12.0]
    contract["alignment"]["particle_field_interpolation"] = "FORBIDDEN_BY_WORKER"
    contract["alignment"]["out_of_window"] = "UNKNOWN_NO_EXTRAPOLATION"
    contract["task_budget_shares"] = {
        "time": {"maximum_fraction_of_task_error_budget": 0.25, "meaning": "budget share, not result pass gate"},
        "output": {"maximum_fraction_of_task_error_budget": 0.25, "meaning": "budget share, not result pass gate"},
    }
    value["observer_calibration_contract"] = contract
    if out.exists():
        raise BuildError(f"refusing existing output: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def add_input(inputs: list[Path], hashes: dict[str, str], path: Path, *, expected: str | None = None) -> None:
    path = regular(path)
    key = str(path)
    if key not in hashes:
        inputs.append(path)
        hashes[key] = expected or sha256_file(path)


def build_observer_request(manifest_path: Path, manifest: dict[str, Any], output_dir: Path,
                           launch_commit: str) -> dict[str, Any]:
    snapshot = load(SNAPSHOT_RESULT)
    raw = str(manifest["raw_root"])
    observer_output = DATA_ROOT / "families/F7/F7_S2_A065_SAME_CFL_SELECTED_NATIVE_OBSERVER_V3/f7-s2-a065-same-cfl-selected-native-observer-v3-root-001/observer/f7_s2_a065_same_cfl_selected_native_observer_v3.json"
    command = [str(PYTHON), str(ENFORCER), "--observer-worker", str(OBSERVER_WORKER),
               "--expected-source-manifest", str(manifest_path), "--raw-root", raw,
               "--runparts", str(RUNPARTS), "--generated-xml", str(GENERATED_XML),
               "--decoder", str(DECODER), "--decoder-source", str(DECODER_SOURCE),
               "--output", "{attempt_root}/observer/f7_s2_a065_same_cfl_selected_native_observer_v3.json",
               "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--cwd", str(SCRIPT_DIR.parent.parent),
               "--expected-frame-count", "1201", "--expected-final-time-s", "12.00003209155591",
               "--final-time-tolerance-s", "1e-12", "--frames", *[str(v) for v in ALL_FRAMES],
               "--query-times", "0.0", "3.0", "6.0", "9.0", "12.0"]
    inputs: list[Path] = []
    hashes: dict[str, str] = {}
    for path in (OBSERVER_WORKER, ENFORCER, SNAPSHOT_WORKER, manifest_path, SNAPSHOT_RESULT,
                 SNAPSHOT_RECEIPT, SNAPSHOT_PROOF, DISPATCH_V8, STRICT_V8, RUNTIME_V8,
                 RUNTIME_V6, RUNTIME_V2, DECODER, DECODER_SOURCE, RUNPARTS, GENERATED_XML,
                 CURRENT_XML, SOLVER_RECEIPT, OWNER, OLD_TEMPLATE):
        add_input(inputs, hashes, path)
    snapshot_records = snapshot["immutable_source_sha_list"]
    deferred = [raw]
    deferred.extend(str(item["path"]) for item in manifest["selected_native_files"])
    request = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F7", "sentinel_id": "F7-S2", "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "case_id": "F7_S2_A065_SAME_CFL_SELECTED_NATIVE_OBSERVER_V3",
        "attempt_id": "f7-s2-a065-same-cfl-selected-native-observer-v3-root-001",
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
            "snapshot_result": str(SNAPSHOT_RESULT), "snapshot_result_sha256": hashes[str(SNAPSHOT_RESULT)],
            "pre_post_complete_stat_required": True, "cross_decode_stat_boundaries": "pre.stat_after == post.stat_before and pre.stat_before == post.stat_after",
            "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER", "unknown_child_status": "FAILURE",
            "particle_field_interpolation": "NOT_PERFORMED_BY_WORKER",
        },
        "snapshot_binding": {"snapshot_result": str(SNAPSHOT_RESULT), "snapshot_result_sha256": hashes[str(SNAPSHOT_RESULT)],
                              "snapshot_receipt": str(SNAPSHOT_RECEIPT), "snapshot_receipt_sha256": hashes[str(SNAPSHOT_RECEIPT)],
                              "snapshot_proof": str(SNAPSHOT_PROOF), "snapshot_proof_sha256": hashes[str(SNAPSHOT_PROOF)],
                              "selected_new_frames": list(NEW_FRAMES), "selected_new_frame_records": snapshot_records},
        "source_binding": {"expected_manifest": str(manifest_path), "expected_manifest_sha256": sha256_file(manifest_path),
                            "raw_root": raw, "selected_frame_ids": list(ALL_FRAMES), "no_hdf5": True,
                            "no_full_raw_tree_scan": True},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH_V8),
                            "strict_guard": str(STRICT_V8), "runtime": str(RUNTIME_V8),
                            "runtime_v6_dependency": str(RUNTIME_V6), "launch_commit": launch_commit,
                            "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden"},
        "qualification": dict(UNKNOWN), "output_root": str(observer_output.parent.parent.parent),
        "manifest_path": str(manifest_path), "launch_commit": launch_commit,
    }
    req_path = output_dir / "f7_s2_a065_same_cfl_selected_native_observer_v3_request.json"
    request["request_sha256"] = canonical_sha(request)
    req_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def build_calibration_request(observer_request: dict[str, Any], output_dir: Path,
                              launch_commit: str) -> dict[str, Any]:
    observer_output = DATA_ROOT / "families/F7/F7_S2_A065_SAME_CFL_SELECTED_NATIVE_OBSERVER_V3/f7-s2-a065-same-cfl-selected-native-observer-v3-root-001/observer/f7_s2_a065_same_cfl_selected_native_observer_v3.json"
    half_observer = DATA_ROOT / "families/F7/F7_S2_A065_HALF_CFL_SELECTED_NATIVE_OBSERVER_V1/f7-s2-a065-half-cfl-selected-native-observer-v1-root-001-root-forward-001/observer/f7_s2_a065_half_cfl_selected_native_observer_v1.json"
    half_runparts = Path("/var/tmp/ds02-stage2/F7/F7_S2_HALF_CFL_SAVEDT_V7/f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/solver_output/RunPARTs.csv")
    command = [str(PYTHON), str(CALIBRATION), "--run", "--same-observer", str(observer_output),
               "--half-observer", str(half_observer), "--same-runparts", str(RUNPARTS),
               "--half-runparts", str(half_runparts), "--contract", str(CONTRACT),
               "--output", "{attempt_root}/report/f7_s2_neighbor_output_calibration_v3.json"]
    inputs: list[Path] = []
    hashes: dict[str, str] = {}
    for path in (CALIBRATION, PYTHON, DISPATCH_V8, STRICT_V8, RUNTIME_V8, RUNTIME_V6, RUNTIME_V2,
                 CONTRACT, half_observer, half_runparts, RUNPARTS, observer_request["__path__"]):
        add_input(inputs, hashes, Path(path))
    request = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F7", "sentinel_id": "F7-S2", "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "case_id": "F7_S2_NEIGHBOR_OUTPUT_CALIBRATION_V3",
        "attempt_id": "f7-s2-neighbor-output-calibration-v3-root-001",
        "command": command, "cwd": str(SCRIPT_DIR.parent.parent), "worktree_root": str(SCRIPT_DIR.parent.parent),
        "input_files": [str(path) for path in inputs], "input_hashes": hashes,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900,
        "estimated_input_read_bytes": sum(path.stat().st_size for path in inputs),
        "estimated_storage_bytes": 64 * 1024**2, "estimated_peak_memory_bytes": 1024**3,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False,
        "hdf5_read": False, "bi4_decode": False,
        "deferred_input_files": [str(observer_output)], "deferred_input_file_count": 1,
        "deferred_hash_policy": {"observer_terminal_status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
                                  "observer_source_integrity": "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT",
                                  "observer_output_must_be_parent_terminal_artifact": True,
                                  "time_alignment": "actual RunPARTs brackets; no interpolation of particle fields",
                                  "output_diagnostic_not_physical_truth": True},
        "source_binding": {"observer_predecessor_request": observer_request["__path__"],
                            "observer_predecessor_request_sha256": sha256_file(Path(observer_request["__path__"])),
                            "same_observer_output": str(observer_output),
                            "same_runparts": str(RUNPARTS), "half_observer": str(half_observer),
                            "task_budget_shares": {"time": 0.25, "output": 0.25},
                            "scientific_qualification": dict(UNKNOWN)},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH_V8),
                            "strict_guard": str(STRICT_V8), "runtime": str(RUNTIME_V8),
                            "runtime_v6_dependency": str(RUNTIME_V6), "launch_commit": launch_commit,
                            "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden"},
        "qualification": dict(UNKNOWN), "launch_commit": launch_commit,
    }
    request["request_sha256"] = canonical_sha(request)
    out = output_dir / "f7_s2_neighbor_output_calibration_v3_request.json"
    out.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def build(output_dir: Path = OUTPUT_DIR, *, launch_commit: str | None = None) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    launch_commit = launch_commit or git_commit()
    for path in (OLD_MANIFEST, SNAPSHOT_RESULT, SNAPSHOT_RECEIPT, SNAPSHOT_PROOF, RUNPARTS,
                 GENERATED_XML, CURRENT_XML, SOLVER_RECEIPT, OWNER, OBSERVER_WORKER, ENFORCER,
                 SNAPSHOT_WORKER, CALIBRATION, CONTRACT, DECODER, DECODER_SOURCE, DISPATCH_V8,
                 STRICT_V8, RUNTIME_V8, RUNTIME_V6, RUNTIME_V2, OLD_TEMPLATE):
        regular(path)
    snapshot = load(SNAPSHOT_RESULT)
    snapshot_sha = sha256_file(SNAPSHOT_RESULT)
    manifest_path = output_dir / "f7_s2_a065_expected_source_manifest_v3.json"
    manifest = build_manifest(manifest_path, snapshot, snapshot_sha)
    observer = build_observer_request(manifest_path, manifest, output_dir, launch_commit)
    observer_path = output_dir / "f7_s2_a065_same_cfl_selected_native_observer_v3_request.json"
    observer["__path__"] = str(observer_path)
    calibration = build_calibration_request(observer, output_dir, launch_commit)
    # The helper key is removed from the persisted request; it only supplies
    # the predecessor path to the second request builder.
    observer.pop("__path__", None)
    observer_path.write_text(json.dumps(observer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Keep the manifest's pending observer_request sentinel.  Including the
    # newly written request in the manifest would create a digest cycle: the
    # observer request hashes this manifest as an input.  The request path is
    # carried by the forward summary and the enforcer only consumes the
    # selected-file records.
    summary = {"schema": "ds02.stage2.f7.neighbor-observer-forward-manifest.v1",
               "status": "READY_PARENT_CPU_V8_SEQUENTIAL", "launch_commit": launch_commit,
               "snapshot_result": str(SNAPSHOT_RESULT), "snapshot_result_sha256": snapshot_sha,
               "manifest": str(manifest_path), "observer_request": str(observer_path),
               "calibration_request": str(output_dir / "f7_s2_neighbor_output_calibration_v3_request.json"),
               "observer_frame_count": len(ALL_FRAMES), "snapshot_new_frames": list(NEW_FRAMES),
               "scientific_qualification": dict(UNKNOWN)}
    summary["sha256"] = canonical_sha(summary)
    (output_dir / "f7_s2_neighbor_observer_forward_manifest_v1.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    ap.add_argument("--launch-commit")
    args = ap.parse_args(argv)
    try:
        result = build(args.output_dir, launch_commit=args.launch_commit)
    except (BuildError, OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

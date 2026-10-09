#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a bounded JSON-only F4 saved-output comparison request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f4-s1.saved-output-empirical-comparison-request.v1"
WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_s1_saved_output_empirical_compare_v1.py"
LOCAL_WORKER = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_s1_saved_output_empirical_compare_v1.py"

PROOF_PATHS = {
    "coarse_same_cfl": PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F4_COARSE_SAME_CFL_24_MISSING_NATIVE_FIELDS_ACTUAL_ROOT_VERIFICATION_155.json",
    "dp0_half_cfl": PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F4_DP0_HALF_CFL_24_MISSING_NATIVE_FIELDS_ACTUAL_ROOT_VERIFICATION_156.json",
    "dp0_same_cfl": PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F4_DP0_SAME_CFL_24_MISSING_NATIVE_FIELDS_ACTUAL_ROOT_VERIFICATION_157.json",
    "fine_same_cfl": PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F4_FINE_SAME_CFL_24_MISSING_NATIVE_FIELDS_ACTUAL_ROOT_VERIFICATION_158.json",
}


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_JSON_hashed_by_builder_and_parent_v8",
    }


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def validate_inputs() -> dict[str, Any]:
    details: dict[str, Any] = {}
    all_reports: list[str] = []
    all_old: list[str] = []
    for label, proof_path in PROOF_PATHS.items():
        proof = load(proof_path, f"F4 {label} proof")
        report_path = regular(Path(str(proof.get("report", ""))), f"F4 {label} report")
        report = load(report_path, f"F4 {label} report")
        if proof.get("run_label") != label or proof.get("selected_frame_count") != 24:
            raise ValueError(f"F4 {label} proof identity/frame count mismatch")
        if proof.get("report_sha256") != sha256(report_path):
            raise ValueError(f"F4 {label} proof/report SHA mismatch")
        if report.get("schema") != "ds02.stage2.f4-s1.missing-native-observer.v1" or report.get("status") != "PASS_MISSING_SELECTED_NATIVE_FIELDS":
            raise ValueError(f"F4 {label} report status/schema mismatch")
        existing = report.get("source", {}).get("existing_observer") if isinstance(report.get("source"), dict) else None
        if not isinstance(existing, dict) or not existing.get("path"):
            raise ValueError(f"F4 {label} report lacks legacy observer binding")
        old_path = regular(Path(str(existing["path"])), f"F4 {label} legacy observer")
        old = load(old_path, f"F4 {label} legacy observer")
        if old.get("schema") != "ds02.stage2.f4-physical-observer.v1":
            raise ValueError(f"F4 {label} legacy observer schema mismatch")
        details[label] = {
            "proof": record(proof_path, f"F4 {label} verification proof"),
            "report": record(report_path, f"F4 {label} actual selected-field report"),
            "legacy_observer": record(old_path, f"F4 {label} legacy nine-frame observer"),
        }
        all_reports.append(str(report_path))
        all_old.append(str(old_path))
    return {"runs": details, "report_paths": all_reports, "legacy_observer_paths": all_old}


def canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def primary_or_local() -> Path:
    if WORKER.is_file() and not WORKER.is_symlink():
        return WORKER
    if LOCAL_WORKER.is_file() and not LOCAL_WORKER.is_symlink():
        return LOCAL_WORKER
    raise FileNotFoundError("F4 empirical comparison worker is missing in both primary and local trees")


def build(args: argparse.Namespace) -> dict[str, Any]:
    source = validate_inputs()
    worker = primary_or_local()
    records: dict[str, dict[str, Any]] = {str(worker.resolve()): record(worker, "F4 empirical comparison worker")}
    for run in source["runs"].values():
        for item in run.values():
            records[item["path"]] = item
    records[str(PYTHON)] = record(PYTHON, "literal venv interpreter")
    worker_path = str(worker.resolve())
    proofs = [f"{label}={PROOF_PATHS[label].resolve()}" for label in sorted(PROOF_PATHS)]
    command = [str(PYTHON), worker_path, "--compare"]
    for item in proofs:
        command += ["--proof", item]
    command += ["--output", "{attempt_root}/comparison/f4_s1_saved_output_empirical_comparison_v1.json"]
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F4_JSON_COMPARISON",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F4",
        "sentinel_id": "F4-S1",
        "physical_case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
        "case_id": args.case_id,
        "attempt_id": args.attempt_id,
        "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY_REPO / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY_REPO),
        "command": command,
        "input_files": input_files,
        "input_hashes": hashes,
        "input_sha256": hashes,
        "input_records": records,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "max_memory_bytes": 512 * 1024**2,
        "estimated_storage_bytes": 16 * 1024**2,
        "estimated_peak_memory_bytes": 128 * 1024**2,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
        "estimated_native_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "hdf5_read": False,
        "native_payload_read": False,
        "raw_directory_scan": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/comparison/f4_s1_saved_output_empirical_comparison_v1.json"},
        "source_binding": {
            "schema": VARIANT,
            "actual_guarded_proof_report_pairs": source["runs"],
            "old9_observers_are_provenance_only": True,
            "native_massfluid_not_mixed_with_old_xml_weighted_values": True,
            "comparison_uses_actual_saved_timestamps": True,
            "interpolation": False,
            "error_bound": "UNKNOWN_NOT_ESTIMATED",
            "spatial_truth": False,
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": "parent-v8-audit", "cpu_parent_binding": "required", "payload_read": "small JSON reports only", "solver_launch": "forbidden"},
        "qualification_stage": "stage2_f4_s1_report_only_async_saved_time_diagnostics",
        "scientific_qualification": {"QI": "PASS_LIMITED_REPORT_COMPARISON_ONLY", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    payload["sha256"] = canonical(payload)
    return payload


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    if not str(PYTHON).endswith("/.venv/bin/python"):
        raise AssertionError("literal venv binding changed")
    return {"status": "PASS", "schema": SCHEMA, "small_json_only": True, "native_payload_read": False, "interpolation": False, "truth_credit": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f4-s1-saved-output-empirical-compare-root162-001.json")
    parser.add_argument("--launch-commit", required=False)
    parser.add_argument("--case-id", default="F4_S1_SAVED_OUTPUT_EMPIRICAL_COMPARE_ROOT162")
    parser.add_argument("--attempt-id", default="f4-s1-saved-output-empirical-compare-root-162-001")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if not args.launch_commit:
        parser.error("--build-request requires --launch-commit")
    try:
        payload = build(args)
        write_once(args.output, payload)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F4_SAVED_OUTPUT_EMPIRICAL_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps({"status": payload["status"], "output": str(args.output.resolve()), "native_payload_read": False, "input_bytes": payload["estimated_input_read_bytes"]}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())

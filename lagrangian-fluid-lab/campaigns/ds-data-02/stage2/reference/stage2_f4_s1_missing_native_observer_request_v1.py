#!/usr/bin/env python3
"""Prepare four parent-ready F4-S1 missing-native decode requests.

ROOT152 found 24 missing native rows around each of the four existing F4-S1
nine-row observers.  This builder consumes only the ROOT152 proof/report,
small observer JSONs, RunPARTs, XML and file metadata.  It stats every missing
Part file but never reads or hashes a native payload.  The worker performs the
first content SHA after the parent reservation and rechecks SHA/stat after
each bounded official decode.

Four independent request files are emitted so the parent can serialize source
I/O and fees by run.  The historical nine-row observers remain immutable and
are recorded as provenance only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import stage2_native_physical_observer_v2 as base


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f4-s1.missing-native-observer-request.v1"
REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DISPATCH = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_s1_missing_native_observer_v1.py"
BOUNDED_DECODER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v2.py"
BASE_OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
HEADER_OBSERVER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_observer_v1.py"
PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F4_COMMON_TIME_OUTPUT_MISSING_ROWS_ACTUAL_ROOT_VERIFICATION_152.json"
ROOT152_REPORT = DATA_ROOT / "families/F4/F4_S1_COMMON_TIME_OUTPUT_CALIBRATION_V5_ROOT_152/f4-s1-common-time-output-calibration-v5-root-152-001-root-forward-030-001/report/f4_s1_common_time_output_calibration_v5.json"
ROOT152_PROOF_SHA = "f78b45411220cdeb1228ef08a7c6211a5543ef54a29f6527f37a28b86d959268"
ROOT152_REQUEST_SHA = "3b37bc44ddbd84dc462d357f95dedf3097aced382384e3f1900abb5f5b65d15e"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-s1-missing-native-observer-v1"
REPORT_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_s1_missing_native_observer_request_v1.json"
QUERY_TIMES = (0.3, 0.6, 0.9, 1.2)
EXPECTED_EXISTING = [0, 599, 600, 1199, 1200, 1799, 1800, 2399, 2400]
LABELS = ("dp0_same_cfl", "dp0_half_cfl", "coarse_same_cfl", "fine_same_cfl")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256_file(path),
    }


def native_stat(path: Path) -> dict[str, int]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"native source is missing or symlinked: {path}")
    stat = path.stat()
    return {
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
    }


def write_once(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if path.exists() or path.is_symlink():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(regular(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    proof = load_object(PROOF)
    report = load_object(ROOT152_REPORT)
    if proof.get("request_sha256") != ROOT152_REQUEST_SHA:
        raise ValueError("ROOT152 proof does not bind the expected consumed request")
    if proof.get("report_sha256") != sha256_file(ROOT152_REPORT):
        raise ValueError("ROOT152 report SHA does not match the terminal proof")
    if int(proof.get("additional_native_frame_count", -1)) != 96:
        raise ValueError("ROOT152 proof does not report exactly 96 missing native rows")
    if report.get("status") not in {
        "COMPLETED_SOURCE_ONLY_COMMON_TIME_OUTPUT_READINESS",
        "COMPLETED_BOUNDED_OUTPUT_AND_ASYNC_DIAGNOSTICS_NO_QUALIFICATION",
    }:
        raise ValueError("ROOT152 report status is not a completed source-only bounded status")
    if tuple(report.get("runs", {})) != LABELS:
        raise ValueError("ROOT152 report run labels drifted")
    for label in LABELS:
        proof_run = proof["runs"][label]
        missing = [int(frame) for frame in proof_run["additional_native_frames_needed"]]
        if len(missing) != 24 or len(set(missing)) != 24:
            raise ValueError(f"ROOT152 missing frame set for {label} is not 24 unique rows")
        if int(proof_run["existing_selected_frames"]) != len(EXPECTED_EXISTING):
            raise ValueError(f"ROOT152 existing observer frame count drifted for {label}")
        if [int(value) for value in report["runs"][label]["selected_frame_ids"]] != EXPECTED_EXISTING:
            raise ValueError(f"ROOT152 report selected frame set drifted for {label}")
    return proof, report


def run_source(label: str, proof: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    proof_run = proof["runs"][label]
    report_run = report["runs"][label]
    observer_path = Path(report_run["observer"]["path"]).expanduser().resolve()
    observer = load_object(observer_path)
    source = observer.get("source", {})
    raw_root = regular(Path(str(source["raw_root"]))) if Path(str(source["raw_root"])).is_file() else Path(str(source["raw_root"])).expanduser().resolve()
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise FileNotFoundError(f"raw root is not a regular directory: {raw_root}")
    runparts = regular(Path(str(source["runparts"]["path"])))
    generated_xml = regular(Path(str(source["generated_xml"]["path"])))
    decoder = regular(Path(str(source["decoder"]["path"])))
    decoder_source = regular(DECODER_SOURCE)
    missing = [int(frame) for frame in proof_run["additional_native_frames_needed"]]
    rows = base.read_runparts(runparts)
    if len(rows) != int(report_run["full_runparts_frame_count"]):
        raise ValueError(f"RunPARTs count mismatch for {label}")
    planned_records: list[dict[str, Any]] = []
    for frame in missing:
        path = raw_root / f"Part_{frame:04d}.bi4"
        planned_records.append({"frame": frame, "path": str(path.resolve()), "planned_stat": native_stat(path), "sha256": "PARENT_GUARD_COMPUTED_AFTER_RESERVATION"})
    query_windows = []
    for query in QUERY_TIMES:
        source_window = report_run["query_windows"].get(str(query))
        if source_window is None:
            raise ValueError(f"missing query window {query} for {label}")
        query_windows.append({
            "query_time_s": query,
            "required_native_frame_ids": source_window["required_native_frame_ids"],
            "existing_frame_ids": source_window["existing_selected_frame_ids"],
            "missing_frame_ids": source_window["missing_from_existing_observer"],
            "actual_required_frame_times_s": source_window["required_native_frame_times_s"],
            "bracket": source_window["bracket"],
            "field_interpolation": "NOT_PERFORMED",
        })
    return {
        "schema": "ds02.stage2.f4-s1.missing-native-observer-spec.v1",
        "run_label": label,
        "family_id": "F4",
        "sentinel_id": "F4-S1",
        "physical_case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
        "raw_root": str(raw_root),
        "runparts": record(runparts),
        "generated_xml": record(generated_xml),
        "decoder": record(decoder),
        "decoder_source": record(decoder_source),
        "existing_observer": record(observer_path),
        "existing_frame_ids": EXPECTED_EXISTING,
        "selected_frames": missing,
        "selected_native_frame_records": planned_records,
        "expected_frame_count": len(rows),
        "expected_final_time_s": float(report_run["terminal_time_s"]),
        "final_time_tolerance_s": 1.0e-12,
        "query_times_s": list(QUERY_TIMES),
        "query_windows": query_windows,
        "source_provenance": {
            "root152_proof": record(PROOF),
            "root152_report": record(ROOT152_REPORT),
            "root152_request_sha256": ROOT152_REQUEST_SHA,
            "preparation_reads_native_payload": False,
            "preparation_hashes_native_payload": False,
        },
    }


def canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({key: val for key, val in value.items() if key != "sha256"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build(*, launch_commit: str | None = None) -> dict[str, Any]:
    proof, report = load_inputs()
    for path in (WORKER, BOUNDED_DECODER, BASE_OBSERVER, HEADER_OBSERVER, PYTHON, DISPATCH, STRICT, RUNTIME, DECODER, DECODER_SOURCE, PROOF, ROOT152_REPORT):
        regular(path)
    commit = launch_commit or subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
    request_paths: list[str] = []
    request_records: list[dict[str, Any]] = []
    total_frames = 0
    total_bytes = 0
    total_estimated_read = 0
    for label in LABELS:
        spec = run_source(label, proof, report)
        spec_path = REQUEST_ROOT / f"f4_s1_{label}_missing_native_spec_v1.json"
        write_once(spec_path, spec)
        static_paths = [
            Path(__file__), WORKER, BOUNDED_DECODER, BASE_OBSERVER, HEADER_OBSERVER,
            PYTHON, DISPATCH, STRICT, RUNTIME, DECODER, DECODER_SOURCE,
            PROOF, ROOT152_REPORT, Path(spec["runparts"]["path"]), Path(spec["generated_xml"]["path"]),
            Path(spec["existing_observer"]["path"]), spec_path,
        ]
        static_paths = list(dict.fromkeys(regular(path) for path in static_paths))
        records = {str(path): record(path) for path in static_paths}
        selected_bytes = sum(int(item["planned_stat"]["bytes"]) for item in spec["selected_native_frame_records"])
        estimated_read = 3 * selected_bytes + 64 * 1024 * 1024
        total_frames += len(spec["selected_frames"])
        total_bytes += selected_bytes
        total_estimated_read += estimated_read
        output_name = f"f4_s1_{label}_missing_native_observer_v1.json"
        case_id = f"F4_S1_{label.upper()}_MISSING_NATIVE_OBSERVER_V1"
        attempt_id = f"f4-s1-{label.replace('_', '-')}-missing-native-observer-v1-root-ready-001"
        command = [
            str(PYTHON), str(WORKER.resolve()), "--spec", str(spec_path.resolve()),
            "--output", f"{{attempt_root}}/observer/{output_name}",
            "--scratch-root", "{attempt_root}/scratch/bi4_decode",
            "--decoder-timeout-s", "300", "--max-decoder-log-bytes", str(64 * 1024),
            "--max-decoder-scratch-bytes", str(256 * 1024 * 1024),
        ]
        input_files = list(records)
        request = {
            "schema": REQUEST_SCHEMA,
            "variant_schema": SCHEMA,
            "status": "READY_FOR_PARENT_GUARD",
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "family_id": "F4",
            "sentinel_id": "F4-S1",
            "physical_case_id": spec["physical_case_id"],
            "case_id": case_id,
            "attempt_id": attempt_id,
            "cwd": str(REPO),
            "worktree_root": str(REPO),
            "launch_commit": commit,
            "command": command,
            "input_files": input_files,
            "input_sha256": {path: records[path]["sha256"] for path in input_files},
            "deferred_input_files": [spec["raw_root"], *[item["path"] for item in spec["selected_native_frame_records"]]],
            "deferred_input_policy": {
                "builder_stat_scope": "selected native files only; no payload read or hash",
                "parent_pre_decode_sha_and_complete_stat": "REQUIRED_AFTER_RESERVATION",
                "worker_pre_decode_post_decode_sha_and_complete_stat": "REQUIRED",
                "cross_decode_stat_boundaries": "pre.stat_after == post.stat_before and pre.stat_before == post.stat_after",
                "full_raw_tree_hash": "NOT_COMPUTED",
                "unknown_child_status": "FAILURE",
            },
            "source_binding": {
                "schema": "ds02.stage2.f4-s1.missing-native-observer-binding.v1",
                "spec": str(spec_path.resolve()),
                "run_label": label,
                "root152_proof_sha256": ROOT152_PROOF_SHA,
                "root152_report_sha256": records[str(ROOT152_REPORT)]["sha256"],
                "source_runparts": spec["runparts"],
                "generated_xml": spec["generated_xml"],
                "existing_observer": spec["existing_observer"],
                "raw_root": spec["raw_root"],
                "existing_frame_ids": EXPECTED_EXISTING,
                "selected_missing_frame_ids": spec["selected_frames"],
                "selected_native_frame_records": spec["selected_native_frame_records"],
                "actual_time_source": "RunPARTs.csv and decoder TimeStep; no frame-index time substitution",
                "official_decoder": spec["decoder"],
                "official_decoder_source": spec["decoder_source"],
                "native_field_contract": ["Idp", "Pos_or_Posd", "Vel", "Rhop", "MassFluid_metadata"],
                "mass_semantics": "native MassFluid times XML typed range count; sample diagnostic only",
            },
            "query_times_s": list(QUERY_TIMES),
            "selected_native_frame_ids": spec["selected_frames"],
            "estimated_input_read_bytes": estimated_read,
            "estimated_native_read_bytes": 3 * selected_bytes,
            "estimated_storage_bytes": 1024 * 1024 * 1024,
            "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
            "cpu_threads": 1,
            "omp_threads": 1,
            "max_wall_seconds": 1800,
            "resource_guard": {
                "parent_cpu_binding": "required",
                "parent_storage_binding": "required",
                "gpu": "none",
                "solver_launch": "forbidden",
                "hdf5_read": "forbidden",
                "native_payload_read": "selected 24 files only after reservation",
                "process_group_cancel": "bounded-v2 SIGTERM_then_SIGKILL_then_wait",
                "parent_death_signal": "PR_SET_PDEATHSIG_SIGTERM_best_effort",
                "max_decoder_log_bytes": 64 * 1024,
                "max_decoder_scratch_bytes": 256 * 1024 * 1024,
                "scratch_cleanup": "one temporary decode directory per frame",
            },
            "output": {"atomic": True, "refuse_overwrite": True, "path": f"{{attempt_root}}/observer/{output_name}"},
            "launch_disabled": False,
            "execution_allowed": True,
            "solver_started": False,
            "gencase_launch": False,
            "hdf5_read": False,
            "bi4_decode": True,
            "raw_directory_scan": False,
            "scientific_qualification": {
                "QI": "PENDING_LIMITED_SELECTED_NATIVE_FIELDS",
                "QN": "UNKNOWN_TIME_OUTPUT_AND_SPATIAL_REFERENCE",
                "QE": "UNKNOWN_NO_REGISTERED_CHARACTERISTIC_EVENT_TIME",
            },
            "preparation_note": "Parent may run this request only after source/resource reservation. Builder did stat but did not read or hash native payload; old nine-row observer remains immutable and is not re-decoded.",
        }
        request["sha256"] = canonical(request)
        request_path = REQUEST_ROOT / f"f4_s1_{label}_missing_native_observer_v1_root-ready.json"
        write_once(request_path, request)
        request_paths.append(str(request_path.resolve()))
        request_records.append({"label": label, "request": record(request_path), "spec": record(spec_path), "selected_frame_count": len(spec["selected_frames"]), "selected_native_bytes": selected_bytes, "estimated_native_read_bytes": 3 * selected_bytes})
    summary = {
        "schema": SCHEMA,
        "status": "PREPARED_FOUR_PARENT_READY_REQUESTS",
        "root152_proof": record(PROOF),
        "root152_proof_expected_sha256": ROOT152_PROOF_SHA,
        "root152_report": record(ROOT152_REPORT),
        "request_count": len(request_records),
        "total_selected_frame_count": total_frames,
        "total_selected_native_bytes_by_stat": total_bytes,
        "total_estimated_native_read_bytes": total_estimated_read,
        "requests": request_records,
        "builder_native_payload_read": False,
        "builder_native_payload_hash": False,
        "old_observer_redecoded": False,
        "scientific_qualification": {"QI": "PENDING_LIMITED_SELECTED_NATIVE_FIELDS", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "launch_commit": commit,
    }
    write_once(REPORT_PATH, summary)
    return summary


def self_test() -> dict[str, Any]:
    assert len(LABELS) == 4 and sum(24 for _ in LABELS) == 96
    assert EXPECTED_EXISTING == [0, 599, 600, 1199, 1200, 1799, 1800, 2399, 2400]
    assert QUERY_TIMES == (0.3, 0.6, 0.9, 1.2)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "request_count": 4,
        "selected_frame_count": 96,
        "builder_reads_native_payload": False,
        "builder_hashes_native_payload": False,
        "execution_allowed": True,
        "scientific_qualification": {"QI": "PENDING", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if args.self_test == args.build:
        parser.error("choose exactly one of --self-test or --build")
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    result = build(launch_commit=args.launch_commit)
    print(json.dumps({"status": result["status"], "request_count": result["request_count"], "total_selected_frame_count": result["total_selected_frame_count"], "report": str(REPORT_PATH.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

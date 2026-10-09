#!/usr/bin/env python3
"""Build the launch-disabled bounded F4-S1 v5 metadata-audit request.

The request runs only ``stage2_f4_s1_common_time_output_calibration_v5.py``
over the immutable v1/v4 reports, four selected-observer JSON files, and four
RunPARTs CSV time axes.  It intentionally contains no BI4, PartVTK, HDF5,
solver, decoder, or deferred native-payload input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
WORKER = REFERENCE / "stage2_f4_s1_common_time_output_calibration_v5.py"
V1_REPORT = REFERENCE / "stage2_f4_actual_common_time_calibration_v1.json"
V4_REPORT = REFERENCE / "stage2_f4_late_common_time_calibration_v4.json"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-s1-common-time-output-v5"
REQUEST_PATH = REQUEST_ROOT / "f4_s1_common_time_output_calibration_v5_root-ready.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
LABELS = ("dp0_same_cfl", "dp0_half_cfl", "coarse_same_cfl", "fine_same_cfl")
QUERIES_S = (0.3, 0.6, 0.9, 1.2)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "dev": int(stat.st_dev),
        "ino": int(stat.st_ino),
        "sha256": _sha256(path),
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build() -> tuple[Path, dict[str, Any]]:
    v1 = _load(V1_REPORT)
    v4 = _load(V4_REPORT)
    if v1.get("schema") != "ds02.stage2.f4-actual-common-time-calibration.v1":
        raise ValueError("F4 v1 source schema drift")
    if v4.get("schema") != "ds02.stage2.f4-late-common-time-calibration.v4":
        raise ValueError("F4 v4 source schema drift")
    if v1.get("sentinel_id") != "F4-S1" or v1.get("family_id") != "F4":
        raise ValueError("F4 v1 identity drift")
    if tuple(v1.get("runs", {})) != LABELS or tuple(v4.get("runs", {})) != LABELS:
        raise ValueError("F4 run label set drift")
    paths: list[Path] = [WORKER, V1_REPORT, V4_REPORT]
    source_records: dict[str, Any] = {}
    source_records["worker"] = _record(WORKER)
    source_records["v1_report"] = _record(V1_REPORT)
    source_records["v4_report"] = _record(V4_REPORT)
    run_sources: dict[str, Any] = {}
    for label in LABELS:
        metadata = v1["runs"][label]
        observer = Path(metadata["observer"]["path"]).resolve()
        runparts = Path(metadata["source_runparts"]["path"]).resolve()
        observer_record = _record(observer)
        runparts_record = _record(runparts)
        paths.extend([observer, runparts])
        source_records[f"{label}.observer"] = observer_record
        source_records[f"{label}.runparts"] = runparts_record
        run_sources[label] = {
            "observer": observer_record,
            "runparts": runparts_record,
            "selected_frames": [0, 599, 600, 1199, 1200, 1799, 1800, 2399, 2400],
        }

    input_bytes = sum(int(record["bytes"]) for record in source_records.values())
    attempt_id = "f4-s1-common-time-output-calibration-v5-root-001"
    output_rel = "{attempt_root}/report/f4_s1_common_time_output_calibration_v5.json"
    command = [
        str(PYTHON),
        str(WORKER),
        "--v1-report", str(V1_REPORT),
        "--v4-report", str(V4_REPORT),
        "--output", output_rel,
    ]
    request: dict[str, Any] = {
        "schema": "ds02.request.v1",
        "family_id": "F4",
        "sentinel_id": "F4-S1",
        "case_id": "F4_S1_COMMON_TIME_OUTPUT_CALIBRATION_V5",
        "physical_case_id": v1["physical_case_id"],
        "attempt_id": attempt_id,
        "kind": "cpu",
        "qualification_stage": "stage2_f4_source_only_common_time_output_readiness",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 16 * 1024 * 1024,
        "estimated_peak_memory_bytes": 256 * 1024 * 1024,
        "estimated_input_bytes": input_bytes,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "input_files": [str(path.resolve()) for path in paths],
        "input_hashes": {str(path.resolve()): source_records["worker"]["sha256"] if path == WORKER else source_records["v1_report"]["sha256"] if path == V1_REPORT else source_records["v4_report"]["sha256"] if path == V4_REPORT else source_records[next(key for key, value in source_records.items() if value["path"] == str(path.resolve()))]["sha256"] for path in paths},
        "source_binding": {
            "schema": "ds02.stage2.f4-s1-common-time-output-binding.v5",
            "source_v1_report": source_records["v1_report"],
            "source_v4_report": source_records["v4_report"],
            "run_sources": run_sources,
            "query_times_s": list(QUERIES_S),
            "local_window_radius_frames": 4,
            "subsample_factors": [2, 4],
            "time_axis": "actual RunPARTs timestamps and native Part IDs; no frame-index time substitution",
            "worker_read_scope": {
                "observer_json_and_runparts_only": True,
                "bi4_read": False,
                "partvtk_read": False,
                "hdf5_read": False,
                "full_native_tree_scan": False,
                "interpolation": False,
                "particle_id_pairing": False,
            },
            "input_stability": "worker checks stat+SHA before/read/after for each supplied small input and fails closed on mutation",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "output": {
            "path": output_rel,
            "atomic": True,
            "refuse_overwrite": True,
        },
        "resource_guard": {
            "parent_cpu_binding": "required",
            "parent_storage_binding": "required",
            "gpu": "none",
            "solver_launch": False,
            "native_payload_read": False,
            "hdf5_read": False,
            "launch_disabled": True,
        },
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "preparation_note": "This is a source-only bounded readiness request. A later parent-guarded run may enumerate missing native Part IDs, but this request itself contains no BI4/PartVTK/HDF5 payload and grants no calibration or qualification credit.",
    }
    return REQUEST_PATH, request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    path, request = build()
    if args.self_test:
        assert request["launch_disabled"] is True
        assert request["execution_allowed"] is False
        assert all(Path(item).suffix in {".py", ".json", ".csv"} for item in request["input_files"])
        print(json.dumps({"status": "PASS", "request": str(path), "input_bytes": request["estimated_input_bytes"]}, indent=2))
        return 0
    if not args.build:
        parser.error("--build or --self-test is required")
    _write_once(path, request)
    print(json.dumps({"status": "BUILT_LAUNCH_DISABLED", "request": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build the launch-disabled F1-S1 output calibration comparison request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1-s1-output-resolution-request.v2"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
WORKER = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f1_s1_output_resolution_calibration_v2.py"
)
BUILDER = Path(__file__).resolve()
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DISPATCH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
)
STRICT = DISPATCH.parent / "ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH.parent / "ds_data02_runtime_v4.py"
SOURCE_XML = DATA_ROOT / (
    "F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/"
    "prepared/F1_FALLBACK_ECC_COARSE.xml"
)
SOURCE_GENCASE_RECEIPT = SOURCE_XML.parent.parent / "execution-receipt.json"
RUNPARTS = {
    "same_cfl": DATA_ROOT / (
        "F1_S1_ORIGINAL_SAMECFL_DENSE_SAVEDT_V2/"
        "f1-s1-samecfl-dense-savedt-v2-primary-001-v5/solver_output/RunPARTs.csv"
    ),
    "half_cfl": DATA_ROOT / (
        "F1_S1_ORIGINAL_HALFCFL_DENSE_SAVEDT_V2/"
        "f1-s1-halfcfl-dense-savedt-v2-primary-001-v5/solver_output/RunPARTs.csv"
    ),
}
OBSERVERS = {
    "same_cfl": DATA_ROOT / "f1-s1-dp010-same-cfl-output-calibration-observer-v2-root-001/observer/f1_s1_dp010_same_cfl_output_calibration_observer_v2.json",
    "half_cfl": DATA_ROOT / "f1-s1-dp010-half-cfl-output-calibration-observer-v2-root-001/observer/f1_s1_dp010_half_cfl_output_calibration_observer_v2.json",
}
QUERY_TIMES = (0.0, 0.4, 0.8, 1.2, 1.6)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def build() -> dict[str, Any]:
    observer_args: list[str] = []
    runpart_args: list[str] = []
    for label in ("same_cfl", "half_cfl"):
        observer_args += ["--observer", f"{label}={OBSERVERS[label]}"]
        runpart_args += ["--runparts", f"{label}={RUNPARTS[label]}"]
    output_path = "{attempt_root}/comparison/f1_s1_output_resolution_calibration_v2.json"
    command = [
        str(PYTHON), str(WORKER), *observer_args, *runpart_args,
        *sum((["--query-time", repr(query)] for query in QUERY_TIMES), []),
        "--output", output_path,
    ]
    existing_inputs = [BUILDER, WORKER, PYTHON, DISPATCH, STRICT, RUNTIME, SOURCE_XML, SOURCE_GENCASE_RECEIPT, RUNPARTS["same_cfl"], RUNPARTS["half_cfl"]]
    input_files = [str(path.resolve()) for path in existing_inputs]
    input_hashes = {str(path.resolve()): sha256_file(path) for path in existing_inputs}
    input_files += [str(OBSERVERS[label].resolve()) for label in ("same_cfl", "half_cfl")]
    input_hashes.update({str(OBSERVERS[label].resolve()): "PARENT_V4_GUARD_HASH_REQUIRED" for label in ("same_cfl", "half_cfl")})
    return {
        "schema": "ds02.request.v1",
        "family_id": "F1",
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": "F1_S1_DP010_OUTPUT_RESOLUTION_CALIBRATION_V2",
        "attempt_id": "f1-s1-dp010-output-resolution-calibration-v2-root-001",
        "kind": "cpu",
        "cpu_task_kind": "comparison",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 268435456,
        "estimated_peak_memory_bytes": 536870912,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "qualification_stage": "stage2_f1_s1_output_resolution_calibration_pending_parent_observer_outputs",
        "source_binding": {
            "schema": SCHEMA,
            "sentinel_id": "F1-S1",
            "family_id": "F1",
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
            "cfl_variants": ["same_cfl", "half_cfl"],
            "query_times_s": list(QUERY_TIMES),
            "local_window_radius_frames": 4,
            "subsample_factors": [2, 4],
            "observer_outputs": {label: str(OBSERVERS[label].resolve()) for label in ("same_cfl", "half_cfl")},
            "comparison_semantics": "actual v2 MK-explicit weighted fluid aggregates versus local 2x/4x saved-row reconstruction; no field/time/physical error claim",
            "mk_semantics": "mkfluid_relative and mk_absolute are retained separately in v2 observer sidecars; aggregate fluid comparison never joins them",
            "pressure_status": "NOT_DECODED_BY_OBSERVER_WORKER",
        },
        "input_files": input_files,
        "input_hashes": input_hashes,
        "deferred_input_files": [str(OBSERVERS[label].resolve()) for label in ("same_cfl", "half_cfl")],
        "deferred_hash_policy": "parent v4 hashes completed v2 observer outputs before comparison; no BI4/H5 payload read by this worker",
        "depends_on": [
            str((REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s1-output-calibration-v2/f1_s1_dp010_same_cfl_output_calibration_observer_v2.json").resolve()),
            str((REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s1-output-calibration-v2/f1_s1_dp010_half_cfl_output_calibration_observer_v2.json").resolve()),
        ],
        "output": {"path": output_path, "atomic": True, "refuse_overwrite": True},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "launch_disabled": True,
        },
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite request: {output}")
    value = build()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    print(json.dumps({"output": str(output), "query_times_s": list(QUERY_TIMES)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

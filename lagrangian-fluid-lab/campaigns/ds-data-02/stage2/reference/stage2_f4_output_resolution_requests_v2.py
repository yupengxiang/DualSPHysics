#!/usr/bin/env python3
"""Prepare bounded F4 output-resolution decode and comparison requests.

The four decode requests use the existing native observer worker on only the
local frames around 0.3, 0.6, 0.9 and 1.2 s.  A fifth CPU request consumes the
small selected-observer JSON outputs and compares 2x/4x local row
subsampling.  All requests are launch-disabled and explicitly retain UNKNOWN
scientific qualification.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-output-resolution-v2"
CALIBRATION_REPORT = REFERENCE / "stage2_f4_late_common_time_calibration_v3.json"
V1_REPORT = REFERENCE / "stage2_f4_actual_common_time_calibration_v1.json"
DECODE_WORKER = REFERENCE / "stage2_native_physical_observer_v1.py"
COMPARE_WORKER = REFERENCE / "stage2_f4_output_resolution_calibration_v1.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py")
STRICT = DISPATCH.parent / "ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH.parent / "ds_data02_runtime_v4.py"
QUERIES = (0.3, 0.6, 0.9, 1.2)
WINDOW_RADIUS_FRAMES = 4
LABELS = ("dp0_same_cfl", "dp0_half_cfl", "coarse_same_cfl", "fine_same_cfl")


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


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def read_runparts(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(lines, delimiter=";"):
        part = (row.get("Part") or "").strip()
        if part.isdigit():
            rows.append({"frame": int(part), "time_s": float((row.get("TimeStep [s]") or "").strip())})
    if not rows or [row["frame"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs is not contiguous: {path}")
    return rows


def bracket(rows: list[dict[str, Any]], query: float) -> tuple[int, int]:
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        raise ValueError(f"query {query} outside {rows[0]['time_s']}..{rows[-1]['time_s']}")
    for index, row in enumerate(rows):
        if abs(row["time_s"] - query) <= 1.0e-12:
            return row["frame"], row["frame"]
        if row["time_s"] > query:
            return rows[index - 1]["frame"], row["frame"]
    raise AssertionError(query)


def selected_frames(rows: list[dict[str, Any]]) -> tuple[list[int], dict[str, Any]]:
    selected: set[int] = set()
    bindings: dict[str, Any] = {}
    for query in QUERIES:
        lower, upper = bracket(rows, query)
        start = max(0, upper - WINDOW_RADIUS_FRAMES)
        end = min(len(rows) - 1, upper + WINDOW_RADIUS_FRAMES)
        local = list(range(start, end + 1))
        selected.update(local)
        bindings[str(query)] = {
            "lower_frame": lower,
            "upper_frame": upper,
            "local_frame_start": start,
            "local_frame_end": end,
            "local_frame_count": len(local),
            "lower_time_s": rows[lower]["time_s"],
            "upper_time_s": rows[upper]["time_s"],
        }
    return sorted(selected), bindings


def base_guard() -> dict[str, Any]:
    return {
        "owner": "stage2-reference-preparation",
        "runner": str(DISPATCH),
        "strict_guard": str(STRICT),
        "runtime": str(RUNTIME),
        "cpu_parent_binding": "required",
        "gpu": "none",
        "solver_launch": "forbidden",
        "hdf5_read": "forbidden",
        "launch_disabled": True,
    }


def write(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_decode(label: str, meta: dict[str, Any]) -> tuple[Path, dict[str, Any], Path]:
    runparts = Path(meta["source_runparts"]["path"]).resolve()
    generated_xml = Path(meta["source_generated_xml"]["path"]).resolve()
    rows = read_runparts(runparts)
    frames, bindings = selected_frames(rows)
    raw_root = runparts.parent / "data"
    compact = label.replace("_", "-")
    case_id = f"F4_S1_{label.upper()}_LOCAL_OUTPUT_CALIBRATION_NATIVE_V1"
    attempt_id = f"f4-s1-{compact}-local-output-calibration-native-v1-root-001"
    output_rel = f"{{attempt_root}}/observer/f4_s1_{label}_local_output_calibration_native_v1.json"
    command = [
        str(PYTHON), str(DECODE_WORKER),
        "--raw-root", str(raw_root),
        "--runparts", str(runparts),
        "--generated-xml", str(generated_xml),
        "--decoder", str(DECODER),
        "--output", output_rel,
        "--scratch-root", "{attempt_root}/scratch/bi4_decode",
        "--expected-frame-count", str(len(rows)),
        "--expected-final-time-s", repr(rows[-1]["time_s"]),
        "--final-time-tolerance-s", "1e-12",
        "--frames", *(str(frame) for frame in frames),
        "--query-times", *(repr(query) for query in QUERIES),
    ]
    text_inputs = [DECODE_WORKER, PYTHON, DISPATCH, STRICT, RUNTIME, runparts, generated_xml, CALIBRATION_REPORT, V1_REPORT]
    input_hashes = {str(path.resolve()): sha256_file(path) for path in text_inputs}
    input_hashes[str(DECODER.resolve())] = "PARENT_V4_GUARD_HASH_REQUIRED"
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F4",
        "case_id": case_id,
        "sentinel_id": "F4-S1",
        "physical_case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
        "attempt_id": attempt_id,
        "kind": "cpu",
        "qualification_stage": "stage2_f4_local_output_calibration_native_pending_parent_cpu_guard",
        "cpu_task_kind": "native_observer",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 2400,
        "estimated_storage_bytes": 1073741824,
        "estimated_peak_memory_bytes": 1073741824,
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_SELECTED_FRAME_BYTES",
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "source_binding": {
            "schema": "ds02.stage2.f4-local-output-calibration-native-binding.v2",
            "label": label,
            "source_runparts": record(runparts),
            "generated_xml": record(generated_xml),
            "calibration_plan_report": record(CALIBRATION_REPORT),
            "raw_root": str(raw_root),
            "full_frame_count": len(rows),
            "selected_frame_ids": frames,
            "query_bindings": bindings,
            "window_radius_frames": WINDOW_RADIUS_FRAMES,
            "time_axis": "actual RunPARTs; no frame-index time substitution",
        },
        "query_times_s": list(QUERIES),
        "selected_native_frame_ids": frames,
        "input_files": [str(path.resolve()) for path in [*text_inputs, DECODER]],
        "input_hashes": input_hashes,
        "deferred_input_files": [str(raw_root), *[str(raw_root / f"Part_{frame:04d}.bi4") for frame in frames]],
        "deferred_hash_policy": "parent v4 hashes selected Part files only immediately before bounded decode; no full native tree scan",
        "output": {
            "path": output_rel,
            "refuse_overwrite": True,
            "atomic": True,
            "native_observer_fields": ["position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"],
        },
        "resource_guard": base_guard(),
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    path = REQUEST_ROOT / f"decode_{label}.json"
    output_path = REPO / f"stage2-runtime-placeholder/{attempt_id}/observer/f4_s1_{label}_local_output_calibration_native_v1.json"
    return path, request, output_path


def build_compare(metas: dict[str, dict[str, Any]], decode_paths: dict[str, Path], decode_outputs: dict[str, Path]) -> tuple[Path, dict[str, Any]]:
    observer_args: list[str] = []
    runpart_args: list[str] = []
    input_files = [COMPARE_WORKER, PYTHON, DISPATCH, STRICT, RUNTIME, CALIBRATION_REPORT, V1_REPORT]
    input_hashes = {str(path.resolve()): sha256_file(path) for path in input_files}
    for label in LABELS:
        observer_args += ["--observer", f"{label}={decode_outputs[label]}"]
        runparts = Path(metas[label]["source_runparts"]["path"]).resolve()
        runpart_args += ["--runparts", f"{label}={runparts}"]
        input_files.append(runparts)
        input_hashes[str(runparts)] = sha256_file(runparts)
        input_files.append(decode_paths[label])
        input_hashes[str(decode_paths[label].resolve())] = sha256_file(decode_paths[label])
    output_rel = "{attempt_root}/comparison/f4_s1_output_resolution_calibration_v1.json"
    command = [str(PYTHON), str(COMPARE_WORKER), *observer_args, *runpart_args,
               *sum((["--query-time", repr(query)] for query in QUERIES), []),
               "--output", output_rel]
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F4",
        "case_id": "F4_S1_OUTPUT_RESOLUTION_CALIBRATION_V1",
        "sentinel_id": "F4-S1",
        "physical_case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
        "attempt_id": "f4-s1-output-resolution-calibration-v1-root-001",
        "kind": "cpu",
        "qualification_stage": "stage2_f4_output_resolution_calibration_pending_parent_selected_observer_outputs",
        "cpu_task_kind": "comparison",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 268435456,
        "estimated_peak_memory_bytes": 536870912,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "source_binding": {
            "schema": "ds02.stage2.f4-output-resolution-calibration-binding.v2",
            "calibration_plan_report": record(CALIBRATION_REPORT),
            "grid_labels": list(LABELS),
            "query_times_s": list(QUERIES),
            "subsample_factors": [2, 4],
            "local_window_radius_frames": WINDOW_RADIUS_FRAMES,
            "observer_outputs": {label: str(decode_outputs[label]) for label in LABELS},
            "comparison_semantics": "actual weighted fluid observables on selected native rows versus linear reconstruction after local 2x/4x row retention; no physical error or QI/QN/QE claim",
        },
        "input_files": [str(path.resolve()) for path in input_files],
        "input_hashes": input_hashes,
        "deferred_input_files": [str(decode_outputs[label]) for label in LABELS],
        "deferred_hash_policy": "parent v4 hashes completed selected observer JSON outputs before comparison; no H5/native payload read",
        "output": {"path": output_rel, "refuse_overwrite": True, "atomic": True},
        "resource_guard": base_guard(),
        "depends_on": [str(decode_paths[label]) for label in LABELS],
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return REQUEST_ROOT / "compare_output_resolution.json", request


def build_all() -> list[Path]:
    report = load(CALIBRATION_REPORT)
    v1_report = load(V1_REPORT)
    if report.get("schema") != "ds02.stage2.f4-late-common-time-calibration.v3":
        raise ValueError("corrected F4 late calibration v3 is required")
    if v1_report.get("schema") != "ds02.stage2.f4-actual-common-time-calibration.v1":
        raise ValueError("F4 actual common-time v1 source binding is required")
    # v3 intentionally carries the corrected budget semantics and actual
    # RunPART brackets, while v1 carries the exact generated-XML/source paths
    # needed to make a new native decode request source-bound.
    metas = v1_report["runs"]
    decode_paths: dict[str, Path] = {}
    decode_outputs: dict[str, Path] = {}
    outputs: list[Path] = []
    for label in LABELS:
        path, value, _ = build_decode(label, metas[label])
        write(path, value)
        outputs.append(path)
        decode_paths[label] = path
        decode_outputs[label] = Path(value["output"]["path"].replace("{attempt_root}", f"/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/{value['attempt_id']}"))
    path, value = build_compare(metas, decode_paths, decode_outputs)
    write(path, value)
    outputs.append(path)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if not args.build:
        parser.error("--build is required")
    print(json.dumps({"requests": [str(path) for path in build_all()]}, indent=2))


if __name__ == "__main__":
    main()

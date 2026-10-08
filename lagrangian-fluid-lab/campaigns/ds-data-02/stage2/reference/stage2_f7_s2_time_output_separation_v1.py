#!/usr/bin/env python3
"""Prepare a bounded metadata-only F7-S2 time/output error separation.

The actual F7-S2 same-CFL run has 1201 native saved frames through
12.00003209155591 s.  Its half-CFL request is source-bound but has no
terminal F7-S2 receipt in this checkout yet.  This worker consumes only the
small RunPARTs/receipt/XML/overlay-manifest/request files.  It never opens a
BI4/H5/Part file and never compares a different F7 physical case as a
surrogate half-CFL result.

The report separates three questions before any field comparison:

* saved-output resolution: actual RunPARTs times and query brackets;
* integration control: CFL/control metadata and saved-window dt summaries;
* physical observer error: deliberately UNKNOWN until a consumer validates
  decoded fields at common physical times.

``--build`` writes one v8 CPU request.  ``--run`` is called by that request;
the parent process remains the only dispatcher.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA = "ds02.stage2.f7-s2-time-output-separation.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPORT_SCHEMA = "ds02.stage2.f7-s2-time-output-separation-report.v1"

REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python").resolve()
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
V6_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
V2_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"

SAME_REQUEST = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "f7-nvme-counterpart-v5-root-001/f7-s2-same-cfl-nvme-request-v5-001.json"
)
SAME_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001/"
    "execution-receipt.json"
)
SAME_RUNPARTS = Path(
    "/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/"
    "f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/RunPARTs.csv"
)
HALF_REQUEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-priority-four-savedt-v2/f7_s2_half_cfl_savedt_v2.json"
SAME_XML = REFERENCE / "stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/F7_OBSTACLE_QUINTIC_B08_A065_same_cfl_savedt.xml"
HALF_XML = REFERENCE / "stage2_savedt_cfl_pair_inputs_v1/F7_S2/half_cfl/F7_OBSTACLE_QUINTIC_B08_A065_half_cfl_savedt.xml"
SAME_MANIFEST = SAME_XML.with_name("overlay-manifest.json")
HALF_MANIFEST = HALF_XML.with_name("overlay-manifest.json")
SAME_MOTION = SAME_XML.with_name("motion_obstacle_quintic.dat")
HALF_MOTION = HALF_XML.with_name("motion_obstacle_quintic.dat")

CASE_ID = "F7_S2_TIME_OUTPUT_SEPARATION_METADATA_V1"
ATTEMPT_ID = "f7-s2-time-output-separation-v1-root-001"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f7-s2-time-output-separation-v1"
REQUEST_PATH = REQUEST_DIR / "f7_s2_time_output_separation_v1.json"
OUTPUT_REPORT = "{attempt_root}/report/f7_s2_time_output_separation_v1.json"

QUERY_TIMES_S = [0.0, 3.0, 6.0, 9.0, 12.0]
TIME_OUTPUT_TASK_FRACTION = 0.25


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an existing regular file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular_file(path, label)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable output: {path}")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def number(value: str) -> float:
    value = value.strip().replace(",", "")
    return float(value)


def parse_runparts(path: Path) -> dict[str, Any]:
    """Read the small RunPARTs summary, never native particle data."""
    path = regular_file(path, "RunPARTs.csv")
    with path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    header_index = next((i for i, row in enumerate(rows) if row and row[0].strip() == "Part"), None)
    if header_index is None:
        raise ValueError(f"RunPARTs header missing: {path}")
    header = rows[header_index]
    indices = {name: i for i, name in enumerate(header)}
    required = ["Part", "TimeStep [s]", "Steps", "DTsMin", "DtMin [s]", "DtMax [s]"]
    if any(name not in indices for name in required):
        raise ValueError(f"RunPARTs required columns missing: {path}")
    data: list[dict[str, float]] = []
    for row in rows[header_index + 1:]:
        if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
            continue
        try:
            data.append({
                "part": number(row[indices["Part"]]),
                "time_s": number(row[indices["TimeStep [s]"]]),
                "steps": number(row[indices["Steps"]]),
                "dtsmin_count": number(row[indices["DTsMin"]]),
                "dtmin_s": number(row[indices["DtMin [s]"]]),
                "dtmax_s": number(row[indices["DtMax [s]"]]),
            })
        except (ValueError, IndexError) as exc:
            raise ValueError(f"non-numeric RunPARTs row in {path}: {row[:6]}") from exc
    if not data:
        raise ValueError(f"RunPARTs has no numeric rows: {path}")
    times = [row["time_s"] for row in data]
    if times[0] != 0.0 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError(f"RunPARTs times are not strictly increasing from zero: {path}")
    intervals = [b - a for a, b in zip(times, times[1:])]
    positive_dtmin = [row["dtmin_s"] for row in data if row["dtmin_s"] > 0.0]
    positive_dtmax = [row["dtmax_s"] for row in data if row["dtmax_s"] > 0.0]
    return {
        "source": record(path, "RunPARTs.csv"),
        "rows": len(data),
        "first_part": int(data[0]["part"]),
        "last_part": int(data[-1]["part"]),
        "first_time_s": times[0],
        "last_time_s": times[-1],
        "part_ids_contiguous": all(int(b["part"]) == int(a["part"]) + 1 for a, b in zip(data, data[1:])),
        "saved_intervals_s": {
            "count": len(intervals),
            "min": min(intervals) if intervals else None,
            "max": max(intervals) if intervals else None,
            "mean": statistics.fmean(intervals) if intervals else None,
        },
        "reported_steps_sum": int(sum(row["steps"] for row in data)),
        "reported_dtsmin_count_sum": int(sum(row["dtsmin_count"] for row in data)),
        "reported_dt_summary_s": {
            "positive_min_of_windows": min(positive_dtmin) if positive_dtmin else None,
            "positive_max_of_windows": max(positive_dtmax) if positive_dtmax else None,
        },
        "query_brackets": query_brackets(times),
        "trace_scope": "RunPARTs save-window summaries; not a complete per-step dt trace",
    }


def query_brackets(times: list[float]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for query in QUERY_TIMES_S:
        if query < times[0] or query > times[-1]:
            result.append({"query_time_s": query, "status": "OUT_OF_RANGE", "interpolation": "NOT_PERFORMED"})
            continue
        exact = next((i for i, value in enumerate(times) if abs(value - query) <= 1e-12), None)
        if exact is not None:
            result.append({"query_time_s": query, "status": "EXACT_SAVED_ROW", "native_row_index": exact, "native_time_s": times[exact], "interpolation": "NOT_PERFORMED"})
            continue
        upper = next(i for i, value in enumerate(times) if value > query)
        lower = upper - 1
        result.append({
            "query_time_s": query,
            "status": "BRACKETED_SAVED_ROWS",
            "lower_native_row_index": lower,
            "lower_time_s": times[lower],
            "upper_native_row_index": upper,
            "upper_time_s": times[upper],
            "interpolation": "NOT_PERFORMED",
        })
    return result


def xml_parameters(path: Path) -> dict[str, str]:
    root = ET.parse(regular_file(path, "overlay XML")).getroot()
    return {
        str(node.get("key")): str(node.get("value"))
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "parameter" and node.get("key") is not None
    }


def manifest_controls(path: Path) -> dict[str, Any]:
    manifest = json.loads(regular_file(path, "overlay manifest").read_text(encoding="utf-8"))
    proof = manifest.get("xml_diff_proof", {})
    return {
        "mode": manifest.get("mode"),
        "source_cfl_values": proof.get("source_cfl_values"),
        "overlay_cfl_values": proof.get("overlay_cfl_values"),
        "cfl_replacements": proof.get("cfl_replacements"),
        "parsed_non_savedt_tree_equivalent": proof.get("parsed_non_savedt_tree_equivalent"),
        "savedt_values": proof.get("savedt_values"),
        "declared_text_edits": proof.get("declared_text_edits"),
    }


def request_status(path: Path, expected_output: Path) -> dict[str, Any]:
    request = json.loads(regular_file(path, "solver request").read_text(encoding="utf-8"))
    terminal = expected_output / "execution-receipt.json"
    status: dict[str, Any] = {
        "request": record(path, "solver request"),
        "case_id": request.get("case_id"),
        "attempt_id": request.get("attempt_id"),
        "physical_case_id": request.get("physical_case_id"),
        "command": request.get("command"),
        "execution_allowed": request.get("execution_allowed"),
        "solver_started": request.get("solver_started"),
        "terminal_receipt": None,
        "terminal_status": "PENDING_TERMINAL_RECEIPT",
    }
    if terminal.is_file():
        receipt = json.loads(terminal.read_text(encoding="utf-8"))
        status["terminal_receipt"] = record(terminal, "terminal receipt")
        status["terminal_status"] = receipt.get("status", "UNKNOWN")
        status["terminal_qualification"] = receipt.get("qualification")
    return status


def build_report(output_path: Path) -> dict[str, Any]:
    same_receipt = json.loads(regular_file(SAME_RECEIPT, "F7 same-CFL receipt").read_text(encoding="utf-8"))
    same_runs = parse_runparts(SAME_RUNPARTS)
    same_xml_controls = xml_parameters(SAME_XML)
    half_xml_controls = xml_parameters(HALF_XML)
    same_overlay = manifest_controls(SAME_MANIFEST)
    half_overlay = manifest_controls(HALF_MANIFEST)
    half_expected = DATA_ROOT / "families/F7/F7_S2_ORIGINAL_HALFCFL_DENSE_SAVEDT_V2/f7_s2-original-halfcfl-dense-savedt-v2-root-002"
    # The exact expected output is also present in the immutable half request;
    # derive it from request identity rather than guessing a completed path.
    half_req = json.loads(regular_file(HALF_REQUEST, "F7 half-CFL request").read_text(encoding="utf-8"))
    half_expected = DATA_ROOT / "families" / "F7" / str(half_req["case_id"]) / str(half_req["attempt_id"])
    same_expected = DATA_ROOT / "families/F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001"
    same_status = {
        "receipt": record(SAME_RECEIPT, "F7 same-CFL receipt"),
        "status": same_receipt.get("status"),
        "cfd_invoked": same_receipt.get("cfd_invoked"),
        "source_content_verified": same_receipt.get("source_validation", {}).get("content_verified"),
        "qualification": same_receipt.get("qualification"),
        "request_reference": record(SAME_REQUEST, "F7 same-CFL request"),
        "raw_output_path_from_receipt": same_receipt.get("filesystem", {}).get("output_root"),
        "expected_data_root_attempt_exists": same_expected.exists(),
    }
    half_status = request_status(HALF_REQUEST, half_expected)
    if half_status["terminal_receipt"] is None:
        half_status["terminal_status"] = "PENDING_CONSUMER_QA_OR_TERMINAL_RECEIPT"

    same_cfl = same_overlay.get("overlay_cfl_values")
    half_cfl = half_overlay.get("overlay_cfl_values")
    controls = {
        "same": {"xml_parameters": same_xml_controls, "overlay": same_overlay, "cfl_values": same_cfl},
        "half": {"xml_parameters": half_xml_controls, "overlay": half_overlay, "cfl_values": half_cfl},
        "physical_source_control_closure": {
            "same_motion_sha256": sha256(SAME_MOTION),
            "half_motion_sha256": sha256(HALF_MOTION),
            "motion_bytes_equal": sha256(SAME_MOTION) == sha256(HALF_MOTION),
            "non_cfl_xml_tree_equivalent_claim": {
                "same": same_overlay.get("parsed_non_savedt_tree_equivalent"),
                "half": half_overlay.get("parsed_non_savedt_tree_equivalent"),
            },
            "status": "SOURCE_BOUND_METADATA_ONLY; effective CFL change is numeric integration condition",
        },
    }
    return {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETED_METADATA_ONLY_HALF_PENDING" if half_status["terminal_receipt"] is None else "COMPLETED_METADATA_ONLY_BOTH_TERMINAL_NEEDS_CONSUMER_QA",
        "family_id": "F7",
        "sentinel_id": "F7-S2",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "scope": "F7-S2 actual same-CFL 1201-frame RunPARTs plus source-bound half-CFL request status; no native field decode",
        "actual_same_cfl": {"execution": same_status, "runparts": same_runs},
        "half_cfl": half_status,
        "controls": controls,
        "frozen_task_tolerances": {
            "position": {"fraction_of_characteristic_length": 0.02, "status": "PRE_REGISTERED_NOT_EVALUATED"},
            "event_neighborhood": {"fraction_of_local_length": 0.05, "status": "PRE_REGISTERED_NOT_EVALUATED"},
            "velocity_and_kinetic_energy": {"fraction_of_nonzero_scale": 0.05, "status": "PRE_REGISTERED_NOT_EVALUATED"},
            "whole_initial_fluid_mass": {"fraction": 0.03, "status": "PRE_REGISTERED_NOT_EVALUATED"},
            "event_time": {"fraction_of_characteristic_time": 0.01, "status": "UNKNOWN_EVENT_SCALE"},
            "time_integration_and_output": {"budget_share_of_task_tolerance": TIME_OUTPUT_TASK_FRACTION, "status": "BUDGET_ONLY_NOT_PASS_FAIL"},
        },
        "error_separation": {
            "spatial_grid_error": "NOT_ASSESSED; this report uses one F7-S2 dp=.020 source",
            "time_integration_error": "PENDING_HALF_TERMINAL_AND_CONSUMER_QA; RunPARTs window dt summaries are not a full per-step trace",
            "output_sampling_error": "ACTUAL_SAME_RUN_BRACKETS_ONLY; no interpolation and no field credit",
            "physical_observer_error": "UNKNOWN; no native/typed field comparison performed",
            "cross_case_half_evidence": "EXCLUDED; F7-S1 half-dt products are not F7-S2 physical identity",
        },
        "next_executable_scope": {
            "after_half_terminal": "decode only pre-registered actual native rows around query times [0,3,6,9,12] with source-enforcer and compare weighted physical observables at exact/bracketed RunPARTs times",
            "output_calibration": "same completed dense run: choose actual saved rows and 2x/4x decimated rows at registered windows; compare decoded observables without interpolating across unequal times",
            "qualification": "QI/QN/QE remain UNKNOWN until consumer calibration and field comparison",
        },
        "no_raw_read": True,
        "no_h5_read": True,
        "no_bi4_read": True,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def input_paths() -> list[Path]:
    paths = [
        Path(__file__), PYTHON, RUNNER, STRICT, RUNTIME, V6_RUNTIME, V2_RUNTIME,
        QUALITY, SAME_REQUEST, SAME_RECEIPT, SAME_RUNPARTS,
        HALF_REQUEST, SAME_XML, HALF_XML, SAME_MANIFEST, HALF_MANIFEST,
        SAME_MOTION, HALF_MOTION,
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if str(path) not in seen:
            regular_file(path, "request input")
            seen.add(str(path))
            unique.append(path)
    return unique


def build_request() -> dict[str, Any]:
    if REQUEST_PATH.exists():
        raise FileExistsError(REQUEST_PATH)
    output_root = DATA_ROOT / "families/F7" / CASE_ID / ATTEMPT_ID
    if output_root.exists():
        raise FileExistsError(output_root)
    inputs = input_paths()
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F7",
        "sentinel_id": "F7-S2",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "qualification_stage": "stage2_f7_s2_time_output_separation_metadata_pending_parent_v8_dispatch",
        "command": [str(PYTHON), str(Path(__file__).resolve()), "--run", "--output", OUTPUT_REPORT],
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": [str(path) for path in inputs],
        "input_hashes": {str(path): sha256(path) for path in inputs},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_native_read_bytes": 0,
        "estimated_storage_bytes": 32 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(RUNNER),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "v6_runtime": str(V6_RUNTIME),
            "v2_runtime": str(V2_RUNTIME),
            "parent_cpu_guard_required": True,
            "gpu": "none",
            "gpu_uuid": "none",
            "solver_launch": "forbidden",
            "new_solver": False,
            "hdf5_read": "forbidden",
            "bi4_read": "forbidden",
            "raw_particle_read": "forbidden; RunPARTs.csv summary is the only data stream read",
            "launch_disabled": False,
            "parent_v8_review_required": True,
        },
        "output": {"atomic": True, "refuse_overwrite": True, "path": OUTPUT_REPORT, "scope": "small RunPARTs/control/error-separation JSON only"},
        "output_protection": {"attempt_root_must_not_exist_at_dispatch": True, "refuse_overwrite": True},
        "source_binding": {
            "schema": "ds02.stage2.f7-s2-time-output-separation-binding.v1",
            "same_cfl": {"request": str(SAME_REQUEST.resolve()), "receipt": str(SAME_RECEIPT.resolve()), "runparts": str(SAME_RUNPARTS.resolve()), "overlay_manifest": str(SAME_MANIFEST.resolve())},
            "half_cfl": {"request": str(HALF_REQUEST.resolve()), "overlay_manifest": str(HALF_MANIFEST.resolve()), "terminal": "must be independently present before half comparison; absent now is explicit PENDING"},
            "motion_dependency": "same SHA-bound motion table; no cross-family substitution",
            "query_times_s": QUERY_TIMES_S,
            "interpolation": "forbidden in this metadata worker",
        },
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "cfd_invoked": False,
        "hdf5_read": False,
        "bi4_read": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REQUEST_PATH, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.build == args.run:
        parser.error("choose exactly one of --build or --run")
    if args.build:
        print(json.dumps(build_request(), ensure_ascii=False, indent=2))
        return 0
    if args.output is None:
        parser.error("--run requires --output")
    report = build_report(args.output)
    atomic_json(args.output, report)
    print(json.dumps({"status": "completed", "report": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare source-bound F4 physical-observer comparison requests.

The completed coarse, same-CFL, and half-CFL runs are compared only through
the actual RunPARTs time axis.  The worker decodes selected native frames and
reports fields by XML particle ranges; it never pairs particle IDs across
grids, infers rigid-body mass, or replaces the immutable native arrays.  The
fine slot remains a real preflight gap until a terminal GenCase XML/receipt
and a full-window solver receipt exist.

This builder reads small XML/JSON/RunPARTs/Run.out/observer sidecars and stats
selected native files without reading their payloads.  It creates only
launch-disabled CPU observer requests for the coarse and half-CFL runs.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f4-physical-observer-calibration-plan.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4")
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_CPP = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_physical_observer_v1.py"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PHYSICAL_CASE_ID = "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
QUERY_TIMES = [0.0, 0.3, 0.6, 0.9, 1.2]
TIME_TOLERANCE = 1.0e-10
COMMON_WINDOW = [0.0, 1.2]
COARSE_REQUEST = REQUEST_ROOT / "stage2-full-window-canary-v1/f4_s1_coarse_dp00123_same_cfl_dense.json"
SAME_REQUEST = REQUEST_ROOT / "stage2-f4-dp0-savedt-pair-v1/same_cfl.json"
HALF_REQUEST = REQUEST_ROOT / "stage2-f4-dp0-savedt-pair-v1/half_cfl.json"
FINE_PREFLIGHT_REQUEST = REQUEST_ROOT / "stage2-remaining-sentinel-spatial-preflight-v1/f4_s1_spatial_v1_fine_dp0p008000.json"
SAME_OBSERVER_OUTPUT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_S1_DP0_SAME_CFL_SELECTED_PHYSICAL_OBSERVER_V2/"
    "f4-s1-dp0-same-cfl-selected-observer-primary-001/observer/"
    "f4_s1_dp0_selected_physical_observer.json"
)
OUTPUT_DIR = REQUEST_ROOT / "stage2-f4-physical-observer-forward-v1"
PLAN_PATH = REFERENCE / "stage2_f4_physical_observer_calibration_plan_v1.json"

OUTPUT_ROOTS = {
    "coarse": DATA_ROOT / "F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2/f4-s1-full-window-coarse-dp01230-v4-primary-001",
    "same_cfl": DATA_ROOT / "F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2/f4-s1-dp0-savedt-same_cfl-primary-001",
    "half_cfl": DATA_ROOT / "F4_S1_DP0_SAVEDT_HALF_CFL_DENSE_T1P2/f4-s1-dp0-savedt-half_cfl-primary-001",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, content_hash: bool = True) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    value: dict[str, Any] = {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if content_hash:
        value["sha256"] = sha256_file(path)
    return value


def stat_only(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        return {"path": str(path), "exists": False, "bytes": None, "mtime_ns": None,
                "sha256": "PARENT_V4_GUARD_REQUIRED_BEFORE_DISPATCH"}
    stat = path.stat()
    return {"path": str(path), "exists": True, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": "PARENT_V4_GUARD_REQUIRED_BEFORE_DISPATCH"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def xml_meta(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find(".//geometry/definition")
    particles = root.find(".//particles")
    constants = root.find(".//constants")
    if definition is None or particles is None or constants is None:
        raise ValueError(f"incomplete F4 XML: {path}")
    cfl = root.find(".//constants/cflnumber")
    mass_node = constants.find("massfluid")
    blocks = []
    for node in particles:
        kind = node.tag.rsplit("}", 1)[-1].lower()
        if kind in {"fixed", "moving", "floating", "fluid"} and node.get("begin") is not None and node.get("count") is not None:
            blocks.append({
                "kind": kind,
                "mk": node.get("mkfluid") if kind == "fluid" else node.get("mk"),
                "begin": int(node.get("begin")),
                "count": int(node.get("count")),
            })
    parameters: dict[str, Any] = {}
    for node in root.findall(".//parameters/parameter"):
        if node.get("key") and node.get("value") is not None:
            raw = node.get("value")
            try:
                value: Any = float(raw)
            except ValueError:
                value = raw
            parameters[node.get("key")] = int(value) if isinstance(value, float) and value.is_integer() else value
    geometry = root.find(".//geometry/commands")
    motion = root.find(".//casedef/motion")
    motion_text = "ABSENT_IN_SOURCE_XML" if motion is None else ET.tostring(motion, encoding="unicode")
    if motion is not None:
        motion_copy = ET.fromstring(motion_text)
        for node in motion_copy.iter():
            if node.tag.rsplit("}", 1)[-1].lower() == "file":
                node.attrib.pop("name", None)
        motion_text = ET.tostring(motion_copy, encoding="unicode")
    fluid_count = sum(item["count"] for item in blocks if item["kind"] == "fluid")
    return {
        "file": record(path),
        "dp_m": float(definition.get("dp")) if definition.get("dp") else None,
        "cfl": float(cfl.get("value")) if cfl is not None else None,
        "parameters": parameters,
        "particles": int(particles.get("np")) if particles.get("np") else None,
        "blocks": blocks,
        "fluid_particle_count": fluid_count,
        "massfluid_kg": float(mass_node.get("value")) if mass_node is not None else None,
        "fluid_sample_mass_kg": fluid_count * float(mass_node.get("value")) if mass_node is not None else None,
        "geometry_hash": hashlib.sha256(ET.tostring(geometry, encoding="unicode").encode()).hexdigest() if geometry is not None else None,
        "motion_hash": hashlib.sha256(motion_text.encode()).hexdigest(),
        "motion_semantics": motion_text,
        "gravity_m_s2": [
            float(node.get(axis, "nan"))
            for axis in ("x", "y", "z")
            for node in root.findall(".//constantsdef/gravity")
        ][:3],
    }


def parse_runparts(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or not lines[0].startswith("Part;TimeStep [s];Steps"):
        raise ValueError(f"unexpected RunPARTs header: {path}")
    rows = []
    for line in lines[1:]:
        if line and line[0].isdigit():
            values = line.split(";")
            rows.append({"part": int(values[0]), "time_s": float(values[1]), "steps": int(values[2])})
    if not rows or [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs parts are not contiguous: {path}")
    return rows


def parse_runout(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    clamp = re.search(r"DTs adjusted to DtMin\.*:\s*([0-9,]+)", text)
    steps = re.search(r"Steps of simulation\.*:\s*([0-9,]+)", text)
    return {
        "aggregate_dtmin_clamps": int(clamp.group(1).replace(",", "")) if clamp else "UNKNOWN",
        "reported_steps": int(steps.group(1).replace(",", "")) if steps else "UNKNOWN",
    }


def bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    times = [row["time_s"] for row in rows]
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW", "actual_window_s": [times[0], times[-1]]}
    right = bisect.bisect_left(times, query)
    if right == 0:
        return {"query_time_s": query, "status": "EXACT_OR_LEFT", "lower_frame": 0, "upper_frame": 0,
                "lower_time_s": times[0], "upper_time_s": times[0]}
    if right == len(times):
        right -= 1
    if abs(times[right] - query) <= TIME_TOLERANCE:
        return {"query_time_s": query, "status": "EXACT", "lower_frame": rows[right]["part"], "upper_frame": rows[right]["part"],
                "lower_time_s": times[right], "upper_time_s": times[right]}
    left = right - 1
    return {
        "query_time_s": query,
        "status": "BRACKETED",
        "lower_frame": rows[left]["part"],
        "upper_frame": rows[right]["part"],
        "lower_time_s": times[left],
        "upper_time_s": times[right],
        "bracket_width_s": times[right] - times[left],
        "interpolation_fraction": (query - times[left]) / (times[right] - times[left]),
    }


def selected_stats(raw_root: Path, frames: list[int]) -> list[dict[str, Any]]:
    return [{"frame": frame, **stat_only(raw_root / f"Part_{frame:04d}.bi4")} for frame in frames]


def compact_observation(observation: dict[str, Any]) -> dict[str, Any]:
    fluid = observation.get("fluid_observables", {})
    by_mk = observation.get("groups", {}).get("fluid", {}).get("by_mk", {})
    return {
        "frame": observation.get("frame"),
        "decoded_time_s": observation.get("time", {}).get("decoded_s"),
        "identity": observation.get("identity"),
        "finite_fields": observation.get("finite_fields"),
        "fluid": {
            "sample_mass_kg": fluid.get("sample_mass_kg"),
            "centroid_m": fluid.get("centroid_m"),
            "mean_velocity_m_per_s": fluid.get("mean_velocity_m_per_s"),
            "density_mean": fluid.get("density", {}).get("mean"),
            "kinetic_energy_j": fluid.get("kinetic_energy_j"),
        },
        "fluid_by_mk": {
            str(mk): {
                "count": item.get("count"),
                "sample_mass_kg": item.get("sample_mass_kg"),
                "centroid_m": item.get("centroid_m"),
                "mean_velocity_m_per_s": item.get("mean_velocity_m_per_s"),
                "density_mean": item.get("density", {}).get("mean"),
                "kinetic_energy_j": item.get("kinetic_energy_j"),
            }
            for mk, item in by_mk.items()
        },
    }


def actual_observer_compact(path: Path) -> dict[str, Any]:
    result = load_json(path)
    query_rows = []
    for query in result.get("time_window", {}).get("queries", []):
        query_rows.append({
            "query_time_s": query.get("query_time_s"),
            "status": query.get("status"),
            "lower_frame": query.get("lower_frame"),
            "upper_frame": query.get("upper_frame"),
            "lower_time_s": query.get("lower_time_s"),
            "upper_time_s": query.get("upper_time_s"),
            "lower_observation": compact_observation(query["lower_observation"]) if query.get("lower_observation") else None,
            "upper_observation": compact_observation(query["upper_observation"]) if query.get("upper_observation") else None,
        })
    return {
        "status": result.get("status"),
        "output": record(path),
        "scope": result.get("scope"),
        "time_window": {
            "first_saved_time_s": result.get("time_window", {}).get("first_saved_time_s"),
            "last_saved_time_s": result.get("time_window", {}).get("last_saved_time_s"),
            "queries": query_rows,
        },
        "mass_semantics": result.get("mass_semantics"),
    }


def get_source_and_effective(request: dict[str, Any], grid: str) -> tuple[Path, Path, dict[str, Any]]:
    binding = request.get("source_binding", {})
    if grid == "coarse":
        source = Path(binding["identity"]["current_source_xml"]["file"]["path"])
        effective = Path(binding["candidate_gencase"]["generated_xml"]["file"]["path"])
    else:
        source = Path(binding["source_xml"]["path"])
        effective = Path(binding["overlay_xml"]["path"])
    return source, effective, binding


def build_completed(grid: str, request_path: Path, output_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    request = load_json(request_path)
    source_xml, effective_xml, binding = get_source_and_effective(request, grid)
    output_root = output_root.resolve()
    receipt_path = output_root / "execution-receipt.json"
    runparts_path = output_root / "solver_output/RunPARTs.csv"
    runout_path = output_root / "solver_output/Run.out"
    raw_root = output_root / "solver_output/data"
    receipt = load_json(receipt_path)
    rows = parse_runparts(runparts_path)
    runout = parse_runout(runout_path)
    brackets = [bracket(rows, query) for query in QUERY_TIMES]
    frames = sorted({frame for item in brackets for frame in (item.get("lower_frame"), item.get("upper_frame")) if frame is not None})
    source_meta = xml_meta(source_xml)
    effective_meta = xml_meta(effective_xml)
    requested_window = request.get("physical_window_s") or binding.get("full_physical_window_s")
    actual_window = [rows[0]["time_s"], rows[-1]["time_s"]]
    endpoint_delta = actual_window[1] - requested_window[1]
    endpoint_status = (
        "ACTUAL_ENDPOINT_REACHED"
        if endpoint_delta >= -TIME_TOLERANCE
        else "QUERY_1P2_COVERED_ENDPOINT_SHORTFALL_RETAINED"
        if actual_window[1] >= QUERY_TIMES[-1] - TIME_TOLERANCE
        else "QUERY_WINDOW_NOT_COVERED"
    )
    selected = selected_stats(raw_root, frames)
    mass_delta = effective_meta["fluid_sample_mass_kg"] - source_meta["fluid_sample_mass_kg"]
    mass_fraction = abs(mass_delta) / source_meta["fluid_sample_mass_kg"] if source_meta["fluid_sample_mass_kg"] else None
    request_input_files = [
        WORKER, DECODER, DECODER_CPP, PYTHON, source_xml, effective_xml,
        receipt_path, runparts_path, runout_path, request_path,
    ]
    request_input_hashes = {str(path.resolve()): sha256_file(path) for path in request_input_files}
    request_input_files_s = [str(path.resolve()) for path in request_input_files]
    request_name = "f4_s1_coarse_same_cfl" if grid == "coarse" else "f4_s1_dp0_half_cfl"
    request_json = OUTPUT_DIR / f"{request_name}_selected_physical_observer.json"
    command = [
        str(PYTHON), str(WORKER),
        "--raw-root", str(raw_root),
        "--runparts", str(runparts_path),
        "--generated-xml", str(effective_xml),
        "--decoder", str(DECODER),
        "--output", "{attempt_root}/observer/f4_s1_selected_physical_observer.json",
        "--scratch-root", "{attempt_root}/scratch/bi4_decode",
        "--expected-frame-count", str(len(rows)),
        "--expected-final-time-s", repr(actual_window[1]),
        "--final-time-tolerance-s", "1e-12",
        "--frames", *(str(frame) for frame in frames),
        "--query-times", *(repr(query) for query in QUERY_TIMES),
    ]
    launch_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                                   capture_output=True, text=True).stdout.strip()
    observer_request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "F4",
        "case_id": f"F4_S1_{'COARSE' if grid == 'coarse' else 'DP0_HALF_CFL'}_SELECTED_PHYSICAL_OBSERVER_FORWARD_V1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": f"{request_name}-selected-physical-observer-forward-v1-root-001",
        "kind": "cpu",
        "qualification_stage": "stage2_selected_native_field_observer_pending_parent_cpu_guard",
        "cpu_task_kind": "conversion",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "estimated_peak_memory_bytes": 384 * 1024 * 1024,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "candidate_solver_receipt": str(receipt_path),
        "candidate_solver_receipt_sha256": sha256_file(receipt_path),
        "source_binding": {
            "schema": "ds02.stage2.f4-physical-observer-forward-binding.v1",
            "sentinel_id": "F4-S1",
            "family_id": "F4",
            "physical_case_id": PHYSICAL_CASE_ID,
            "grid": grid,
            "cfl_mode": request.get("source_binding", {}).get("overlay_diff", {}).get("mode", request.get("source_binding", {}).get("grid", "UNKNOWN")),
            "source_xml": record(source_xml),
            "effective_xml": record(effective_xml),
            "source_request": record(request_path),
            "solver_receipt": record(receipt_path),
            "runparts": record(runparts_path),
            "runout": record(runout_path),
            "source_window_s": requested_window,
            "actual_saved_window_s": actual_window,
            "actual_endpoint_status": endpoint_status,
            "source_controls": {
                "source_cfl": source_meta["cfl"],
                "effective_cfl": effective_meta["cfl"],
                "source_parameters": source_meta["parameters"],
                "effective_parameters": effective_meta["parameters"],
                "geometry_hash_equal": source_meta["geometry_hash"] == effective_meta["geometry_hash"],
                "motion_hash_equal": source_meta["motion_hash"] == effective_meta["motion_hash"],
            },
            "initial_sample_mass_audit": {
                "source_fluid_sample_mass_kg": source_meta["fluid_sample_mass_kg"],
                "effective_fluid_sample_mass_kg": effective_meta["fluid_sample_mass_kg"],
                "delta_kg": mass_delta,
                "absolute_fraction_of_source": mass_fraction,
                "whole_initial_3pct_status": "PASS_DIAGNOSTIC_ONLY" if mass_fraction is not None and mass_fraction <= 0.03 else "HARD_FAIL_OR_UNKNOWN",
                "continuum_mass": "UNKNOWN_NOT_SUBSTITUTED",
                "particle_mass_rescale": False,
            },
            "native_source_role": "immutable source; worker selected frames only; parent guard must hash selected payloads",
        },
        "observer_scope": {
            "selected_frames": frames,
            "query_times_s": QUERY_TIMES,
            "query_brackets": brackets,
            "decoded_fields": ["Idp", "Pos/Posd", "Vel", "Rhop"],
            "observables": ["identity", "position", "velocity", "density", "fluid sample mass", "fluid centroid", "fluid mean velocity", "fluid kinetic energy"],
            "particle_field_interpolation": "NOT_PERFORMED; compare aggregate observables only after consumer registers bracket policy",
            "full_trajectory_observer": "SEPARATE_PARENT_GUARDED_PASS_REQUIRED",
            "typed_conversion": "NOT_PERFORMED",
            "hdf5": "NOT_READ_OR_CREATED",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "selected_payload_inputs": {
            "records": selected,
            "bytes_estimate": sum(int(item.get("bytes") or 0) for item in selected),
            "hash_policy": "parent v4 guard content-hashes selected Part files before dispatch; preparation stats only",
            "full_tree_hash": "NOT_COMPUTED_BY_PREPARATION_OR_WORKER",
        },
        "input_files": request_input_files_s,
        "input_hashes": request_input_hashes,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "consumed_runtime": str(RUNTIME_V2),
            "launch_commit": launch_commit,
            "cpu_parent_binding": "required",
            "cpu_only": True,
            "gpu_uuid": "NONE",
            "solver_launch": "forbidden",
            "estimated_raw_payload_read_bytes": sum(int(item.get("bytes") or 0) for item in selected),
        },
        "scope": {
            "sentinel_id": "F4-S1",
            "physical_case_id": PHYSICAL_CASE_ID,
            "full_native_window_retained": True,
            "selected_field_observer_only": True,
            "solver_started_by_preparation": False,
            "reads_hdf5": False,
            "reads_native_payloads_in_preparation": False,
            "launch_disabled": True,
            "execution_allowed": False,
            "scientific_qualification": "UNKNOWN",
        },
        "launch_commit": launch_commit,
        "launch_disabled": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "primary_gpu_dispatch_required": False,
        "dispatch_status": "PENDING_PARENT_CPU_GUARD_REVIEW",
        "do_not_execute_from_preparation_worktree": True,
    }
    study = {
        "grid": grid,
        "status": "ACTUAL_NATIVE_WINDOW_METADATA_READY_OBSERVER_PENDING",
        "request": record(request_path),
        "source_xml": record(source_xml),
        "effective_xml": record(effective_xml),
        "solver_receipt": record(receipt_path),
        "runparts": record(runparts_path),
        "runout": record(runout_path),
        "source_meta": source_meta,
        "effective_meta": effective_meta,
        "actual_saved_window_s": actual_window,
        "requested_window_s": requested_window,
        "endpoint_delta_s": endpoint_delta,
        "endpoint_status": endpoint_status,
        "runout_clamp_count": runout["aggregate_dtmin_clamps"],
        "runout_reported_steps": runout["reported_steps"],
        "queries": brackets,
        "selected_frames": frames,
        "selected_payload_stat_bytes": sum(int(item.get("bytes") or 0) for item in selected),
        "prepared_request": str(request_json.resolve()),
        "observer_status": "PENDING_PARENT_CPU_GUARD",
    }
    return study, observer_request


def build_fine_slot() -> dict[str, Any]:
    request = load_json(FINE_PREFLIGHT_REQUEST)
    scope = request.get("scope", {})
    source_identity = scope.get("continuous_source_identity", {})
    return {
        "grid": "fine",
        "status": "NOT_READY_NO_TERMINAL_FINE_GENCASE_OR_SOLVER_OUTPUT",
        "dp_m": scope.get("intentional_resolution_variation", {}).get("dp_m", 0.008),
        "preflight_request": record(FINE_PREFLIGHT_REQUEST),
        "preflight_case_id": request.get("case_id"),
        "preflight_attempt_id": request.get("attempt_id"),
        "continuous_source_xml": source_identity.get("generated_xml"),
        "generated_xml": "UNKNOWN_UNTIL_FINE_GUARDED_GENCASE_TERMINAL_RECEIPT",
        "solver_output": "UNKNOWN_NOT_STARTED",
        "observer_request": "BLOCKED_UNTIL_SOURCE_BOUND_FINE_SOLVER_RECEIPT_AND_RUNPARTS",
        "full_window_required_s": COMMON_WINDOW,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build_plan() -> tuple[dict[str, Any], list[tuple[Path, dict[str, Any]]]]:
    coarse_study, coarse_request = build_completed("coarse", COARSE_REQUEST, OUTPUT_ROOTS["coarse"])
    same_study, _same_request = build_completed("same_cfl", SAME_REQUEST, OUTPUT_ROOTS["same_cfl"])
    half_study, half_request = build_completed("half_cfl", HALF_REQUEST, OUTPUT_ROOTS["half_cfl"])
    same_observer = actual_observer_compact(SAME_OBSERVER_OUTPUT)
    launch_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                                   capture_output=True, text=True).stdout.strip()
    source_xml = Path(same_study["source_xml"]["path"])
    source_meta = same_study["source_meta"]
    plan = {
        "schema": SCHEMA,
        "status": "SOURCE_BOUND_F4_OBSERVER_COMPARISON_PREPARED_NO_NEW_LAUNCH",
        "current_head": launch_commit,
        "physical_identity": {
            "sentinel_id": "F4-S1",
            "family_id": "F4",
            "physical_case_id": PHYSICAL_CASE_ID,
            "source_xml": record(source_xml),
            "source_role": "immutable F4-S1 centered drop source",
        },
        "common_query_registration": {
            "query_times_s": QUERY_TIMES,
            "common_query_scope_s": COMMON_WINDOW,
            "time_policy": "actual RunPARTs brackets; no frame-index pairing, particle-ID pairing, extrapolation, or worker field interpolation",
            "query_1p2_endpoint_rule": "a saved time >=1.2 is required; source endpoint shortfalls are retained and never filled by extrapolation",
        },
        "worker_binding": {
            "worker": record(WORKER),
            "decoder": record(DECODER),
            "decoder_source": record(DECODER_CPP),
            "fields": ["Idp", "Pos/Posd", "Vel", "Rhop"],
            "observables": ["identity", "position", "velocity", "density", "fluid sample mass", "fluid centroid", "fluid mean velocity", "fluid kinetic energy"],
            "mass_rule": "particle sample mass only; do not substitute particle sum for continuum or rigid-body mass",
            "full_native_scan": "NOT_PERFORMED_BY_SELECTED_WORKER",
        },
        "grid_studies": {
            "coarse": coarse_study,
            "same_cfl": same_study,
            "half_cfl": half_study,
            "fine": build_fine_slot(),
        },
        "actual_same_cfl_selected_observer": same_observer,
        "comparison_design": {
            "spatial": {
                "pairing": "compare XML-defined material groups and macro observables at common physical query times; never pair native particle IDs across dp",
                "reports": ["per-kind/per-mk count", "sample mass", "mass-weighted centroid", "mean velocity", "density distribution", "kinetic energy", "finite/identity checks"],
                "intentional_variations": ["dp", "h", "massfluid", "particle count", "lattice phase", "particle block begin/count"],
            },
            "temporal": {
                "same_vs_half": "separate numerical controls; half-CFL aggregate DtMin clamps and endpoint shortfall remain diagnostics",
                "bracket_error": "report lower/upper actual times and bracket width; aggregate interpolation is a consumer decision and does not create native fields",
                "dense_selected_observer_limit": "five query times/selected frames cannot establish event-time or output-resolution convergence",
                "full_trajectory_next": "parent-guarded one-pass macro-observable decode over all 2401 native frames for each available grid; retain raw source",
            },
            "output": {
                "native": "immutable complete native tree remains primary array source",
                "typed": "selected query anchors only until separate typed request; no H5 created here",
                "downsample": "derived after raw retention; no solver replacement",
                "full_time_observer": "required for trajectory/event claims; selected-frame result is development evidence only",
            },
            "control_and_material": {
                "same_cfl_xml_cfl": source_meta["cfl"],
                "half_cfl_xml_cfl": half_study["effective_meta"]["cfl"],
                "coarse_xml_cfl": coarse_study["effective_meta"]["cfl"],
                "geometry_hash_policy": "must match source XML; numerical resolution fields may differ",
                "sample_mass_policy": "whole-initial source fraction <=0.03 is a diagnostic budget only; no mass rescaling; scientific qualification UNKNOWN",
            },
        },
        "frozen_error_budgets": {
            "position_macro_time_rmse_fraction_of_reference_length": 0.02,
            "position_event_max_fraction_of_reference_length": 0.05,
            "velocity_or_kinetic_energy_nonzero_reference_scale_fraction": 0.05,
            "region_mass_or_source_flux_absolute_fraction_of_source_initial": 0.03,
            "event_time_width_or_drift_fraction_of_characteristic_time": 0.01,
            "time_discretization_budget_fraction_of_total_event_gate": 0.25,
            "output_observer_budget_fraction_of_total_event_gate": 0.25,
            "status": "PRE_REGISTERED_THRESHOLDS; consumer must supply reference scales and event definitions before qualification",
            "source": "review-source/QUALITY_LABEL_SPLIT_ZH.md",
        },
        "conditional_precontact_com_gravity_anchor": {
            "status": "CONDITIONAL_PRECONTACT_ONLY_NOT_EVALUATED",
            "source_gravity_m_s2": source_meta["gravity_m_s2"],
            "source_motion_declaration": "ABSENT_IN_SOURCE_XML",
            "formula": "COM(t)=COM(t0)+V_COM(t0)*(t-t0)+0.5*g*(t-t0)^2",
            "applicable_only_if": [
                "the selected material group is identified by XML range and remains isolated before first contact",
                "all boundary/contact/kernel-support distances and group-to-group contacts are measured as clear for the window",
                "no moving boundary, periodic, inlet/outlet, damping, or other external control acts on the group",
                "gravity remains the only external acceleration and particle exclusions are zero",
                "initial COM and velocity come from the decoded native frame using particle sample mass semantics",
            ],
            "invalid_after": ["first contact", "boundary interaction", "particle exclusion", "moving/periodic/control event", "unknown contact state"],
            "required_observer_evidence": ["per-group COM/velocity", "boundary/contact distance or explicit contact flag", "finite/identity status", "actual saved-time bracket"],
            "mass_limit": "an analytical COM anchor calibrates the observer operator only; it does not validate SPH dynamics, rigid-body mass, or post-contact behavior",
        },
        "resource_and_launch": {
            "new_solver_started": False,
            "new_gpu_started": False,
            "new_h5_read": False,
            "selected_requests_launch_disabled": True,
            "parent_guard_required": True,
            "selected_payload_hash_policy": "parent v4 guard hashes selected Part files immediately before any CPU observer dispatch",
            "full_trajectory_pass": "not launched; requires parent I/O reservation and complete raw-read cost review",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return plan, [(OUTPUT_DIR / "f4_s1_coarse_same_cfl_selected_physical_observer.json", coarse_request),
                  (OUTPUT_DIR / "f4_s1_dp0_half_cfl_selected_physical_observer.json", half_request)]


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        raise SystemExit("use --prepare; outputs refuse overwrite")
    plan, requests = build_plan()
    for path, value in requests:
        atomic_json(path, value)
    atomic_json(PLAN_PATH, plan)
    print(json.dumps({
        "status": plan["status"],
        "plan": str(PLAN_PATH),
        "requests": [str(path) for path, _ in requests],
        "same_observer_status": plan["actual_same_cfl_selected_observer"]["status"],
        "coarse_query_status": plan["grid_studies"]["coarse"]["endpoint_status"],
        "half_query_status": plan["grid_studies"]["half_cfl"]["endpoint_status"],
        "fine_status": plan["grid_studies"]["fine"]["status"],
        "solver_started": False,
        "hdf5_read": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

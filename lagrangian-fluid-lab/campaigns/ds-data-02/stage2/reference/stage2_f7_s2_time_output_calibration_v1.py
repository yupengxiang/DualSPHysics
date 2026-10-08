#!/usr/bin/env python3
"""Prepare bounded F7 same/half-CFL time and output calibration.

This is a forward-only preparation entry point.  The manufactured trajectory
checks the interpolation implementation on the *actual* irregular RunPARTs
brackets; it is not a physical solution and cannot grant a solver or grid
qualification.  The native requests select the bracket endpoints and their
immediate neighbours from each completed F7 run.  A parent guard may hash and
decode those selected Part files later.  This module never opens a BI4 file,
reads HDF5, starts a solver, or hashes a raw directory.

The native contract deliberately separates three quantities:

* the saved-time bracket width (an output/time-alignment fact),
* the manufactured linear-interpolation error (an algorithm self-test), and
* same-index field differences between same and half CFL (an integrator/output
  diagnostic, which remains unknown until the selected fields are decoded).

No neighbouring-run difference is treated as truth for another grid, and no
field interpolation is performed by the eventual observer worker.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
MANIFEST_SCHEMA = "ds02.stage2.native-observer-source-manifest.v1"
SCHEMA = "ds02.stage2.f7-s2.time-output-calibration.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SNAPSHOT_WORKER = REFERENCE / "stage2_native_source_snapshot_v2.py"
OBSERVER = REFERENCE / "stage2_native_physical_observer_v2.py"
ENFORCER = REFERENCE / "stage2_native_physical_observer_enforcer_v2.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
V8_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
V8_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
V8_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
V6_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
V2_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
CALIBRATION_CONTRACT = REFERENCE / "stage2_f7_s2_observer_calibration_contract_v3.json"
REPORT_PATH = REFERENCE / "stage2_f7_s2_time_output_calibration_v1.json"
REQUEST_DIR = REQUEST_ROOT / "stage2-f7-s2-time-output-calibration-v1"
PART_RE = re.compile(r"^Part_(\d+)\.bi4$")
QUERY_TIMES_S = [0.0, 3.0, 6.0, 9.0, 12.0]
NEIGHBOR_RADIUS = 1
PHYSICAL_CASE = "F7_OBSTACLE_QUINTIC_B08_A065"
FAMILY = "F7"
SENTINEL = "F7-S2"


SOURCES: dict[str, dict[str, Path | str]] = {
    "same_cfl": {
        "mode": "same_cfl",
        "raw_root": Path("/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/data"),
        "runparts": Path("/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/RunPARTs.csv"),
        "solver_receipt": DATA_ROOT / "families/F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json",
        "solver_request": MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/f7-nvme-counterpart-v5-root-001/f7-s2-same-cfl-nvme-request-v5-001.json",
        "overlay_xml": REFERENCE / "stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/F7_OBSTACLE_QUINTIC_B08_A065_same_cfl_savedt.xml",
        "overlay_manifest": REFERENCE / "stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/overlay-manifest.json",
    },
    "half_cfl": {
        "mode": "half_cfl",
        "raw_root": Path("/var/tmp/ds02-stage2/F7/F7_S2_HALF_CFL_SAVEDT_V7/f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/solver_output/data"),
        "runparts": Path("/var/tmp/ds02-stage2/F7/F7_S2_HALF_CFL_SAVEDT_V7/f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/solver_output/RunPARTs.csv"),
        "solver_receipt": DATA_ROOT / "families/F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/execution-receipt.json",
        "solver_request": MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/f7-half-cfl-v7-root-prepared-001/f7-s2-half-cfl-solver-v6-root-forward-001.json",
        "overlay_xml": REFERENCE / "stage2_savedt_cfl_pair_inputs_v1/F7_S2/half_cfl/F7_OBSTACLE_QUINTIC_B08_A065_half_cfl_savedt.xml",
        "overlay_manifest": REFERENCE / "stage2_savedt_cfl_pair_inputs_v1/F7_S2/half_cfl/overlay-manifest.json",
    },
}

CURRENT_XML = DATA_ROOT / "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/root-stage1-f7-angle065-genuine-gencase-085/prepared/F7_OBSTACLE_QUINTIC_B08_A065.xml"
GENCASE_RECEIPT = DATA_ROOT / "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/root-stage1-f7-angle065-genuine-gencase-085/execution-receipt.json"
OWNER = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_064_stage1_target_angle_full601_native099_nvme_typed_v1/owners/F7_OBSTACLE_QUINTIC_B08_A065.owner.json")
MOTION = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/motion_obstacle_quintic.dat")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular non-symlink file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
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


def parse_runparts(path: Path, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with regular(path, label).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for raw in reader:
            if not raw or not raw.get("Part"):
                continue
            try:
                frame = int(raw["Part"].strip().replace(",", ""))
                time_s = float(raw["TimeStep [s]"])
                steps = int(raw.get("Steps", "0").strip().replace(",", "")) if raw.get("Steps") else 0
            except (KeyError, TypeError, ValueError):
                # RunPARTs may have a trailing comment/status row.  It is not a
                # saved native frame and is excluded explicitly.
                continue
            if not math.isfinite(time_s) or not math.isfinite(float(steps)):
                raise ValueError(f"{label} has a non-finite row")
            rows.append({"frame": frame, "time_s": time_s, "steps": steps})
    if not rows or [row["frame"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"{label} frames are not contiguous zero-based saved rows")
    times = [row["time_s"] for row in rows]
    if abs(times[0]) > 1e-12 or any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError(f"{label} times are not strictly increasing from zero")
    return rows


def bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    times = [row["time_s"] for row in rows]
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUT_OF_RANGE", "field_interpolation": "FORBIDDEN"}
    if abs(query - times[0]) <= 1e-12:
        return {"query_time_s": query, "status": "EXACT_OR_LEFT", "lower_frame": 0, "upper_frame": 0,
                "lower_time_s": times[0], "upper_time_s": times[0], "bracket_width_s": 0.0,
                "field_interpolation": "FORBIDDEN"}
    for upper in range(1, len(rows)):
        if times[upper] >= query:
            lower = upper - 1
            if abs(times[upper] - query) <= 1e-12:
                return {"query_time_s": query, "status": "EXACT", "lower_frame": upper, "upper_frame": upper,
                        "lower_time_s": times[upper], "upper_time_s": times[upper], "bracket_width_s": 0.0,
                        "field_interpolation": "FORBIDDEN"}
            return {"query_time_s": query, "status": "BRACKETED", "lower_frame": lower, "upper_frame": upper,
                    "lower_time_s": times[lower], "upper_time_s": times[upper],
                    "bracket_width_s": times[upper] - times[lower],
                    "bracket_fraction": (query - times[lower]) / (times[upper] - times[lower]),
                    "field_interpolation": "FORBIDDEN"}
    raise AssertionError("query bracket search did not terminate")


def selected_neighborhood(rows: list[dict[str, Any]], query_times: list[float], radius: int = NEIGHBOR_RADIUS) -> tuple[list[int], list[dict[str, Any]]]:
    brackets = [bracket(rows, query) for query in query_times]
    selected: set[int] = set()
    for item in brackets:
        if item["status"] not in {"EXACT", "EXACT_OR_LEFT", "BRACKETED"}:
            continue
        low = int(item["lower_frame"])
        high = int(item["upper_frame"])
        selected.update(range(max(0, low - radius), min(len(rows) - 1, high + radius) + 1))
    frames = sorted(selected)
    if not frames or any(frame < 0 or frame >= len(rows) for frame in frames):
        raise ValueError("selected neighborhood is empty or outside RunPARTs")
    return frames, brackets


def source_config(mode: str) -> dict[str, Any]:
    if mode not in SOURCES:
        raise ValueError(f"unknown F7 mode: {mode}")
    source = {key: Path(value) if isinstance(value, Path) else value for key, value in SOURCES[mode].items()}
    rows = parse_runparts(source["runparts"], f"{mode} RunPARTs")
    if len(rows) != 1201 or rows[-1]["frame"] != 1200:
        raise ValueError(f"{mode} expected 1201 saved rows through frame 1200")
    frames, brackets = selected_neighborhood(rows, QUERY_TIMES_S)
    return {"mode": mode, "source": source, "rows": rows, "frames": frames, "brackets": brackets}


def trajectory(t: float) -> dict[str, Any]:
    """A deterministic smooth manufactured path, used only for interpolation QA."""
    if not math.isfinite(t):
        raise ValueError("manufactured time must be finite")
    x = [
        0.17 + 0.011 * t + 0.0023 * t * t + 0.00011 * t * t * t,
        -0.08 + 0.019 * math.sin(0.43 * t) + 0.0007 * t * t,
        0.31 + 0.013 * math.cos(0.37 * t) + 0.0011 * t,
    ]
    v = [
        0.011 + 0.0046 * t + 0.00033 * t * t,
        0.019 * 0.43 * math.cos(0.43 * t) + 0.0014 * t,
        -0.013 * 0.37 * math.sin(0.37 * t) + 0.0011,
    ]
    energy = 0.5 * sum(component * component for component in v)
    return {"position_m": x, "velocity_m_per_s": v, "kinetic_energy_j": energy}


def lerp(left: Any, right: Any, fraction: float) -> Any:
    if isinstance(left, list):
        return [lerp(a, b, fraction) for a, b in zip(left, right)]
    return (1.0 - fraction) * float(left) + fraction * float(right)


def abs_error(left: Any, right: Any) -> Any:
    if isinstance(left, list):
        return [abs_error(a, b) for a, b in zip(left, right)]
    return abs(float(left) - float(right))


def max_value(value: Any) -> float:
    if isinstance(value, list):
        return max(max_value(item) for item in value)
    return float(value)


def state_lerp(left: dict[str, Any], right: dict[str, Any], fraction: float) -> dict[str, Any]:
    return {
        "position_m": lerp(left["position_m"], right["position_m"], fraction),
        "velocity_m_per_s": lerp(left["velocity_m_per_s"], right["velocity_m_per_s"], fraction),
        "kinetic_energy_j": lerp(left["kinetic_energy_j"], right["kinetic_energy_j"], fraction),
    }


def calibration_contract() -> dict[str, Any]:
    contract = load_object(CALIBRATION_CONTRACT, "F7 observer calibration contract")
    if contract.get("schema") != "ds02.stage2.f7-s2.observer-calibration-contract.v3":
        raise ValueError("unexpected F7 calibration contract schema")
    # The existing contract's quarter shares are budget allocations, never
    # gates.  Copy the source contract by value so this report cannot silently
    # change a frozen tolerance after observations exist.
    return contract


def manufactured_report(contexts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    contract = calibration_contract()
    source_reports: dict[str, Any] = {}
    for mode, context in contexts.items():
        rows = context["rows"]
        entries: list[dict[str, Any]] = []
        for item in context["brackets"]:
            if item["status"] == "OUT_OF_RANGE":
                entries.append({"query_time_s": item["query_time_s"], "status": "UNKNOWN_OUT_OF_RANGE"})
                continue
            if item["status"] in {"EXACT", "EXACT_OR_LEFT"}:
                exact = trajectory(float(item["query_time_s"]))
                entries.append({**item, "manufactured_error": {"position_linf_m": 0.0,
                                                                   "velocity_linf_m_per_s": 0.0,
                                                                   "kinetic_energy_abs_j": 0.0},
                                "manufactured_truth": exact, "manufactured_linear_value": exact})
                continue
            lower = trajectory(float(item["lower_time_s"]))
            upper = trajectory(float(item["upper_time_s"]))
            truth = trajectory(float(item["query_time_s"]))
            interp = state_lerp(lower, upper, float(item["bracket_fraction"]))
            error = {
                "position_linf_m": max_value(abs_error(interp["position_m"], truth["position_m"])),
                "velocity_linf_m_per_s": max_value(abs_error(interp["velocity_m_per_s"], truth["velocity_m_per_s"])),
                "kinetic_energy_abs_j": abs_error(interp["kinetic_energy_j"], truth["kinetic_energy_j"]),
            }
            entries.append({**item, "manufactured_truth": truth, "manufactured_linear_value": interp,
                            "manufactured_error": error})
        source_reports[mode] = {
            "runparts": record(context["source"]["runparts"], f"{mode} RunPARTs"),
            "row_count": len(rows),
            "last_saved_time_s": rows[-1]["time_s"],
            "selected_neighborhood_radius": NEIGHBOR_RADIUS,
            "selected_native_frame_ids": context["frames"],
            "query_brackets": entries,
            "selected_native_paths_are_deferred": True,
        }
    errors = [
        entry["manufactured_error"]
        for source in source_reports.values()
        for entry in source["query_brackets"]
        if "manufactured_error" in entry
    ]
    scales = contract.get("scales", {})
    return {
        "schema": SCHEMA,
        "status": "PREPARED_MANUFACTURED_INTERPOLATION_AND_NATIVE_NEIGHBOR_CONTRACT",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_code": record(Path(__file__), "calibration source"),
        "physical_identity": {"family_id": FAMILY, "sentinel_id": SENTINEL, "physical_case_id": PHYSICAL_CASE},
        "query_times_s": QUERY_TIMES_S,
        "frozen_observer_calibration_contract": contract,
        "manufactured_trajectory": {
            "status": "ALGORITHM_ONLY_NOT_PHYSICAL_TRUTH",
            "definition": "smooth analytic position with analytic derivative; scalar is 0.5*sum(v_i^2)",
            "purpose": "test linear interpolation on each actual irregular RunPARTs bracket",
            "source_times": "each completed same/half RunPARTs.csv, no Part/BI4 read",
            "normalization_scales_copied_for_diagnostic_only": scales,
            "maximum_errors": {
                "position_linf_m": max((item["position_linf_m"] for item in errors), default=0.0),
                "velocity_linf_m_per_s": max((item["velocity_linf_m_per_s"] for item in errors), default=0.0),
                "kinetic_energy_abs_j": max((item["kinetic_energy_abs_j"] for item in errors), default=0.0),
            },
            "scientific_credit": "NONE; this does not calibrate solver integration or native field output error",
        },
        "native_observation_contract": {
            "status": "PARENT_GUARDED_SNAPSHOT_AND_ENFORCED_DECODE_PENDING",
            "source_runs": source_reports,
            "selection_rule": "each query bracket plus one immediately adjacent saved row on each available side",
            "field_interpolation": "FORBIDDEN_BY_OBSERVER_WORKER",
            "raw_scope": "selected Part files only; no full raw-tree hash; no HDF5",
            "required_post_decode_analysis": {
                "time_alignment": "retain exact lower/upper native times and bracket widths; no extrapolation",
                "output_sampling": "use decoded neighbouring rows to test a pre-registered downsampling/interpolation reconstruction; report as output error only",
                "integrator_difference": "compare same-index or explicitly time-bracketed same/half fields separately; do not call it output error",
                "grid_truth": "UNKNOWN; no adjacent-run difference is a truth reference",
            },
        },
        "separation_of_unknowns": {
            "manufactured_interpolation_error": "COMPUTED_ALGORITHM_TEST_ONLY",
            "actual_output_interpolation_error": "UNKNOWN_PENDING_SELECTED_NATIVE_DECODE",
            "same_half_integrator_difference": "UNKNOWN_PENDING_SELECTED_NATIVE_DECODE",
            "physical_qualification_QI_QN_QE": "UNKNOWN",
        },
    }


def git_commit() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN_GIT_COMMIT"
    return result.stdout.strip()


def static_dependency_paths(mode: str, template: Path | None = None) -> list[Path]:
    source = SOURCES[mode]
    paths: list[Path] = [Path(__file__), SNAPSHOT_WORKER, OBSERVER, ENFORCER, DECODER, DECODER_SOURCE,
                         V8_RUNNER, V8_STRICT, V8_RUNTIME, V6_RUNTIME, V2_RUNTIME, PYTHON,
                         CALIBRATION_CONTRACT, CURRENT_XML, GENCASE_RECEIPT, OWNER, MOTION]
    paths.extend(Path(value) for key, value in source.items() if key not in {"mode", "raw_root", "runparts"})
    paths.append(Path(source["runparts"]))
    if template is not None:
        paths.append(template)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if str(resolved) not in seen:
            seen.add(str(resolved))
            unique.append(resolved)
    return unique


def build_snapshot_request(mode: str, context: dict[str, Any]) -> dict[str, Any]:
    source = context["source"]
    frames = context["frames"]
    stem = f"f7_s2_{mode}_time_output_selected_source_v1"
    template_path = REQUEST_DIR / f"{stem}_template.json"
    request_path = REQUEST_DIR / f"{stem}_snapshot_request.json"
    raw_root = str(Path(source["raw_root"]).expanduser().resolve())
    selected_paths = [str(Path(raw_root) / f"Part_{frame:04d}.bi4") for frame in frames]
    template = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "case_id": f"F7_S2_{mode.upper()}_TIME_OUTPUT_SELECTED_SOURCE_V1",
        "attempt_id": f"f7-s2-{mode}-time-output-selected-source-v1-root-001",
        "selected_native_frame_ids": frames,
        "query_times_s": QUERY_TIMES_S,
        "query_brackets": {str(query): item for query, item in zip(QUERY_TIMES_S, context["brackets"])},
        "deferred_input_files": [raw_root, *selected_paths],
        "source_binding": {
            "mode": mode,
            "raw_root": raw_root,
            "runparts": record(Path(source["runparts"]), f"{mode} RunPARTs"),
            "overlay_xml": record(Path(source["overlay_xml"]), f"{mode} overlay XML"),
            "solver_receipt": record(Path(source["solver_receipt"]), f"{mode} solver receipt"),
            "solver_request": record(Path(source["solver_request"]), f"{mode} solver request"),
            "current_xml": record(CURRENT_XML, "CURRENT XML"),
            "source_owner": record(OWNER, "F7 source owner"),
            "gencase_receipt": record(GENCASE_RECEIPT, "F7 GenCase receipt"),
            "motion": record(MOTION, "F7 motion table"),
        },
        "deferred_hash_policy": {
            "snapshot_worker": SNAPSHOT_SCHEMA,
            "selected_frames_only": True,
            "exact_selected_native_frame_ids": frames,
            "builder_bi4_read": False,
            "builder_bi4_hash": False,
            "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER",
            "snapshot_pre_post_stat": "REQUIRED; mutation rejects snapshot",
            "observer_enforcer_pre_post_stat": "REQUIRED after snapshot binding",
            "hdf5_read": False,
            "solver_launch": False,
        },
        "execution_allowed": False,
        "launch_disabled": True,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "output_calibration": {
            "contract": str(REPORT_PATH),
            "mode": mode,
            "native_frame_selection": "bracket plus radius-one neighbouring saved rows",
            "no_interpolation_in_snapshot": True,
        },
    }
    template_static_paths = static_dependency_paths(mode)
    template_input_files = [str(regular(path, "snapshot template static dependency")) for path in template_static_paths]
    template["input_files"] = template_input_files
    template["input_hashes"] = {path: sha256(Path(path)) for path in template_input_files}
    atomic_json(template_path, template)
    static_paths = static_dependency_paths(mode, template_path)
    input_files = [str(regular(path, "snapshot static dependency")) for path in static_paths]
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "case_id": f"F7_S2_{mode.upper()}_TIME_OUTPUT_SELECTED_SOURCE_V1",
        "attempt_id": f"f7-s2-{mode}-time-output-selected-source-v1-root-001",
        "launch_commit": git_commit(),
        "command": [str(PYTHON), str(SNAPSHOT_WORKER), "--observer-request", str(template_path.resolve()),
                     "--output", "{attempt_root}/native_selected_source_snapshot_v1.json"],
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": input_files,
        "input_hashes": {path: sha256(Path(path)) for path in input_files},
        "selected_native_frame_ids": frames,
        "query_times_s": QUERY_TIMES_S,
        "query_brackets": template["query_brackets"],
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_EXACT_SELECTED_PARTS; builder does not stat BI4",
        "estimated_storage_bytes": 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": False,
        "deferred_input_files": [raw_root, *selected_paths],
        "deferred_input_file_count": len(selected_paths),
        "deferred_hash_policy": template["deferred_hash_policy"],
        "source_binding": template["source_binding"],
        "snapshot_template": {"path": str(template_path.resolve()), "sha256": sha256(template_path)},
        "output": {"atomic": True, "refuse_overwrite": True,
                   "path": "{attempt_root}/native_selected_source_snapshot_v1.json"},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(V8_RUNNER),
                           "strict_guard": str(V8_STRICT), "runtime": str(V8_RUNTIME),
                           "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden",
                           "hdf5_read": "forbidden", "bi4_decode": "hash-only snapshot stage",
                           "parent_v8_review_required": True},
        "output_root": str(DATA_ROOT / "families/F7" / f"F7_S2_{mode.upper()}_TIME_OUTPUT_SELECTED_SOURCE_V1" /
                          f"f7-s2-{mode}-time-output-selected-source-v1-root-001"),
        "qualification_stage": "stage2_f7_s2_time_output_selected_source_snapshot_v1_pending_parent_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(request_path, request)
    return {"template": template, "request": request, "template_path": template_path, "request_path": request_path}


def build_observer_request(mode: str, snapshot_receipt: Path, snapshot_result: Path, output_dir: Path) -> dict[str, Any]:
    """Bind a completed parent snapshot without reading any BI4 in this builder."""
    context = source_config(mode)
    snapshot_receipt_obj = load_object(snapshot_receipt, f"{mode} snapshot receipt")
    snapshot_result_obj = load_object(snapshot_result, f"{mode} snapshot result")
    if snapshot_receipt_obj.get("status") != "completed" or snapshot_receipt_obj.get("returncode") != 0:
        raise ValueError(f"{mode} snapshot receipt is not successful")
    if snapshot_result_obj.get("schema") != SNAPSHOT_SCHEMA or snapshot_result_obj.get("status") != "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE":
        raise ValueError(f"{mode} snapshot result is not stable v2 success")
    records = snapshot_result_obj.get("immutable_source_sha_list")
    if not isinstance(records, list) or [int(item.get("frame", -1)) for item in records] != context["frames"]:
        raise ValueError(f"{mode} snapshot frame list does not match prepared neighborhood")
    raw_root = str(Path(context["source"]["raw_root"]).expanduser().resolve())
    normalized = [{"frame": int(item["frame"]), "path": str(Path(str(item["path"])).resolve()),
                   "bytes": int(item["bytes"]), "sha256": str(item["sha256"])} for item in records]
    if any(Path(item["path"]).parent != Path(raw_root) or not PART_RE.fullmatch(Path(item["path"]).name) for item in normalized):
        raise ValueError(f"{mode} snapshot contains a selected path outside its raw root")
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refuse to populate non-empty observer request directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"f7_s2_{mode}_time_output_expected_source_manifest_v1.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "case_id": f"F7_S2_{mode.upper()}_TIME_OUTPUT_OBSERVER_V1",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "raw_root": raw_root,
        "selected_native_frame_ids": context["frames"],
        "selected_native_files": normalized,
        "selected_source_sha256": snapshot_result_obj.get("source_sha_list_digest"),
        "source_sha_policy": "snapshot v2 selected files; enforcer v2 complete stat boundaries around child decode",
        "query_times_s": QUERY_TIMES_S,
        "query_brackets": {str(q): item for q, item in zip(QUERY_TIMES_S, context["brackets"])},
        "output_calibration_contract": str(REPORT_PATH),
    }
    atomic_json(manifest_path, manifest)
    source = context["source"]
    static_paths = static_dependency_paths(mode)
    static_paths.extend([snapshot_receipt, snapshot_result, manifest_path])
    static_paths = list(dict.fromkeys(path.expanduser().resolve() for path in static_paths))
    input_files = [str(regular(path, "observer static dependency")) for path in static_paths]
    input_hashes = {path: sha256(Path(path)) for path in input_files}
    output_name = f"f7_s2_{mode}_time_output_observer_v1.json"
    command = [str(PYTHON), str(ENFORCER), "--observer-worker", str(OBSERVER),
               "--expected-source-manifest", str(manifest_path), "--raw-root", raw_root,
               "--runparts", str(Path(source["runparts"]).resolve()),
               "--generated-xml", str(Path(source["overlay_xml"]).resolve()),
               "--decoder", str(DECODER), "--decoder-source", str(DECODER_SOURCE),
               "--output", f"{{attempt_root}}/observer/{output_name}",
               "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--cwd", str(REPO),
               "--expected-frame-count", str(len(context["rows"])),
               "--expected-final-time-s", repr(context["rows"][-1]["time_s"]),
               "--final-time-tolerance-s", "1e-12", "--frames", *[str(frame) for frame in context["frames"]],
               "--query-times", *[str(query) for query in QUERY_TIMES_S]]
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY,
        "sentinel_id": SENTINEL,
        "physical_case_id": PHYSICAL_CASE,
        "case_id": f"F7_S2_{mode.upper()}_TIME_OUTPUT_OBSERVER_V1",
        "attempt_id": f"f7-s2-{mode}-time-output-observer-v1-root-001",
        "launch_commit": git_commit(),
        "command": command,
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "selected_native_frame_ids": context["frames"],
        "query_times_s": QUERY_TIMES_S,
        "query_brackets": {str(q): item for q, item in zip(QUERY_TIMES_S, context["brackets"])},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_native_read_bytes": int(snapshot_result_obj.get("selected_native_total_bytes", 0)),
        "estimated_storage_bytes": 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": True,
        "deferred_input_files": [raw_root, *[item["path"] for item in normalized]],
        "deferred_input_file_count": len(normalized),
        "deferred_hash_policy": {
            "snapshot_terminal_result": record(snapshot_result, f"{mode} snapshot result"),
            "builder_bi4_read": False,
            "builder_bi4_hash": False,
            "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER",
            "observer_runtime_scope": "exact selected native neighborhood frames only",
            "enforcer_v2_pre_decode_sha_and_complete_stat": "REQUIRED",
            "enforcer_v2_post_decode_sha_and_complete_stat": "REQUIRED",
            "cross_decode_stat_boundaries": "pre.stat_after == post.stat_before and pre.stat_before == post.stat_after",
            "unknown_child_status": "FAILURE",
            "hdf5_read": False,
            "particle_field_interpolation": "NOT_PERFORMED_BY_WORKER",
        },
        "source_snapshot_binding": {
            "snapshot_receipt": record(snapshot_receipt, f"{mode} snapshot receipt"),
            "snapshot_result": record(snapshot_result, f"{mode} snapshot result"),
            "expected_source_manifest": record(manifest_path, f"{mode} expected source manifest"),
            "selected_source_sha256": snapshot_result_obj.get("source_sha_list_digest"),
            "selected_native_files": normalized,
            "builder_did_not_read_bi4": True,
        },
        "output_calibration": {
            "report": record(REPORT_PATH, "F7 time/output calibration report"),
            "manufactured_trajectory": "algorithm-only interpolation self-test",
            "actual_native_field_interpolation": "forbidden",
            "post_decode_output_test": "pre-registered local-neighbour reconstruction only",
            "same_half_integrator_difference": "separate diagnostic; not output-error truth",
        },
        "output": {"atomic": True, "refuse_overwrite": True,
                   "path": f"{{attempt_root}}/observer/{output_name}",
                   "scratch_cleanup": "worker-owned temporary decoder tree"},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(V8_RUNNER),
                           "strict_guard": str(V8_STRICT), "runtime": str(V8_RUNTIME),
                           "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden",
                           "hdf5_read": "forbidden", "parent_v8_review_required": True},
        "output_root": str(DATA_ROOT / "families/F7" / f"F7_S2_{mode.upper()}_TIME_OUTPUT_OBSERVER_V1" /
                          f"f7-s2-{mode}-time-output-observer-v1-root-001"),
        "qualification_stage": "stage2_f7_s2_time_output_selected_native_observer_v1_pending_parent_v8_dispatch",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(output_dir / f"{output_name.removesuffix('.json')}_request.json", request)
    atomic_json(output_dir / f"f7_s2_{mode}_time_output_observer_v1_manifest.json", {
        "schema": SCHEMA,
        "status": "PREPARED_SNAPSHOT_BOUND_ENFORCER_V2",
        "mode": mode,
        "snapshot_result": record(snapshot_result, f"{mode} snapshot result"),
        "manifest": record(manifest_path, f"{mode} expected source manifest"),
        "selected_native_frame_count": len(normalized),
        "bi4_read_by_builder": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    })
    return request


def self_test() -> dict[str, Any]:
    values = [0.0, 0.5, 1.0]
    low = trajectory(values[0])
    high = trajectory(values[-1])
    mid = trajectory(values[1])
    exact = state_lerp(low, high, 0.5)
    assert max_value(abs_error(exact["position_m"], mid["position_m"])) > 0.0
    linear_error = abs(lerp(1.0, 3.0, 0.25) - 1.5)
    assert linear_error == 0.0
    rows = [{"frame": index, "time_s": float(index), "steps": 1} for index in range(13)]
    frames, brackets = selected_neighborhood(rows, QUERY_TIMES_S, radius=1)
    assert frames == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    assert all(item["status"] in {"EXACT", "EXACT_OR_LEFT"} for item in brackets)
    assert bracket(rows, -0.1)["status"] == "OUT_OF_RANGE"
    return {"status": "PASS", "manufactured_nonzero_curvature": True,
            "linear_exactness": True, "neighborhood_selection": True,
            "bi4_read": False, "solver_launch": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-report", action="store_true")
    parser.add_argument("--build-snapshot-requests", action="store_true")
    parser.add_argument("--build-observer-request", choices=sorted(SOURCES))
    parser.add_argument("--snapshot-receipt", type=Path)
    parser.add_argument("--snapshot-result", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    if args.build_report:
        contexts = {mode: source_config(mode) for mode in SOURCES}
        report = manufactured_report(contexts)
        atomic_json(REPORT_PATH, report)
        print(json.dumps({"status": report["status"], "output": str(REPORT_PATH),
                          "same_frames": contexts["same_cfl"]["frames"],
                          "half_frames": contexts["half_cfl"]["frames"]}, indent=2))
        return 0
    if args.build_snapshot_requests:
        REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        if not REPORT_PATH.is_file():
            raise SystemExit("build the manufactured report before snapshot requests")
        outputs = [build_snapshot_request(mode, source_config(mode)) for mode in SOURCES]
        print(json.dumps({"status": "PASS_PREPARED_SNAPSHOT_REQUESTS",
                          "requests": [str(item["request_path"]) for item in outputs]}, indent=2))
        return 0
    if args.build_observer_request:
        if args.snapshot_receipt is None or args.snapshot_result is None or args.output_dir is None:
            parser.error("--build-observer-request requires --snapshot-receipt, --snapshot-result, and --output-dir")
        request = build_observer_request(args.build_observer_request, args.snapshot_receipt,
                                         args.snapshot_result, args.output_dir)
        print(json.dumps({"status": "PASS_PREPARED_OBSERVER_REQUEST",
                          "case_id": request["case_id"], "selected_frames": request["selected_native_frame_ids"]}, indent=2))
        return 0
    parser.error("choose --self-test, --build-report, --build-snapshot-requests, or --build-observer-request")


if __name__ == "__main__":
    raise SystemExit(main())

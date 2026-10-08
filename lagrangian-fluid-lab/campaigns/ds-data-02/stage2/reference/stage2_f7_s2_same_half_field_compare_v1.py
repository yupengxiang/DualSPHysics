#!/usr/bin/env python3
"""Compare the completed F7 same/half-CFL selected native observers.

Both 9-frame observers are real decoded fields.  Their native times are not
identical, so this worker pairs equal native frame IDs without interpolating
either run.  It reports weighted fluid COM, velocity, and kinetic-energy
differences as bounded asynchronous same-index diagnostics.  It also reports
the field span between the actual lower/upper native rows surrounding each
registered query time.  That span is an observable bracket diagnostic, not a
claim of pure output error or an integration-error estimate.

The worker reads only observer JSON, RunPARTs, receipts, XML/control metadata,
and the frozen source-scale contract.  It never opens BI4/Part/HDF5 data,
invokes a decoder, or starts a solver.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import csv
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f7-s2.same-half-field-compare.v1"
REPORT_SCHEMA = "ds02.stage2.f7-s2.same-half-field-compare-report.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"

SAME_OBSERVER = DATA_ROOT / (
    "families/F7/F7_S2_A065_SAME_CFL_SELECTED_NATIVE_OBSERVER_V2/"
    "f7-s2-a065-same-cfl-selected-native-observer-v2-root-001-root-forward-001/"
    "observer/f7_s2_a065_same_cfl_selected_native_observer_v2.json"
)
HALF_OBSERVER = DATA_ROOT / (
    "families/F7/F7_S2_A065_HALF_CFL_SELECTED_NATIVE_OBSERVER_V1/"
    "f7-s2-a065-half-cfl-selected-native-observer-v1-root-001-root-forward-001/"
    "observer/f7_s2_a065_half_cfl_selected_native_observer_v1.json"
)
SAME_OBSERVER_RECEIPT = SAME_OBSERVER.parent.parent / "execution-receipt.json"
HALF_OBSERVER_RECEIPT = HALF_OBSERVER.parent.parent / "execution-receipt.json"
SAME_SOLVER_RECEIPT = DATA_ROOT / (
    "families/F7/f7-obstacle-quintic-b08-a065/"
    "f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json"
)
HALF_SOLVER_RECEIPT = DATA_ROOT / (
    "families/F7/f7-obstacle-quintic-b08-a065/"
    "f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/execution-receipt.json"
)
SAME_SOLVER_REQUEST = MAIN / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "f7-nvme-counterpart-v5-root-001/f7-s2-same-cfl-nvme-request-v5-001.json"
)
HALF_SOLVER_REQUEST = MAIN / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "f7-half-cfl-v7-root-prepared-001/f7-s2-half-cfl-solver-v6-root-forward-001.json"
)
SAME_RUNPARTS = Path(
    "/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/"
    "f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/RunPARTs.csv"
)
HALF_RUNPARTS = Path(
    "/var/tmp/ds02-stage2/F7/F7_S2_HALF_CFL_SAVEDT_V7/"
    "f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/solver_output/RunPARTs.csv"
)
CALIBRATION_CONTRACT = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f7_s2_observer_calibration_contract_v3.json"
)
SOURCE_XML = DATA_ROOT / (
    "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/"
    "root-stage1-f7-angle065-genuine-gencase-085/prepared/"
    "F7_OBSTACLE_QUINTIC_B08_A065.xml"
)
SOURCE_OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/"
    "handoff_20261003/root_followup_064_stage1_target_angle_full601_native099_nvme_typed_v1/"
    "owners/F7_OBSTACLE_QUINTIC_B08_A065.owner.json"
)
MOTION = SOURCE_XML.parent / "motion_obstacle_quintic.dat"
SAME_XML = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/"
    "F7_OBSTACLE_QUINTIC_B08_A065_same_cfl_savedt.xml"
)
HALF_XML = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_savedt_cfl_pair_inputs_v1/F7_S2/half_cfl/"
    "F7_OBSTACLE_QUINTIC_B08_A065_half_cfl_savedt.xml"
)
SAME_MANIFEST = SAME_XML.with_name("overlay-manifest.json")
HALF_MANIFEST = HALF_XML.with_name("overlay-manifest.json")

REQUEST_DIR = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-f7-s2-same-half-field-compare-v1"
)
REQUEST_PATH = REQUEST_DIR / "f7_s2_same_half_field_compare_v1.json"
CASE_ID = "F7_S2_SAME_HALF_FIELD_COMPARE_V1"
ATTEMPT_ID = "f7-s2-same-half-field-compare-v1-root-001"
OUTPUT_RELATIVE = "{attempt_root}/report/f7_s2_same_half_field_compare_v1.json"
QUERY_TIMES_S = [0.0, 3.0, 6.0, 9.0, 12.0]
EXPECTED_FRAMES = [0, 299, 300, 599, 600, 899, 900, 1199, 1200]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse overwrite immutable output: {path}")
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


def finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} is boolean")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite")
    return result


def vec3(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must be a length-3 list")
    return [finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def norm(value: list[float]) -> float:
    return math.sqrt(sum(component * component for component in value))


def sub(left: list[float], right: list[float]) -> list[float]:
    return [left[index] - right[index] for index in range(3)]


def parse_runparts(path: Path, label: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with regular(path, label).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for raw in reader:
            if not raw or not raw.get("Part"):
                continue
            try:
                frame = int(raw["Part"].strip().replace(",", ""))
                time_s = finite(raw["TimeStep [s]"], f"{label}.time")
            except (KeyError, TypeError, ValueError):
                continue
            rows.append({"frame": frame, "time_s": time_s})
    if not rows or [row["frame"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"{label} frames are not contiguous zero-based rows")
    times = [row["time_s"] for row in rows]
    if abs(times[0]) > 1e-12 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError(f"{label} times are not strictly increasing from zero")
    return {"record": record(path, label), "rows": rows, "times_s": times, "row_count": len(rows), "last_time_s": times[-1]}


def bracket(times: list[float], query: float) -> dict[str, Any]:
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUT_OF_RANGE", "interpolation": "NOT_PERFORMED"}
    if abs(query - times[0]) <= 1e-12:
        return {"query_time_s": query, "status": "EXACT_OR_LEFT", "lower_frame": 0, "upper_frame": 0, "lower_time_s": times[0], "upper_time_s": times[0], "bracket_width_s": 0.0, "interpolation": "NOT_PERFORMED"}
    for right, upper_time in enumerate(times[1:], 1):
        if upper_time >= query:
            lower = right - 1
            exact = abs(upper_time - query) <= 1e-12
            return {"query_time_s": query, "status": "EXACT" if exact else "BRACKETED", "lower_frame": right if exact else lower, "upper_frame": right, "lower_time_s": upper_time if exact else times[lower], "upper_time_s": upper_time, "bracket_width_s": 0.0 if exact else upper_time - times[lower], "interpolation": "NOT_PERFORMED"}
    raise AssertionError("bracket search did not terminate")


def observer_rows(path: Path, runparts: dict[str, Any], label: str) -> dict[int, dict[str, Any]]:
    observer = load_json(path, label)
    if observer.get("schema") != "ds02.stage2.native-physical-observer.v2" or observer.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"{label} is not a successful native observer")
    scope = observer.get("scope", {})
    if scope.get("runparts_frame_count") != runparts["row_count"] or scope.get("hdf5_read") is not False or scope.get("typed_conversion") != "NOT_PERFORMED":
        raise ValueError(f"{label} scope/RunPARTs contract mismatch")
    observations = observer.get("observations")
    if not isinstance(observations, list) or [int(item.get("frame", -1)) for item in observations] != EXPECTED_FRAMES:
        raise ValueError(f"{label} selected frame contract mismatch")
    result: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(observations):
        frame = int(item["frame"])
        time = item.get("time", {})
        for key in ("runparts_s", "decoded_s", "absolute_error_s"):
            finite(time.get(key), f"{label}[{index}].time.{key}")
        if time.get("status") != "PASS_DECODED_TIME_MATCH":
            raise ValueError(f"{label} time status is not PASS")
        fluid = item.get("groups", {}).get("fluid", {})
        centroid = vec3(fluid.get("weighted_centroid_m"), f"{label}[{index}].weighted_centroid_m")
        velocity = vec3(fluid.get("weighted_velocity_m_per_s"), f"{label}[{index}].weighted_velocity_m_per_s")
        ke = finite(fluid.get("kinetic_energy_j"), f"{label}[{index}].kinetic_energy_j")
        sample_mass = finite(item.get("fluid_observables", {}).get("sample_mass_kg"), f"{label}[{index}].sample_mass_kg")
        if not math.isfinite(ke) or sample_mass <= 0:
            raise ValueError(f"{label} non-positive/non-finite fluid field")
        result[frame] = {"frame": frame, "time_s": finite(time["runparts_s"], f"{label}[{index}].time"), "centroid_m": centroid, "velocity_m_per_s": velocity, "kinetic_energy_j": ke, "sample_mass_kg": sample_mass}
    return result


def calibration_scales(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("status") != "SOURCE_BOUND_SCALES_REGISTERED_EVENT_TIME_UNKNOWN":
        raise ValueError("calibration contract status changed")
    scales = contract.get("reference_scales", {})
    frozen = contract.get("frozen_error_budget", {})
    L = finite(contract.get("source_geometry", {}).get("L_position_reference_scalar_m"), "L")
    velocity = finite(scales.get("velocity_scale_m_per_s"), "velocity scale")
    kinetic = finite(scales.get("kinetic_energy_scale_j"), "KE scale")
    position_fraction = finite(frozen.get("position_fraction_of_L"), "position fraction")
    velocity_fraction = finite(frozen.get("velocity_and_ke_fraction_of_registered_nonzero_scale"), "velocity fraction")
    if L <= 0 or velocity <= 0 or kinetic <= 0 or position_fraction <= 0 or velocity_fraction <= 0:
        raise ValueError("registered scales must be positive")
    return {
        "contract": record(CALIBRATION_CONTRACT, "calibration contract"),
        "L_position_reference_m": L,
        "velocity_scale_m_per_s": velocity,
        "kinetic_energy_scale_j": kinetic,
        "position_gate_m": L * position_fraction,
        "velocity_gate_m_per_s": velocity * velocity_fraction,
        "kinetic_energy_gate_j": kinetic * velocity_fraction,
        "position_fraction_of_L": position_fraction,
        "velocity_and_ke_fraction_of_scale": velocity_fraction,
        "event_time_status": contract.get("event_time", {}).get("status"),
        "event_time_characteristic_s": contract.get("event_time", {}).get("characteristic_time_s"),
    }


def validate_pair(same: dict[int, dict[str, Any]], half: dict[int, dict[str, Any]], scales: dict[str, Any]) -> list[dict[str, Any]]:
    if set(same) != set(half) or set(same) != set(EXPECTED_FRAMES):
        raise ValueError("same/half selected frame sets differ")
    rows: list[dict[str, Any]] = []
    for frame in EXPECTED_FRAMES:
        left, right = same[frame], half[frame]
        time_delta = right["time_s"] - left["time_s"]
        position_delta = sub(right["centroid_m"], left["centroid_m"])
        velocity_delta = sub(right["velocity_m_per_s"], left["velocity_m_per_s"])
        ke_delta = right["kinetic_energy_j"] - left["kinetic_energy_j"]
        rows.append({
            "frame": frame,
            "same_time_s": left["time_s"],
            "half_time_s": right["time_s"],
            "time_delta_half_minus_same_s": time_delta,
            "time_exact_match": abs(time_delta) <= 1e-12,
            "same_sample_mass_kg": left["sample_mass_kg"],
            "half_sample_mass_kg": right["sample_mass_kg"],
            "centroid_delta_half_minus_same_m": position_delta,
            "centroid_delta_norm_m": norm(position_delta),
            "velocity_delta_half_minus_same_m_per_s": velocity_delta,
            "velocity_delta_norm_m_per_s": norm(velocity_delta),
            "kinetic_energy_delta_half_minus_same_j": ke_delta,
            "kinetic_energy_delta_abs_j": abs(ke_delta),
            "registered_gate_checks": {
                "position_within_2pct_L": norm(position_delta) <= scales["position_gate_m"],
                "velocity_within_5pct_registered_scale": norm(velocity_delta) <= scales["velocity_gate_m_per_s"],
                "kinetic_energy_within_5pct_registered_scale": abs(ke_delta) <= scales["kinetic_energy_gate_j"],
            },
            "interpretation": "ASYNC_SAME_NATIVE_FRAME_INDEX_DIAGNOSTIC; includes time/CFL and field differences; no interpolation or qualification",
        })
    return rows


def bracket_diagnostics(rows: dict[int, dict[str, Any]], runparts: dict[str, Any], scales: dict[str, Any], label: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for query in QUERY_TIMES_S:
        query_bracket = bracket(runparts["times_s"], query)
        entry: dict[str, Any] = {"query_time_s": query, "run": label, "runparts_bracket": query_bracket, "interpolation": "NOT_PERFORMED"}
        if query_bracket["status"] == "OUT_OF_RANGE":
            entry["status"] = "FAIL_QUERY_OUT_OF_RANGE"
            result.append(entry)
            continue
        lower = rows.get(query_bracket["lower_frame"])
        upper = rows.get(query_bracket["upper_frame"])
        if lower is None or upper is None:
            entry["status"] = "UNKNOWN_SELECTED_OBSERVER_DOES_NOT_CONTAIN_BRACKET_ENDPOINTS"
            result.append(entry)
            continue
        position_delta = sub(upper["centroid_m"], lower["centroid_m"])
        velocity_delta = sub(upper["velocity_m_per_s"], lower["velocity_m_per_s"])
        ke_delta = upper["kinetic_energy_j"] - lower["kinetic_energy_j"]
        entry.update({
            "status": "PASS_NATIVE_BRACKET_SPAN_COMPUTED",
            "lower_frame": lower["frame"],
            "upper_frame": upper["frame"],
            "lower_time_s": lower["time_s"],
            "upper_time_s": upper["time_s"],
            "native_bracket_position_span_norm_m": norm(position_delta),
            "native_bracket_velocity_span_norm_m_per_s": norm(velocity_delta),
            "native_bracket_kinetic_energy_span_abs_j": abs(ke_delta),
            "registered_gate_reference": {
                "position_gate_m": scales["position_gate_m"],
                "velocity_gate_m_per_s": scales["velocity_gate_m_per_s"],
                "kinetic_energy_gate_j": scales["kinetic_energy_gate_j"],
            },
            "interpretation": "BOUNDED_NATIVE_BRACKET_CHANGE; not isolated output truncation error, integration error, or neighboring-grid truth",
        })
        result.append(entry)
    return result


def self_test() -> dict[str, Any]:
    scales = {"position_gate_m": 0.02, "velocity_gate_m_per_s": 0.05, "kinetic_energy_gate_j": 1.0}
    same = {frame: {"time_s": float(frame), "centroid_m": [0.0, 0.0, 0.0], "velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0, "sample_mass_kg": 1.0} for frame in EXPECTED_FRAMES}
    half = {
        frame: {
            **item,
            "centroid_m": list(item["centroid_m"]),
            "velocity_m_per_s": list(item["velocity_m_per_s"]),
        }
        for frame, item in same.items()
    }
    half[299]["centroid_m"][0] = 0.01
    half[300]["velocity_m_per_s"][1] = 0.04
    rows = validate_pair(same, half, scales)
    if rows[1]["registered_gate_checks"]["position_within_2pct_L"] is not True:
        raise AssertionError("manufactured position gate failed")
    half[600]["kinetic_energy_j"] = 2.0
    rows = validate_pair(same, half, scales)
    if rows[4]["registered_gate_checks"]["kinetic_energy_within_5pct_registered_scale"] is not False:
        raise AssertionError("manufactured KE gate was accepted")
    try:
        validate_pair(same, {frame: item for frame, item in half.items() if frame != 1200}, scales)
    except ValueError:
        pass
    else:
        raise AssertionError("mismatched frame set accepted")
    return {"status": "PASS", "checks": ["finite same-index vector diagnostics", "registered gate counterexample", "mismatched frame set rejection"], "passed": 3}


def build_report(output: Path) -> dict[str, Any]:
    contract = load_json(CALIBRATION_CONTRACT, "F7 calibration contract")
    scales = calibration_scales(contract)
    same_runparts = parse_runparts(SAME_RUNPARTS, "same-CFL RunPARTs")
    half_runparts = parse_runparts(HALF_RUNPARTS, "half-CFL RunPARTs")
    same = observer_rows(SAME_OBSERVER, same_runparts, "same-CFL observer")
    half = observer_rows(HALF_OBSERVER, half_runparts, "half-CFL observer")
    pairs = validate_pair(same, half, scales)
    same_brackets = bracket_diagnostics(same, same_runparts, scales, "same_cfl")
    half_brackets = bracket_diagnostics(half, half_runparts, scales, "half_cfl")
    time_deltas = [row["time_delta_half_minus_same_s"] for row in pairs]
    report = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_ASYNC_SAME_INDEX_FIELD_DIAGNOSTICS_NO_QUALIFICATION",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sentinel_id": "F7-S2",
        "family_id": "F7",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "read_scope": {
            "same_observer": record(SAME_OBSERVER, "same observer"),
            "half_observer": record(HALF_OBSERVER, "half observer"),
            "same_runparts": same_runparts["record"],
            "half_runparts": half_runparts["record"],
            "hdf5_read": False,
            "bi4_read": False,
            "native_decoder_invoked": False,
            "typed_conversion": "NOT_PERFORMED",
            "source_scope": "completed selected observer JSON and saved-row time metadata only",
        },
        "source_binding": {
            "same_observer_receipt": record(SAME_OBSERVER_RECEIPT, "same observer receipt"),
            "half_observer_receipt": record(HALF_OBSERVER_RECEIPT, "half observer receipt"),
            "same_solver_receipt": record(SAME_SOLVER_RECEIPT, "same solver receipt"),
            "half_solver_receipt": record(HALF_SOLVER_RECEIPT, "half solver receipt"),
            "same_solver_request": record(SAME_SOLVER_REQUEST, "same solver request"),
            "half_solver_request": record(HALF_SOLVER_REQUEST, "half solver request"),
            "source_xml": record(SOURCE_XML, "F7 source XML"),
            "source_owner": record(SOURCE_OWNER, "F7 source owner"),
            "motion_table": record(MOTION, "F7 motion table"),
            "same_overlay_xml": record(SAME_XML, "same overlay XML"),
            "half_overlay_xml": record(HALF_XML, "half overlay XML"),
            "same_overlay_manifest": record(SAME_MANIFEST, "same overlay manifest"),
            "half_overlay_manifest": record(HALF_MANIFEST, "half overlay manifest"),
            "calibration_contract": scales["contract"],
        },
        "registered_scales": scales,
        "pairing": {
            "method": "same native frame ID paired across same/half; each run keeps its own decoded RunPARTs time",
            "expected_frames": EXPECTED_FRAMES,
            "interpolation": "NOT_PERFORMED",
            "exact_time_match_count": sum(row["time_exact_match"] for row in pairs),
            "asynchronous_time_match_count": sum(not row["time_exact_match"] for row in pairs),
            "max_abs_time_delta_s": max(abs(value) for value in time_deltas),
            "min_time_delta_s": min(time_deltas),
            "max_time_delta_s": max(time_deltas),
            "status": "UNKNOWN_TIME_ALIGNMENT_EXCEPT_FRAME0",
        },
        "same_half_pair_diagnostics": pairs,
        "native_query_bracket_diagnostics": {"same_cfl": same_brackets, "half_cfl": half_brackets},
        "output_vs_integration_separation": {
            "output_calibration_status": "BOUNDED_NATIVE_BRACKET_CHANGE_ONLY",
            "integration_comparison_status": "ASYNC_SAME_INDEX_DIAGNOSTIC_ONLY",
            "what_is_computed": "field differences at equal native frame IDs plus lower/upper field spans around registered query times",
            "what_is_not_computed": ["interpolated common-time fields", "pure output truncation error", "pure CFL integration error", "neighboring-grid truth", "event-time error"],
            "next_observation_if_needed": "decode registered adjacent native rows in each run at the same query neighborhoods, then compare actual omitted-row fields without interpolation",
        },
        "manufactured_semantic_selftests": self_test(),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, report)
    return report


def input_paths() -> list[Path]:
    paths = [
        Path(__file__), PYTHON, RUNNER, STRICT, RUNTIME,
        SAME_OBSERVER, HALF_OBSERVER, SAME_OBSERVER_RECEIPT, HALF_OBSERVER_RECEIPT,
        SAME_SOLVER_RECEIPT, HALF_SOLVER_RECEIPT, SAME_SOLVER_REQUEST, HALF_SOLVER_REQUEST,
        SAME_RUNPARTS, HALF_RUNPARTS, CALIBRATION_CONTRACT, SOURCE_XML, SOURCE_OWNER, MOTION,
        SAME_XML, HALF_XML, SAME_MANIFEST, HALF_MANIFEST,
    ]
    unique = list(dict.fromkeys(path.expanduser().resolve() for path in paths))
    for path in unique:
        if path.suffix.lower() in {".bi4", ".h5", ".hdf5"}:
            raise ValueError(f"same/half compare must not include raw/native input: {path}")
        regular(path, "request input")
    return unique


def build_request(launch_commit: str) -> dict[str, Any]:
    if REQUEST_PATH.exists():
        raise FileExistsError(f"refuse overwrite immutable request: {REQUEST_PATH}")
    paths = input_paths()
    records = {str(path): record(path, "request input") for path in paths}
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F7",
        "sentinel_id": "F7-S2",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "qualification_stage": "stage2_f7_s2_actual_same_half_field_diagnostic_frozen_scales_no_interpolation",
        "command": [str(PYTHON), str(Path(__file__).resolve()), "--run", "--output", OUTPUT_RELATIVE],
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": [str(path) for path in paths],
        "input_hashes": {str(path): item["sha256"] for path, item in records.items()},
        "input_records": records,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 32 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": False,
        "deferred_input_files": [],
        "scope": {
            "same_fields": "actual weighted fluid COM/velocity/KE from same-CFL 9-frame observer JSON",
            "half_fields": "actual weighted fluid COM/velocity/KE from half-CFL 9-frame observer JSON",
            "pairing": "equal native frame IDs; asynchronous saved times retained",
            "brackets": "actual RunPARTs lower/upper rows at queries 0,3,6,9,12; no interpolation",
            "output_error": "bounded native bracket span only; no pure output/integration decomposition",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source_binding": {
            "same_observer_sha_policy": "input_hashes covers observer JSON; worker does not reread native Part files",
            "half_observer_sha_policy": "input_hashes covers observer JSON; worker does not reread native Part files",
            "frozen_scale_contract": "position 2%L; velocity/KE 5% registered nonzero scale; event T remains UNKNOWN",
            "sample_mass_not_continuum_or_rigid_mass": True,
            "no_interpolation": True,
            "no_neighboring_grid_truth": True,
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(RUNNER),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "launch_commit": launch_commit,
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "bi4_read": "forbidden",
            "hdf5_read": "forbidden",
            "parent_v8_review_required": True,
        },
        "output": {"atomic": True, "refuse_overwrite": True, "path": OUTPUT_RELATIVE},
        "output_root": str(DATA_ROOT / "families/F7" / CASE_ID / ATTEMPT_ID),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(REQUEST_PATH, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    selected = [args.self_test, args.run, args.build_request]
    if sum(selected) != 1:
        parser.error("choose exactly one operation")
    if args.self_test:
        result = self_test()
    elif args.build_request:
        if not args.launch_commit:
            parser.error("--build-request requires --launch-commit")
        request = build_request(args.launch_commit)
        result = {"status": "PASS_REQUEST_BUILT", "path": str(REQUEST_PATH), "sha256": sha256(REQUEST_PATH), "input_count": len(request["input_files"]), "estimated_input_read_bytes": request["estimated_input_read_bytes"]}
    else:
        if args.output is None:
            parser.error("--run requires --output")
        result = build_report(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

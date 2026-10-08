#!/usr/bin/env python3
"""Bind the completed F7-S2 nine-frame observer to baseline/half actual control and observer alignment.

This is a small, forward-only CPU audit.  It reads the already completed
selected-observer JSON plus RunPARTs/control metadata.  It does not open a
BI4/Part/HDF5 file, invoke a decoder, or start a solver.  The same-CFL
observer fields are therefore real decoded evidence, while the source
baseline and half-CFL terminal/control/status evidence remains separate from
fields until its selected observer is available.

The report deliberately keeps three questions separate:

* same-CFL nine-frame field availability and native query brackets;
* baseline/half control and input-closure compatibility;
* output/integration error calibration, which needs additional dense rows or
  an actual half-CFL observer and cannot be inferred from nine rows.

``--self-test`` exercises the semantic gates with manufactured dictionaries.
``--run`` writes one immutable report.  ``--build-request`` writes a small
parent-guarded request for that metadata/observer audit.
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
import tempfile
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA = "ds02.stage2.f7-s2-observer-alignment-output.v2"
REPORT_SCHEMA = "ds02.stage2.f7-s2-observer-alignment-output-report.v2"
REQUEST_SCHEMA = "ds02.request.v1"

REPO = Path(__file__).resolve().parents[5]
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V8_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
V8_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
V8_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"

ACTUAL_OBSERVER = DATA_ROOT / (
    "families/F7/F7_S2_A065_SAME_CFL_SELECTED_NATIVE_OBSERVER_V2/"
    "f7-s2-a065-same-cfl-selected-native-observer-v2-root-001-root-forward-001/"
    "observer/f7_s2_a065_same_cfl_selected_native_observer_v2.json"
)
ACTUAL_OBSERVER_RECEIPT = ACTUAL_OBSERVER.parent.parent / "execution-receipt.json"
ACTUAL_SAME_RECEIPT = DATA_ROOT / (
    "families/F7/f7-obstacle-quintic-b08-a065/"
    "f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json"
)
ACTUAL_SAME_REQUEST = MAIN / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "f7-nvme-counterpart-v5-root-001/f7-s2-same-cfl-nvme-request-v5-001.json"
)
ACTUAL_RUNPARTS = Path(
    "/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/"
    "f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/RunPARTs.csv"
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
BASELINE_RECEIPT = DATA_ROOT / (
    "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/"
    "root-stage1-f7-a065-full601-native-099/execution-receipt.json"
)
BASELINE_RUNPARTS = BASELINE_RECEIPT.parent / "solver_output/RunPARTs.csv"
BASELINE_REQUEST = MAIN / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-priority-four-savedt-v2/f7_s2_half_cfl_savedt_v2.json"
)
HALF_QA = REFERENCE / "stage2_f7_s2_half_cfl_initial_qa_audit_v3.json"
HALF_ACTUAL_RECEIPT = DATA_ROOT / (
    "families/F7/f7-obstacle-quintic-b08-a065/"
    "f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/execution-receipt.json"
)
HALF_ACTUAL_RUNPARTS = Path(
    "/var/tmp/ds02-stage2/F7/F7_S2_HALF_CFL_SAVEDT_V7/"
    "f7-s2-a065-half-cfl-savedt-v7-001-root-forward-001/solver_output/RunPARTs.csv"
)
HALF_ACTUAL_XML = DATA_ROOT / (
    "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/"
    "f7-half-cfl-gencase-v8-001-root-001/prepared/"
    "F7_OBSTACLE_QUINTIC_B08_A065_half_cfl01.xml"
)
HALF_ACTUAL_REQUEST = MAIN / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "f7-half-cfl-v7-root-prepared-001/f7-s2-half-cfl-solver-v6-root-forward-001.json"
)
HALF_ACTUAL_QA = DATA_ROOT / (
    "families/F7/F7_S2_HALF_CFL_INITIAL_TYPED_QA_OUTER_V12/"
    "f7-s2-half-cfl-initial-typed-qa-outer-v12-root-001-root-forward-001/"
    "qa/f7-s2-half-cfl-initial-typed-qa-v12-outer-report.json"
)
HALF_SNAPSHOT_REQUEST = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-f7-s2-half-native-observer-v1/"
    "f7_s2_a065_half_cfl_selected_native_source_snapshot_v1.json"
)
HALF_XML = REFERENCE / (
    "stage2_savedt_cfl_pair_inputs_v1/F7_S2/half_cfl/"
    "F7_OBSTACLE_QUINTIC_B08_A065_half_cfl_savedt.xml"
)
HALF_MANIFEST = HALF_XML.with_name("overlay-manifest.json")
HALF_MOTION = HALF_XML.with_name("motion_obstacle_quintic.dat")
SAME_XML = REFERENCE / (
    "stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/"
    "F7_OBSTACLE_QUINTIC_B08_A065_same_cfl_savedt.xml"
)
SAME_MANIFEST = SAME_XML.with_name("overlay-manifest.json")
CALIBRATION_CONTRACT = REFERENCE / "stage2_f7_s2_observer_calibration_contract_v3.json"
SNAPSHOT_RESULT = DATA_ROOT / (
    "families/F7/F7_S2_A065_SELECTED_NATIVE_SOURCE_SNAPSHOT_V2/"
    "f7-s2-a065-selected-native-source-snapshot-v2-root-001-root-forward-001/"
    "native_selected_source_snapshot_v2.json"
)
SNAPSHOT_RECEIPT = SNAPSHOT_RESULT.parent / "execution-receipt.json"
EXPECTED_SOURCE_MANIFEST = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-f7-s2-native-observer-v2-forward-root-001/"
    "f7_s2_a065_expected_source_manifest_v2.json"
)

REQUEST_DIR = REQUEST_ROOT / "stage2-f7-s2-observer-alignment-output-v2"
REQUEST_PATH = REQUEST_DIR / "f7_s2_observer_alignment_output_v2.json"
CASE_ID = "F7_S2_OBSERVER_ALIGNMENT_OUTPUT_V2"
ATTEMPT_ID = "f7-s2-observer-alignment-output-v2-root-001"
OUTPUT_RELATIVE = "{attempt_root}/report/f7_s2_observer_alignment_output_v2.json"

QUERY_TIMES_S = [0.0, 3.0, 6.0, 9.0, 12.0]
EXPECTED_FRAMES = [0, 299, 300, 599, 600, 899, 900, 1199, 1200]
EXPECTED_RELATIVE_MK = 1
EXPECTED_ABSOLUTE_MK = 2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an existing regular file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256(path),
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
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


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} is boolean, not a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite")
    return result


def parse_runparts(path: Path, label: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with regular(path, label).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for raw in reader:
            if not raw or not raw.get("Part"):
                continue
            try:
                frame = int(raw["Part"].strip().replace(",", ""))
                time_s = finite_number(raw["TimeStep [s]"], f"{label}.time")
            except (KeyError, TypeError, ValueError):
                # RunPARTs has a trailing human-readable comment section.
                continue
            rows.append({"frame": frame, "time_s": time_s})
    if not rows or [row["frame"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"{label} frames are not contiguous zero-based rows")
    times = [row["time_s"] for row in rows]
    if abs(times[0]) > 1e-12 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError(f"{label} times are not strictly increasing from zero")
    return {
        "record": record(path, label),
        "row_count": len(rows),
        "first_frame": rows[0]["frame"],
        "last_frame": rows[-1]["frame"],
        "first_time_s": times[0],
        "last_time_s": times[-1],
        "times_s": times,
        "scope": "saved native output times; not a complete per-step dt trace",
    }


def bracket(times: list[float], query: float) -> dict[str, Any]:
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUT_OF_RANGE", "interpolation": "NOT_PERFORMED"}
    if abs(query - times[0]) <= 1e-12:
        return {
            "query_time_s": query,
            "status": "EXACT_OR_LEFT",
            "lower_frame": 0,
            "upper_frame": 0,
            "lower_time_s": times[0],
            "upper_time_s": times[0],
            "bracket_width_s": 0.0,
            "interpolation": "NOT_PERFORMED",
        }
    for right, upper_time in enumerate(times[1:], 1):
        if upper_time >= query:
            lower = right - 1
            exact = abs(upper_time - query) <= 1e-12
            return {
                "query_time_s": query,
                "status": "EXACT" if exact else "BRACKETED",
                "lower_frame": right if exact else lower,
                "upper_frame": right,
                "lower_time_s": upper_time if exact else times[lower],
                "upper_time_s": upper_time,
                "bracket_width_s": 0.0 if exact else upper_time - times[lower],
                "interpolation": "NOT_PERFORMED",
            }
    raise AssertionError("bracket search did not terminate")


def xml_parameters(path: Path) -> dict[str, str]:
    root = ET.parse(regular(path, "XML")).getroot()
    return {
        str(node.get("key")): str(node.get("value"))
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "parameter" and node.get("key") is not None
    }


def overlay_control(path: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path, "overlay manifest")
    proof = manifest.get("xml_diff_proof", {})
    params = xml_parameters(path)
    return {
        "xml": record(path, "overlay XML"),
        "manifest": record(manifest_path, "overlay manifest"),
        "parameters": params,
        "mode": manifest.get("mode"),
        "source_cfl_values": proof.get("source_cfl_values"),
        "overlay_cfl_values": proof.get("overlay_cfl_values"),
        "parsed_non_savedt_tree_equivalent": proof.get("parsed_non_savedt_tree_equivalent"),
        "savedt_values": proof.get("savedt_values"),
        "declared_text_edits": proof.get("declared_text_edits"),
    }


def observer_summary(observer: dict[str, Any], runparts: dict[str, Any]) -> dict[str, Any]:
    if observer.get("schema") != "ds02.stage2.native-physical-observer.v2":
        raise ValueError("unexpected selected observer schema")
    if observer.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"selected observer is not successful: {observer.get('status')}")
    scope = observer.get("scope", {})
    observations = observer.get("observations")
    if not isinstance(observations, list) or len(observations) != 9:
        raise ValueError("selected observer must contain exactly nine observations")
    frames = [int(item.get("frame", -1)) for item in observations]
    if frames != EXPECTED_FRAMES:
        raise ValueError(f"selected observer frame contract mismatch: {frames}")
    if scope.get("runparts_frame_count") != runparts["row_count"]:
        raise ValueError("observer and RunPARTs frame counts differ")
    if scope.get("hdf5_read") is not False or scope.get("typed_conversion") != "NOT_PERFORMED":
        raise ValueError("observer scope is wider than the registered native-only scope")
    for index, observation in enumerate(observations):
        time = observation.get("time", {})
        for key in ("runparts_s", "decoded_s", "absolute_error_s"):
            finite_number(time.get(key), f"observer.observations[{index}].time.{key}")
        if time.get("status") != "PASS_DECODED_TIME_MATCH":
            raise ValueError(f"observer time status is not PASS at index {index}")
        if observation.get("identity", {}).get("particle_count") != 70179:
            raise ValueError(f"observer particle count mismatch at index {index}")
        if observation.get("finite_fields") != {"position": True, "velocity": True, "density": True}:
            raise ValueError(f"observer finite-field contract mismatch at index {index}")
        fluid = observation.get("fluid_observables", {})
        if fluid.get("status") != "PASS":
            raise ValueError(f"fluid observer status mismatch at index {index}")
        finite_number(fluid.get("sample_mass_kg"), f"observer fluid mass {index}")
        centroid = fluid.get("centroid_m")
        velocity = fluid.get("mean_velocity_m_per_s")
        if not isinstance(centroid, list) or len(centroid) != 3:
            raise ValueError(f"missing fluid centroid at index {index}")
        if not isinstance(velocity, list) or len(velocity) != 3:
            raise ValueError(f"missing fluid velocity at index {index}")
        for component in centroid + velocity:
            finite_number(component, f"observer fluid vector {index}")
        finite_number(fluid.get("kinetic_energy_j"), f"observer fluid KE {index}")
        groups = observation.get("groups", {})
        relative = groups.get("fluid", {}).get("by_mkfluid_relative", {})
        absolute = groups.get("fluid", {}).get("by_mk_absolute", {})
        if str(EXPECTED_RELATIVE_MK) not in relative or str(EXPECTED_ABSOLUTE_MK) not in absolute:
            raise ValueError(f"native MK mapping missing at index {index}")
    observer_times = [float(item["time"]["runparts_s"]) for item in observations]
    expected_brackets = [bracket(runparts["times_s"], query) for query in QUERY_TIMES_S]
    actual_brackets = observer.get("time_window", {}).get("queries", [])
    if len(actual_brackets) != len(expected_brackets):
        raise ValueError("observer query bracket count mismatch")
    return {
        "status": "PASS_ACTUAL_NINE_NATIVE_FIELDS",
        "selected_frame_count": len(observations),
        "selected_frames": frames,
        "observer_times_s": observer_times,
        "runparts_frame_count": runparts["row_count"],
        "runparts_last_time_s": runparts["last_time_s"],
        "native_mk_mapping": {
            "fluid_relative": EXPECTED_RELATIVE_MK,
            "fluid_absolute": EXPECTED_ABSOLUTE_MK,
            "meaning": "observer group keys retain relative mkfluid and absolute mk separately",
        },
        "sample_mass_semantics": "native fluid particle sample mass only; not continuum or rigid-body mass",
        "query_brackets": expected_brackets,
        "observer_query_brackets": actual_brackets,
        "field_interpolation": "NOT_PERFORMED",
        "observer_scope": scope,
    }


def baseline_status(baseline_request: dict[str, Any], baseline_receipt: dict[str, Any], baseline_runparts: dict[str, Any], source_xml: Path) -> dict[str, Any]:
    command = baseline_request.get("source_binding", {}).get("current_source_exact", {}).get("source_solver_controls", {}).get("actual_completed_command")
    receipt_status = baseline_receipt.get("status")
    baseline_params = xml_parameters(source_xml)
    return {
        "status": "PASS_BASELINE_SOURCE_CONTROL_METADATA_BOUND",
        "physical_case_id": baseline_request.get("physical_case_id"),
        "receipt_status": receipt_status,
        "receipt_returncode": baseline_receipt.get("returncode"),
        "actual_command": command,
        "source_xml_parameters": {
            key: baseline_params.get(key)
            for key in ("CFLnumber", "cflnumber", "TimeMax", "TimeOut", "DtFixed", "DtMin")
            if key in baseline_params
        },
        "saved_frame_count": baseline_runparts["row_count"],
        "last_saved_time_s": baseline_runparts["last_time_s"],
        "field_observer_available": False,
        "field_comparison_status": "UNKNOWN_BASELINE_FIELDS_NOT_DECODED",
        "semantics": "baseline receipt/RunPARTs establish source control and window metadata only",
    }


def half_status(half_request: dict[str, Any], half_qa: dict[str, Any], half_xml: Path, half_manifest: Path, half_motion: Path) -> dict[str, Any]:
    source_binding = half_request.get("source_binding", {})
    motion_entries = source_binding.get("motion_and_auxiliary_source", [])
    xml_root = ET.parse(regular(half_xml, "half XML")).getroot()
    motion_names = [
        node.find("file").get("name")
        for node in xml_root.iter()
        if node.tag.rsplit("}", 1)[-1] == "mvrotfile" and node.find("file") is not None
    ]
    qa_gate = half_qa.get("forward_solver_gate", {})
    qa_status = half_qa.get("status")
    source_closure = {
        "request_motion_dependency_entries": len(motion_entries),
        "xml_motion_file_names": motion_names,
        "motion_file_available": half_motion.is_file(),
        "motion_sha256": sha256(half_motion) if half_motion.is_file() else None,
        "request_lists_motion_dependency": bool(motion_entries),
    }
    if not motion_entries:
        control_status = "BLOCKED_REQUEST_MISSING_XML_MOTION_DEPENDENCY"
    else:
        control_status = "PASS_REQUEST_MOTION_DEPENDENCY_LISTED"
    return {
        "status": "PENDING_NO_HALF_NATIVE_OBSERVER",
        "qa_status": qa_status,
        "solver_launch_allowed": qa_gate.get("solver_launch_allowed"),
        "forward_solver_gate_status": qa_gate.get("status"),
        "control_source_closure": source_closure,
        "control_source_status": control_status,
        "half_control": overlay_control(half_xml, half_manifest),
        "field_observer_available": False,
        "field_comparison_status": "UNKNOWN_HALF_FIELDS_NOT_DECODED",
        "required_next_evidence": [
            "parent-resolved motion copy and source SHA/stat closure",
            "half-CFL terminal solver receipt",
            "half-CFL selected-source snapshot and enforcer-v2 observer",
        ],
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def half_actual_status(
    half_request: dict[str, Any],
    half_receipt: dict[str, Any],
    half_runparts: dict[str, Any],
    half_qa: dict[str, Any],
    half_xml: Path,
    half_manifest: Path,
    half_motion: Path,
    snapshot_request: dict[str, Any],
) -> dict[str, Any]:
    execution = half_receipt.get("execution", {})
    filesystem = half_receipt.get("filesystem", {})
    returncode = execution.get("returncode")
    cfd_invoked = execution.get("cfd_invoked")
    terminal_status = "PASS_HALF_TERMINAL_RETURN0" if returncode == 0 and cfd_invoked is True else "FAIL_HALF_TERMINAL_RECEIPT"
    half_queries = [bracket(half_runparts["times_s"], query) for query in QUERY_TIMES_S]
    qa_status = half_qa.get("status")
    snapshot_identity = {
        "schema": snapshot_request.get("schema"),
        "case_id": snapshot_request.get("case_id"),
        "attempt_id": snapshot_request.get("attempt_id"),
        "selected_native_frame_ids": snapshot_request.get("selected_native_frame_ids"),
        "deferred_input_file_count": snapshot_request.get("deferred_input_file_count"),
    }
    actual_parameters = xml_parameters(half_xml)
    return {
        "status": terminal_status,
        "solver_terminal_status": half_receipt.get("status"),
        "returncode": returncode,
        "cfd_invoked": cfd_invoked,
        "cpu_core_seconds": execution.get("cpu_core_seconds"),
        "gpu_seconds_cutoff": execution.get("gpu_seconds_cutoff"),
        "external_product_bytes": filesystem.get("external_product_bytes"),
        "actual_command": execution.get("launch_argv"),
        "runparts": {
            "row_count": half_runparts["row_count"],
            "last_saved_time_s": half_runparts["last_time_s"],
            "query_brackets": half_queries,
            "scope": half_runparts["scope"],
        },
        "qa_status": qa_status,
        "control": overlay_control(half_xml, half_manifest),
        "actual_generated_xml": record(half_xml, "actual half generated XML"),
        "actual_generated_xml_parameters": {
            key: actual_parameters.get(key)
            for key in ("CFLnumber", "cflnumber", "TimeMax", "TimeOut", "DtFixed", "DtMin")
            if key in actual_parameters
        },
        "motion_sha256": sha256(half_motion),
        "half_snapshot_request": snapshot_identity,
        "field_observer_available": False,
        "field_comparison_status": "PENDING_HALF_SELECTED_NATIVE_OBSERVER",
        "time_alignment_status": "UNKNOWN_UNTIL_COMMON_QUERY_COMPARISON",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def output_integration_plan(actual: dict[str, Any], same_control: dict[str, Any], half: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    brackets = actual["query_brackets"]
    widths = [entry["bracket_width_s"] for entry in brackets if entry["status"] == "BRACKETED"]
    return {
        "status": "READY_METADATA_ONLY_PENDING_DENSE_AND_HALF_FIELDS",
        "actual_same_cfl_query_bracket_widths_s": widths,
        "actual_same_cfl_max_query_bracket_width_s": max(widths) if widths else 0.0,
        "saved_row_observation_scope": "nine selected native rows and their actual RunPARTs brackets only",
        "output_error_calibration": {
            "status": "PENDING_ADJACENT_DENSE_FIELD_DECODE",
            "required_comparison": "decode retained and omitted native rows from the same run at registered query neighborhoods",
            "no_interpolation_in_this_worker": True,
            "no_neighboring_grid_truth": True,
            "same_run_2x_4x_plan": {
                "retained_source": "actual same-CFL dense RunPARTs/native output",
                "derived_cadences_s": [0.02, 0.04],
                "field_rows_required_before_error_estimate": True,
                "additional_solver": False,
            },
        },
        "integration_error_calibration": {
            "status": "UNKNOWN_UNTIL_HALF_OBSERVER",
            "same_control": same_control,
            "half_control": half.get("control", half.get("half_control")),
            "cfl_pair": {"same": 0.2, "half": 0.1},
            "fixed_physical_source_required": True,
            "half_motion_closure_required": half.get("control_source_status", "ACTUAL_RECEIPT_MOTION_SHA_BOUND"),
            "same_last_saved_time_s": actual.get("runparts_last_time_s"),
            "half_last_saved_time_s": half.get("runparts", {}).get("last_saved_time_s"),
            "same_half_terminal_time_delta_s": (
                half.get("runparts", {}).get("last_saved_time_s") - actual.get("runparts_last_time_s")
                if half.get("runparts", {}).get("last_saved_time_s") is not None and actual.get("runparts_last_time_s") is not None
                else None
            ),
            "terminal_time_alignment": "UNKNOWN_TIME_ALIGNMENT; actual same/half endpoints differ and must retain own brackets",
            "dt_trace_scope": "RunPARTs saved-window summary only; no full per-step trace credit",
        },
        "frozen_error_budget": {
            "position_fraction_of_registered_L": contract.get("frozen_error_budget", {}).get("position_fraction_of_L"),
            "velocity_fraction_of_registered_nonzero_scale": contract.get("frozen_error_budget", {}).get("velocity_and_ke_fraction_of_registered_nonzero_scale"),
            "event_time_fraction": contract.get("frozen_error_budget", {}).get("event_time_fraction_of_characteristic_T"),
            "time_share_max_fraction_of_task_budget": contract.get("frozen_error_budget", {}).get("time_and_output_each_max_fraction_of_task_budget"),
            "output_share_max_fraction_of_task_budget": contract.get("frozen_error_budget", {}).get("time_and_output_each_max_fraction_of_task_budget"),
            "event_time_status": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build_report(output: Path) -> dict[str, Any]:
    observer = load_json(ACTUAL_OBSERVER, "actual F7 selected observer")
    actual_runparts = parse_runparts(ACTUAL_RUNPARTS, "actual same-CFL RunPARTs")
    baseline_runparts = parse_runparts(BASELINE_RUNPARTS, "baseline RunPARTs")
    baseline_request = load_json(BASELINE_REQUEST, "half-CFL source request")
    baseline_receipt = load_json(BASELINE_RECEIPT, "baseline solver receipt")
    half_qa = load_json(HALF_ACTUAL_QA, "actual half-CFL initial QA")
    half_receipt = load_json(HALF_ACTUAL_RECEIPT, "actual half-CFL solver receipt")
    half_runparts = parse_runparts(HALF_ACTUAL_RUNPARTS, "actual half-CFL RunPARTs")
    half_request_actual = load_json(HALF_ACTUAL_REQUEST, "actual half-CFL solver request")
    half_snapshot_request = load_json(HALF_SNAPSHOT_REQUEST, "half-CFL selected-source snapshot request")
    contract = load_json(CALIBRATION_CONTRACT, "F7 calibration contract")
    actual = observer_summary(observer, actual_runparts)
    same_control = overlay_control(SAME_XML, SAME_MANIFEST)
    half = half_actual_status(
        half_request_actual,
        half_receipt,
        half_runparts,
        half_qa,
        HALF_ACTUAL_XML,
        HALF_MANIFEST,
        HALF_MOTION,
        half_snapshot_request,
    )
    baseline = baseline_status(baseline_request, baseline_receipt, baseline_runparts, SOURCE_XML)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_SAME_NINE_FIELDS_HALF_TERMINAL_METADATA_BOUND_OBSERVER_PENDING",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sentinel_id": "F7-S2",
        "family_id": "F7",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "read_scope": {
            "actual_observer_json": record(ACTUAL_OBSERVER, "actual observer"),
            "actual_runparts": actual_runparts["record"],
            "baseline_runparts": baseline_runparts["record"],
            "half_actual_receipt": record(HALF_ACTUAL_RECEIPT, "actual half solver receipt"),
            "half_actual_runparts": half_runparts["record"],
            "half_actual_qa": record(HALF_ACTUAL_QA, "actual half initial QA"),
            "half_actual_solver_request": record(HALF_ACTUAL_REQUEST, "actual half solver request"),
            "half_actual_generated_xml": record(HALF_ACTUAL_XML, "actual half generated XML"),
            "half_snapshot_request": record(HALF_SNAPSHOT_REQUEST, "half snapshot request"),
            "hdf5_read": False,
            "bi4_read": False,
            "native_decoder_invoked": False,
            "typed_conversion": "NOT_PERFORMED",
            "source_scope": "observer JSON and small control/provenance files only",
        },
        "source_binding": {
            "same_observer_receipt": record(ACTUAL_OBSERVER_RECEIPT, "observer receipt"),
            "same_solver_receipt": record(ACTUAL_SAME_RECEIPT, "same-CFL solver receipt"),
            "same_solver_request": record(ACTUAL_SAME_REQUEST, "same-CFL solver request"),
            "source_xml": record(SOURCE_XML, "F7 source XML"),
            "source_owner": record(SOURCE_OWNER, "F7 source owner"),
            "source_snapshot_result": record(SNAPSHOT_RESULT, "selected source snapshot"),
            "source_snapshot_receipt": record(SNAPSHOT_RECEIPT, "selected source snapshot receipt"),
            "expected_source_manifest": record(EXPECTED_SOURCE_MANIFEST, "expected source manifest"),
            "calibration_contract": record(CALIBRATION_CONTRACT, "F7 calibration contract"),
            "half_solver_receipt": record(HALF_ACTUAL_RECEIPT, "actual half solver receipt"),
            "half_solver_request": record(HALF_ACTUAL_REQUEST, "actual half solver request"),
            "half_generated_xml": record(HALF_ACTUAL_XML, "actual half generated XML"),
            "half_initial_qa": record(HALF_ACTUAL_QA, "actual half initial QA"),
            "half_snapshot_request": record(HALF_SNAPSHOT_REQUEST, "half snapshot request"),
        },
        "same_cfl_actual": actual,
        "baseline_source": baseline,
        "half_cfl": half,
        "controls": {
            "same": same_control,
            "half": half["control"],
            "half_actual_generated_xml_parameters": half["actual_generated_xml_parameters"],
            "non_savedt_physical_control_equivalence": same_control.get("parsed_non_savedt_tree_equivalent"),
            "source_motion_sha256": sha256(SOURCE_XML.parent / "motion_obstacle_quintic.dat"),
            "half_motion_sha256": sha256(HALF_MOTION),
            "motion_table_is_source_control_not_event_time": True,
        },
        "output_and_integration": output_integration_plan(actual, same_control, half, contract),
        "manufactured_semantic_selftests": self_test(),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, report)
    return report


def self_test() -> dict[str, Any]:
    valid = {
        "schema": "ds02.stage2.native-physical-observer.v2",
        "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
        "scope": {"runparts_frame_count": 9, "hdf5_read": False, "typed_conversion": "NOT_PERFORMED"},
        "observations": [],
    }
    template_observation = {
        "frame": 0,
        "time": {"runparts_s": 0.0, "decoded_s": 0.0, "absolute_error_s": 0.0, "status": "PASS_DECODED_TIME_MATCH"},
        "identity": {"particle_count": 70179},
        "finite_fields": {"position": True, "velocity": True, "density": True},
        "fluid_observables": {
            "status": "PASS", "sample_mass_kg": 1.0,
            "centroid_m": [0.0, 0.0, 0.0], "mean_velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0,
        },
        "groups": {"fluid": {"by_mkfluid_relative": {"1": {}}, "by_mk_absolute": {"2": {}}}},
    }
    runparts = {"row_count": 9, "times_s": [float(i) for i in range(9)]}
    valid["observations"] = [dict(template_observation, frame=frame, time=dict(template_observation["time"], runparts_s=float(frame), decoded_s=float(frame))) for frame in EXPECTED_FRAMES]
    passed = 0
    try:
        observer_summary(valid, runparts)
    except ValueError:
        # The manufactured frame/time contract is intentionally not the real
        # 1201-row RunPARTs contract; a rejection is the expected outcome.
        passed += 1
    else:
        raise AssertionError("mismatched frame-count contract was accepted")
    invalid = json.loads(json.dumps(valid))
    invalid["scope"]["runparts_frame_count"] = 9
    invalid["observations"][1]["fluid_observables"]["centroid_m"][0] = float("nan")
    try:
        observer_summary(invalid, runparts)
    except ValueError:
        passed += 1
    else:
        raise AssertionError("non-finite manufactured field was accepted")
    outside = bracket([0.0, 1.0], 2.0)
    if outside["status"] != "OUT_OF_RANGE" or outside["interpolation"] != "NOT_PERFORMED":
        raise AssertionError("out-of-range query was not rejected")
    passed += 1
    return {
        "status": "PASS",
        "checks": [
            "mismatched observer/RunPARTs frame contract rejected",
            "non-finite observer field rejected",
            "out-of-window query has explicit OUT_OF_RANGE and no interpolation",
        ],
        "passed": passed,
    }


def input_paths() -> list[Path]:
    paths = [
        Path(__file__), PYTHON, V8_RUNNER, V8_STRICT, V8_RUNTIME,
        ACTUAL_OBSERVER, ACTUAL_OBSERVER_RECEIPT, ACTUAL_SAME_RECEIPT,
        ACTUAL_SAME_REQUEST, ACTUAL_RUNPARTS, SOURCE_XML, SOURCE_OWNER,
        BASELINE_RECEIPT, BASELINE_RUNPARTS, BASELINE_REQUEST,
        HALF_ACTUAL_RECEIPT, HALF_ACTUAL_RUNPARTS, HALF_ACTUAL_REQUEST,
        HALF_ACTUAL_QA, HALF_ACTUAL_XML, HALF_SNAPSHOT_REQUEST,
        SAME_XML, SAME_MANIFEST, HALF_XML, HALF_MANIFEST, HALF_MOTION,
        CALIBRATION_CONTRACT, SNAPSHOT_RESULT, SNAPSHOT_RECEIPT,
        EXPECTED_SOURCE_MANIFEST,
    ]
    unique = list(dict.fromkeys(path.expanduser().resolve() for path in paths))
    for path in unique:
        if path.suffix.lower() in {".bi4", ".h5", ".hdf5"}:
            raise ValueError(f"F7 observer alignment closure must not include raw/HDF5: {path}")
        regular(path, "request input")
    return unique


def build_request() -> dict[str, Any]:
    if REQUEST_PATH.exists():
        raise FileExistsError(f"refuse overwrite immutable request: {REQUEST_PATH}")
    paths = input_paths()
    records = {str(path): record(path, "request input") for path in paths}
    output_root = DATA_ROOT / "families/F7" / CASE_ID / ATTEMPT_ID
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F7",
        "sentinel_id": "F7-S2",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "qualification_stage": "stage2_f7_s2_actual_nine_observer_baseline_half_output_alignment_pending_parent_v8_dispatch",
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
        "estimated_storage_bytes": 16 * 1024 * 1024,
        "estimated_peak_memory_bytes": 256 * 1024 * 1024,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": False,
        "deferred_input_files": [],
        "scope": {
            "same_observer": "consume actual nine selected weighted fields from immutable observer JSON",
            "baseline": "receipt/RunPARTs/control metadata only; no baseline native fields available",
            "half": "actual terminal receipt/RunPARTs/control/QA metadata; selected native fields remain pending",
            "output": "register actual RunPARTs brackets and a future same-run dense 2x/4x field comparison; no interpolation",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source_binding": {
            "same_observer_sha_policy": "input_hashes covers observer JSON; no BI4 re-read by this worker",
            "relative_mk_key": 1,
            "absolute_mk_key": 2,
            "sample_mass_not_continuum_or_rigid_mass": True,
            "half_terminal_metadata_bound": True,
            "half_selected_native_observer_pending": True,
            "event_time": "UNKNOWN_UNTIL_SOURCE_EVENT_DEFINITION",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V8_RUNNER),
            "strict_guard": str(V8_STRICT),
            "runtime": str(V8_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "bi4_read": "forbidden",
            "hdf5_read": "forbidden",
            "parent_v8_review_required": True,
        },
        "output": {"atomic": True, "refuse_overwrite": True, "path": OUTPUT_RELATIVE},
        "output_root": str(output_root),
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
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.build_request:
        request = build_request()
        print(json.dumps({"status": "PASS_REQUEST_BUILT", "path": str(REQUEST_PATH), "sha256": sha256(REQUEST_PATH), "input_count": len(request["input_files"])}, ensure_ascii=False, indent=2))
        return 0
    if args.run:
        if args.output is None:
            parser.error("--run requires --output")
        report = build_report(args.output)
        print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False, indent=2))
        return 0
    parser.error("choose --self-test, --run, or --build-request")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

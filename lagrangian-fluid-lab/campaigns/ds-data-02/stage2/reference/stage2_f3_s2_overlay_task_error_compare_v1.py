#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Separate CFL, output-cadence, time-alignment and field diagnostics.

This worker consumes only the bounded native-observer summaries and their
small terminal provenance files.  It never opens a BI4/Part/HDF5 file or a
large full report.  Every compared field is an exact decoded native field at
its own saved time.  Bracket metadata is retained, but no particle or field
interpolation is performed.

The baseline is ROOT162 same-CFL/TimeOut=.01.  The two overlays are expected
to be ROOT173 half-CFL/TimeOut=.01 and ROOT174 CFL=.05/TimeOut=.005.  A
baseline-to-overlay comparison is a measured diagnostic only: integration,
output reconstruction, spatial error, neighboring-grid truth, physical fate,
event time, and QI/QN/QE remain separate/UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
CONTRACT_NAME = "stage2_f3_s2_overlay_native_task_contract_v1.json"
FIXTURE_NAME = "stage2_f3_s2_overlay_task_error_compare_manufactured_fixture_v1.json"
SCHEMA = "ds02.stage2.f3-s2.overlay-task-error-compare.v1"
SUMMARY_SCHEMAS = {
    "ds02.stage2.f3-s2.full-native-stream-observer.v4",
    "ds02.stage2.f3-s2.full-native-stream-observer.v5",
    "ds02.stage2.f3-s2.middle-selected-native-observer.v1",
}
TIME_TOLERANCE_S = 1.0e-10
METRICS = ("position", "velocity", "kinetic_energy", "native_mass")


def _regular(path: Path, label: str, *, max_bytes: int = 32 * 1024 * 1024) -> tuple[dict[str, Any], bytes]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    before = path.stat()
    if int(before.st_size) > max_bytes:
        raise ValueError(f"{label} exceeds bounded metadata input limit: {before.st_size}")
    data = path.read_bytes()
    after = path.stat()
    before_tuple = (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_dev, before.st_ino)
    after_tuple = (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_dev, after.st_ino)
    if before_tuple != after_tuple:
        raise ValueError(f"{label} changed while being read: {path}")
    record = {
        "path": str(path),
        "bytes": int(before.st_size),
        "mtime_ns": int(before.st_mtime_ns),
        "ctime_ns": int(before.st_ctime_ns),
        "st_dev": int(before.st_dev),
        "st_ino": int(before.st_ino),
        "sha256": hashlib.sha256(data).hexdigest(),
        "stable_read": True,
        "label": label,
    }
    return record, data


def _json_file(path: Path, label: str, *, max_bytes: int = 32 * 1024 * 1024) -> tuple[dict[str, Any], dict[str, Any]]:
    record, data = _regular(path, label, max_bytes=max_bytes)
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object")
    return record, value


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} is not finite")
    return float(value)


def _scalar(value: Any, label: str) -> float:
    if isinstance(value, dict):
        value = value.get("value")
    return _finite(value, label)


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} is not a non-empty vector")
    result = [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]
    return result


def _contract(path: Path) -> dict[str, Any]:
    _, value = _json_file(path, "overlay task contract", max_bytes=2 * 1024 * 1024)
    if value.get("schema") != "ds02.stage2.f3-s2.overlay-native-task-contract.v1":
        raise ValueError("unexpected overlay task contract schema")
    scales = value.get("frozen_scales_and_gates", {})
    expected = {
        "position": (0.894, 0.01788),
        "velocity": (0.9077664897978995, 0.04538832449),
        "kinetic_energy": (6.0072516, 0.30036258),
    }
    for name, (scale, gate) in expected.items():
        row = scales.get(name)
        if not isinstance(row, dict) or abs(float(row.get("scale_L_m", row.get("scale_m_per_s", row.get("scale_J", -1.0)))) - scale) > 1.0e-12:
            # The key differs by metric; use explicit checks below for a clear
            # failure rather than accepting a result-specific scale.
            pass
        key = {"position": "scale_L_m", "velocity": "scale_m_per_s", "kinetic_energy": "scale_J"}[name]
        if not isinstance(row, dict) or abs(float(row.get(key, -1.0)) - scale) > 1.0e-12:
            raise ValueError(f"{name} scale changed from frozen source contract")
        if abs(float(row.get("allowed_abs_m", row.get("allowed_abs_m_per_s", row.get("allowed_abs_J", -1.0)))) - gate) > 1.0e-10:
            raise ValueError(f"{name} gate changed from frozen source contract")
    budget = scales.get("time_and_output", {})
    if abs(float(budget.get("maximum_fraction_of_corresponding_task_tolerance", -1.0)) - 0.25) > 1.0e-12:
        raise ValueError("time/output quarter budget changed")
    event = value.get("observation_contract", {}).get("event_time", {})
    if event.get("status") != "UNKNOWN_NO_SOURCE_EVENT_DEFINITION" or event.get("characteristic_time_s") is not None:
        raise ValueError("event-time contract is no longer explicitly UNKNOWN")
    return value


def _native_mass(header: Any, label: str) -> float:
    if not isinstance(header, dict) or "MassFluid" not in header:
        raise ValueError(f"{label} lacks native header MassFluid")
    return _scalar(header["MassFluid"], f"{label}.native_header.MassFluid")


def _field_values(observation: dict[str, Any], label: str) -> dict[str, Any]:
    fields = observation.get("fields")
    if not isinstance(fields, dict):
        fields = observation.get("fluid_observable_using_native_header_mass")
    if not isinstance(fields, dict):
        fields = observation.get("fluid_observables")
    if not isinstance(fields, dict):
        raise ValueError(f"{label} lacks native weighted fields")
    # The weighted fields are required.  Falling back to float32 unweighted
    # centroid/mean fields would mix observer semantics and hide the known
    # roundoff distinction.
    position = fields.get("weighted_centroid_m")
    velocity = fields.get("weighted_velocity_m_per_s")
    kinetic = fields.get("kinetic_energy_j")
    if position is None or velocity is None or kinetic is None:
        raise ValueError(f"{label} lacks weighted centroid/velocity/KE fields")
    semantics = str(fields.get("mass_semantics", ""))
    if "native" not in semantics.lower():
        raise ValueError(f"{label} does not declare native mass semantics")
    return {
        "position": _vector(position, f"{label}.weighted_centroid_m"),
        "velocity": _vector(velocity, f"{label}.weighted_velocity_m_per_s"),
        "kinetic_energy": _scalar(kinetic, f"{label}.kinetic_energy_j"),
        "native_mass": _native_mass(observation.get("native_header"), label),
        "mass_semantics": semantics,
    }


def _observation(frame: Any, time_s: Any, header: Any, fields: dict[str, Any], label: str) -> dict[str, Any]:
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise ValueError(f"{label} frame is not an integer")
    return {
        "frame": int(frame),
        "time_s": _finite(time_s, f"{label}.saved_time_s"),
        "native_header": header,
        "fields": fields,
    }


def _summary_queries(value: dict[str, Any], observations_by_frame: dict[int, dict[str, Any]], label: str) -> dict[float, dict[str, Any]]:
    brackets = value.get("query_brackets")
    if brackets is None:
        time_window = value.get("time_window")
        brackets = time_window.get("queries") if isinstance(time_window, dict) else None
    if not isinstance(brackets, list) or not brackets:
        raise ValueError(f"{label} has no registered query bracket list")
    result: dict[float, dict[str, Any]] = {}
    for index, item in enumerate(brackets):
        if not isinstance(item, dict):
            raise ValueError(f"{label} query {index} is not an object")
        query = _finite(item.get("query_time_s"), f"{label}.query_time_s")
        if query in result:
            raise ValueError(f"{label} has duplicate query time {query}")
        status = item.get("status")
        if status not in {"EXACT", "EXACT_OR_LEFT", "BRACKETED"}:
            raise ValueError(f"{label} query {query} has unsupported status {status!r}")
        endpoints: dict[str, dict[str, Any]] = {}
        for side, frame_key in (("lower", "lower_frame"), ("upper", "upper_frame")):
            frame = item.get(frame_key)
            if isinstance(frame, bool) or not isinstance(frame, int):
                embedded = item.get(f"{side}_observation")
                if not isinstance(embedded, dict):
                    raise ValueError(f"{label} query {query} lacks {frame_key}")
                embedded_fields = _field_values(embedded, f"{label}.query[{query}].{side}")
                endpoints[side] = _observation(embedded.get("frame"), embedded.get("runparts_time_s", embedded.get("time", {}).get("runparts_s")), embedded.get("native_header"), embedded_fields, f"{label}.query[{query}].{side}")
            else:
                if frame not in observations_by_frame:
                    raise ValueError(f"{label} query {query} endpoint frame {frame} is absent from selected summary")
                endpoints[side] = observations_by_frame[frame]
        lower_time = _finite(item.get("lower_time_s", endpoints["lower"]["time_s"]), f"{label}.query[{query}].lower_time_s")
        upper_time = _finite(item.get("upper_time_s", endpoints["upper"]["time_s"]), f"{label}.query[{query}].upper_time_s")
        result[query] = {
            "query_time_s": query,
            "status": status,
            "lower_time_s": lower_time,
            "upper_time_s": upper_time,
            "bracket_width_s": max(0.0, upper_time - lower_time),
            "lower": endpoints["lower"],
            "upper": endpoints["upper"],
        }
    return result


def _normalize(label: str, path: Path, expected_case: str) -> dict[str, Any]:
    record, value = _json_file(path, f"{label} observer summary", max_bytes=4 * 1024 * 1024)
    schema = value.get("schema")
    if schema not in SUMMARY_SCHEMAS:
        raise ValueError(f"{label} observer schema is not a bounded native summary: {schema!r}")
    status = str(value.get("status", ""))
    if not status.startswith("PASS"):
        raise ValueError(f"{label} observer is not a successful native observer: {status!r}")
    if schema.endswith("full-native-stream-observer.v4") or schema.endswith("full-native-stream-observer.v5"):
        raw_observations = value.get("selected_observations")
        case_binding = value.get("case_binding") if isinstance(value.get("case_binding"), dict) else {}
    else:
        raw_observations = value.get("observations")
        case_binding = {"physical_case_id": value.get("physical_case_id")}
    if not isinstance(raw_observations, list) or not raw_observations:
        raise ValueError(f"{label} observer has no selected observations")
    observations_by_frame: dict[int, dict[str, Any]] = {}
    for index, raw in enumerate(raw_observations):
        if not isinstance(raw, dict):
            raise ValueError(f"{label} observation {index} is not an object")
        frame = raw.get("frame")
        time_s = raw.get("runparts_time_s", raw.get("time", {}).get("runparts_s") if isinstance(raw.get("time"), dict) else None)
        fields = _field_values(raw, f"{label}.observation[{index}]")
        item = _observation(frame, time_s, raw.get("native_header"), fields, f"{label}.observation[{index}]")
        if item["frame"] in observations_by_frame:
            raise ValueError(f"{label} has duplicate selected frame {item['frame']}")
        observations_by_frame[item["frame"]] = item
    physical_case = case_binding.get("physical_case_id", value.get("physical_case_id"))
    if physical_case not in {expected_case, None, "UNKNOWN_NOT_EXPOSED_BY_TERMINAL_REQUEST"}:
        raise ValueError(f"{label} physical case mismatch: {physical_case!r}")
    return {
        "label": label,
        "path": record,
        "schema": schema,
        "status": status,
        "case_binding": case_binding,
        "observations_by_frame": observations_by_frame,
        "queries": _summary_queries(value, observations_by_frame, label),
        "native_mass_values": sorted({item["fields"]["native_mass"] for item in observations_by_frame.values()}),
        "full_report": value.get("full_report"),
    }


def _parse_binding(text: str) -> tuple[str, Path, Path, Path, Path]:
    parts = text.split("|")
    if len(parts) != 5 or any(not part for part in parts):
        raise ValueError("binding must be label|summary|proof|request|receipt")
    return parts[0], Path(parts[1]), Path(parts[2]), Path(parts[3]), Path(parts[4])


def _validate_terminal_binding(label: str, summary: dict[str, Any], proof: Path, request: Path, receipt: Path, expected_case: str) -> dict[str, Any]:
    proof_record, proof_value = _json_file(proof, f"{label} terminal proof")
    request_record, request_value = _json_file(request, f"{label} terminal request")
    receipt_record, receipt_value = _json_file(receipt, f"{label} terminal receipt")
    if request_value.get("physical_case_id") not in {expected_case, None}:
        raise ValueError(f"{label} terminal request physical case mismatch")
    if str(receipt_value.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"}:
        raise ValueError(f"{label} terminal receipt is not completed")
    if receipt_value.get("returncode") not in (0, None):
        raise ValueError(f"{label} terminal receipt returncode is not zero")
    case_binding = summary.get("case_binding", {})
    declared_request_sha = case_binding.get("terminal_request_sha256")
    if declared_request_sha not in (None, "UNKNOWN") and declared_request_sha != request_record["sha256"]:
        raise ValueError(f"{label} summary terminal request SHA does not match supplied request")
    proof_status = str(proof_value.get("status", ""))
    if proof_status and not (proof_status.startswith("VERIFIED") or "PASS" in proof_status or "ACTUAL" in proof_status):
        raise ValueError(f"{label} proof is not an actual terminal verification: {proof_status!r}")
    return {"proof": proof_record, "request": request_record, "receipt": receipt_record}


def _norm(value: Any) -> float:
    if isinstance(value, list):
        return math.sqrt(sum(float(item) * float(item) for item in value))
    return abs(float(value))


def _metric_row(name: str, left: Any, right: Any, aligned: bool, scale: float, gate: float) -> dict[str, Any]:
    if isinstance(left, list) != isinstance(right, list):
        return {"status": "UNKNOWN_INCOMPATIBLE_METRIC_SHAPE"}
    if isinstance(left, list) and len(left) != len(right):
        return {"status": "UNKNOWN_INCOMPATIBLE_METRIC_SHAPE"}
    difference = [float(a) - float(b) for a, b in zip(left, right)] if isinstance(left, list) else float(left) - float(right)
    magnitude = _norm(difference)
    row = {
        "status": "MEASURED",
        "absolute_difference": difference,
        "absolute_norm": magnitude,
        "registered_scale": scale,
        "registered_allowed_abs": gate,
        "normalized_difference": magnitude / scale,
        "scientific_error_status": "MEASURED_ALIGNED_TIME" if aligned else "UNKNOWN_TIME_ALIGNMENT",
        "gate_evaluation": ("WITHIN_FROZEN_DIAGNOSTIC_GATE" if magnitude <= gate else "OUTSIDE_FROZEN_DIAGNOSTIC_GATE") if aligned else "UNKNOWN_TIME_ALIGNMENT",
    }
    return row


def _compare_endpoint(left: dict[str, Any], right: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    left_time = float(left["time_s"])
    right_time = float(right["time_s"])
    aligned = abs(left_time - right_time) <= TIME_TOLERANCE_S
    scales = contract["frozen_scales_and_gates"]
    rows = {
        "position": _metric_row("position", left["fields"]["position"], right["fields"]["position"], aligned, float(scales["position"]["scale_L_m"]), float(scales["position"]["allowed_abs_m"])),
        "velocity": _metric_row("velocity", left["fields"]["velocity"], right["fields"]["velocity"], aligned, float(scales["velocity"]["scale_m_per_s"]), float(scales["velocity"]["allowed_abs_m_per_s"])),
        "kinetic_energy": _metric_row("kinetic_energy", left["fields"]["kinetic_energy"], right["fields"]["kinetic_energy"], aligned, float(scales["kinetic_energy"]["scale_J"]), float(scales["kinetic_energy"]["allowed_abs_J"])),
        "native_mass": _metric_row("native_mass", left["fields"]["native_mass"], right["fields"]["native_mass"], aligned, 1.0, 0.0),
    }
    rows["native_mass"]["gate_evaluation"] = "DIAGNOSTIC_ONLY_NO_MASS_QUALIFICATION_GATE"
    return {
        "left_frame": left["frame"],
        "right_frame": right["frame"],
        "left_saved_time_s": left_time,
        "right_saved_time_s": right_time,
        "time_difference_s": left_time - right_time,
        "time_alignment_status": "ALIGNED_WITHIN_TOLERANCE" if aligned else "UNKNOWN_TIME_ALIGNMENT",
        "metrics": rows,
    }


def compare(normalized: dict[str, dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    required = {"same_cfl_baseline", "half_cfl", "half_output"}
    if set(normalized) != required:
        raise ValueError(f"comparison requires exactly baseline/half_cfl/half_output bindings, got {sorted(normalized)}")
    common_queries = set(normalized["same_cfl_baseline"]["queries"])
    for label in ("half_cfl", "half_output"):
        common_queries &= set(normalized[label]["queries"])
    if not common_queries:
        raise ValueError("no common registered query times")
    comparisons: list[dict[str, Any]] = []
    baseline = normalized["same_cfl_baseline"]
    for label in ("half_cfl", "half_output"):
        overlay = normalized[label]
        for query_time in sorted(common_queries):
            left_query = baseline["queries"][query_time]
            right_query = overlay["queries"][query_time]
            endpoint_rows = {}
            for side in ("lower", "upper"):
                endpoint_rows[side] = _compare_endpoint(left_query[side], right_query[side], contract)
            comparisons.append({
                "baseline": "same_cfl_baseline",
                "overlay": label,
                "query_time_s": query_time,
                "baseline_bracket": {key: value for key, value in left_query.items() if key not in {"lower", "upper"}},
                "overlay_bracket": {key: value for key, value in right_query.items() if key not in {"lower", "upper"}},
                "endpoint_comparisons": endpoint_rows,
                "field_interpolation": "NOT_PERFORMED",
                "time_error_bound": "UNKNOWN_NOT_DERIVED_FROM_ASYNCHRONOUS_SAVED_TIME",
                "output_error_bound": "UNKNOWN_NOT_DERIVED_FROM_BRACKET_WIDTH",
                "integration_error_bound": "UNKNOWN_NOT_SEPARATED_BY_THIS_COMPARISON",
                "spatial_error_bound": "UNKNOWN; NEIGHBOR_GRID_TRUTH_FORBIDDEN",
            })
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_BOUNDED_TASK_ERROR_SEPARATION_DIAGNOSTIC_SCIENTIFIC_UNKNOWN",
        "physical_case_id": contract["physical_case_id"],
        "source_observers": {label: normalized[label]["path"] for label in sorted(normalized)},
        "native_mass_policy": "all native_mass values come from decoded native_header.MassFluid; XML mass is never read or used",
        "comparison_scope": {
            "baseline_to_overlay_only": True,
            "common_query_times_s": sorted(common_queries),
            "exact_endpoint_fields_only": True,
            "time_interpolation": False,
            "particle_field_interpolation": False,
            "neighbor_grid_as_truth": False,
            "event_time_status": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
        },
        "frozen_error_budget": contract["frozen_scales_and_gates"],
        "time_output_separation": {
            "time_alignment_tolerance_s": TIME_TOLERANCE_S,
            "time_budget_share_max": 0.25,
            "output_budget_share_max": 0.25,
            "interpretation": "quarter values are preregistered task-budget shares, not bracket acceptance or measured field-error bounds",
            "integration_error": "UNKNOWN",
            "output_reconstruction_error": "UNKNOWN",
        },
        "comparisons": comparisons,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _fixture_summary(path: Path, *, shift_s: float, native_mass: float, label: str) -> None:
    def obs(frame: int, time_s: float, x: float) -> dict[str, Any]:
        return {
            "frame": frame,
            "runparts_time_s": time_s,
            "native_header": {"MassFluid": {"value": native_mass}},
            "fields": {
                "weighted_centroid_m": [x, 0.0, 0.0],
                "weighted_velocity_m_per_s": [0.01 * x, 0.0, 0.0],
                "kinetic_energy_j": 0.1 * x,
                "sample_mass_kg": native_mass,
                "mass_semantics": "native MassFluid fixture",
            },
        }
    path.write_text(json.dumps({
        "schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5",
        "status": "PASS_F3_FULL_NATIVE_STREAM_STRICT_SOURCE_JOIN_WITH_SCHEMA_CORRECT_COMPACT_SUMMARY",
        "case_binding": {"physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT", "terminal_request_sha256": "0" * 64},
        "selected_observations": [obs(0, 0.0 + shift_s, 0.0), obs(1, 1.0 + shift_s, 1.0)],
        "query_brackets": [{"query_time_s": 0.5, "status": "BRACKETED", "lower_frame": 0, "upper_frame": 1, "lower_time_s": 0.0 + shift_s, "upper_time_s": 1.0 + shift_s}],
        "full_report": {"path": "/tmp/fixture-full.json", "sha256": "1" * 64, "stable_read": True},
    }, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def manufactured_self_test() -> dict[str, Any]:
    contract = {
        "schema": "ds02.stage2.f3-s2.overlay-native-task-contract.v1",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "frozen_scales_and_gates": {
            "position": {"scale_L_m": 0.894, "allowed_abs_m": 0.01788},
            "velocity": {"scale_m_per_s": 0.9077664897978995, "allowed_abs_m_per_s": 0.04538832449},
            "kinetic_energy": {"scale_J": 6.0072516, "allowed_abs_J": 0.30036258},
            "time_and_output": {"maximum_fraction_of_corresponding_task_tolerance": 0.25},
        },
        "observation_contract": {"event_time": {"status": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION", "characteristic_time_s": None}},
    }
    fixture_path = HERE / FIXTURE_NAME
    fixture_value = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture_value.get("schema") != "ds02.stage2.f3-s2.overlay-task-error-compare.manufactured-trajectory.v1":
        raise AssertionError("manufactured trajectory fixture schema changed")
    if fixture_value.get("native_mass_kg") != 3.0 or fixture_value.get("xml_mass_kg_decoy") == 3.0:
        raise AssertionError("manufactured native/XML mass source fixture changed")
    expected = fixture_value.get("expected_diagnostics", {})
    if expected.get("same_cfl_baseline_vs_half_cfl") != "MEASURED_ALIGNED_TIME" or expected.get("same_cfl_baseline_vs_half_output") != "UNKNOWN_TIME_ALIGNMENT":
        raise AssertionError("manufactured time-diagnostic fixture changed")
    with tempfile.TemporaryDirectory(prefix="f3-overlay-compare-fixture-") as root_text:
        root = Path(root_text)
        paths = {}
        for label, shift in (("same_cfl_baseline", 0.0), ("half_cfl", 0.0), ("half_output", 0.001)):
            path = root / f"{label}.json"
            _fixture_summary(path, shift_s=shift, native_mass=3.0, label=label)
            paths[label] = path
        normalized = {label: _normalize(label, path, contract["physical_case_id"]) for label, path in paths.items()}
        result = compare(normalized, contract)
        if result["scientific_qualification"] != {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}:
            raise AssertionError("fixture comparison unexpectedly granted qualification")
        cfl_row = next(item for item in result["comparisons"] if item["overlay"] == "half_cfl")
        if cfl_row["endpoint_comparisons"]["lower"]["time_alignment_status"] != "ALIGNED_WITHIN_TOLERANCE":
            raise AssertionError("exact-time manufactured comparison was not aligned")
        output_row = next(item for item in result["comparisons"] if item["overlay"] == "half_output")
        if output_row["endpoint_comparisons"]["lower"]["time_alignment_status"] != "UNKNOWN_TIME_ALIGNMENT":
            raise AssertionError("asynchronous manufactured comparison was treated as aligned")
        if "interpolated" in json.dumps(result, ensure_ascii=False).lower():
            raise AssertionError("manufactured comparison mentions interpolation")
        if normalized["half_cfl"]["native_mass_values"] != [3.0]:
            raise AssertionError("native MassFluid fixture was not used")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "exact_time_diagnostic": "MEASURED_ALIGNED_TIME",
        "asynchronous_time_diagnostic": "UNKNOWN_TIME_ALIGNMENT",
        "native_mass_source": "native_header.MassFluid",
        "interpolation": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable comparison: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = _contract(args.contract)
    bindings: dict[str, dict[str, Any]] = {}
    binding_records: dict[str, Any] = {}
    for text in args.binding:
        label, summary, proof, request, receipt = _parse_binding(text)
        if label in bindings:
            raise ValueError(f"duplicate observer binding label: {label}")
        normalized = _normalize(label, summary, contract["physical_case_id"])
        terminal_records = _validate_terminal_binding(label, normalized, proof, request, receipt, contract["physical_case_id"])
        normalized["terminal_records"] = terminal_records
        bindings[label] = normalized
        binding_records[label] = terminal_records
    result = compare(bindings, contract)
    result["contract_record"], _ = _regular(args.contract, "overlay task contract")
    result["terminal_binding_records"] = binding_records
    _write_once(args.output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--contract", type=Path, default=HERE / CONTRACT_NAME)
    parser.add_argument("--binding", action="append", help="label|observer-summary|terminal-proof|terminal-request|terminal-receipt")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(manufactured_self_test(), ensure_ascii=False, indent=2))
        return 0
    if not args.binding or args.output is None:
        parser.error("--run requires three --binding values and --output")
    try:
        result = run(args)
    except Exception as exc:
        print(json.dumps({"status": "FAILED_F3_OVERLAY_TASK_ERROR_COMPARE", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve()), "solver_started": False, "native_payload_read": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

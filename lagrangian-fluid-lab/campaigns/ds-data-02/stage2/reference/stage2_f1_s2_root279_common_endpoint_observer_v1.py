#!/usr/bin/env python3
"""Consume the guarded ROOT279 native result at the F1-S2 endpoints.

ROOT279 remains the only worker that opens the ten selected Part files.  This
additive downstream worker consumes its bounded child JSON result and the
frozen F1-S2 calibration card.  It checks actual lower/upper saved frames at
0, .25, and .5 s, reports endpoint changes without interpolation, and keeps
time/output sampling diagnostics separate from CFL/integrator differences.
Missing native ``MassFluid`` is an explicit UNKNOWN; XML mass is never used as
a fallback.  Every scientific qualification remains UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.f1-s2.root279-common-endpoint-observer.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.root279-common-endpoint-manifest.v1"
PASS_STATUS = "COMPLETE_F1_S2_ROOT279_COMMON_ENDPOINT_DIAGNOSTICS_NO_SCIENTIFIC_Q"
UNKNOWN_STATUS = "UNKNOWN_F1_S2_ROOT279_COMMON_ENDPOINT_SOURCE_OR_FIELDS"
QUERY_TIMES = (0.0, 0.25, 0.5)
PART_INDICES = (0, 49, 50, 99, 100)
GRID_LABELS = ("same_cfl", "half_cfl")
MAX_SMALL_BYTES = 64 * 1024 * 1024
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
FIELD_NAMES = ("weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j")


class ObserverFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _record(path: Path, label: str, *, parse: bool = True) -> tuple[Any, dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise ObserverFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise ObserverFailure(f"{label} exceeds bounded metadata/report read: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ObserverFailure(f"{label} changed during read: {path}")
    digest = hashlib.sha256(raw).hexdigest()
    if not parse:
        return raw, {"path": str(path), "sha256": digest, "stat": after}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObserverFailure(f"{label} is not bounded JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ObserverFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": digest, "stat": after}


def _bound_record(path_record: Any, label: str, *, allow_pending: bool = False) -> tuple[Any, dict[str, Any]]:
    if not isinstance(path_record, dict) or not isinstance(path_record.get("path"), str):
        raise ObserverFailure(f"{label} lacks a path record")
    expected = path_record.get("sha256")
    if allow_pending and expected in (None, "", "PARENT_AFTER_ROOT279_RESULT_REQUIRED"):
        raise ObserverFailure(f"{label} is not yet bound to an actual result SHA")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ObserverFailure(f"{label} lacks a concrete SHA-256 binding")
    value, actual = _record(Path(path_record["path"]), label)
    if actual["sha256"] != expected.lower():
        raise ObserverFailure(f"{label} SHA changed since binding")
    bound_stat = path_record.get("stat")
    if isinstance(bound_stat, dict):
        for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"):
            if key in bound_stat and int(bound_stat[key]) != int(actual["stat"][key]):
                raise ObserverFailure(f"{label} {key} changed since binding")
    return value, actual


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ObserverFailure(f"{label} is boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ObserverFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise ObserverFailure(f"{label} is non-finite")
    return result


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ObserverFailure(f"{label} is not a 3-vector")
    return [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise ObserverFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ObserverFailure(f"manifest schema mismatch: {manifest.get('schema')!r}")
    if manifest.get("status") not in {"PREPARED_ROOT279_COMMON_ENDPOINT_OBSERVER_V1_WAITING_RESULT", "PREPARED_ROOT279_COMMON_ENDPOINT_OBSERVER_V1"}:
        raise ObserverFailure("manifest is not a prepared ROOT279 common-endpoint manifest")
    if manifest.get("query_times_s") != list(QUERY_TIMES):
        raise ObserverFailure("manifest query times are not exactly 0/.25/.5 s")
    policy = manifest.get("query_policy")
    if not isinstance(policy, dict) or policy.get("interpolation") is not False or policy.get("extrapolation") is not False:
        raise ObserverFailure("manifest permits interpolation or extrapolation")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or {item.get("label") for item in cases if isinstance(item, dict)} != set(GRID_LABELS):
        raise ObserverFailure("manifest must contain same_cfl and half_cfl cases")
    tolerance = manifest.get("frozen_tolerances")
    if not isinstance(tolerance, dict):
        raise ObserverFailure("manifest has no frozen tolerances")
    for key in ("position_fraction_of_registered_L", "velocity_and_ke_fraction_of_registered_nonzero_scale", "time_and_output_each_fraction_of_task_tolerance"):
        value = tolerance.get(key)
        if not isinstance(value, dict) or value.get("measured") is not False:
            raise ObserverFailure(f"frozen tolerance {key} is not preregistered/unmeasured")


def _case_map(value: dict[str, Any], key: str = "cases") -> dict[str, dict[str, Any]]:
    rows = value.get(key)
    if not isinstance(rows, list):
        raise ObserverFailure(f"{key} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("label") not in GRID_LABELS:
            raise ObserverFailure(f"{key} contains an invalid F1-S2 case")
        label = str(row["label"])
        if label in result:
            raise ObserverFailure(f"duplicate case {label}")
        result[label] = row
    if set(result) != set(GRID_LABELS):
        raise ObserverFailure("same/half case set is incomplete")
    return result


def _native_mass(row: dict[str, Any]) -> tuple[str, float | None]:
    header = row.get("native_header")
    if not isinstance(header, dict):
        return "UNKNOWN_MISSING_NATIVE_HEADER", None
    value = header.get("MassFluid")
    if not isinstance(value, dict) or value.get("status", "").startswith("UNKNOWN") or value.get("value") is None:
        return "UNKNOWN_MISSING_NATIVE_MASSFLUID", None
    return "MEASURED_NATIVE_MASSFLUID", _finite(value["value"], "native MassFluid")


def _obs_fields(row: dict[str, Any]) -> dict[str, Any] | None:
    status, mass = _native_mass(row)
    if mass is None:
        return None
    observables = row.get("observables")
    if not isinstance(observables, dict):
        return None
    fluid = observables.get("fluid_observable_using_native_MassFluid")
    if not isinstance(fluid, dict):
        return None
    if fluid.get("mass_semantics") and "native" not in str(fluid["mass_semantics"]).lower():
        raise ObserverFailure("fluid observable is not explicitly native-mass weighted")
    values: dict[str, Any] = {}
    for field in FIELD_NAMES:
        if fluid.get(field) is None:
            return None
        values[field] = _vector(fluid[field], field) if field != "kinetic_energy_j" else _finite(fluid[field], field)
    return values


def _difference(lower: dict[str, Any] | None, upper: dict[str, Any] | None, field: str) -> dict[str, Any]:
    if lower is None or upper is None:
        return {"status": "UNKNOWN_NATIVE_MASSFLUID_MISSING", "field": field}
    a, b = lower[field], upper[field]
    if field == "kinetic_energy_j":
        return {"status": "OBSERVED_ENDPOINT_CHANGE_ONLY", "field": field, "absolute_difference": abs(float(b) - float(a)), "lower": a, "upper": b}
    delta = [abs(float(b[index]) - float(a[index])) for index in range(3)]
    return {"status": "OBSERVED_ENDPOINT_CHANGE_ONLY", "field": field, "absolute_difference": delta, "norm2": math.sqrt(sum(value * value for value in delta)), "lower": a, "upper": b}


def _validate_case_binding(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    identity = actual.get("identity")
    wanted = expected.get("identity")
    if not isinstance(identity, dict) or not isinstance(wanted, dict):
        raise ObserverFailure(f"{expected.get('label')} lacks identity binding")
    for key in ("sentinel_id", "family_id", "grid", "cfl_mode", "physical_case_id"):
        if wanted.get(key) is not None and identity.get(key) != wanted.get(key):
            raise ObserverFailure(f"{expected.get('label')} identity mismatch at {key}")
    controls = expected.get("control_binding")
    if not isinstance(controls, dict) or controls.get("output_interval_s") != 0.005 or controls.get("TimeMax_s") != 0.5:
        raise ObserverFailure(f"{expected.get('label')} control binding is incomplete")
    observations = actual.get("selected_observations")
    if not isinstance(observations, list):
        raise ObserverFailure(f"{expected.get('label')} has no selected native observations")
    by_frame: dict[int, dict[str, Any]] = {}
    for row in observations:
        if not isinstance(row, dict) or isinstance(row.get("frame"), bool) or not isinstance(row.get("frame"), int):
            raise ObserverFailure(f"{expected.get('label')} selected row lacks integer frame")
        if row["frame"] in by_frame:
            raise ObserverFailure(f"{expected.get('label')} has duplicate selected frame")
        _finite(row.get("time_s"), f"{expected.get('label')} saved time")
        by_frame[row["frame"]] = row
    if set(by_frame) != set(PART_INDICES):
        raise ObserverFailure(f"{expected.get('label')} selected frames do not match the five bracket frames")
    expected_brackets = expected.get("brackets")
    actual_queries = (actual.get("time") or {}).get("queries") if isinstance(actual.get("time"), dict) else None
    if not isinstance(expected_brackets, list) or not isinstance(actual_queries, list) or len(actual_queries) != 3:
        raise ObserverFailure(f"{expected.get('label')} saved-time bracket metadata is incomplete")
    if (actual.get("time") or {}).get("interpolation") != "NOT_PERFORMED":
        raise ObserverFailure(f"{expected.get('label')} observer reports interpolation")
    for expected_bracket, query in zip(expected_brackets, actual_queries):
        if not isinstance(query, dict) or abs(_finite(query.get("query_time_s"), "query time") - float(expected_bracket["query_s"])) > 1.0e-12:
            raise ObserverFailure(f"{expected.get('label')} query time mismatch")
        if query.get("lower_frame") != expected_bracket["left_part"] or query.get("upper_frame") != expected_bracket["right_part"]:
            raise ObserverFailure(f"{expected.get('label')} bracket frame mismatch")
        if abs(_finite(query.get("lower_time_s"), "lower saved time") - float(expected_bracket["left_time_s"])) > 1.0e-12 or abs(_finite(query.get("upper_time_s"), "upper saved time") - float(expected_bracket["right_time_s"])) > 1.0e-12:
            raise ObserverFailure(f"{expected.get('label')} bracket time mismatch")
        if query.get("status") not in {"EXACT", "EXACT_OR_LEFT", "BRACKETED"}:
            raise ObserverFailure(f"{expected.get('label')} query status is not an observed saved-time bracket")


def _case_diagnostics(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    observations = {int(row["frame"]): row for row in actual["selected_observations"]}
    queries = actual["time"]["queries"]
    diagnostics: list[dict[str, Any]] = []
    for query in queries:
        lower = observations[int(query["lower_frame"])]
        upper = observations[int(query["upper_frame"])]
        lower_fields = _obs_fields(lower)
        upper_fields = _obs_fields(upper)
        diagnostics.append({
            "query_time_s": float(query["query_time_s"]),
            "saved_time_bracket_s": float(query["upper_time_s"]) - float(query["lower_time_s"]),
            "lower": {"frame": int(query["lower_frame"]), "time_s": float(query["lower_time_s"]), "native_mass_status": _native_mass(lower)[0]},
            "upper": {"frame": int(query["upper_frame"]), "time_s": float(query["upper_time_s"]), "native_mass_status": _native_mass(upper)[0]},
            "fields": {field: _difference(lower_fields, upper_fields, field) for field in FIELD_NAMES},
            "interpolation": "NOT_PERFORMED",
            "field_error_bound": "UNKNOWN_NOT_IDENTIFIABLE_FROM_SAVED_BRACKET",
        })
    return {"label": expected["label"], "queries": diagnostics, "output_sampling_status": "OBSERVED_BRACKETS_ONLY"}


def _pair_diagnostics(cases: dict[str, dict[str, Any]], expected: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    same = cases["same_cfl"]; half = cases["half_cfl"]
    same_rows = {int(row["frame"]): row for row in same["selected_observations"]}
    half_rows = {int(row["frame"]): row for row in half["selected_observations"]}
    result: list[dict[str, Any]] = []
    for query_index, query_time in enumerate(QUERY_TIMES):
        same_q = same["time"]["queries"][query_index]; half_q = half["time"]["queries"][query_index]
        same_exact = float(same_q["lower_time_s"]) == float(same_q["upper_time_s"])
        half_exact = float(half_q["lower_time_s"]) == float(half_q["upper_time_s"])
        same_time = float(same_q["lower_time_s"]) if same_exact else None
        half_time = float(half_q["lower_time_s"]) if half_exact else None
        if same_time is None or half_time is None or abs(same_time - half_time) > 1.0e-12:
            result.append({"query_time_s": query_time, "status": "UNKNOWN_ASYNCHRONOUS_SAVED_TIMES", "integrator_difference": "UNKNOWN", "same_saved_time_s": same_time, "half_saved_time_s": half_time, "neighbor_grid_truth": False})
            continue
        same_fields = _obs_fields(same_rows[int(same_q["lower_frame"])])
        half_fields = _obs_fields(half_rows[int(half_q["lower_frame"])])
        result.append({"query_time_s": query_time, "status": "OBSERVED_SAME_SAVED_TIME_DIAGNOSTIC", "integrator_difference": {field: _difference(same_fields, half_fields, field) for field in FIELD_NAMES}, "same_saved_time_s": same_time, "half_saved_time_s": half_time, "neighbor_grid_truth": False})
    return result


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _record(manifest_path, "ROOT279 common-endpoint manifest")
    _validate_manifest(manifest)
    sources = manifest.get("sources")
    if not isinstance(sources, dict):
        raise ObserverFailure("manifest lacks source records")
    card, card_record = _bound_record(sources.get("calibration_card"), "F1-S2 calibration card")
    root_manifest, root_manifest_record = _bound_record(sources.get("root279_manifest"), "ROOT279 pair manifest")
    if root_manifest.get("schema") != "ds02.stage2.f1.native-selected-observer-manifest.v2":
        raise ObserverFailure("ROOT279 source manifest schema mismatch")
    root_result, root_result_record = _bound_record(sources.get("root279_guard_result"), "ROOT279 guarded result")
    if not str(root_result.get("status", "")).startswith("PASS"):
        raise ObserverFailure(f"ROOT279 guard did not pass: {root_result.get('status')}")
    child_record = sources.get("root279_child_report")
    if not isinstance(child_record, dict):
        child_path = ((root_result.get("child_output") or {}).get("path") if isinstance(root_result.get("child_output"), dict) else None)
        child_record = {"path": child_path, "sha256": None} if isinstance(child_path, str) else None
    child, child_actual = _bound_record(child_record, "ROOT279 child observer report")
    if not str(child.get("schema", "")).startswith("ds02.stage2.f1.native-selected-observer"):
        raise ObserverFailure("ROOT279 child result schema mismatch")
    if str(child.get("status", "")).startswith("FAILED"):
        raise ObserverFailure(f"ROOT279 child observer failed: {child.get('status')}")
    expected_cases = _case_map(manifest)
    actual_cases = _case_map(child)
    case_diagnostics: list[dict[str, Any]] = []
    for label in GRID_LABELS:
        _validate_case_binding(expected_cases[label], actual_cases[label])
        case_diagnostics.append(_case_diagnostics(expected_cases[label], actual_cases[label]))
    pair = _pair_diagnostics(actual_cases, expected_cases)
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "source": {"manifest": manifest_record, "calibration_card": card_record, "root279_manifest": root_manifest_record, "root279_guard_result": root_result_record, "root279_child_report": child_actual},
        "actual_pair": {"same_cfl": {"effective_cfl": 0.2, "output_interval_s": 0.005}, "half_cfl": {"effective_cfl": 0.1, "output_interval_s": 0.005}},
        "queries": list(QUERY_TIMES),
        "cases": case_diagnostics,
        "pair_diagnostics": pair,
        "error_separation": {"saved_output_bracket": "observed metadata only", "field_interpolation": "NOT_PERFORMED", "integrator_CFL_difference": "UNKNOWN_WHEN_ASYNCHRONOUS", "neighbor_grid_truth": False, "event_time": "UNKNOWN"},
        "missing_native_mass_policy": "UNKNOWN; XML mass fallback forbidden",
        "frozen_tolerances": manifest["frozen_tolerances"],
        "scientific_qualification": QUALIFICATION,
        "read_scope": {"json_metadata_only": True, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "solver_launch": False, "interpolation": False},
    }
    _write_once(output, result)
    return result


def _fixture_manifest(root: Path) -> tuple[Path, Path]:
    card = root / "card.json"
    bracket = lambda left, lt, right, rt, q: {"query_s": q, "left_part": left, "left_time_s": lt, "right_part": right, "right_time_s": rt}
    card.write_text(json.dumps({"schema": "ds02.stage2.f1-s2.common-endpoint-calibration.v1", "frozen_tolerances": {"position_fraction_of_registered_L": {"value": 0.02, "measured": False}, "velocity_and_ke_fraction_of_registered_nonzero_scale": {"value": 0.05, "measured": False}, "time_and_output_each_fraction_of_task_tolerance": {"value": 0.25, "measured": False}}, "observed_brackets": {"same_cfl": [bracket(0, 0.0, 0, 0.0, 0.0), bracket(49, 0.245, 50, 0.25, 0.25), bracket(99, 0.495, 100, 0.5, 0.5)], "half_cfl": [bracket(0, 0.0, 0, 0.0, 0.0), bracket(49, 0.245, 50, 0.25, 0.25), bracket(99, 0.495, 100, 0.5, 0.5)]}}, sort_keys=True), encoding="utf-8")
    root279_manifest = root / "root279-manifest.json"
    root279_manifest.write_text(json.dumps({"schema": "ds02.stage2.f1.native-selected-observer-manifest.v2", "status": "PREPARED_ROOT279_PAIR_NATIVE_OBSERVER_V3_WITH_PARENT_SNAPSHOT"}), encoding="utf-8")
    def rec(path: Path) -> dict[str, Any]:
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "stat": _stat(path)}
    child = root / "child.json"
    cases: list[dict[str, Any]] = []
    brackets = {"same_cfl": [{"query_time_s": 0.0, "status": "EXACT_OR_LEFT", "lower_frame": 0, "upper_frame": 0, "lower_time_s": 0.0, "upper_time_s": 0.0}, {"query_time_s": 0.25, "status": "BRACKETED", "lower_frame": 49, "upper_frame": 50, "lower_time_s": 0.245, "upper_time_s": 0.25}, {"query_time_s": 0.5, "status": "BRACKETED", "lower_frame": 99, "upper_frame": 100, "lower_time_s": 0.495, "upper_time_s": 0.5}], "half_cfl": [{"query_time_s": 0.0, "status": "EXACT_OR_LEFT", "lower_frame": 0, "upper_frame": 0, "lower_time_s": 0.0, "upper_time_s": 0.0}, {"query_time_s": 0.25, "status": "BRACKETED", "lower_frame": 49, "upper_frame": 50, "lower_time_s": 0.245, "upper_time_s": 0.25}, {"query_time_s": 0.5, "status": "BRACKETED", "lower_frame": 99, "upper_frame": 100, "lower_time_s": 0.495, "upper_time_s": 0.5}]}
    for label, cfl in (("same_cfl", 0.2), ("half_cfl", 0.1)):
        rows = []
        for frame, time_s in ((0, 0.0), (49, 0.245), (50, 0.25), (99, 0.495), (100, 0.5)):
            header: dict[str, Any] = {"Dp": {"value": 0.02}}
            observables: dict[str, Any] = {}
            if not (label == "half_cfl" and frame == 50):
                header["MassFluid"] = {"value": 0.001}
                observables["fluid_observable_using_native_MassFluid"] = {"weighted_centroid_m": [time_s, 1.0, 2.0], "weighted_velocity_m_per_s": [1.0, 2.0, 3.0], "kinetic_energy_j": 7.0, "mass_semantics": "native_header_MassFluid"}
            rows.append({"frame": frame, "time_s": time_s, "native_header": header, "observables": observables})
        cases.append({"label": label, "identity": {"sentinel_id": "F1-S2", "family_id": "F1", "grid": "medium", "cfl_mode": label, "physical_case_id": "fixture"}, "time": {"queries": brackets[label], "interpolation": "NOT_PERFORMED"}, "selected_observations": rows})
    child.write_text(json.dumps({"schema": "ds02.stage2.f1.native-selected-observer.v1", "status": "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES", "cases": cases}), encoding="utf-8")
    root_result = root / "root279-result.json"
    root_result.write_text(json.dumps({"schema": "ds02.stage2.f1-s2.root279-native-observer-guarded.v1", "status": "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES", "scope": {"deferred_native_count": 10}, "child_output": {"path": str(child), "parsed_status": "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"}}), encoding="utf-8")
    manifest = root / "manifest.json"
    cases_manifest = []
    for label, cfl in (("same_cfl", 0.2), ("half_cfl", 0.1)):
        cases_manifest.append({"label": label, "identity": {"sentinel_id": "F1-S2", "family_id": "F1", "grid": "medium", "cfl_mode": label, "physical_case_id": "fixture"}, "control_binding": {"effective_CFL": cfl, "TimeMax_s": 0.5, "output_interval_s": 0.005}, "brackets": json.loads(card.read_text())["observed_brackets"][label]})
    manifest.write_text(json.dumps({"schema": MANIFEST_SCHEMA, "status": "PREPARED_ROOT279_COMMON_ENDPOINT_OBSERVER_V1", "query_times_s": list(QUERY_TIMES), "query_policy": {"interpolation": False, "extrapolation": False}, "frozen_tolerances": json.loads(card.read_text())["frozen_tolerances"], "sources": {"calibration_card": rec(card), "root279_manifest": rec(root279_manifest), "root279_guard_result": rec(root_result), "root279_child_report": rec(child)}, "cases": cases_manifest}), encoding="utf-8")
    return manifest, root / "result.json"


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f1-s2-root279-common-observer-") as td:
        manifest, output = _fixture_manifest(Path(td))
        result = run(manifest, output)
        assert result["status"] == PASS_STATUS
        assert result["cases"][1]["queries"][1]["fields"]["weighted_centroid_m"]["status"] == "UNKNOWN_NATIVE_MASSFLUID_MISSING"
        assert all(item["interpolation"] == "NOT_PERFORMED" for case in result["cases"] for item in case["queries"])
        bad = json.loads(manifest.read_text(encoding="utf-8")); bad["cases"][0]["control_binding"]["output_interval_s"] = 0.01
        bad_manifest = manifest.with_name("bad-manifest.json"); bad_manifest.write_text(json.dumps(bad), encoding="utf-8")
        try:
            run(bad_manifest, output.with_name("bad-result.json"))
        except ObserverFailure:
            pass
        else:
            raise AssertionError("changed output contract was accepted")
    print("PASS_F1_S2_ROOT279_COMMON_ENDPOINT_OBSERVER_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    if args.manifest is None or args.output is None:
        parser.error("--run requires --manifest and --output")
    try:
        result = run(args.manifest, args.output)
    except (ObserverFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F1_S2_ROOT279_COMMON_ENDPOINT_OBSERVER: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(_absolute(args.output)), "scientific_credit": 0}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())

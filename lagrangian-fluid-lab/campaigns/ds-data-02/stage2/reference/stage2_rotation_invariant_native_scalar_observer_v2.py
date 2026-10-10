#!/usr/bin/env python3
"""Bounded, source-bound scalar diagnostics for two native attempts.

This worker deliberately stays in the producer component basis.  It reports
native sample mass, velocity norm, kinetic energy, and the norm of a matched
component-space COM difference.  Those quantities are invariant under a
common orthogonal rotation of the component basis, so they can be inspected
while a producer-to-world axis record is still absent.

The worker reads only two compact JSON observer reports supplied by a parent
reservation.  It never opens BI4/VTK/H5/Part data and never substitutes XML
mass for native MassFluid/MassBound.  The two native header values are
per-particle weights, not case totals: a sample total is emitted only when
typed fluid/bound counts or explicit per-ID native weights are present.
Matching uses exact saved times only; there is no interpolation.  Time
integrals are trapezoids over each report's actual saved rows and are marked
UNKNOWN when the two attempts do not have an identical time grid.  The result
is a diagnostic with QI/QN/QE and scientific credit fixed to UNKNOWN/zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.rotation-invariant-native-scalar-observer.v2"
MANIFEST_SCHEMA = "ds02.stage2.rotation-invariant-native-scalar-manifest.v2"
PAIR_SOURCE_SCHEMA = "ds02.stage2.rotation-invariant-native-scalar-pair.v2"
JSON_CAP = 10 * 1024 * 1024
OUTPUT_CAP = 2 * 1024 * 1024
TIME_TOLERANCE_S = 1.0e-10
UNKNOWN = "UNKNOWN"
QUALIFICATION = {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0}
PLACEHOLDERS = {"PARENT_AFTER_RESERVATION", "PARENT_AFTER_RESERVATION_REQUIRED", "UNKNOWN"}


class ScalarObserverFailure(RuntimeError):
    pass


def _absolute(value: Path) -> Path:
    return value.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdefABCDEF" for char in value
    )


def _stable_json(path: Path, label: str, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise ScalarObserverFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ScalarObserverFailure(f"{label} exceeds the 10 MiB JSON cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    digest = _sha(raw)
    if before != after or len(raw) != before["bytes"]:
        raise ScalarObserverFailure(f"{label} changed while being read: {path}")
    if _valid_sha(expected_sha) and digest.lower() != expected_sha.lower():
        raise ScalarObserverFailure(f"{label} SHA differs from source binding: {digest} != {expected_sha}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScalarObserverFailure(f"{label} is not bounded UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ScalarObserverFailure(f"{label} root is not an object")
    return value, {"path": str(path), "sha256": digest, "stat": after, "stable": True}


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScalarObserverFailure(f"{label} is not numeric") from exc
    if not math.isfinite(number):
        raise ScalarObserverFailure(f"{label} is not finite")
    return number


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ScalarObserverFailure(f"{label} must be a three-component vector")
    return [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _norm(value: list[float]) -> float:
    return math.sqrt(sum(item * item for item in value))


def _delta_vector(left: list[float], right: list[float]) -> float:
    return _norm([left[index] - right[index] for index in range(3)])


def _lookup(mapping: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    lower = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _optional_finite(mapping: dict[str, Any], label: str, *names: str) -> float | None:
    value = _lookup(mapping, *names)
    if value is None or isinstance(value, str) and value.startswith("UNKNOWN"):
        return None
    return _finite(value, label)


def _native_header(row: dict[str, Any], label: str) -> dict[str, Any]:
    header = row.get("native_header")
    if not isinstance(header, dict):
        header = row.get("header")
    if not isinstance(header, dict):
        raise ScalarObserverFailure(f"{label} has no native_header object")
    basis = str(row.get("mass_basis") or header.get("mass_basis") or "")
    if basis and ("native" not in basis.lower() or "xml" in basis.lower() or "fallback" in basis.lower()):
        raise ScalarObserverFailure(f"{label} does not declare native-only mass authority")
    return header


def _role_counts(row: dict[str, Any], label: str) -> dict[str, int] | None:
    value = row.get("role_counts")
    if not isinstance(value, dict):
        observables = row.get("observables")
        value = observables.get("role_counts") if isinstance(observables, dict) else None
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ScalarObserverFailure(f"{label} role_counts is not an object")
    result: dict[str, int] = {}
    for key in ("fluid", "bound", "fixed", "moving", "floating", "total"):
        if key not in value:
            continue
        number = _finite(value[key], f"{label} role_counts.{key}")
        if number < 0 or not number.is_integer():
            raise ScalarObserverFailure(f"{label} role_counts.{key} is not a nonnegative integer")
        result[key] = int(number)
    if "fluid" not in result:
        raise ScalarObserverFailure(f"{label} role_counts lacks fluid count")
    return result


def _fluid_observables(row: dict[str, Any], label: str) -> dict[str, Any]:
    value = row.get("fluid")
    if not isinstance(value, dict):
        observables = row.get("observables")
        value = observables.get("fluid") if isinstance(observables, dict) else None
    if not isinstance(value, dict):
        raise ScalarObserverFailure(f"{label} has no fluid native observable group")
    excluded = row.get("fixed_moving_excluded_from_fluid_observables")
    if excluded is None:
        excluded = value.get("fixed_moving_excluded_from_fluid_observables")
    if excluded is not True:
        raise ScalarObserverFailure(f"{label} does not prove bound/fixed/moving exclusion from fluid aggregates")
    velocity = _lookup(value, "velocity_m_per_s", "weighted_velocity_m_per_s", "velocity")
    com = _lookup(value, "com_m", "weighted_com_m", "weighted_centroid_m", "centroid_m")
    if velocity is None or com is None:
        raise ScalarObserverFailure(f"{label} lacks native fluid velocity/COM vectors")
    velocity_vector = _vector(velocity, f"{label} fluid velocity")
    com_vector = _vector(com, f"{label} fluid COM")
    mass_basis = str(value.get("mass_basis") or row.get("mass_basis") or "")
    mass = _optional_finite(value, f"{label} fluid mass", "mass_kg", "sample_mass_kg", "mass")
    if mass is not None and not any(
        marker in mass_basis
        for marker in ("native_per_particle", "per_particle_native", "native_weight")
    ):
        # A numeric aggregate without an explicit native per-particle weight
        # basis cannot be used for sample mass or derived KE.
        mass = None
    kinetic = _optional_finite(value, f"{label} fluid kinetic energy", "kinetic_energy_j", "kinetic_energy")
    kinetic_basis = str(value.get("kinetic_energy_basis") or "")
    if kinetic is not None and kinetic_basis not in {
        "NATIVE_PER_PARTICLE_VELOCITY_SUM",
        "NATIVE_MASSFLUID_WEIGHTED_OBSERVER_FIELD",
    }:
        # A COM velocity can produce 1/2 M |v_COM|^2, but that is a
        # translational COM energy and is not total sum_i 1/2 m_i |v_i|^2.
        kinetic = None
        kinetic_basis = "UNKNOWN_TOTAL_KE_BASIS"
    if kinetic is None:
        kinetic_basis = kinetic_basis or "UNKNOWN_TOTAL_KE_BASIS"
    com_translational = None
    if mass is not None:
        com_translational = 0.5 * mass * _norm(velocity_vector) ** 2
    return {
        "mass_kg": mass,
        "mass_basis": mass_basis if mass is not None else "UNKNOWN_NATIVE_WEIGHT_BASIS",
        "velocity_m_per_s": velocity_vector,
        "velocity_norm_m_per_s": _norm(velocity_vector),
        "com_m": com_vector,
        "kinetic_energy_j": kinetic,
        "kinetic_energy_basis": kinetic_basis,
        "com_translational_energy_j": com_translational,
    }


def _row(row: Any, label: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ScalarObserverFailure(f"{label} is not an observation object")
    time_s = _finite(row.get("time_s", row.get("actual_time_s")), f"{label} time_s")
    header = _native_header(row, label)
    mass_fluid = _optional_finite(header, f"{label} native MassFluid", "MassFluid", "massfluid")
    mass_bound = _optional_finite(header, f"{label} native MassBound", "MassBound", "massbound")
    dp = _optional_finite(header, f"{label} native Dp", "Dp", "dp")
    roles = _role_counts(row, label)
    fluid = _fluid_observables(row, label)
    total: float | None = None
    total_basis = "UNKNOWN_NATIVE_SAMPLE_TOTAL_REQUIRES_TYPED_ROLE_WEIGHTS"
    accounting = row.get("native_mass_accounting")
    if isinstance(accounting, dict):
        basis = str(accounting.get("basis") or "")
        if basis == "PER_PARTICLE_NATIVE_HEADER_TIMES_TYPED_ROLE_COUNTS":
            fluid_count = roles.get("fluid") if roles else None
            bound_count = roles.get("bound") if roles else None
            if (
                isinstance(fluid_count, int)
                and isinstance(bound_count, int)
                and mass_fluid is not None
                and mass_bound is not None
                and fluid_count >= 0
                and bound_count >= 0
            ):
                total = fluid_count * mass_fluid + bound_count * mass_bound
                total_basis = basis
        elif basis == "PER_ID_NATIVE_MASS_WEIGHTS":
            value = accounting.get("total_mass_kg")
            if value is not None:
                total = _finite(value, f"{label} per-ID native total mass")
                total_basis = basis
    # Never add MassFluid and MassBound directly: they are per-particle
    # weights, not two case-level masses.
    return {
        "time_s": time_s,
        "native_mass_fluid_per_particle_kg": mass_fluid,
        "native_mass_bound_per_particle_kg": mass_bound,
        "native_sample_mass_total_kg": total,
        "native_sample_mass_total_basis": total_basis,
        "native_dp_m": dp,
        "role_counts": roles,
        "fluid": fluid,
    }


def _rows(report: dict[str, Any], rows_key: str) -> list[dict[str, Any]]:
    value: Any = report
    for part in rows_key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ScalarObserverFailure(f"observer rows path {rows_key!r} is absent")
        value = value[part]
    if not isinstance(value, list) or not value:
        raise ScalarObserverFailure(f"observer rows path {rows_key!r} is not a nonempty list")
    result = [_row(item, f"observer row {index}") for index, item in enumerate(value)]
    if any(right["time_s"] <= left["time_s"] for left, right in zip(result, result[1:])):
        raise ScalarObserverFailure("observer saved times are not strictly increasing")
    return result


def _trapz(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row["fluid"].get(key) for row in rows]
    if any(value is None for value in values):
        return None
    return sum(
        0.5 * (float(left) + float(right)) * (right_row["time_s"] - left_row["time_s"])
        for left, right, left_row, right_row in zip(values, values[1:], rows, rows[1:])
    )


def _source_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    identity = manifest.get("source_identity")
    if not isinstance(identity, dict):
        raise ScalarObserverFailure("manifest source_identity is missing")
    digest = identity.get("source_identity_digest")
    if not isinstance(digest, str) or not digest or digest in PLACEHOLDERS:
        raise ScalarObserverFailure("manifest source_identity_digest is not bound")
    if identity.get("component_basis") != "PRODUCER_COMPONENT_XYZ":
        raise ScalarObserverFailure("scalar observer requires the producer component basis")
    if identity.get("world_orientation") != UNKNOWN:
        raise ScalarObserverFailure("world orientation must remain UNKNOWN")
    if identity.get("world_directional_claims") is not False:
        raise ScalarObserverFailure("world-directional claims must be explicitly disabled")
    if identity.get("flux_claims") is not False or identity.get("owner_mass_claims") is not False:
        raise ScalarObserverFailure("flux/owner claims must remain explicitly disabled")
    return identity


def _attempts(manifest: dict[str, Any], identity: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = manifest.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 2:
        raise ScalarObserverFailure("manifest must contain exactly two attempts")
    result: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            raise ScalarObserverFailure(f"attempt {index} is not an object")
        if attempt.get("source_identity_digest") != identity["source_identity_digest"]:
            raise ScalarObserverFailure(f"attempt {index} source identity does not match common source")
        report = attempt.get("report")
        if not isinstance(report, dict) or not isinstance(report.get("path"), str):
            raise ScalarObserverFailure(f"attempt {index} report record lacks an exact path")
        rows_key = attempt.get("rows_key", "observations")
        if not isinstance(rows_key, str) or not rows_key:
            raise ScalarObserverFailure(f"attempt {index} rows_key is invalid")
        result.append({"label": str(attempt.get("label") or f"attempt-{index}"),
                       "attempt_id": str(attempt.get("attempt_id") or f"attempt-{index}"),
                       "report": report, "rows_key": rows_key})
    if result[0]["attempt_id"] == result[1]["attempt_id"]:
        raise ScalarObserverFailure("the two attempts must have distinct attempt_id values")
    return result


def _pair_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "sample_mass_total_delta_kg": None,
        "speed_norm_delta_m_per_s": None,
        "kinetic_energy_delta_j": None,
        "com_translational_energy_delta_j": None,
        "component_com_delta_norm_m": None,
        "status": "UNKNOWN_NATIVE_SCALAR",
    }
    if left["native_sample_mass_total_kg"] is not None and right["native_sample_mass_total_kg"] is not None:
        metrics["sample_mass_total_delta_kg"] = abs(left["native_sample_mass_total_kg"] - right["native_sample_mass_total_kg"])
    metrics["speed_norm_delta_m_per_s"] = abs(left["fluid"]["velocity_norm_m_per_s"] - right["fluid"]["velocity_norm_m_per_s"])
    if left["fluid"]["kinetic_energy_j"] is not None and right["fluid"]["kinetic_energy_j"] is not None:
        metrics["kinetic_energy_delta_j"] = abs(left["fluid"]["kinetic_energy_j"] - right["fluid"]["kinetic_energy_j"])
    if left["fluid"]["com_translational_energy_j"] is not None and right["fluid"]["com_translational_energy_j"] is not None:
        metrics["com_translational_energy_delta_j"] = abs(left["fluid"]["com_translational_energy_j"] - right["fluid"]["com_translational_energy_j"])
    if left["fluid"]["com_m"] is not None and right["fluid"]["com_m"] is not None:
        metrics["component_com_delta_norm_m"] = _delta_vector(left["fluid"]["com_m"], right["fluid"]["com_m"])
    metrics["status"] = "COMPONENT_SCALAR_MATCHED" if any(value is not None for key, value in metrics.items() if key != "status") else "UNKNOWN_NATIVE_SCALAR"
    return metrics


def _integral_pair(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    times_left = [row["time_s"] for row in left]
    times_right = [row["time_s"] for row in right]
    same_grid = len(times_left) == len(times_right) and all(
        abs(a - b) <= TIME_TOLERANCE_S for a, b in zip(times_left, times_right)
    )
    if not same_grid:
        return {"status": "UNKNOWN_ASYNC_SAVED_TIMES", "speed_norm_dt_delta_m": None,
                "kinetic_energy_dt_delta_j_s": None, "interpolation": False}
    left_speed = _trapz(left, "velocity_norm_m_per_s")
    right_speed = _trapz(right, "velocity_norm_m_per_s")
    left_ke = _trapz(left, "kinetic_energy_j")
    right_ke = _trapz(right, "kinetic_energy_j")
    return {
        "status": "COMPONENT_SCALAR_TIME_INTEGRAL_MATCHED",
        "speed_norm_dt_delta_m": abs(left_speed - right_speed) if left_speed is not None and right_speed is not None else None,
        "kinetic_energy_dt_delta_j_s": abs(left_ke - right_ke) if left_ke is not None and right_ke is not None else None,
        "interpolation": False,
        "time_grid_rows": len(times_left),
        "time_start_s": times_left[0],
        "time_end_s": times_left[-1],
    }


def run(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest, manifest_record = _stable_json(manifest_path, "scalar observer manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ScalarObserverFailure("scalar observer manifest schema mismatch")
    identity = _source_identity(manifest)
    attempts = _attempts(manifest, identity)
    query_times = manifest.get("query_times_s")
    if not isinstance(query_times, list) or not query_times:
        raise ScalarObserverFailure("manifest query_times_s is empty")
    query_times = [_finite(value, "query time") for value in query_times]
    if query_times != sorted(set(query_times)):
        raise ScalarObserverFailure("query_times_s must be sorted and unique")
    decoded: list[dict[str, Any]] = []
    for attempt in attempts:
        report, record = _stable_json(Path(attempt["report"]["path"]),
                                      f"{attempt['label']} compact native report",
                                      attempt["report"].get("sha256"))
        if report.get("source_identity_digest") != identity["source_identity_digest"]:
            raise ScalarObserverFailure(f"{attempt['label']} report source identity mismatch")
        if report.get("world_orientation", UNKNOWN) != UNKNOWN:
            raise ScalarObserverFailure(f"{attempt['label']} report asserts a world orientation")
        decoded.append({"attempt": attempt, "report_record": record,
                        "rows": _rows(report, attempt["rows_key"])})
    pair_rows: list[dict[str, Any]] = []
    for query in query_times:
        entries: list[dict[str, Any] | None] = []
        for decoded_attempt in decoded:
            entries.append(next((row for row in decoded_attempt["rows"] if abs(row["time_s"] - query) <= TIME_TOLERANCE_S), None))
        if any(item is None for item in entries):
            pair_rows.append({"query_time_s": query, "status": "UNKNOWN_NO_EXACT_SAVED_TIME",
                              "interpolation": False, "metrics": None})
        else:
            pair_rows.append({"query_time_s": query, "status": "EXACT_SAVED_TIME",
                              "interpolation": False, "metrics": _pair_metrics(entries[0], entries[1])})
    value = {
        "schema": SCHEMA,
        "status": "COMPLETE_ROTATION_INVARIANT_NATIVE_SCALAR_DIAGNOSTIC",
        "manifest": manifest_record,
        "source_identity": identity,
        "attempts": [{"label": item["attempt"]["label"], "attempt_id": item["attempt"]["attempt_id"],
                       "report": item["report_record"], "rows": len(item["rows"]),
                       "time_start_s": item["rows"][0]["time_s"], "time_end_s": item["rows"][-1]["time_s"]}
                      for item in decoded],
        "matched_queries": pair_rows,
        "integral_comparison": _integral_pair(decoded[0]["rows"], decoded[1]["rows"]),
        "axis_scope": {
            "component_basis": "PRODUCER_COMPONENT_XYZ",
            "producer_to_world_orientation": UNKNOWN,
            "world_directional_velocity": UNKNOWN,
            "flux": UNKNOWN,
            "continuous_owner_mass": UNKNOWN,
            "identity_world_rotation": False,
        },
        "metric_scope": {
            "rotation_invariant": ["native_sample_mass_total_kg", "velocity_norm_m_per_s",
                                    "kinetic_energy_j", "com_translational_energy_j",
                                    "component_com_delta_norm_m"],
            "mass_authority": "NATIVE_MASSFLUID_MASSBOUND_PER_PARTICLE_PLUS_TYPED_ROLE_COUNTS_OR_PER_ID_WEIGHTS",
            "header_mass_semantics": {
                "MassFluid": "PER_FLUID_PARTICLE_KG",
                "MassBound": "PER_BOUND_PARTICLE_KG",
                "header_only_total": UNKNOWN,
            },
            "kinetic_energy_semantics": {
                "total": "SUM_PER_ID_0P5_MASS_VELOCITY_SQUARED_ONLY",
                "com_translational": "0P5_NATIVE_FLUID_SAMPLE_MASS_TIMES_WEIGHTED_COM_SPEED_SQUARED",
                "com_velocity_is_not_total_ke": True,
            },
            "xml_mass_fallback": False,
            "time_matching": "EXACT_SAVED_TIME_ONLY",
            "interpolation": False,
            "integral_semantics": "trapezoid_over_each_actual_saved_time_grid;_not_integration_truth",
        },
        "scientific_qualification": dict(QUALIFICATION),
        "read_scope": {"compact_json_only": True, "native_bi4": False, "vtk": False,
                        "hdf5": False, "solver_launch": False, "gencase_launch": False},
    }
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > OUTPUT_CAP:
        raise ScalarObserverFailure("scalar diagnostic exceeds compact output cap")
    output_path = _absolute(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise ScalarObserverFailure(f"refusing to overwrite output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(output_path)
    return value


def _fixture_report(path: Path, *, rotated: bool = False, async_time: bool = False, typed: bool = True) -> None:
    def rotate(vector: list[float]) -> list[float]:
        return [vector[1], -vector[0], vector[2]] if rotated else vector
    times = [0.0, 0.25, 0.5]
    if async_time:
        times = [0.0, 0.25, 0.5001]
    observations: list[dict[str, Any]] = []
    for index, time_s in enumerate(times):
        velocity = rotate([3.0 + index, 4.0, 0.0])
        com = rotate([1.0 + index, 2.0, 3.0])
        row = {
            "time_s": time_s,
            "native_header": {"MassFluid": 2.0, "MassBound": 1.0, "Dp": 0.1, "mass_basis": "native_header_per_particle"},
            "mass_basis": "native_header_per_particle",
            "role_counts": {"fluid": 2, "bound": 1, "fixed": 1, "moving": 0, "floating": 0, "total": 3},
            "fixed_moving_excluded_from_fluid_observables": True,
            "fluid": {"mass_kg": 4.0, "mass_basis": "native_per_particle_mass_times_typed_fluid_count",
                      "velocity_m_per_s": velocity, "com_m": com,
                      "kinetic_energy_j": 0.5 * 4.0 * _norm(velocity) ** 2,
                      "kinetic_energy_basis": "NATIVE_PER_PARTICLE_VELOCITY_SUM"},
        }
        if typed:
            row["native_mass_accounting"] = {
                "basis": "PER_PARTICLE_NATIVE_HEADER_TIMES_TYPED_ROLE_COUNTS",
                "typed_role_source": "native_Idp_role_counts",
            }
        else:
            row["role_counts"] = {"fluid": 2}
        observations.append(row)
    path.write_text(json.dumps({
        "schema": "ds02.stage2.manufactured-native-observer.v2",
        "status": "COMPLETE_NATIVE_FIELDS",
        "source_identity_digest": "fixture-source-identity",
        "world_orientation": UNKNOWN,
        "observations": observations,
    }, sort_keys=True) + "\n", encoding="utf-8")


def _fixture_manifest(root: Path, report_a: Path, report_b: Path) -> Path:
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_ROTATION_INVARIANT_NATIVE_SCALAR",
        "source_identity": {"source_identity_digest": "fixture-source-identity",
                            "physical_case_id": "fixture-case",
                            "component_basis": "PRODUCER_COMPONENT_XYZ",
                            "world_orientation": UNKNOWN,
                            "world_directional_claims": False,
                            "flux_claims": False,
                            "owner_mass_claims": False},
        "attempts": [
            {"label": "same-cfl", "attempt_id": "attempt-a", "rows_key": "observations",
             "source_identity_digest": "fixture-source-identity",
             "report": {"path": str(report_a), "sha256": _sha(report_a.read_bytes()), "stat": _stat(report_a)}},
            {"label": "half-cfl", "attempt_id": "attempt-b", "rows_key": "observations",
             "source_identity_digest": "fixture-source-identity",
             "report": {"path": str(report_b), "sha256": _sha(report_b.read_bytes()), "stat": _stat(report_b)}},
        ],
        "query_times_s": [0.0, 0.25, 0.5],
        "scientific_scope": dict(QUALIFICATION),
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="rotation-invariant-scalars-") as value:
        root = Path(value)
        report_a = root / "same.json"; report_b = root / "half.json"
        _fixture_report(report_a); _fixture_report(report_b, rotated=True)
        manifest = _fixture_manifest(root, report_a, report_b)
        output = root / "result.json"
        result = run(manifest, output)
        assert result["scientific_qualification"] == QUALIFICATION
        assert result["axis_scope"]["producer_to_world_orientation"] == UNKNOWN
        assert result["integral_comparison"]["status"] == "COMPONENT_SCALAR_TIME_INTEGRAL_MATCHED"
        exact = [item for item in result["matched_queries"] if item["status"] == "EXACT_SAVED_TIME"]
        assert len(exact) == 3
        assert all(item["metrics"]["speed_norm_delta_m_per_s"] == 0.0 for item in exact)
        assert all(item["metrics"]["kinetic_energy_delta_j"] == 0.0 for item in exact)
        assert all(item["metrics"]["sample_mass_total_delta_kg"] == 0.0 for item in exact)
        # Header values alone are per-particle weights.  Without both typed
        # role counts and an accounting basis, a case/sample total stays
        # UNKNOWN instead of becoming MassFluid + MassBound.
        header_only = root / "header-only.json"
        _fixture_report(header_only, typed=False)
        header_manifest = _fixture_manifest(root, report_a, header_only)
        header_result = run(header_manifest, root / "header-only-result.json")
        header_exact = [item for item in header_result["matched_queries"] if item["status"] == "EXACT_SAVED_TIME"]
        assert all(item["metrics"]["sample_mass_total_delta_kg"] is None for item in header_exact)
        # A world-axis assertion is a hard input contradiction, not a way to
        # turn the component diagnostic into a world result.
        bad = json.loads(manifest.read_text(encoding="utf-8")); bad["source_identity"]["world_orientation"] = "BOUND"
        manifest.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        try:
            run(manifest, root / "bad-world.json")
        except ScalarObserverFailure:
            pass
        else:
            raise AssertionError("world-axis assertion was accepted")
        # A changed source identity is rejected even when the scalar fields
        # themselves look finite.
        bad["source_identity"]["world_orientation"] = UNKNOWN
        bad["attempts"][1]["source_identity_digest"] = "different-source"
        manifest.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        try:
            run(manifest, root / "bad-identity.json")
        except ScalarObserverFailure:
            pass
        else:
            raise AssertionError("source identity mismatch was accepted")
        # Exact-time matching is explicit; an async endpoint is retained as
        # UNKNOWN rather than interpolated.
        _fixture_report(report_b, rotated=True, async_time=True)
        good = _fixture_manifest(root, report_a, report_b)
        async_result = run(good, root / "async.json")
        assert async_result["matched_queries"][-1]["status"] == "UNKNOWN_NO_EXACT_SAVED_TIME"
    print("PASS_ROTATION_INVARIANT_NATIVE_SCALAR_FIXTURE_NO_WORLD_OR_Q_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.manifest is None or args.output is None:
            parser.error("--run requires --manifest and --output")
        run(args.manifest, args.output)
        print(json.dumps({"status": "COMPLETE_ROTATION_INVARIANT_NATIVE_SCALAR_DIAGNOSTIC",
                          "output": str(_absolute(args.output)), "scientific_credit": 0}, sort_keys=True))
        return 0
    except (ScalarObserverFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROTATION_INVARIANT_NATIVE_SCALAR_OBSERVER: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

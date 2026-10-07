#!/usr/bin/env python3
"""Audit two CURRENT F6 rigid-state sentinel trajectories.

This is a bounded metadata/CSV audit of already completed official
``FloatingInfo`` exports.  It deliberately does not open ``trajectory.h5``,
read particle frames, run a solver, or claim a physical/dynamical result.

The audit keeps the physical rigid-body mass (128 kg) separate from the
floating SPH support-lattice sample mass (16384 * 0.015625 kg = 256 kg).
It records the actual center, linear velocity, angular velocity and
roll/pitch/yaw trajectory with units, and derives an explicit quaternion
lineage for SO(3) comparisons.  The SO(3) tolerance is frozen at RMSE <= 2
degrees and maximum <= 5 degrees.  Only the initial pose has an XML reference
for these existing sentinels; the full-time reference/qualification result is
therefore left UNKNOWN.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds02.stage2.f6-rigid-observation.v1"
BINDING_SCHEMA = "ds02.stage2.f6-rigid-observation-binding.v1"
EXPECTED_SENTINELS = ("F6-S1", "F6-S2")
EXPECTED_CASES = {
    "F6-S1": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
    "F6-S2": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
}
BODY_MASS_KG = 128.0
SUPPORT_COUNT = 16384
SUPPORT_MASS_KG = 256.0
SO3_RMSE_LIMIT_DEG = 2.0
SO3_MAX_LIMIT_DEG = 5.0
FLOAT_TOL = 1.0e-6
TIME_TOL_S = 1.0e-6


class AuditError(RuntimeError):
    """Raised when a source-bound audit cannot establish its contract."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path | str, label: str) -> Path:
    value = Path(path).expanduser().resolve()
    if not value.is_file():
        raise AuditError(f"{label} is missing: {value}")
    return value


def read_json(path: Path | str, label: str) -> dict[str, Any]:
    value = require_file(path, label)
    try:
        payload = json.loads(value.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - error text is contract evidence
        raise AuditError(f"{label} is invalid JSON: {value}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AuditError(f"{label} is not a JSON object: {value}")
    return payload


def write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def close(a: float, b: float, tolerance: float = FLOAT_TOL) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance


def finite_vector(values: Iterable[float], label: str) -> list[float]:
    result = [float(value) for value in values]
    if not result or not all(math.isfinite(value) for value in result):
        raise AuditError(f"{label} has non-finite values")
    return result


def value_attr(node: ET.Element | None, name: str, label: str) -> float:
    if node is None or node.get(name) is None:
        raise AuditError(f"{label} lacks attribute {name}")
    try:
        value = float(node.get(name, ""))
    except ValueError as exc:
        raise AuditError(f"{label}.{name} is not numeric") from exc
    if not math.isfinite(value):
        raise AuditError(f"{label}.{name} is not finite")
    return value


def vec3_child(parent: ET.Element, child_name: str, label: str) -> list[float]:
    node = parent.find(child_name)
    return [
        value_attr(node, axis, f"{label}/{child_name}")
        for axis in ("x", "y", "z")
    ]


def parse_xml_contract(xml_path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        raise AuditError(f"generated XML is invalid: {xml_path}: {exc}") from exc
    floating = root.find(".//floatings/floating")
    particles = root.find(".//particles/floating")
    if floating is None or particles is None:
        raise AuditError(f"floating/body particle contract missing in {xml_path}")
    massbody = value_attr(floating.find("massbody"), "value", "floatings/floating/massbody")
    center = vec3_child(floating, "center", "floatings/floating")
    inertia = vec3_child(floating, "inertia", "floatings/floating")
    angularvel = vec3_child(floating, "angularvelini", "floatings/floating")
    rotation_dof_node = floating.find("rotationDOF")
    rotation_dof = [
        int(value_attr(rotation_dof_node, axis, "floatings/floating/rotationDOF"))
        for axis in ("x", "y", "z")
    ]
    count_text = particles.get("count")
    mk_text = particles.get("mk")
    if count_text is None or mk_text is None:
        raise AuditError(f"generated floating particle group lacks count/mk: {xml_path}")
    try:
        count = int(count_text)
        mk = int(mk_text)
    except ValueError as exc:
        raise AuditError(f"generated floating particle count/mk is not integral: {xml_path}") from exc
    masspart = value_attr(particles.find("masspart"), "value", "particles/floating/masspart")
    support_mass = float(count * masspart)
    if not close(massbody, BODY_MASS_KG):
        raise AuditError(f"physical massbody is {massbody}, expected {BODY_MASS_KG}: {xml_path}")
    if count != SUPPORT_COUNT or not close(support_mass, SUPPORT_MASS_KG, 1.0e-5):
        raise AuditError(
            f"support sample contract is count={count}, mass={support_mass}, "
            f"expected count={SUPPORT_COUNT}, mass={SUPPORT_MASS_KG}: {xml_path}"
        )
    return {
        "physical_rigid_body": {
            "mass_kg": massbody,
            "center_m": center,
            "inertia_diag_kg_m2": inertia,
            "rotation_dof": rotation_dof,
            "initial_angular_velocity_rad_s": angularvel,
            "mass_semantics": "XML massbody used by the rigid-body solver equations",
        },
        "sph_support_sample": {
            "particle_count": count,
            "mk": mk,
            "masspart_kg": masspart,
            "mass_sum_kg": support_mass,
            "mass_semantics": "floating SPH support-lattice sample weight; not physical rigid-body mass",
        },
        "units": {
            "mass": "kg",
            "center": "m",
            "inertia": "kg*m^2",
            "angular_velocity": "rad/s",
        },
    }


def quaternion_from_euler_deg(roll: float, pitch: float, yaw: float) -> list[float]:
    """Intrinsic XYZ Euler to normalized xyzw quaternion.

    FloatingInfo exposes axis-labelled roll/pitch/yaw in degrees.  We retain
    those source columns and make this derived convention explicit so SO(3)
    comparisons do not accidentally become component-wise Euler comparisons.
    """
    r, p, y = (math.radians(value) for value in (roll, pitch, yaw))
    cr, sr = math.cos(r / 2.0), math.sin(r / 2.0)
    cp, sp = math.cos(p / 2.0), math.sin(p / 2.0)
    cy, sy = math.cos(y / 2.0), math.sin(y / 2.0)
    q = [
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    ]
    norm = math.sqrt(sum(value * value for value in q))
    if not math.isfinite(norm) or norm <= 0.0:
        raise AuditError("derived quaternion is not normalizable")
    return [value / norm for value in q]


def quaternion_distance_deg(first: Sequence[float], second: Sequence[float]) -> float:
    if len(first) != 4 or len(second) != 4:
        raise AuditError("SO(3) quaternion requires four components")
    dot = sum(float(a) * float(b) for a, b in zip(first, second))
    # q and -q represent the same rotation; abs(dot) removes that sign gauge.
    cosine = max(-1.0, min(1.0, abs(dot)))
    return math.degrees(2.0 * math.acos(cosine))


def so3_metrics(reference: Sequence[Sequence[float]], candidate: Sequence[Sequence[float]]) -> dict[str, Any]:
    if len(reference) != len(candidate) or not reference:
        raise AuditError("SO(3) comparison needs equally sized non-empty trajectories")
    errors = [quaternion_distance_deg(a, b) for a, b in zip(reference, candidate)]
    rmse = math.sqrt(sum(value * value for value in errors) / len(errors))
    maximum = max(errors)
    return {
        "sample_count": len(errors),
        "errors_deg": errors,
        "rmse_deg": rmse,
        "max_deg": maximum,
        "tolerance_rmse_deg": SO3_RMSE_LIMIT_DEG,
        "tolerance_max_deg": SO3_MAX_LIMIT_DEG,
        "pass": bool(rmse <= SO3_RMSE_LIMIT_DEG and maximum <= SO3_MAX_LIMIT_DEG),
    }


def manufactured_so3_tests() -> dict[str, Any]:
    # Same physical z rotations expressed once as a continuous angle and once
    # wrapped across +pi/-pi.  Raw Euler subtraction sees 360-degree jumps;
    # SO(3) must see zero error.
    continuous = [170.0, 179.0, 181.0, 190.0]
    wrapped = [170.0, 179.0, -179.0, -170.0]
    reference = [quaternion_from_euler_deg(0.0, 0.0, angle) for angle in continuous]
    candidate = [quaternion_from_euler_deg(0.0, 0.0, angle) for angle in wrapped]
    crossing = so3_metrics(reference, candidate)
    naive_euler_errors = [abs(a - b) for a, b in zip(continuous, wrapped)]
    naive_rmse = math.sqrt(sum(value * value for value in naive_euler_errors) / len(naive_euler_errors))

    # Quaternion sign flips are a representation change, not a physical error.
    sign_flipped = [q if index % 2 == 0 else [-value for value in q] for index, q in enumerate(reference)]
    sign_gauge = so3_metrics(reference, sign_flipped)

    # A six-degree error must fail the frozen maximum threshold.
    six_degree_error = [quaternion_from_euler_deg(0.0, 0.0, angle + 6.0) for angle in continuous]
    threshold_failure = so3_metrics(reference, six_degree_error)
    checks = {
        "cross_pi_so3_passes": crossing["pass"] and crossing["max_deg"] < 1.0e-9,
        "cross_pi_naive_euler_would_fail": naive_rmse > SO3_MAX_LIMIT_DEG,
        "quaternion_sign_gauge_passes": sign_gauge["pass"] and sign_gauge["max_deg"] < 1.0e-9,
        "six_degree_max_fails": not threshold_failure["pass"] and threshold_failure["max_deg"] > SO3_MAX_LIMIT_DEG,
    }
    if not all(checks.values()):
        raise AuditError(f"manufactured SO(3) test failed: {checks}")
    return {
        "status": "passed",
        "frozen_tolerances_deg": {"rmse": SO3_RMSE_LIMIT_DEG, "max": SO3_MAX_LIMIT_DEG},
        "cross_pi": {
            "reference_euler_z_deg": continuous,
            "candidate_wrapped_euler_z_deg": wrapped,
            "naive_euler_rmse_deg": naive_rmse,
            "so3": crossing,
        },
        "quaternion_sign_flip": sign_gauge,
        "six_degree_threshold_failure": threshold_failure,
        "checks": checks,
    }


def parse_float(value: str, label: str) -> float:
    try:
        result = float(value.strip())
    except ValueError as exc:
        raise AuditError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise AuditError(f"{label} is not finite")
    return result


def parse_floating_csv(path: Path, expected_frames: int, expected_end_s: float) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if not reader.fieldnames:
            raise AuditError(f"FloatingInfo CSV has no header: {path}")
        fields = [str(name).strip() for name in reader.fieldnames]
        required = {
            "part", "time [s]", "fvel.x [m/s]", "fvel.y [m/s]", "fvel.z [m/s]",
            "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]",
            "center.x [m]", "center.y [m]", "center.z [m]",
            "roll [deg]", "pitch [deg]", "yaw [deg]",
        }
        missing = sorted(required.difference(fields))
        if missing:
            raise AuditError(f"FloatingInfo CSV lacks required fields {missing}: {path}")
        rows = list(reader)
    if len(rows) != expected_frames:
        raise AuditError(f"FloatingInfo CSV has {len(rows)} rows, expected {expected_frames}: {path}")
    times: list[float] = []
    centers: list[list[float]] = []
    linear: list[list[float]] = []
    angular: list[list[float]] = []
    euler: list[list[float]] = []
    parts: list[int] = []
    for ordinal, row in enumerate(rows):
        if any(name not in row or row[name] is None for name in required):
            raise AuditError(f"FloatingInfo row {ordinal} is missing a required value: {path}")
        try:
            part = int(str(row["part"]).strip())
        except ValueError as exc:
            raise AuditError(f"FloatingInfo part is not integral at row {ordinal}: {path}") from exc
        parts.append(part)
        times.append(parse_float(str(row["time [s]"]), f"time row {ordinal}"))
        centers.append([parse_float(str(row[f"center.{axis} [m]"]), f"center.{axis} row {ordinal}") for axis in "xyz"])
        linear.append([parse_float(str(row[f"fvel.{axis} [m/s]"]), f"fvel.{axis} row {ordinal}") for axis in "xyz"])
        angular.append([parse_float(str(row[f"fomega.{axis} [rad/s]"]), f"fomega.{axis} row {ordinal}") for axis in "xyz"])
        euler.append([parse_float(str(row[f"{axis} [deg]"]), f"{axis} row {ordinal}") for axis in ("roll", "pitch", "yaw")])
    if parts != list(range(expected_frames)):
        raise AuditError(f"FloatingInfo part sequence is not 0..{expected_frames - 1}: {path}")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise AuditError(f"FloatingInfo times are not strictly increasing: {path}")
    if not close(times[0], 0.0, TIME_TOL_S) or not close(times[-1], expected_end_s, TIME_TOL_S):
        raise AuditError(f"FloatingInfo time window {times[0]}..{times[-1]} disagrees with CURRENT {expected_end_s}: {path}")
    quaternions = [quaternion_from_euler_deg(*angles) for angles in euler]
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "frames": expected_frames,
        "row_ordinals": list(range(expected_frames)),
        "part_values": parts,
        "time_s": times,
        "center_m": centers,
        "linear_velocity_m_s": linear,
        "angular_velocity_rad_s": angular,
        "orientation_euler_deg": euler,
        "orientation_quaternion_xyzw": quaternions,
        "units": {
            "time": "s",
            "center": "m",
            "linear_velocity": "m/s",
            "angular_velocity": "rad/s",
            "orientation_euler": "deg",
            "orientation_quaternion": "dimensionless xyzw",
        },
        "orientation_convention": "FloatingInfo roll/pitch/yaw axis labels; derived intrinsic XYZ quaternion xyzw",
    }


def declared_ref(path: Path, expected_sha256: str | None, label: str) -> dict[str, Any]:
    actual = sha256_file(require_file(path, label))
    if expected_sha256 is not None and actual != expected_sha256:
        raise AuditError(f"{label} digest differs: {path}; expected {expected_sha256}, got {actual}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def current_cases(current: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = current.get("cases", current)
    if not isinstance(entries, list):
        raise AuditError("CURRENT336.json does not contain a case list")
    result: dict[str, dict[str, Any]] = {}
    for item in entries:
        if isinstance(item, dict) and item.get("physical_case_id") in EXPECTED_CASES.values():
            result[str(item["physical_case_id"])] = item
    if set(result) != set(EXPECTED_CASES.values()):
        raise AuditError(f"CURRENT does not contain both F6 sentinel cases: {sorted(result)}")
    return result


def audit_sentinel(
    sentinel: Mapping[str, Any],
    current: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    sentinel_id = str(sentinel.get("sentinel_id"))
    physical_id = str(sentinel.get("source_physical_case_id"))
    if sentinel_id not in EXPECTED_SENTINELS or physical_id != EXPECTED_CASES[sentinel_id]:
        raise AuditError(f"unexpected sentinel mapping: {sentinel_id} -> {physical_id}")
    current_entry = current[physical_id]
    bind = binding.get(sentinel_id)
    if not isinstance(bind, dict):
        raise AuditError(f"binding lacks {sentinel_id}")
    if bind.get("physical_case_id") != physical_id:
        raise AuditError(f"binding physical identity mismatch for {sentinel_id}")
    if current_entry.get("physical_case_id") != physical_id or current_entry.get("runtime_case_alias") != physical_id:
        raise AuditError(f"CURRENT identity/alias mismatch for {sentinel_id}")
    if int(current_entry.get("frames", -1)) != 241:
        raise AuditError(f"CURRENT frame count mismatch for {sentinel_id}")

    source_bindings = current_entry.get("source_bindings", {})
    xml_current = source_bindings.get("generated_xml", {})
    solver_current = source_bindings.get("solver_receipt", {})
    xml_path = require_file(bind["generated_xml_path"], f"{sentinel_id} generated XML")
    solver_receipt_path = require_file(bind["solver_receipt_path"], f"{sentinel_id} solver receipt")
    if str(xml_path) != str(Path(xml_current.get("path", "")).resolve()):
        raise AuditError(f"{sentinel_id} generated XML is not the CURRENT binding")
    if str(solver_receipt_path) != str(Path(solver_current.get("path", "")).resolve()):
        raise AuditError(f"{sentinel_id} solver receipt is not the CURRENT binding")
    xml_ref = declared_ref(xml_path, xml_current.get("sha256"), f"{sentinel_id} generated XML")
    solver_ref = declared_ref(solver_receipt_path, solver_current.get("sha256"), f"{sentinel_id} solver receipt")
    solver = read_json(solver_receipt_path, f"{sentinel_id} solver receipt")
    if solver.get("schema") != "ds02.execution-receipt.v1" or solver.get("status") != "completed" or solver.get("returncode") != 0:
        raise AuditError(f"{sentinel_id} solver receipt is not completed")
    request = solver.get("request", {})
    if request.get("case_id") != physical_id or request.get("family_id") != "F6":
        raise AuditError(f"{sentinel_id} solver receipt request identity mismatch")
    raw_root = Path(str(current_entry.get("raw_root", {}).get("path", ""))).resolve()
    if not raw_root.is_dir() or raw_root.name != "data":
        raise AuditError(f"{sentinel_id} CURRENT raw root is not a data directory: {raw_root}")
    # The S1 receipt stores the immutable attempt root in request.attempt_root;
    # the S2 receipt stores the same root as top-level output_root.  Accept both
    # receipt-layout spellings, then require the exact CURRENT raw-root child.
    attempt_root_text = (
        solver.get("request", {}).get("attempt_root")
        or solver.get("output_root")
        or solver.get("request", {}).get("output_root")
    )
    if not attempt_root_text:
        raise AuditError(f"{sentinel_id} solver receipt has no bound attempt/output root")
    attempt_root = Path(str(attempt_root_text)).resolve()
    if raw_root != (attempt_root / "solver_output" / "data").resolve():
        raise AuditError(f"{sentinel_id} raw root does not belong to solver receipt attempt")
    if request.get("attempt_id") and str(request["attempt_id"]) != attempt_root.name:
        raise AuditError(f"{sentinel_id} solver attempt_id disagrees with its output root")
    receipt_output_root = solver.get("output_root")
    if receipt_output_root and Path(str(receipt_output_root)).resolve() != attempt_root:
        raise AuditError(f"{sentinel_id} solver receipt output_root disagrees with CURRENT raw root")
    receipt_xml = request.get("gencase_xml")
    if receipt_xml and Path(str(receipt_xml)).resolve() != xml_path:
        raise AuditError(f"{sentinel_id} solver gencase XML differs from CURRENT generated XML")
    receipt_xml_sha = request.get("gencase_xml_sha256")
    if receipt_xml_sha and str(receipt_xml_sha) != xml_ref["sha256"]:
        raise AuditError(f"{sentinel_id} solver gencase XML digest differs from CURRENT generated XML")

    runparts_path = require_file(bind["runparts_path"], f"{sentinel_id} RunPARTs.csv")
    runout_path = require_file(bind["runout_path"], f"{sentinel_id} Run.out")
    if runparts_path.parent != raw_root.parent or runout_path.parent != raw_root.parent:
        raise AuditError(f"{sentinel_id} RunPARTs/Run.out are not in the same solver_output parent")
    runparts_ref = declared_ref(runparts_path, bind.get("runparts_sha256"), f"{sentinel_id} RunPARTs.csv")
    runout_ref = declared_ref(runout_path, bind.get("runout_sha256"), f"{sentinel_id} Run.out")

    floating_report_path = require_file(bind["floating_report_path"], f"{sentinel_id} FloatingInfo report")
    floating_report_ref = declared_ref(floating_report_path, bind.get("floating_report_sha256"), f"{sentinel_id} FloatingInfo report")
    floating_report = read_json(floating_report_path, f"{sentinel_id} FloatingInfo report")
    if floating_report.get("schema") != "ds02.f6.fulltime-floatinginfo-worker-result.v1" or floating_report.get("status") != "completed" or floating_report.get("returncode") != 0:
        raise AuditError(f"{sentinel_id} FloatingInfo report is not completed")
    if floating_report.get("case", {}).get("physical_case_id") != physical_id:
        raise AuditError(f"{sentinel_id} FloatingInfo report physical identity mismatch")
    output = floating_report.get("output", {})
    csv_path = require_file(bind["floating_csv_path"], f"{sentinel_id} FloatingInfo CSV")
    if str(csv_path) != str(Path(str(output.get("csv", ""))).resolve()):
        raise AuditError(f"{sentinel_id} FloatingInfo CSV differs from its completed report")
    csv_ref = declared_ref(csv_path, output.get("sha256"), f"{sentinel_id} FloatingInfo CSV")
    if bind.get("floating_csv_sha256") and bind["floating_csv_sha256"] != csv_ref["sha256"]:
        raise AuditError(f"{sentinel_id} FloatingInfo CSV differs from binding")
    command = floating_report.get("official_command", [])
    if not isinstance(command, list) or str(raw_root) not in [str(item) for item in command]:
        raise AuditError(f"{sentinel_id} FloatingInfo command is not bound to CURRENT raw root")
    native_receipt = floating_report.get("native_receipt", {})
    if native_receipt.get("actual_sha256") != solver_ref["sha256"] or native_receipt.get("status") != "completed":
        raise AuditError(f"{sentinel_id} FloatingInfo native receipt is not the bound solver receipt")

    partfloat_path = require_file(bind["partfloatinfo_path"], f"{sentinel_id} PartFloatInfo.ibi4")
    if partfloat_path.parent != raw_root:
        raise AuditError(f"{sentinel_id} PartFloatInfo.ibi4 is outside CURRENT raw root")
    partfloat_ref = declared_ref(partfloat_path, bind.get("partfloatinfo_sha256"), f"{sentinel_id} PartFloatInfo.ibi4")
    inventory_entry = floating_report.get("partfloatinfo_inventory", {}).get("entry", {})
    if inventory_entry.get("sha256") != partfloat_ref["sha256"] or str(Path(str(inventory_entry.get("path", ""))).resolve()) != str(partfloat_path):
        raise AuditError(f"{sentinel_id} PartFloatInfo inventory does not bind the raw file")

    xml_contract = parse_xml_contract(xml_path)
    current_numbers = current_entry.get("known_numeric_physical_parameters", {})
    expected_numbers = sentinel.get("actual_parameters", {})
    omega_keys = (
        "initial_angular_velocity_x_rad_s",
        "initial_angular_velocity_y_rad_s",
        "initial_angular_velocity_z_rad_s",
    )
    current_omega = finite_vector((current_numbers[key] for key in omega_keys), "CURRENT omega")
    expected_omega = finite_vector((expected_numbers[key] for key in omega_keys), f"{sentinel_id} sentinel omega")
    xml_omega = xml_contract["physical_rigid_body"]["initial_angular_velocity_rad_s"]
    if any(not close(a, b) for a, b in zip(current_omega, expected_omega)) or any(not close(a, b) for a, b in zip(xml_omega, expected_omega)):
        raise AuditError(f"{sentinel_id} current/sentinel/XML initial omega disagree")
    expected_end = float(current_entry["actual_time_window_s"][1])
    trajectory = parse_floating_csv(csv_path, int(current_entry["frames"]), expected_end)
    if any(abs(a - b) > 1.0e-6 for a, b in zip(trajectory["angular_velocity_rad_s"][0], expected_omega)):
        raise AuditError(f"{sentinel_id} FloatingInfo frame 0 omega disagrees with XML")
    if any(abs(a - b) > 1.0e-6 for a, b in zip(trajectory["center_m"][0], xml_contract["physical_rigid_body"]["center_m"])):
        raise AuditError(f"{sentinel_id} FloatingInfo frame 0 center disagrees with XML")
    initial_reference = [quaternion_from_euler_deg(0.0, 0.0, 0.0)]
    initial_observed = [trajectory["orientation_quaternion_xyzw"][0]]
    initial_so3 = so3_metrics(initial_reference, initial_observed)
    if not initial_so3["pass"]:
        raise AuditError(f"{sentinel_id} initial SO(3) XML pose gate failed")

    report_parse = floating_report.get("parse", {})
    return {
        "sentinel_id": sentinel_id,
        "physical_case_id": physical_id,
        "current_binding": {
            "case_entry": current_entry,
            "generated_xml": xml_ref,
            "solver_receipt": solver_ref,
            "raw_root": str(raw_root),
            "runparts": runparts_ref,
            "runout": runout_ref,
        },
        "floatinginfo_binding": {
            "worker_report": floating_report_ref,
            "official_command": command,
            "official_binary_sha256": floating_report.get("official_binary_sha256"),
            "csv": csv_ref,
            "partfloatinfo": partfloat_ref,
            "report_parse_status": {
                "rows_examined": report_parse.get("rows_examined"),
                "first_time_s": report_parse.get("first_time_s"),
                "last_time_s": report_parse.get("last_time_s"),
                "native_time_comparison": report_parse.get("native_time_comparison"),
            },
        },
        "physical_contract": xml_contract,
        "observed_rigid_state": trajectory,
        "so3_gate": {
            "frozen_tolerances_deg": {"rmse": SO3_RMSE_LIMIT_DEG, "max": SO3_MAX_LIMIT_DEG},
            "reference_scope": "initial_XML_identity_pose_only",
            "full_time_reference_status": "UNKNOWN",
            "initial_frame": initial_so3,
            "qualification_status": "NOT_ASSESSED",
        },
        "interpretation": {
            "body_mass_kg": BODY_MASS_KG,
            "support_sample_mass_kg": SUPPORT_MASS_KG,
            "mass_separation_preserved": True,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "observation_scope": "Actual FloatingInfo pose/omega/center series only; no H5 or particle-frame read.",
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    current_path = require_file(args.current, "CURRENT336")
    matrix_path = require_file(args.sentinel_matrix, "sentinel matrix")
    binding_path = require_file(args.binding, "F6 rigid observation binding")
    current = read_json(current_path, "CURRENT336")
    matrix = read_json(matrix_path, "sentinel matrix")
    binding_payload = read_json(binding_path, "F6 rigid observation binding")
    if binding_payload.get("schema") != BINDING_SCHEMA:
        raise AuditError("unexpected F6 rigid observation binding schema")
    if binding_payload.get("h5_opened") is not False:
        raise AuditError("binding must declare h5_opened=false")
    by_case = current_cases(current)
    sentinel_rows = [item for item in matrix.get("sentinels", []) if isinstance(item, dict) and item.get("family") == "F6"]
    if {item.get("sentinel_id") for item in sentinel_rows} != set(EXPECTED_SENTINELS):
        raise AuditError("sentinel matrix must contain exactly F6-S1 and F6-S2")
    results = []
    for sentinel in sorted(sentinel_rows, key=lambda item: EXPECTED_SENTINELS.index(str(item["sentinel_id"]))):
        results.append(audit_sentinel(sentinel, by_case, binding_payload["sentinels"]))
    manufactured = manufactured_so3_tests()
    output = {
        "schema": SCHEMA,
        "status": "completed",
        "purpose": "Source-bound actual F6 rigid-state observation preparation for the two CURRENT sentinels.",
        "source_policy": {
            "h5_opened": False,
            "h5_paths_consumed": [],
            "particle_frames_read": False,
            "solver_launched": False,
            "cfd_or_model_run": False,
        },
        "source_inputs": {
            "current": {"path": str(current_path), "sha256": sha256_file(current_path), "bytes": current_path.stat().st_size},
            "sentinel_matrix": {"path": str(matrix_path), "sha256": sha256_file(matrix_path), "bytes": matrix_path.stat().st_size},
            "binding": {"path": str(binding_path), "sha256": sha256_file(binding_path), "bytes": binding_path.stat().st_size},
        },
        "frozen_contract": {
            "so3_rmse_tolerance_deg": SO3_RMSE_LIMIT_DEG,
            "so3_max_tolerance_deg": SO3_MAX_LIMIT_DEG,
            "orientation_source": "FloatingInfo roll/pitch/yaw [deg]",
            "derived_orientation": "intrinsic XYZ quaternion [x,y,z,w]",
            "units": {
                "time": "s",
                "center": "m",
                "linear_velocity": "m/s",
                "angular_velocity": "rad/s",
                "euler_orientation": "deg",
                "quaternion": "dimensionless",
            },
            "mass_semantics": {
                "physical_rigid_body_mass_kg": BODY_MASS_KG,
                "floating_sph_support_sample_mass_kg": SUPPORT_MASS_KG,
                "relationship": "separate quantities; never summed or substituted",
            },
        },
        "manufactured_so3_tests": manufactured,
        "sentinels": results,
        "qualification": {
            "status": "NOT_ASSESSED",
            "reason": "Existing sentinels provide actual full-time observations but no bound full-time reference trajectory; only initial XML identity pose is compared.",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
    }
    write_atomic(args.output, output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--sentinel-matrix", required=True, type=Path)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(args)
    except AuditError as exc:
        raise SystemExit(f"AuditError: {exc}")
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "sentinels": [item["sentinel_id"] for item in result["sentinels"]], "h5_opened": result["source_policy"]["h5_opened"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

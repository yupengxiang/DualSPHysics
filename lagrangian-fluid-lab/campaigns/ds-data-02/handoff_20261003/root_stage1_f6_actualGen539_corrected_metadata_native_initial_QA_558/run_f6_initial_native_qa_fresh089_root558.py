#!/usr/bin/env python3
"""Run the fresh F6 initial-native QA for the fresh089 actual GenCase cases.

The request carrying this worker is source-only and disabled.  Root may enable
it through the strict CPU runner after reviewing the bindings.  At execution
time this worker reads the exact generated XML/BI4 pair for each endpoint, invokes
the official PartVTK helper, and writes a private CSV plus a compact JSON audit
under the fresh attempt output root.  It never runs GenCase, a solver, a
converter, a renderer, or FloatingInfo.

The typed checks reuse the successful pre-019 audit's intended population
checks, while the mass report is deliberately corrected: the CSV's type-2
support sum is 256 kg, the XML physical body mass is 128 kg, and the per-node
solver masspart is 0.015625 kg.  These values remain separate.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

try:
    import numpy as np  # type: ignore
    from scipy.spatial import cKDTree  # type: ignore
except Exception as exc:  # pragma: no cover - Root strict environment owns dependencies
    np = None  # type: ignore
    cKDTree = None  # type: ignore
    _IMPORT_ERROR = repr(exc)
else:
    _IMPORT_ERROR = None


SCHEMA = "ds02.f6.stage1-mechanical-pose-omega-initial-native-qa-result.v3"
BINDING_SCHEMA = "ds02.f6.stage1-mechanical-pose-omega-initial-native-qa-binding.v3"
DEFAULT_PARTVTK = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
DEFAULT_PARTVTK_SHA256 = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
CENTER = (2.4, 1.2, 1.08)
BASE_BODY_LOW = (2.0, 0.8, 0.88)
BASE_BODY_HIGH = (2.8, 1.6, 1.28)
FLUID_LOW = (0.4, 0.4, 0.04)
FLUID_HIGH = (4.4, 2.0, 0.84)
FLOATING_TYPE = 2
FLOATING_MK = 60
FLUID_TYPE = 3
FLUID_MK = 1
FIXED_TYPE = 0
FIXED_MK = 30
RECIPE_COUNTS = {"fixed": 73441, "moving": 0, "floating": 16384, "fluid": 327680, "total": 417505}
VELOCITY_TOLERANCE = 1.0e-9
GEOMETRY_TOLERANCE = 1.0e-9


class QAError(RuntimeError):
    """Raised for a fail-closed source or native-input mismatch."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QAError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise QAError(f"{label} is missing: {path}")
    return path


def verify_hash(path: Path, expected: str, label: str) -> str:
    require_file(path, label)
    observed = sha256(path)
    if expected and observed != expected:
        raise QAError(f"{label} hash mismatch: {path}: {observed} != {expected}")
    return observed


def finite(value: float) -> bool:
    return math.isfinite(float(value))


def normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def parse_int(value: str, label: str) -> int:
    number = float(value.strip())
    if not math.isfinite(number) or not number.is_integer():
        raise QAError(f"{label} is not a finite integer: {value!r}")
    return int(number)


def parse_type(value: str) -> str:
    text = value.strip().lower()
    aliases = {"0": "fixed", "fixed": "fixed", "1": "moving", "moving": "moving",
               "2": "floating", "body": "floating", "floating": "floating",
               "3": "fluid", "fluid": "fluid"}
    if text in aliases:
        return aliases[text]
    try:
        number = parse_int(text, "particle type")
    except (ValueError, QAError):
        return "unknown"
    return aliases.get(str(number), "unknown")


def find_column(headers: Sequence[str], *, exact: Iterable[str] = (), contains: Iterable[str] = ()) -> int | None:
    values = [normalise(value) for value in headers]
    for alias in exact:
        target = normalise(alias)
        for index, value in enumerate(values):
            if value == target:
                return index
    for alias in contains:
        target = normalise(alias)
        for index, value in enumerate(values):
            if target in value:
                return index
    return None


def open_partvtk_rows(path: Path) -> tuple[Any, list[str], Iterator[list[str]]]:
    handle = require_file(path, "PartVTK CSV").open("r", encoding="utf-8", errors="replace", newline="")
    for line in handle:
        if "Pos.x" in line and "Type" in line and "Mk" in line and "Mass" in line:
            delimiter = ";" if line.count(";") >= line.count(",") else ","
            reader = csv.reader(itertools.chain([line], handle), delimiter=delimiter)
            try:
                headers = [str(value).strip() for value in next(reader)]
            except StopIteration as exc:
                handle.close()
                raise QAError(f"PartVTK CSV header is empty: {path}") from exc
            return handle, headers, reader
    handle.close()
    raise QAError(f"typed PartVTK CSV header not found: {path}")


def vector(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise QAError(f"missing XML node: {label}")
    values: list[float] = []
    for axis in "xyz":
        raw = node.get(axis)
        if raw is None:
            raise QAError(f"missing XML {label}.{axis}")
        value = float(raw)
        if not finite(value):
            raise QAError(f"non-finite XML {label}.{axis}")
        values.append(value)
    return values


def xml_contract(source_path: Path, generated_path: Path, endpoint: Mapping[str, Any], expected_counts: Mapping[str, int]) -> dict[str, Any]:
    source_root = ET.parse(source_path).getroot()
    generated_root = ET.parse(generated_path).getroot()
    source_floating = source_root.find(".//casedef/floatings/floating")
    generated_floating = generated_root.find(".//casedef/floatings/floating")
    generated_particles = generated_root.find(".//execution/particles")
    if generated_particles is None:
        generated_particles = generated_root.find(".//particles")
    if source_floating is None or generated_floating is None or generated_particles is None:
        raise QAError(f"floating XML contract is incomplete: {generated_path}")

    source_omega = vector(source_floating.find("angularvelini"), "source.angularvelini")
    expected_omega = [float(value) for value in endpoint["omega_rad_s"]]
    generated_casedef_omega = vector(generated_floating.find("angularvelini"), "generated.casedef.angularvelini")
    generated_particle_floating = generated_particles.find("floating")
    if generated_particle_floating is None:
        raise QAError(f"generated execution particles lacks floating block: {generated_path}")
    generated_particle_omega = vector(generated_particle_floating.find("angularvelini"), "generated.particles.angularvelini")

    source_center = vector(source_floating.find("center"), "source.center")
    generated_center = vector(generated_floating.find("center"), "generated.center")
    source_inertia = vector(source_floating.find("inertia"), "source.inertia")
    generated_inertia = vector(generated_floating.find("inertia"), "generated.inertia")
    source_massbody_node = source_floating.find("massbody")
    generated_massbody_node = generated_floating.find("massbody")
    particle_masspart_node = generated_particle_floating.find("masspart")
    if source_massbody_node is None or generated_massbody_node is None or particle_masspart_node is None:
        raise QAError(f"generated floating mass contract is incomplete: {generated_path}")
    source_massbody = float(source_massbody_node.get("value", "nan"))
    generated_massbody = float(generated_massbody_node.get("value", "nan"))
    masspart = float(particle_masspart_node.get("value", "nan"))

    source_tdof = vector_int(source_floating.find("translationDOF"), "source.translationDOF")
    source_rdof = vector_int(source_floating.find("rotationDOF"), "source.rotationDOF")
    generated_tdof = vector_int(generated_floating.find("translationDOF"), "generated.translationDOF")
    generated_rdof = vector_int(generated_floating.find("rotationDOF"), "generated.rotationDOF")

    summary = generated_particles.find("_summary")
    counts: dict[str, int] = {}
    for name in ("fixed", "floating", "fluid"):
        # Genuine GenCase writes an empty ``_summary`` marker and keeps
        # the typed count attributes on the sibling particle nodes.  Prefer a
        # populated summary when available, then fall back to those siblings.
        node = summary.find(name) if summary is not None else None
        if node is None:
            node = generated_particles.find(name)
        if node is None or node.get("count") is None:
            raise QAError(f"generated XML lacks count for {name}: {generated_path}")
        counts[name] = int(node.get("count", "-1"))
    counts["moving"] = 0
    counts["total"] = int(generated_particles.get("np", "-1"))
    constants = generated_root.find(".//constants")
    data2d_node = constants.find("data2d") if constants is not None else None
    data2d = data2d_node is not None and data2d_node.get("value", "false").lower() == "true"
    rho_node = constants.find("rhop0") if constants is not None else None
    rho0 = float(rho_node.get("value", "nan")) if rho_node is not None else float("nan")
    massfluid_node = constants.find("massfluid") if constants is not None else None
    massfluid = float(massfluid_node.get("value", "nan")) if massfluid_node is not None else float("nan")

    same = lambda left, right, tol=1.0e-9: len(left) == len(right) and all(abs(a - b) <= tol for a, b in zip(left, right))
    checks = {
        "source_angular_declaration_matches_endpoint": same(source_omega, expected_omega, 1.0e-12),
        "generated_casedef_angular_declaration_matches_source": same(generated_casedef_omega, source_omega, 1.0e-12),
        "generated_particle_angular_declaration_matches_source": same(generated_particle_omega, source_omega, 1.0e-12),
        "source_center_matches_physical_contract": same(source_center, list(CENTER), 1.0e-12),
        "generated_center_matches_physical_contract": same(generated_center, list(CENTER), 1.0e-9),
        "source_massbody_128kg": abs(source_massbody - 128.0) <= 1.0e-12,
        "generated_massbody_128kg": abs(generated_massbody - 128.0) <= 1.0e-9,
        "masspart_0p015625kg": abs(masspart - float(endpoint["expected_masspart_kg"])) <= 1.0e-12,
        "source_and_generated_free_6dof": source_tdof == [1, 1, 1] and source_rdof == [1, 1, 1] and generated_tdof == [1, 1, 1] and generated_rdof == [1, 1, 1],
        "generated_true_3d_data2d_false": not data2d,
        "generated_counts_match_actual_gencase_report": counts == {str(k): int(v) for k, v in expected_counts.items() if str(k) != "dimension"},
        "generated_rho0_1000kg_m3": abs(rho0 - 1000.0) <= 1.0e-9,
        "generated_massfluid_matches_masspart": abs(massfluid - masspart) <= 1.0e-12,
    }
    return {
        "source_xml": str(source_path),
        "source_xml_sha256": sha256(source_path),
        "generated_xml": str(generated_path),
        "generated_xml_sha256": sha256(generated_path),
        "source_angularvelini_rad_s": source_omega,
        "generated_casedef_angularvelini_rad_s": generated_casedef_omega,
        "generated_particle_angularvelini_rad_s": generated_particle_omega,
        "expected_angularvelini_rad_s": expected_omega,
        "source_center_m": source_center,
        "generated_center_m": generated_center,
        "source_massbody_kg": source_massbody,
        "generated_massbody_kg": generated_massbody,
        "masspart_kg": masspart,
        "source_inertia_kg_m2": source_inertia,
        "generated_inertia_kg_m2": generated_inertia,
        "source_translation_dof": source_tdof,
        "source_rotation_dof": source_rdof,
        "generated_translation_dof": generated_tdof,
        "generated_rotation_dof": generated_rdof,
        "data2d": data2d,
        "rho0_kg_m3": rho0,
        "massfluid_kg": massfluid,
        "typed_summary_counts": counts,
        "checks": checks,
        "all_xml_checks_passed": all(checks.values()),
    }


def vector_int(node: ET.Element | None, label: str) -> list[int]:
    if node is None:
        raise QAError(f"missing XML node: {label}")
    values: list[int] = []
    for axis in "xyz":
        raw = node.get(axis)
        if raw is None:
            raise QAError(f"missing XML {label}.{axis}")
        values.append(parse_int(raw, label))
    return values


def aabb_gap(first: Sequence[float], second: Sequence[float]) -> list[float]:
    # Positive value means a separating gap on that axis; zero/negative means
    # the axis projections touch/overlap.  The body-fluid contract is expected
    # to separate in z; body-fixed nearest distance is checked separately.
    return [max(first[0] - second[3], second[0] - first[3]),
            max(first[1] - second[4], second[1] - first[4]),
            max(first[2] - second[5], second[2] - first[5])]


def pose_rotation_matrix(axis: Sequence[float], angle_deg: float) -> tuple[tuple[float, float, float], ...]:
    """Return the right-handed Rodrigues matrix for the declared GenCase pose."""
    if len(axis) != 3 or not all(finite(value) for value in axis) or not finite(angle_deg):
        raise QAError("initial pose axis/angle is non-finite or incomplete")
    norm = math.sqrt(sum(float(value) * float(value) for value in axis))
    if norm <= 0.0:
        raise QAError("initial pose axis has zero length")
    x, y, z = (float(value) / norm for value in axis)
    theta = math.radians(float(angle_deg))
    c = math.cos(theta)
    s = math.sin(theta)
    one_c = 1.0 - c
    return (
        (c + x * x * one_c, x * y * one_c - z * s, x * z * one_c + y * s),
        (y * x * one_c + z * s, c + y * y * one_c, y * z * one_c - x * s),
        (z * x * one_c - y * s, z * y * one_c + x * s, c + z * z * one_c),
    )


def pose_aware_body_bounds(endpoint: Mapping[str, Any]) -> tuple[list[float], list[float]]:
    """Compute the allowed AABB after the declared body-center rotation.

    The old fresh088 worker compared rotated points against the unrotated
    ``BODY_LOW/BODY_HIGH`` box, which rejects legitimate yaw poses.  This
    envelope is derived only from the source physical box and the declared
    rotateaxis pose; it does not inspect a particle payload.
    """
    pose = endpoint.get("initial_orientation_axis_angle")
    if not isinstance(pose, Mapping):
        raise QAError("endpoint lacks initial_orientation_axis_angle")
    center = tuple(float(value) for value in CENTER)
    matrix = pose_rotation_matrix(pose.get("axis", ()), float(pose.get("angle_deg", float("nan"))))
    corners = []
    for x in (BASE_BODY_LOW[0], BASE_BODY_HIGH[0]):
        for y in (BASE_BODY_LOW[1], BASE_BODY_HIGH[1]):
            for z in (BASE_BODY_LOW[2], BASE_BODY_HIGH[2]):
                delta = (x - center[0], y - center[1], z - center[2])
                rotated = tuple(
                    center[row] + sum(matrix[row][column] * delta[column] for column in range(3))
                    for row in range(3)
                )
                corners.append(rotated)
    low = [min(point[axis] for point in corners) for axis in range(3)]
    high = [max(point[axis] for point in corners) for axis in range(3)]
    return low, high


def find_csv(prefix: Path) -> Path:
    candidates = [prefix.with_suffix(".csv"), Path(str(prefix) + ".csv"), Path(str(prefix) + "_all.csv")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = sorted(prefix.parent.glob(prefix.name + "*.csv"))
    for candidate in matches:
        if "stats" not in candidate.name.lower():
            return candidate
    raise QAError(f"PartVTK did not produce a particle CSV for prefix: {prefix}")


def run_partvtk(partvtk: Path, bi4: Path, xml: Path, output_dir: Path, threads: int) -> tuple[Path, dict[str, Any]]:
    output_dir.mkdir(parents=False, exist_ok=False)
    prefix = output_dir / "initial_particles"
    stdout_path = output_dir / "PartVTK.stdout.log"
    command = [
        str(partvtk), "-filedata", str(bi4), "-filexml", str(xml),
        "-savecsv", str(prefix),
        "-csvsep:1", "-onlytype:+all", "-vars:+all", f"-threads:{threads}",
    ]
    started = time.monotonic()
    with stdout_path.open("w", encoding="utf-8") as stream:
        completed = subprocess.run(command, cwd=str(output_dir), stdout=stream, stderr=subprocess.STDOUT, check=False)
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        raise QAError(f"PartVTK failed with returncode={completed.returncode}: {stdout_path}")
    csv_path = find_csv(prefix)
    receipt = {
        "schema": "ds02.f6.stage1-omega-partvtk-receipt.v1",
        "command": command,
        "cwd": str(output_dir),
        "returncode": int(completed.returncode),
        "elapsed_seconds": elapsed,
        "stdout": str(stdout_path),
        "stdout_sha256": sha256(stdout_path),
        "csv": str(csv_path),
        "csv_sha256": sha256(csv_path),
        "launch_allowed": False,
    }
    write_json(output_dir / "partvtk-receipt.json", receipt)
    return csv_path, receipt


def audit_csv(csv_path: Path, xml_info: Mapping[str, Any], expected_counts: Mapping[str, int], endpoint: Mapping[str, Any]) -> dict[str, Any]:
    handle, headers, rows = open_partvtk_rows(csv_path)
    norm = [normalise(header) for header in headers]
    columns = {
        "x": find_column(headers, contains=("posx",)),
        "y": find_column(headers, contains=("posy",)),
        "z": find_column(headers, contains=("posz",)),
        "vx": find_column(headers, contains=("velx", "velocityx")),
        "vy": find_column(headers, contains=("vely", "velocityy")),
        "vz": find_column(headers, contains=("velz", "velocityz")),
        "idp": find_column(headers, exact=("idp", "particleid", "uid"), contains=("idp",)),
        "type": find_column(headers, exact=("type", "particletype"), contains=("type",)),
        "mk": find_column(headers, exact=("mk", "marker"), contains=("mk",)),
        "mass": find_column(headers, exact=("mass",), contains=("mass",)),
        "density": find_column(headers, exact=("rhop", "density"), contains=("rhop", "density")),
    }
    missing = [name for name, index in columns.items() if index is None]
    if missing:
        handle.close()
        raise QAError(f"PartVTK CSV lacks required columns {missing}: {headers}")
    assert all(index is not None for index in columns.values())
    indices = {name: int(index) for name, index in columns.items()}

    counts = {"fixed": 0, "moving": 0, "floating": 0, "fluid": 0, "unknown": 0}
    mk_counts: dict[str, int] = {}
    uid_seen: set[int] = set()
    coordinate_seen: set[tuple[float, float, float]] = set()
    body_points: list[tuple[float, float, float]] = []
    body_masses: list[float] = []
    body_velocities: list[tuple[float, float, float]] = []
    fluid_points: list[tuple[float, float, float]] = []
    fluid_velocities: list[tuple[float, float, float]] = []
    fixed_points: list[tuple[float, float, float]] = []
    fluid_mass = 0.0
    body_mass = 0.0
    min_mass = float("inf")
    max_mass = float("-inf")
    min_density = float("inf")
    max_density = float("-inf")
    fluid_density_values: list[float] = []
    rows_read = 0
    parse_errors = 0
    all_finite = True
    all_positive_weights = True
    all_positive_density = True
    all_type_mk_consistent = True
    all_velocities_finite = True
    duplicate_uid_count = 0
    out_of_range_uid_count = 0
    expected_total = int(expected_counts["total"])

    try:
        for row in rows:
            if not row or len(row) <= max(indices.values()):
                continue
            try:
                x = float(row[indices["x"]]); y = float(row[indices["y"]]); z = float(row[indices["z"]])
                vx = float(row[indices["vx"]]); vy = float(row[indices["vy"]]); vz = float(row[indices["vz"]])
                uid = parse_int(row[indices["idp"]], "Idp")
                mk = parse_int(row[indices["mk"]], "Mk")
                mass = float(row[indices["mass"]])
                density = float(row[indices["density"]])
                kind = parse_type(row[indices["type"]])
            except (TypeError, ValueError, QAError):
                parse_errors += 1
                continue
            rows_read += 1
            point = (x, y, z)
            velocity = (vx, vy, vz)
            coordinate_seen.add(point)
            if uid in uid_seen:
                duplicate_uid_count += 1
            uid_seen.add(uid)
            if uid < 0 or uid >= expected_total:
                out_of_range_uid_count += 1
            if kind not in counts:
                counts["unknown"] += 1
                all_type_mk_consistent = False
            else:
                counts[kind] += 1
                expected_mk = {
                    "fixed": FIXED_MK,
                    "moving": None,
                    "floating": FLOATING_MK,
                    "fluid": FLUID_MK,
                }[kind]
                if expected_mk is not None and mk != expected_mk:
                    all_type_mk_consistent = False
            mk_counts[f"{kind}:mk{mk}"] = mk_counts.get(f"{kind}:mk{mk}", 0) + 1
            row_finite = all(finite(value) for value in (*point, *velocity, mass, density))
            all_finite = all_finite and row_finite
            all_velocities_finite = all_velocities_finite and all(finite(value) for value in velocity)
            all_positive_weights = all_positive_weights and finite(mass) and mass > 0.0
            all_positive_density = all_positive_density and finite(density) and density > 0.0
            if finite(mass):
                min_mass = min(min_mass, mass); max_mass = max(max_mass, mass)
            if finite(density):
                min_density = min(min_density, density); max_density = max(max_density, density)
            if kind == "floating" and mk == FLOATING_MK:
                body_points.append(point); body_masses.append(mass); body_velocities.append(velocity); body_mass += mass
            elif kind == "fluid" and mk == FLUID_MK:
                fluid_points.append(point); fluid_velocities.append(velocity); fluid_mass += mass; fluid_density_values.append(density)
            elif kind == "fixed" and mk == FIXED_MK:
                fixed_points.append(point)
    finally:
        handle.close()

    body_count = len(body_points)
    fluid_count = len(fluid_points)
    fixed_count = len(fixed_points)
    body_arr = np.asarray(body_points, dtype=np.float64) if np is not None else None
    fluid_arr = np.asarray(fluid_points, dtype=np.float64) if np is not None else None
    fixed_arr = np.asarray(fixed_points, dtype=np.float64) if np is not None else None
    if np is None or cKDTree is None:
        raise QAError(f"numpy/scipy unavailable in Root strict environment: {_IMPORT_ERROR}")

    body_bounds = [body_arr.min(axis=0).tolist(), body_arr.max(axis=0).tolist()] if body_count else [[], []]
    fluid_bounds = [fluid_arr.min(axis=0).tolist(), fluid_arr.max(axis=0).tolist()] if fluid_count else [[], []]
    fixed_bounds = [fixed_arr.min(axis=0).tolist(), fixed_arr.max(axis=0).tolist()] if fixed_count else [[], []]
    if body_count:
        body_weights = np.asarray(body_masses, dtype=np.float64)
        body_centroid = (body_arr * body_weights[:, None]).sum(axis=0) / float(body_weights.sum())
    else:
        body_centroid = np.asarray([float("nan")] * 3)
    pose_bounds = pose_aware_body_bounds(endpoint)
    body_bounds_inside = bool(body_count and all(body_arr[:, axis].min() >= pose_bounds[0][axis] - GEOMETRY_TOLERANCE and body_arr[:, axis].max() <= pose_bounds[1][axis] + GEOMETRY_TOLERANCE for axis in range(3)))
    body_y_unique = len(np.unique(body_arr[:, 1])) if body_count else 0
    body_z_unique = len(np.unique(body_arr[:, 2])) if body_count else 0
    fluid_y_unique = len(np.unique(fluid_arr[:, 1])) if fluid_count else 0
    fluid_z_unique = len(np.unique(fluid_arr[:, 2])) if fluid_count else 0

    body_fluid_min_distance = float("nan")
    body_fixed_min_distance = float("nan")
    if body_count and fluid_count:
        distances, _ = cKDTree(fluid_arr).query(body_arr, k=1)
        body_fluid_min_distance = float(np.min(distances))
    if body_count and fixed_count:
        distances, _ = cKDTree(fixed_arr).query(body_arr, k=1)
        body_fixed_min_distance = float(np.min(distances))
    body_fluid_gap = aabb_gap((*body_bounds[0], *body_bounds[1]), (*fluid_bounds[0], *fluid_bounds[1])) if body_count and fluid_count else [float("nan")] * 3
    body_fixed_gap = aabb_gap((*body_bounds[0], *body_bounds[1]), (*fixed_bounds[0], *fixed_bounds[1])) if body_count and fixed_count else [float("nan")] * 3
    max_fluid_velocity = float(np.max(np.abs(np.asarray(fluid_velocities, dtype=np.float64)))) if fluid_velocities else float("nan")
    max_body_velocity = float(np.max(np.abs(np.asarray(body_velocities, dtype=np.float64)))) if body_velocities else float("nan")
    fluid_density_min = float(min(fluid_density_values)) if fluid_density_values else float("nan")
    fluid_density_max = float(max(fluid_density_values)) if fluid_density_values else float("nan")
    declared_center = np.asarray(CENTER, dtype=np.float64)
    body_centroid_error = (body_centroid - declared_center).tolist() if body_count else [float("nan")] * 3
    body_centroid_matches_declared_center = bool(body_count and np.all(np.abs(body_centroid - declared_center) <= 3.0e-6))

    xml_counts = dict(xml_info["typed_summary_counts"])
    checks = {
        "rows_read_exact_actual_total": rows_read == expected_counts["total"],
        "no_csv_parse_errors": parse_errors == 0,
        "all_native_uid_finite_integer_unique_complete": rows_read == expected_total and len(uid_seen) == expected_total and duplicate_uid_count == 0 and out_of_range_uid_count == 0 and uid_seen == set(range(expected_total)),
        "all_native_type_and_mk_known": all_type_mk_consistent and counts["unknown"] == 0 and counts["fixed"] == expected_counts["fixed"] and counts["moving"] == expected_counts["moving"] and counts["floating"] == expected_counts["floating"] and counts["fluid"] == expected_counts["fluid"],
        "all_native_coordinates_velocities_weights_density_finite": all_finite and all_velocities_finite,
        "all_native_weights_positive": all_positive_weights,
        "all_native_density_positive": all_positive_density,
        "native_coordinates_unique": len(coordinate_seen) == rows_read,
        "floating_count_complete_actual": body_count == expected_counts["floating"],
        "fluid_count_complete_actual": fluid_count == expected_counts["fluid"],
        "fixed_count_complete_actual": fixed_count == expected_counts["fixed"],
        "true_3d_coordinate_diversity": not bool(xml_info["data2d"]) and fluid_y_unique > 1 and fluid_z_unique > 1 and body_y_unique > 1 and body_z_unique > 1,
        "initial_fluid_velocities_finite_and_zero": bool(fluid_velocities) and finite(max_fluid_velocity) and max_fluid_velocity <= VELOCITY_TOLERANCE,
        "gencase_body_particle_velocities_zero": bool(body_velocities) and finite(max_body_velocity) and max_body_velocity <= VELOCITY_TOLERANCE,
        "body_bounds_inside_pose_aware_physical_envelope": body_bounds_inside,
        "body_weighted_centroid_matches_declared_center": body_centroid_matches_declared_center,
        "body_fluid_no_gross_overlap": bool(body_fluid_gap and max(body_fluid_gap) > GEOMETRY_TOLERANCE and finite(body_fluid_min_distance) and body_fluid_min_distance > GEOMETRY_TOLERANCE),
        "body_fixed_no_gross_overlap": bool(finite(body_fixed_min_distance) and body_fixed_min_distance > GEOMETRY_TOLERANCE),
        "csv_counts_agree_with_generated_xml": {"fixed": fixed_count, "moving": counts["moving"], "floating": body_count, "fluid": fluid_count, "total": rows_read} == xml_counts,
        "fluid_native_mass_5120kg": abs(fluid_mass - 5120.0) <= 1.0e-6,
        "native_support_mass_256kg": abs(body_mass - 256.0) <= 1.0e-6,
        "native_support_mass_distinct_from_physical_128kg": abs(body_mass - float(xml_info["generated_massbody_kg"])) > 1.0e-6,
    }
    return {
        "csv": str(csv_path),
        "csv_sha256": sha256(csv_path),
        "headers": headers,
        "columns": {name: headers[index] for name, index in indices.items()},
        "rows_read": rows_read,
        "parse_errors": parse_errors,
        "typed_counts": counts,
        "typed_mk_counts": mk_counts,
        "type_mk_consistent": all_type_mk_consistent,
        "uid": {"unique_count": len(uid_seen), "duplicate_count": duplicate_uid_count, "out_of_range_count": out_of_range_uid_count, "complete_range": len(uid_seen) == expected_total and uid_seen == set(range(expected_total))},
        "all_coordinates_unique_count": len(coordinate_seen),
        "bounds_m": {"body": body_bounds, "fluid": fluid_bounds, "fixed": fixed_bounds, "pose_aware_expected_body": pose_bounds},
        "body": {"count": body_count, "native_support_mass_kg": body_mass, "weighted_centroid_m": body_centroid.tolist(), "weighted_centroid_error_m": body_centroid_error, "declared_center_m": list(CENTER), "max_particle_velocity_m_s": max_body_velocity, "y_unique": body_y_unique, "z_unique": body_z_unique},
        "fluid": {"count": fluid_count, "native_mass_kg": fluid_mass, "max_abs_velocity_m_s": max_fluid_velocity, "density_min_kg_m3": fluid_density_min, "density_max_kg_m3": fluid_density_max, "y_unique": fluid_y_unique, "z_unique": fluid_z_unique},
        "geometry": {"body_fluid_min_distance_m": body_fluid_min_distance, "body_fixed_min_distance_m": body_fixed_min_distance, "body_fluid_aabb_axis_gaps_m": body_fluid_gap, "body_fixed_aabb_axis_gaps_m": body_fixed_gap, "pose_aware_body_bounds_m": pose_bounds, "pose_axis_angle": endpoint["initial_orientation_axis_angle"]},
        "native_mass_semantics": {"native_support_mass_kg": body_mass, "physical_mass_kg": float(xml_info["generated_massbody_kg"]), "masspart_kg": float(xml_info["masspart_kg"]), "normalization_applied": False, "interpretation": "PartVTK type-2 Mass sum is lattice support weight; it is not the declared physical rigid-body mass"},
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }


def validate_binding(binding_path: Path, binding: Mapping[str, Any], partvtk: Path, expected_partvtk_sha256: str) -> None:
    if binding.get("schema") != BINDING_SCHEMA or binding.get("status") != "source_only_disabled":
        raise QAError("F6 fresh089 binding is not the expected disabled source package")
    if binding.get("launch_allowed") is not False:
        raise QAError("F6 fresh089 binding must keep launch_allowed=false")
    # The request/guard binds this file before launch.  The worker only needs
    # to ensure it is readable here; a self-comparison would provide no
    # provenance guarantee and is intentionally avoided.
    require_file(binding_path, "binding")
    verify_hash(partvtk, expected_partvtk_sha256, "official PartVTK")
    plan_info = binding.get("source_plan")
    receipt_info = binding.get("source_build_receipt")
    if not isinstance(plan_info, dict) or not isinstance(receipt_info, dict):
        raise QAError("binding lacks source plan/receipt")
    plan_path = Path(str(plan_info["path"]))
    receipt_path = Path(str(receipt_info["path"]))
    verify_hash(plan_path, str(plan_info["sha256"]), "source plan")
    verify_hash(receipt_path, str(receipt_info["sha256"]), "source-build receipt")
    receipt = load_json(receipt_path)
    if receipt.get("status") != "source_built_only" or receipt.get("launch_allowed") is not False:
        raise QAError("source-build receipt is not source-only disabled")
    prior = binding.get("prior_typed_qa_source")
    if not isinstance(prior, dict):
        raise QAError("prior typed QA source binding missing")
    verify_hash(Path(str(prior["script"])), str(prior["sha256"]), "prior typed QA source")
    # fresh066 fixes the 064 source/worker contract mismatch.  The binding
    # field is deliberately singular and exact; accepting the old
    # ``historical_evidence_preserved`` spelling would make a stale binding
    # look valid again.
    historical = binding.get("historical_evidence")
    if not isinstance(historical, list) or len(historical) != 2:
        raise QAError("historical QA/semantic evidence binding must contain exactly two immutable records")
    for item in historical:
        if not isinstance(item, dict):
            raise QAError("malformed historical evidence record")
        verify_hash(Path(str(item["path"])), str(item["sha256"]), str(item.get("id", "historical evidence")))
    endpoints = binding.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) < 1:
        raise QAError("fresh089 binding must contain at least one endpoint")
    expected_endpoint_count = int(binding.get("case_count", len(endpoints)))
    if len(endpoints) != expected_endpoint_count:
        raise QAError(f"fresh089 endpoint count mismatch: {len(endpoints)} != {expected_endpoint_count}")
    plan = load_json(plan_path)
    plan_rows = {str(row["endpoint_id"]): row for row in plan.get("endpoints", []) if isinstance(row, dict) and row.get("endpoint_id")}
    for endpoint in endpoints:
        endpoint_id = str(endpoint.get("endpoint_id", ""))
        if not endpoint_id or Path(endpoint_id).name != endpoint_id or endpoint_id not in plan_rows:
            raise QAError(f"endpoint is not present in source plan: {endpoint_id}")
        plan_row = plan_rows[endpoint_id]
        if str(endpoint.get("source_plan_condition_sha256")) != str(plan_row.get("source_plan_condition_sha256")):
            raise QAError(f"source-plan condition binding mismatch: {endpoint_id}")
        if [float(value) for value in endpoint.get("omega_rad_s", [])] != [float(value) for value in plan_row.get("initial_angular_velocity_rad_s", [])]:
            raise QAError(f"source-plan angular declaration mismatch: {endpoint_id}")
        expected_counts = {str(key): int(value) for key, value in endpoint.get("expected_counts", {}).items() if str(key) != "dimension"}
        if expected_counts != RECIPE_COUNTS or int(endpoint.get("expected_counts", {}).get("dimension", -1)) != 3:
            raise QAError(f"endpoint native count contract drift: {endpoint_id}")
        if abs(float(endpoint.get("expected_native_support_mass_kg", float("nan"))) - 256.0) > 1.0e-12 or abs(float(endpoint.get("expected_physical_mass_kg", float("nan"))) - 128.0) > 1.0e-12 or abs(float(endpoint.get("expected_masspart_kg", float("nan"))) - 0.015625) > 1.0e-12:
            raise QAError(f"endpoint mass contract drift: {endpoint_id}")
        source_definition = Path(str(endpoint["source_definition"]))
        verify_hash(source_definition, str(endpoint["source_definition_sha256"]), f"source definition {endpoint_id}")
        if str(endpoint["source_definition_sha256"]) != str(plan_row.get("source_definition_sha256")):
            raise QAError(f"source-plan definition binding mismatch: {endpoint_id}")
        owner_path = Path(str(endpoint["canonical_owner"]))
        verify_hash(owner_path, str(endpoint["canonical_owner_sha256"]), f"canonical owner {endpoint_id}")
        owner = load_json(owner_path)
        if owner.get("physical_condition_sha256") != endpoint["physical_condition_sha256"]:
            raise QAError(f"canonical physical hash mismatch: {endpoint_id}")
        if owner.get("source_definition_sha256") != endpoint["source_definition_sha256"]:
            raise QAError(f"canonical source-definition hash mismatch: {endpoint_id}")
        if owner.get("source_plan_condition_sha256") != endpoint["source_plan_condition_sha256"]:
            raise QAError(f"canonical source-plan condition hash mismatch: {endpoint_id}")
        if str(owner.get("source_definition")) != str(endpoint["source_definition"]):
            raise QAError(f"canonical source-definition path mismatch: {endpoint_id}")
        parameters = owner.get("physical_binding", {}).get("parameters", {})
        if abs(float(parameters.get("body_mass_kg", float("nan"))) - 128.0) > 1.0e-12:
            raise QAError(f"owner physical mass drift: {endpoint_id}")
        if [float(value) for value in parameters.get("body_center_m", [])] != list(CENTER):
            raise QAError(f"owner center drift: {endpoint_id}")
        if [float(value) for value in parameters.get("initial_angular_velocity_rad_s", [])] != [float(value) for value in endpoint["omega_rad_s"]]:
            raise QAError(f"owner omega drift: {endpoint_id}")
        actual = endpoint.get("actual_gencase")
        if not isinstance(actual, Mapping) or actual.get("status") != "completed" or int(actual.get("returncode", -1)) != 0:
            raise QAError(f"Root539 GenCase metadata is not completed/0: {endpoint_id}")
        generated_xml = Path(str(endpoint["generated_xml"]))
        generated_bi4 = Path(str(endpoint["generated_bi4"]))
        execution_receipt = Path(str(endpoint["execution_receipt"]))
        prepared_report = Path(str(endpoint["prepared_input_report"]))
        verify_hash(generated_xml, str(endpoint["generated_xml_sha256"]), f"generated XML {endpoint_id}")
        verify_hash(execution_receipt, str(endpoint["execution_receipt_sha256"]), f"GenCase receipt {endpoint_id}")
        verify_hash(prepared_report, str(endpoint["prepared_input_report_sha256"]), f"prepared-input report {endpoint_id}")
        if generated_bi4.suffix.lower() != ".bi4":
            raise QAError(f"actual GenCase BI4 path is not a BI4 path: {endpoint_id}")
        launch = load_json(execution_receipt)
        report = load_json(prepared_report)
        if launch.get("status") != "completed" or launch.get("returncode") != 0 or int(launch.get("total_particles", -1)) != expected_counts["total"] or int(launch.get("fluid_particles", -1)) != expected_counts["fluid"] or int(launch.get("solver_dimension_from_gencase", -1)) != 3:
            raise QAError(f"Root539 GenCase receipt is not the completed 3D endpoint: {endpoint_id}")
        report_counts = {str(key): int(value) for key, value in report.get("generated_xml_particle_counts", {}).items()}
        if int(report.get("actual_total_particles", -1)) != expected_counts["total"] or report_counts != {key: value for key, value in expected_counts.items() if key != 'total'}:
            raise QAError(f"Root539 prepared report count mismatch: {endpoint_id}")
        if report.get("xml_sha256") != endpoint["generated_xml_sha256"]:
            raise QAError(f"Root539 producer XML digest mismatch: {endpoint_id}")
        if report.get("bi4_sha256") != endpoint["generated_bi4_sha256"] or not re.fullmatch(r"[0-9a-f]{64}", str(report.get("bi4_sha256", ""))):
            raise QAError(f"Root539 producer BI4 attestation mismatch: {endpoint_id}")
        xml_info = xml_contract(source_definition, generated_xml, endpoint, expected_counts)
        if not all(xml_info["checks"].values()):
            raise QAError(f"Root539 generated XML contract mismatch: {endpoint_id}")


def run(binding_path: Path, output_root: Path, partvtk_path: Path, expected_partvtk_sha256: str, threads: int) -> int:
    binding = load_json(binding_path)
    validate_binding(binding_path, binding, partvtk_path, expected_partvtk_sha256)
    if threads < 1:
        raise QAError("threads must be positive")
    output_root.mkdir(parents=True, exist_ok=False)
    endpoint_results: list[dict[str, Any]] = []
    all_pass = True
    for endpoint in binding["endpoints"]:
        endpoint_id = str(endpoint["endpoint_id"])
        endpoint_root = output_root / endpoint_id
        endpoint_root.mkdir(parents=False, exist_ok=False)
        result_path = endpoint_root / "initial-native-qa.json"
        try:
            generated_xml = Path(str(endpoint["generated_xml"]))
            generated_bi4 = Path(str(endpoint["generated_bi4"]))
            expected_counts = {str(key): int(value) for key, value in endpoint["expected_counts"].items() if str(key) != "dimension"}
            xml_info = xml_contract(Path(str(endpoint["source_definition"])), generated_xml, endpoint, expected_counts)
            csv_path, partvtk_receipt = run_partvtk(partvtk_path, generated_bi4, generated_xml, endpoint_root / "partvtk", threads)
            csv_info = audit_csv(csv_path, xml_info, expected_counts, endpoint)
            checks = dict(xml_info["checks"])
            checks.update({f"csv_{name}": value for name, value in csv_info["checks"].items()})
            endpoint_result = {
                "schema": SCHEMA,
                "family_id": "F6",
                "endpoint_id": endpoint_id,
                "role": endpoint["role"],
                "physical_condition_sha256": endpoint["physical_condition_sha256"],
                "source_plan_condition_sha256": endpoint["source_plan_condition_sha256"],
                "generated_xml": str(generated_xml),
                "generated_bi4": str(generated_bi4),
                "generated_xml_sha256": endpoint["generated_xml_sha256"],
                "generated_bi4_sha256": endpoint["generated_bi4_sha256"],
                "xml_contract": xml_info,
                "partvtk": partvtk_receipt,
                "csv_audit": csv_info,
                "checks": checks,
                "pass": bool(all(checks.values())),
                "historical_evidence": "QA019 failure and semantic020 report are hash-bound and not rejudged",
                "angular_state": {
                    "declared_angularvelini_rad_s": [float(value) for value in endpoint["omega_rad_s"]],
                    "gencase_particle_v0_zero_scope": "GenCase particle serialization only",
                    "particle_v0_zero_proves_no_angular_velocity": False,
                    "full_native_floatinginfo_state0": "required_followup",
                    "status": "declaration_bound; propagation_unobserved",
                },
                "mass_semantics": {
                    "physical_mass_kg": float(xml_info["generated_massbody_kg"]),
                    "native_support_mass_kg": float(csv_info["native_mass_semantics"]["native_support_mass_kg"]),
                    "masspart_kg": float(xml_info["masspart_kg"]),
                    "normalization_applied": False,
                    "physical_and_native_support_masses_must_not_be_equal": True,
                },
                "q_n_status": "not_assessed",
                "precision_status": "not_accepted",
                "production_approval": "none",
                "independent_case_count_increment": 0,
                "launch_allowed": False,
            }
        except Exception as exc:  # preserve a reviewable fail-closed endpoint report
            endpoint_result = {
                "schema": SCHEMA,
                "family_id": "F6",
                "endpoint_id": endpoint_id,
                "physical_condition_sha256": endpoint.get("physical_condition_sha256"),
                "pass": False,
                "error": repr(exc),
                "historical_evidence": "QA019 failure and semantic020 report remain untouched and not rejudged",
                "angular_state": {"particle_v0_zero_proves_no_angular_velocity": False, "full_native_floatinginfo_state0": "required_followup"},
                "mass_semantics": {"normalization_applied": False, "physical_and_native_support_masses_must_not_be_equal": True},
                "q_n_status": "not_assessed",
                "precision_status": "not_accepted",
                "production_approval": "none",
                "launch_allowed": False,
            }
        write_json(result_path, endpoint_result)
        endpoint_results.append({"endpoint_id": endpoint_id, "result": str(result_path), "result_sha256": sha256(result_path), "pass": bool(endpoint_result.get("pass")), "error": endpoint_result.get("error")})
        all_pass = all_pass and bool(endpoint_result.get("pass"))

    index = {
        "schema": "ds02.f6.stage1-omega-initial-native-qa-index.v1",
        "family_id": "F6",
        "scope_id": binding["scope_id"],
        "binding": str(binding_path),
        "binding_sha256": sha256(binding_path),
        "partvtk_executable": str(partvtk_path),
        "partvtk_executable_sha256": sha256(partvtk_path),
        "endpoints": endpoint_results,
        "status": "initial-native-integrity-pass" if all_pass else "initial-native-integrity-fail",
        "pass": all_pass,
        "historical_evidence_policy": "QA019 failure and semantic020 audit are preserved by hash and never rejudged",
        "angular_propagation_policy": "GenCase V0=0 does not prove zero angular velocity; full native FloatingInfo state0 is required",
        "mass_policy": "physical 128 kg, native support 256 kg, and masspart 0.015625 kg remain distinct; no normalization",
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "launch_allowed": False,
    }
    write_json(output_root / "initial-native-qa-index.json", index)
    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--partvtk-exe", type=Path, default=Path(DEFAULT_PARTVTK))
    parser.add_argument("--expected-partvtk-sha256", default=DEFAULT_PARTVTK_SHA256)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    return run(args.binding, args.output_root, args.partvtk_exe, args.expected_partvtk_sha256, args.threads)


if __name__ == "__main__":
    raise SystemExit(main())

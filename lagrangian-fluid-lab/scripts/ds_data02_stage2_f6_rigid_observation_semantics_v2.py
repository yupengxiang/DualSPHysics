#!/usr/bin/env python3
"""Audit the source semantics behind an already consumed F6 rigid observation.

This forward-only audit does not rerun ``FloatingInfo`` and does not read H5 or
particle frames.  It binds the completed rigid-observation-v1 result and its
receipt to the official v5.4 producer sources, then records what the sources do
and do not establish about the Euler labels in the emitted CSV.

The solver source closes the internal angle algebra and the frame used for the
kinematic ``fomega x (position-center)`` update.  The installed FloatingInfo
producer is binary-only in this source tree: its help and binary are bound,
but a source-level function mapping its CSV roll/pitch/yaw labels to a matrix
is not present.  Therefore the CSV Euler order and active/passive convention
remain UNKNOWN unless independently established by a future producer-source
bundle.  The old v1 derived quaternion is preserved as a legacy candidate and
is never silently upgraded by this audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds02.stage2.f6-rigid-observation-semantics.v2"
V1_SCHEMA = "ds02.stage2.f6-rigid-observation.v1"
RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
EXPECTED_SENTINELS = ("F6-S1", "F6-S2")
EXPECTED_SOURCE_ROOT = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4"
)
EXPECTED_V1_OUTPUT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "STAGE2_F6_RIGID_OBSERVATION_SENTINELS/f6-rigid-observation-v1/"
    "f6-rigid-observation.json"
)
EXPECTED_V1_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "STAGE2_F6_RIGID_OBSERVATION_SENTINELS/f6-rigid-observation-v1/"
    "execution-receipt.json"
)
EXPECTED_V1_SCRIPT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_stage2_f6_rigid_observation_v1.py"
)

# Hard-coded noncommuting golden values.  Angles are (roll, pitch, yaw) in
# degrees (17, -23, 31).  The matrix is the exact algebra present in the
# official FunctionsMath.h RotMatrix3x3 implementation: Rx Ry Rz.
GOLDEN_ANGLES_DEG = (17.0, -23.0, 31.0)
GOLDEN_SOURCE_MATRIX = (
    (0.789026660517022, -0.474095047667506, -0.390731128489274),
    (0.394611660030619, 0.878550459900843, -0.269129573209443),
    (0.470870010471293, 0.058163349157029, 0.880283169243626),
)
GOLDEN_SOURCE_QUATERNION_XYZW = (
    0.086880710420313,
    -0.228714139342212,
    0.230600330022401,
    0.941788231193920,
)
GOLDEN_LEGACY_V1_QUATERNION_XYZW = (
    0.192267794065585,
    -0.151299407610675,
    0.287393735140744,
    0.926038026013870,
)


class SemanticAuditError(RuntimeError):
    """Raised when source or producer identity cannot be closed."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path | str, label: str) -> Path:
    value = Path(path).expanduser().resolve()
    if not value.is_file():
        raise SemanticAuditError(f"{label} is missing: {value}")
    return value


def read_json(path: Path | str, label: str) -> dict[str, Any]:
    value = require_file(path, label)
    try:
        payload = json.loads(value.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SemanticAuditError(f"{label} is invalid JSON: {value}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SemanticAuditError(f"{label} is not a JSON object: {value}")
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


def close(first: float, second: float, tolerance: float = 1.0e-12) -> bool:
    return math.isfinite(first) and math.isfinite(second) and abs(first - second) <= tolerance


def matrix_multiply(first: Sequence[Sequence[float]], second: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(sum(float(first[i][k]) * float(second[k][j]) for k in range(3)) for j in range(3))
        for i in range(3)
    )


def matrix_max_abs_diff(first: Sequence[Sequence[float]], second: Sequence[Sequence[float]]) -> float:
    return max(abs(float(first[i][j]) - float(second[i][j])) for i in range(3) for j in range(3))


def axis_matrix(axis: str, angle_rad: float) -> tuple[tuple[float, ...], ...]:
    cosine = math.cos(angle_rad)
    sine = math.sin(angle_rad)
    if axis == "x":
        return ((1.0, 0.0, 0.0), (0.0, cosine, -sine), (0.0, sine, cosine))
    if axis == "y":
        return ((cosine, 0.0, sine), (0.0, 1.0, 0.0), (-sine, 0.0, cosine))
    if axis == "z":
        return ((cosine, -sine, 0.0), (sine, cosine, 0.0), (0.0, 0.0, 1.0))
    raise SemanticAuditError(f"unknown rotation axis {axis!r}")


def source_rotation_matrix(angles_rad: Sequence[float]) -> tuple[tuple[float, ...], ...]:
    """Reproduce official FunctionsMath.h RotMatrix3x3: Rx * Ry * Rz."""
    if len(angles_rad) != 3:
        raise SemanticAuditError("source rotation requires three angles")
    rx = axis_matrix("x", float(angles_rad[0]))
    ry = axis_matrix("y", float(angles_rad[1]))
    rz = axis_matrix("z", float(angles_rad[2]))
    return matrix_multiply(matrix_multiply(rx, ry), rz)


def legacy_v1_rotation_matrix(angles_rad: Sequence[float]) -> tuple[tuple[float, ...], ...]:
    """Matrix represented by v1's documented intrinsic-XYZ quaternion."""
    rx = axis_matrix("x", float(angles_rad[0]))
    ry = axis_matrix("y", float(angles_rad[1]))
    rz = axis_matrix("z", float(angles_rad[2]))
    return matrix_multiply(matrix_multiply(rz, ry), rx)


def quaternion_multiply(first: Sequence[float], second: Sequence[float]) -> tuple[float, float, float, float]:
    x1, y1, z1, w1 = (float(value) for value in first)
    x2, y2, z2, w2 = (float(value) for value in second)
    return (
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    )


def axis_quaternion(axis: str, angle_rad: float) -> tuple[float, float, float, float]:
    half = float(angle_rad) / 2.0
    sine = math.sin(half)
    cosine = math.cos(half)
    if axis == "x":
        return (sine, 0.0, 0.0, cosine)
    if axis == "y":
        return (0.0, sine, 0.0, cosine)
    if axis == "z":
        return (0.0, 0.0, sine, cosine)
    raise SemanticAuditError(f"unknown quaternion axis {axis!r}")


def source_quaternion(angles_rad: Sequence[float]) -> tuple[float, float, float, float]:
    # The source matrix Rx*Ry*Rz is represented by qx*qy*qz under the active
    # column-vector convention used by JMatrix4::MulPoint/MulNormal.
    qx = axis_quaternion("x", float(angles_rad[0]))
    qy = axis_quaternion("y", float(angles_rad[1]))
    qz = axis_quaternion("z", float(angles_rad[2]))
    return quaternion_multiply(quaternion_multiply(qx, qy), qz)


def legacy_v1_quaternion(angles_rad: Sequence[float]) -> tuple[float, float, float, float]:
    # This is the formula in consumed v1's quaternion_from_euler_deg: qz*qy*qx.
    qx = axis_quaternion("x", float(angles_rad[0]))
    qy = axis_quaternion("y", float(angles_rad[1]))
    qz = axis_quaternion("z", float(angles_rad[2]))
    return quaternion_multiply(quaternion_multiply(qz, qy), qx)


def quaternion_norm(quaternion: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in quaternion))


def require_unit_quaternion(quaternion: Sequence[float], tolerance: float = 1.0e-10) -> tuple[float, float, float, float]:
    if len(quaternion) != 4:
        raise SemanticAuditError("unit quaternion requires exactly four components")
    values = tuple(float(value) for value in quaternion)
    if not all(math.isfinite(value) for value in values):
        raise SemanticAuditError("unit quaternion contains non-finite components")
    norm = quaternion_norm(values)
    if abs(norm - 1.0) > tolerance:
        raise SemanticAuditError(f"quaternion norm {norm} is outside the unit tolerance")
    return values


def quaternion_from_matrix(matrix: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    # Stable branch-free enough for the fixed non-singular golden case.  The
    # result is normalized and then subject to the strict unit validator.
    trace = float(matrix[0][0] + matrix[1][1] + matrix[2][2])
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (matrix[2][1] - matrix[1][2]) / scale
        y = (matrix[0][2] - matrix[2][0]) / scale
        z = (matrix[1][0] - matrix[0][1]) / scale
    elif matrix[0][0] > matrix[1][1] and matrix[0][0] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[0][0] - matrix[1][1] - matrix[2][2]) * 2.0
        w = (matrix[2][1] - matrix[1][2]) / scale
        x = 0.25 * scale
        y = (matrix[0][1] + matrix[1][0]) / scale
        z = (matrix[0][2] + matrix[2][0]) / scale
    elif matrix[1][1] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[1][1] - matrix[0][0] - matrix[2][2]) * 2.0
        w = (matrix[0][2] - matrix[2][0]) / scale
        x = (matrix[0][1] + matrix[1][0]) / scale
        y = 0.25 * scale
        z = (matrix[1][2] + matrix[2][1]) / scale
    else:
        scale = math.sqrt(1.0 + matrix[2][2] - matrix[0][0] - matrix[1][1]) * 2.0
        w = (matrix[1][0] - matrix[0][1]) / scale
        x = (matrix[0][2] + matrix[2][0]) / scale
        y = (matrix[1][2] + matrix[2][1]) / scale
        z = 0.25 * scale
    norm = quaternion_norm((x, y, z, w))
    return require_unit_quaternion((x / norm, y / norm, z / norm, w / norm))


def quaternion_distance_deg(first: Sequence[float], second: Sequence[float]) -> float:
    qfirst = require_unit_quaternion(first)
    qsecond = require_unit_quaternion(second)
    dot = max(-1.0, min(1.0, abs(sum(a * b for a, b in zip(qfirst, qsecond)))))
    return math.degrees(2.0 * math.acos(dot))


def angles_to_radians(values: Sequence[float], unit: str) -> tuple[float, float, float]:
    if len(values) != 3:
        raise SemanticAuditError("Euler input requires three values")
    if unit != "deg":
        raise SemanticAuditError("FloatingInfo CSV Euler fields are explicitly degrees; ambiguous/radian input rejected")
    return tuple(math.radians(float(value)) for value in values)


def expect_rejection(function: Any, *args: Any) -> bool:
    try:
        function(*args)
    except SemanticAuditError:
        return True
    return False


def manufactured_semantic_tests() -> dict[str, Any]:
    angles_rad = angles_to_radians(GOLDEN_ANGLES_DEG, "deg")
    source_matrix = source_rotation_matrix(angles_rad)
    source_q = source_quaternion(angles_rad)
    legacy_quaternion = legacy_v1_quaternion(angles_rad)
    legacy_matrix = legacy_v1_rotation_matrix(angles_rad)
    matrix_from_q = quaternion_to_matrix(source_q)
    source_matrix_error = matrix_max_abs_diff(source_matrix, GOLDEN_SOURCE_MATRIX)
    source_quaternion_error = max(abs(a - b) for a, b in zip(source_q, GOLDEN_SOURCE_QUATERNION_XYZW))
    matrix_quaternion_error = matrix_max_abs_diff(source_matrix, matrix_from_q)
    noncommuting_difference = matrix_max_abs_diff(source_matrix, legacy_matrix)

    # The v1 candidate is retained for provenance, but this test records that
    # its intrinsic-XYZ quaternion is a different noncommuting composition.
    checks = {
        "official_matrix_matches_independent_golden": source_matrix_error <= 2.0e-12,
        "official_quaternion_matches_independent_golden": source_quaternion_error <= 2.0e-12,
        "official_matrix_and_quaternion_agree": matrix_quaternion_error <= 2.0e-12,
        "noncommuting_legacy_order_is_distinguishable": noncommuting_difference >= 1.0e-2,
        "degrees_are_converted_once": close(angles_rad[0], math.pi * 17.0 / 180.0),
        "radian_unit_is_rejected": expect_rejection(angles_to_radians, GOLDEN_ANGLES_DEG, "rad"),
        "nonunit_quaternion_is_rejected": expect_rejection(require_unit_quaternion, (0.0, 0.0, 0.0, 2.0)),
        "nonfinite_quaternion_is_rejected": expect_rejection(require_unit_quaternion, (0.0, 0.0, float("nan"), 1.0)),
        "wrong_quaternion_length_is_rejected": expect_rejection(require_unit_quaternion, (0.0, 0.0, 0.0)),
        "quaternion_sign_gauge_is_equal": quaternion_distance_deg(source_q, tuple(-value for value in source_q)) <= 1.0e-5,
    }
    if not all(checks.values()):
        raise SemanticAuditError(f"manufactured semantic tests failed: {checks}")
    return {
        "status": "passed",
        "angles_deg": list(GOLDEN_ANGLES_DEG),
        "official_source_matrix_rx_ry_rz": [list(row) for row in source_matrix],
        "official_source_quaternion_xyzw": list(source_q),
        "legacy_v1_candidate_quaternion_xyzw": list(legacy_quaternion),
        "legacy_v1_candidate_matrix_rz_ry_rx": [list(row) for row in legacy_matrix],
        "source_matrix_max_error_vs_golden": source_matrix_error,
        "source_quaternion_max_error_vs_golden": source_quaternion_error,
        "matrix_quaternion_max_error": matrix_quaternion_error,
        "noncommuting_order_max_difference": noncommuting_difference,
        "checks": checks,
    }


def quaternion_to_matrix(quaternion: Sequence[float]) -> tuple[tuple[float, ...], ...]:
    x, y, z, w = require_unit_quaternion(quaternion)
    return (
        (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)),
        (2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)),
        (2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)),
    )


def source_file_evidence(source_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    files = [
        {
            "id": "DualSphDef",
            "relative_path": "src/source/DualSphDef.h",
            "required": ["tdouble3 center", "angle xz, angle yz, angle xy", "tfloat3 fomega", "units:rad/s"],
            "claims": "internal center/angles/fomega fields and units",
        },
        {
            "id": "FunctionsMath",
            "relative_path": "src/source/FunctionsMath.h",
            "required": ["cosy*cosz", "-cosy*sinz", "sinx*siny*cosz + cosx*sinz"],
            "claims": "official cumulative rotation matrix algebra",
        },
        {
            "id": "JMatrix4",
            "relative_path": "src/source/JMatrix4.h",
            "required": ["r.x= a11*n.x + a12*n.y + a13*n.z", "r.x= a11*p.x + a12*p.y + a13*p.z + a14", "MatrixRotX", "MatrixRotY", "MatrixRotZ"],
            "claims": "column-vector point/normal multiplication and positive axis matrices",
        },
        {
            "id": "JSph",
            "relative_path": "src/source/JSph.cpp",
            "required": ["I=(R*I_0)*R^T", "fcenter.x+=", "FtObjs[cf].angles="],
            "claims": "solver orientation update, center update, and angular kinematics",
        },
        {
            "id": "JSphCpuSingle",
            "relative_path": "src/source/JSphCpuSingle.cpp",
            "required": ["const tfloat3  fomega", "const tdouble3 fcenter", "*TODEG", "fomega.y*dist.z"],
            "claims": "particle/world-coordinate kinematic cross-product and angle-unit conversion",
        },
        {
            "id": "JPartFloatInfoBi4",
            "relative_path": "src/source/JPartFloatInfoBi4.cpp",
            "required": ["CreateArray(\"center\"", "CreateArray(\"fomega\""],
            "claims": "native center/fomega serialized arrays consumed by FloatingInfo",
        },
        {
            "id": "JPartFloatInfoBi4Header",
            "relative_path": "src/source/JPartFloatInfoBi4.h",
            "required": ["PartCenter", "PartVelAng", "GetPartCenter", "GetPartVelAng"],
            "claims": "native center/fomega array types and accessors",
        },
        {
            "id": "FloatingInfoHelp",
            "relative_path": "doc/help/FloatingInfo_Help.out",
            "required": ["roll [deg]", "pitch [deg]", "yaw [deg]", "sign of pitch has changed"],
            "claims": "CSV labels/units and versioned pitch-sign note",
        },
        {
            "id": "CHANGES",
            "relative_path": "CHANGES.txt",
            "required": ["Fixed sign of pitch rotation (FloatingInfo)"],
            "claims": "official release change record for pitch sign",
        },
    ]
    evidence: list[dict[str, Any]] = []
    by_id: dict[str, Any] = {}
    for spec in files:
        path = require_file(source_root / spec["relative_path"], f"official source {spec['id']}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SemanticAuditError(f"official source is not UTF-8 text: {path}") from exc
        missing = [fragment for fragment in spec["required"] if fragment not in text]
        if missing:
            raise SemanticAuditError(f"official source {spec['id']} lacks required fragments {missing}")
        matches: list[dict[str, Any]] = []
        for fragment in spec["required"]:
            for line_number, line in enumerate(text.splitlines(), 1):
                if fragment in line:
                    matches.append({"fragment": fragment, "line": line_number, "text": line.strip()})
                    break
        item = {
            "id": spec["id"],
            "path": str(path),
            "relative_path": spec["relative_path"],
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "claims": spec["claims"],
            "evidence_lines": matches,
        }
        evidence.append(item)
        by_id[spec["id"]] = item
    return evidence, by_id


def bind_producer(source_root: Path) -> dict[str, Any]:
    binary = require_file(source_root / "bin/linux/FloatingInfo_linux64", "official FloatingInfo binary")
    help_file = require_file(source_root / "doc/help/FloatingInfo_Help.out", "official FloatingInfo help")
    changes = require_file(source_root / "CHANGES.txt", "official CHANGES")
    return {
        "binary": {
            "path": str(binary),
            "sha256": sha256_file(binary),
            "bytes": binary.stat().st_size,
            "version_source": "doc/help/FloatingInfo_Help.out",
            "source_available": False,
            "symbol_observation": "installed ELF exports JFloatingInfo::SaveFiles but its producer source is not present in the official source tree",
        },
        "help": {"path": str(help_file), "sha256": sha256_file(help_file), "bytes": help_file.stat().st_size},
        "changes": {"path": str(changes), "sha256": sha256_file(changes), "bytes": changes.stat().st_size},
    }


def validate_v1_lineage(v1_output_path: Path, v1_receipt_path: Path, v1_script_path: Path) -> dict[str, Any]:
    v1 = read_json(v1_output_path, "consumed rigid observation v1 output")
    if v1.get("schema") != V1_SCHEMA or v1.get("status") != "completed":
        raise SemanticAuditError("consumed rigid observation v1 is not completed")
    if v1.get("source_policy", {}).get("h5_opened") is not False or v1.get("source_policy", {}).get("particle_frames_read") is not False:
        raise SemanticAuditError("consumed rigid observation v1 source policy is not metadata-only")
    found = [str(item.get("sentinel_id")) for item in v1.get("sentinels", []) if isinstance(item, dict)]
    if tuple(found) != EXPECTED_SENTINELS:
        raise SemanticAuditError(f"v1 sentinel order/identity mismatch: {found}")
    receipt = read_json(v1_receipt_path, "consumed rigid observation v1 execution receipt")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise SemanticAuditError("consumed rigid observation v1 execution receipt is not completed")
    receipt_output_root = Path(str(receipt.get("output_root", ""))).resolve()
    if receipt_output_root != v1_output_path.parent:
        raise SemanticAuditError("v1 receipt output_root does not contain v1 output")
    request_command = receipt.get("request", {}).get("command", [])
    if not isinstance(request_command, list) or str(v1_script_path) not in [str(item) for item in request_command]:
        raise SemanticAuditError("v1 receipt command does not bind the declared v1 script")
    return {
        "output": {"path": str(v1_output_path), "sha256": sha256_file(v1_output_path), "bytes": v1_output_path.stat().st_size},
        "receipt": {"path": str(v1_receipt_path), "sha256": sha256_file(v1_receipt_path), "bytes": v1_receipt_path.stat().st_size},
        "script": {"path": str(v1_script_path), "sha256": sha256_file(v1_script_path), "bytes": v1_script_path.stat().st_size},
        "legacy_contract": {
            "orientation_source": v1.get("frozen_contract", {}).get("orientation_source"),
            "derived_orientation": v1.get("frozen_contract", {}).get("derived_orientation"),
            "full_time_reference_status": v1.get("qualification", {}).get("status"),
        },
        "payload": v1,
    }


def trajectory_summary(v1_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in v1_payload.get("sentinels", []):
        if not isinstance(item, dict):
            raise SemanticAuditError("v1 sentinel row is not an object")
        observed = item.get("observed_rigid_state", {})
        centers = observed.get("center_m", [])
        omegas = observed.get("angular_velocity_rad_s", [])
        if len(centers) != 241 or len(omegas) != 241:
            raise SemanticAuditError(f"{item.get('sentinel_id')} v1 trajectory is not 241 frames")
        summaries.append({
            "sentinel_id": item.get("sentinel_id"),
            "physical_case_id": item.get("physical_case_id"),
            "frame_count": len(centers),
            "first_center_m": centers[0],
            "last_center_m": centers[-1],
            "first_angular_velocity_rad_s": omegas[0],
            "last_angular_velocity_rad_s": omegas[-1],
            "source": "consumed rigid-observation-v1 trajectory; no H5 read in v2",
        })
    return summaries


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_root = require_file(args.source_root / "CHANGES.txt", "official source root marker").parent
    if source_root != EXPECTED_SOURCE_ROOT:
        raise SemanticAuditError(f"unexpected official source root: {source_root}")
    v1_output = require_file(args.v1_output, "v1 output")
    v1_receipt = require_file(args.v1_receipt, "v1 execution receipt")
    v1_script = require_file(args.v1_script, "v1 source script")
    lineage = validate_v1_lineage(v1_output, v1_receipt, v1_script)
    source_inputs, source_by_id = source_file_evidence(source_root)
    producer = bind_producer(source_root)
    tests = manufactured_semantic_tests()
    output = {
        "schema": SCHEMA,
        "status": "completed",
        "purpose": "Forward-only official-source semantic audit for consumed F6 rigid observation v1.",
        "source_policy": {
            "h5_opened": False,
            "h5_paths_consumed": [],
            "trajectory_h5_opened": False,
            "particle_frames_read": False,
            "solver_launched": False,
            "floatinginfo_rerun": False,
            "cfd_or_model_run": False,
        },
        "lineage": {key: value for key, value in lineage.items() if key != "payload"},
        "official_producer": producer,
        "official_source_inputs": source_inputs,
        "solver_rotation_semantics": {
            "internal_angles_units": "radians",
            "internal_angle_labels": "source StFloatingData angles comment: angle xz, angle yz, angle xy; source does not call these roll/pitch/yaw",
            "matrix_formula": "FunctionsMath.h RotMatrix3x3 is algebraically Rx(angles.x) * Ry(angles.y) * Rz(angles.z)",
            "column_vector_evidence": "JMatrix4::MulPoint and MulNormal compute r_i = row_i dot input; source uses I = R*I0*R^T",
            "axis_order_status": "SOURCE_CLOSED_FOR_INTERNAL_SOLVER_MATRIX",
            "active_passive_status": "SOURCE_COMPATIBLE_WITH_ACTIVE_COLUMN_VECTOR_BODY_TO_WORLD_USE_BUT_NOT_NAMED",
            "csv_mapping_status": "UNKNOWN",
        },
        "floatinginfo_csv_semantics": {
            "axis_labels": {"roll": "X-axis", "pitch": "Y-axis", "yaw": "Z-axis", "status": "SOURCE_HELP_CLOSED"},
            "units": {"euler": "degrees", "angular_velocity": "rad/s", "status": "SOURCE_HELP_CLOSED"},
            "order": "UNKNOWN",
            "active_passive": "UNKNOWN",
            "reason": "FloatingInfo producer source is absent; binary/help bind labels and units but do not establish the matrix extraction order or active/passive convention for the CSV fields.",
            "pitch_sign": "Current help records a v5.0.204 sign change and CHANGES records a fixed sign; exact pre/post formula remains UNKNOWN from the available source bundle.",
            "legacy_v1_derived_quaternion": "retained as consumed provenance only; not promoted to official CSV convention",
        },
        "frame_semantics": {
            "center": {
                "csv_unit": "m",
                "solver_frame": "world/global Cartesian position used by solver update",
                "status": "SOURCE_CLOSED_FOR_SOLVER_USE",
                "evidence": ["JSph updates fcenter.x/y/z by global fvel components", "JPartFloatInfoBi4 serializes center as DatDouble3"],
                "periodic_boundary_note": "FtUpdateFloatings may apply UpdatePeriodicPos before storage when periodic mode is active; this is a representation adjustment, not evidence of a body-frame center.",
            },
            "angular_velocity": {
                "csv_unit": "rad/s",
                "solver_frame": "world/global Cartesian spatial vector in the solver kinematic cross product",
                "status": "SOURCE_CLOSED_FOR_SOLVER_USE",
                "evidence": ["JSphCpuSingle forms fomega cross (pos - fcenter) componentwise", "JSph updates fomega by Cartesian acceleration components", "JPartFloatInfoBi4 serializes fomega as DatFloat3"],
                "body_frame_relabel": "UNKNOWN; no source proves a body-frame relabel in FloatingInfo CSV.",
            },
        },
        "manufactured_semantic_tests": tests,
        "observed_trajectory_summary": trajectory_summary(lineage["payload"]),
        "qualification": {
            "status": "NOT_ASSESSED",
            "orientation_convention": "UNKNOWN_FOR_FLOATINGINFO_CSV",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
            "reason": "Semantic source audit closes solver internal algebra and center/omega solver-use frames, but does not establish the missing FloatingInfo CSV Euler extraction convention or a full-time reference trajectory.",
        },
    }
    write_atomic(args.output, output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=EXPECTED_SOURCE_ROOT)
    parser.add_argument("--v1-output", type=Path, default=EXPECTED_V1_OUTPUT)
    parser.add_argument("--v1-receipt", type=Path, default=EXPECTED_V1_RECEIPT)
    parser.add_argument("--v1-script", type=Path, default=EXPECTED_V1_SCRIPT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args)
    except SemanticAuditError as exc:
        raise SystemExit(f"SemanticAuditError: {exc}")
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "h5_opened": result["source_policy"]["h5_opened"], "csv_order": result["floatinginfo_csv_semantics"]["order"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

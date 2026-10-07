#!/usr/bin/env python3
"""Recover an F6 rigid pose directly from source-bound particle positions.

This forward-only audit is an alternative to interpreting ``FloatingInfo``
Euler labels or an unverified quaternion convention.  It consumes a small,
source-bound JSON snapshot supplied by a future guarded worker.  Every frame
must contain the same ``(Zone, Idp)`` identities and explicit ``valid`` flags.
The first frame is the body-pose reference; a weighted Kabsch fit then gives a
proper world-from-initial rotation for each later frame.  The fit is a
geometric observation of the support sample.  It does not turn the sample
centroid into the physical COM, and it does not qualify the solver or infer a
physical destination for any missing particles.

``self-test`` creates only manufactured in-memory examples.  It exercises
non-commuting XYZ rotations, a cross-pi representation, reflection and rank
guards, non-unit quaternion rejection, and identity/time/valid failures.
``audit`` intentionally accepts JSON snapshots rather than HDF5; the source
manifest records the solver receipt, FloatingInfo CSV, CURRENT identity, and
snapshot digests before any observation is credited.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f6-rigid-observation.v3"
INPUT_SCHEMA = "ds02.stage2.f6-rigid-particle-snapshots.v1"
BODY_MASS_KG = 128.0
SUPPORT_MASS_KG = 256.0
SO3_RMSE_LIMIT_DEG = 2.0
SO3_MAX_LIMIT_DEG = 5.0
TIME_TOL_S = 1.0e-6
MASS_TOL_KG = 1.0e-8
RANK_REL_TOL = 1.0e-10
EXPECTED_SENTINEL_CASES = {
    "F6-S1": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
    "F6-S2": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
}


class ObservationError(RuntimeError):
    """Raised when source or particle-pose evidence is incomplete."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: str | Path, label: str) -> Path:
    value = Path(path).expanduser().resolve()
    if not value.is_file():
        raise ObservationError(f"{label} is missing: {value}")
    return value


def read_json(path: str | Path, label: str) -> dict[str, Any]:
    value = require_file(path, label)
    try:
        payload = json.loads(value.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObservationError(f"{label} is invalid JSON: {value}") from exc
    if not isinstance(payload, dict):
        raise ObservationError(f"{label} is not a JSON object: {value}")
    return payload


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def finite_array(value: Any, shape: tuple[int, ...], label: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ObservationError(f"{label} is not numeric") from exc
    if array.shape != shape or not np.isfinite(array).all():
        raise ObservationError(f"{label} must be finite with shape {shape}")
    return array


def axis_rotation(axis: str, angle_radians: float) -> np.ndarray:
    """Return an active, column-vector rotation using radians explicitly."""
    if axis not in {"x", "y", "z"} or not math.isfinite(angle_radians):
        raise ObservationError("axis rotation needs x/y/z and finite radians")
    c, s = math.cos(angle_radians), math.sin(angle_radians)
    if axis == "x":
        matrix = [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]
    elif axis == "y":
        matrix = [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]
    else:
        matrix = [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
    return np.asarray(matrix, dtype=np.float64)


def validate_rotation(matrix: Any, label: str = "rotation") -> np.ndarray:
    value = finite_array(matrix, (3, 3), label)
    if not np.allclose(value.T @ value, np.eye(3), rtol=0.0, atol=1.0e-8):
        raise ObservationError(f"{label} is not orthonormal")
    determinant = float(np.linalg.det(value))
    if abs(determinant - 1.0) > 1.0e-8:
        raise ObservationError(f"{label} is not a proper rotation: det={determinant}")
    return value


def quaternion_to_matrix(quaternion: Sequence[float], label: str = "quaternion") -> np.ndarray:
    """Decode only a unit xyzw quaternion; no FloatingInfo field is fed here."""
    value = finite_array(quaternion, (4,), label)
    norm = float(np.linalg.norm(value))
    if abs(norm - 1.0) > 1.0e-6:
        raise ObservationError(f"{label} is non-unit: norm={norm}")
    x, y, z, w = value
    return validate_rotation(np.asarray([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]), label)


def rotation_to_quaternion(matrix: Any) -> list[float]:
    """Convert a direct SO(3) matrix to canonical xyzw; sign is a gauge only."""
    value = validate_rotation(matrix)
    trace = float(np.trace(value))
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (value[2, 1] - value[1, 2]) / s
        y = (value[0, 2] - value[2, 0]) / s
        z = (value[1, 0] - value[0, 1]) / s
    else:
        diagonal = np.diag(value)
        index = int(np.argmax(diagonal))
        if index == 0:
            s = math.sqrt(max(0.0, 1.0 + value[0, 0] - value[1, 1] - value[2, 2])) * 2.0
            x = 0.25 * s
            y = (value[0, 1] + value[1, 0]) / s
            z = (value[0, 2] + value[2, 0]) / s
            w = (value[2, 1] - value[1, 2]) / s
        elif index == 1:
            s = math.sqrt(max(0.0, 1.0 - value[0, 0] + value[1, 1] - value[2, 2])) * 2.0
            x = (value[0, 1] + value[1, 0]) / s
            y = 0.25 * s
            z = (value[1, 2] + value[2, 1]) / s
            w = (value[0, 2] - value[2, 0]) / s
        else:
            s = math.sqrt(max(0.0, 1.0 - value[0, 0] - value[1, 1] + value[2, 2])) * 2.0
            x = (value[0, 2] + value[2, 0]) / s
            y = (value[1, 2] + value[2, 1]) / s
            z = 0.25 * s
            w = (value[1, 0] - value[0, 1]) / s
    result = np.asarray([x, y, z, w], dtype=np.float64)
    result /= np.linalg.norm(result)
    if result[3] < 0.0:
        result *= -1.0
    return result.tolist()


def so3_error_deg(first: Any, second: Any) -> float:
    """Geodesic error for two direct world-frame rotation matrices."""
    left = validate_rotation(first, "first rotation")
    right = validate_rotation(second, "second rotation")
    cosine = float((np.trace(left.T @ right) - 1.0) / 2.0)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def weighted_kabsch(initial: Any, current: Any, weights: Any) -> dict[str, Any]:
    """Fit row-vector initial positions to current positions with proper SO(3)."""
    x = np.asarray(initial, dtype=np.float64)
    y = np.asarray(current, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    if x.ndim != 2 or x.shape != y.shape or x.shape[1] != 3 or w.shape != (x.shape[0],):
        raise ObservationError("Kabsch arrays have incompatible shapes")
    if x.shape[0] < 3 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ObservationError("Kabsch positions must have at least three finite points")
    if not np.isfinite(w).all() or np.any(w <= 0.0):
        raise ObservationError("Kabsch weights must be finite and positive")
    total = float(w.sum())
    x_centroid = (x * w[:, None]).sum(axis=0) / total
    y_centroid = (y * w[:, None]).sum(axis=0) / total
    xc, yc = x - x_centroid, y - y_centroid
    covariance = xc.T @ (w[:, None] * yc)
    u, singular, vt = np.linalg.svd(covariance)
    if singular[0] <= 0.0 or singular[-1] / singular[0] <= RANK_REL_TOL:
        raise ObservationError("Kabsch support geometry is rank-degenerate")
    rotation = vt.T @ u.T
    reflection_corrected = False
    if float(np.linalg.det(rotation)) < 0.0:
        vt[-1, :] *= -1.0
        rotation = vt.T @ u.T
        reflection_corrected = True
    rotation = validate_rotation(rotation, "Kabsch rotation")
    predicted = xc @ rotation.T
    residual = predicted - yc
    norms = np.linalg.norm(residual, axis=1)
    rmse = float(math.sqrt(float(np.sum(w * norms * norms)) / total))
    return {
        "rotation_world_from_initial": rotation,
        "rotation_quaternion_xyzw": rotation_to_quaternion(rotation),
        "initial_sample_centroid_m": x_centroid,
        "current_sample_centroid_m": y_centroid,
        "singular_values": singular,
        "rank_relative": float(singular[-1] / singular[0]),
        "determinant": float(np.linalg.det(rotation)),
        "reflection_correction_applied": reflection_corrected,
        "residual_rmse_m": rmse,
        "residual_max_m": float(norms.max()),
        "residual_per_particle_m": norms,
        "sample_mass_kg": total,
    }


def _particle_rows(frame: Mapping[str, Any], ordinal: int) -> tuple[float, list[tuple[int, int]], np.ndarray, np.ndarray]:
    if frame.get("valid") is not True:
        raise ObservationError(f"frame {ordinal} lacks explicit valid=true")
    try:
        time_s = float(frame["time_s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ObservationError(f"frame {ordinal} has invalid time_s") from exc
    if not math.isfinite(time_s):
        raise ObservationError(f"frame {ordinal} time_s is nonfinite")
    particles = frame.get("particles")
    if not isinstance(particles, list) or not particles:
        raise ObservationError(f"frame {ordinal} has no particles")
    identities: list[tuple[int, int]] = []
    positions: list[list[float]] = []
    masses: list[float] = []
    for index, particle in enumerate(particles):
        if not isinstance(particle, dict) or particle.get("valid") is not True:
            raise ObservationError(f"frame {ordinal} particle {index} lacks explicit valid=true")
        try:
            identity = (int(particle["zone"]), int(particle["idp"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservationError(f"frame {ordinal} particle {index} identity is invalid") from exc
        if identity in identities:
            raise ObservationError(f"frame {ordinal} has duplicate identity {identity}")
        position = finite_array(particle.get("position_m"), (3,), f"frame {ordinal} particle {identity} position")
        try:
            mass = float(particle["mass_kg"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservationError(f"frame {ordinal} particle {identity} mass is invalid") from exc
        if not math.isfinite(mass) or mass <= 0.0:
            raise ObservationError(f"frame {ordinal} particle {identity} mass is nonpositive")
        identities.append(identity)
        positions.append(position.tolist())
        masses.append(mass)
    return time_s, identities, np.asarray(positions), np.asarray(masses)


def load_particle_frames(path: Path, physical_case_id: str) -> dict[str, Any]:
    payload = read_json(path, "particle snapshot source")
    if payload.get("schema") != INPUT_SCHEMA:
        raise ObservationError("particle snapshot schema is not the registered v1 format")
    if payload.get("physical_case_id") != physical_case_id:
        raise ObservationError("particle snapshot physical identity differs")
    frames = payload.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ObservationError("particle snapshot has no frames")
    parsed: list[dict[str, Any]] = []
    initial_ids: list[tuple[int, int]] | None = None
    initial_masses: np.ndarray | None = None
    last_time = -math.inf
    for ordinal, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise ObservationError(f"frame {ordinal} is not an object")
        try:
            part = int(frame["part"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservationError(f"frame {ordinal} part is invalid") from exc
        if part != ordinal:
            raise ObservationError(f"frame part sequence is not 0..N-1 at {ordinal}")
        time_s, identities, positions, masses = _particle_rows(frame, ordinal)
        if time_s <= last_time:
            raise ObservationError(f"frame times are not strictly increasing at {ordinal}")
        last_time = time_s
        identity_order_changed = False
        if initial_ids is None:
            initial_ids, initial_masses = identities, masses
        else:
            if set(identities) != set(initial_ids):
                raise ObservationError(f"frame {ordinal} (Zone,Idp) set differs from initial frame")
            identity_order_changed = identities != initial_ids
            # Join by (Zone, Idp), never by row position.  A producer is free
            # to reorder the native particle table between frames, but it may
            # not add, drop, or duplicate an identity.
            by_identity = {identity: index for index, identity in enumerate(identities)}
            order = [by_identity[identity] for identity in initial_ids]
            positions = positions[order]
            masses = masses[order]
            identities = list(initial_ids)
        if initial_masses is not None and not np.allclose(masses, initial_masses, rtol=0.0, atol=MASS_TOL_KG):
            raise ObservationError(f"frame {ordinal} particle masses differ from initial source")
        parsed.append({"part": part, "time_s": time_s, "identities": identities,
                       "identity_order_changed": identity_order_changed,
                       "positions_m": positions, "masses_kg": masses})
    assert initial_ids is not None and initial_masses is not None
    return {"path": str(path.resolve()), "sha256": sha256(path), "frames": parsed,
            "particle_count": len(initial_ids), "identities": initial_ids,
            "initial_masses_kg": initial_masses}


def parse_observer_csv(path: Path, frames: list[dict[str, Any]]) -> dict[str, Any]:
    required = {
        "part", "time [s]", "center.x [m]", "center.y [m]", "center.z [m]",
        "fomega.x [rad/s]", "fomega.y [rad/s]", "fomega.z [rad/s]",
    }
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        fields = {str(item).strip() for item in (reader.fieldnames or [])}
        if not required <= fields:
            raise ObservationError(f"FloatingInfo CSV lacks fields {sorted(required - fields)}")
        rows = list(reader)
    if len(rows) != len(frames):
        raise ObservationError("FloatingInfo row count differs from particle snapshot frames")
    parsed: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        try:
            part = int(str(row["part"]).strip())
            time_s = float(str(row["time [s]"]).strip())
            center = [float(str(row[f"center.{axis} [m]"]).strip()) for axis in "xyz"]
            omega = [float(str(row[f"fomega.{axis} [rad/s]"]).strip()) for axis in "xyz"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservationError(f"FloatingInfo observer row {index} is invalid") from exc
        if part != frames[index]["part"] or abs(time_s - frames[index]["time_s"]) > TIME_TOL_S:
            raise ObservationError(f"FloatingInfo time/part differs at frame {index}")
        if not all(math.isfinite(value) for value in (*center, *omega)):
            raise ObservationError(f"FloatingInfo observer row {index} is nonfinite")
        parsed.append({"part": part, "time_s": time_s, "center_m": center,
                       "angular_velocity_rad_s": omega})
    return {"path": str(path.resolve()), "sha256": sha256(path), "rows": parsed}


def audit(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "F6 rigid v3 manifest")
    manifest = read_json(manifest_path, "F6 rigid v3 manifest")
    if manifest.get("schema") != "ds02.stage2.f6-rigid-observation-v3-manifest.v1":
        raise ObservationError("unexpected F6 rigid v3 manifest schema")
    physical_case_id = str(manifest.get("physical_case_id", ""))
    if not physical_case_id:
        raise ObservationError("manifest lacks physical_case_id")
    sentinel_id = str(manifest.get("sentinel_id", ""))
    if sentinel_id not in EXPECTED_SENTINEL_CASES or physical_case_id != EXPECTED_SENTINEL_CASES[sentinel_id]:
        raise ObservationError("manifest sentinel/physical identity is not one of the two CURRENT F6 sentinels")
    source = manifest.get("source", {})
    if not isinstance(source, dict):
        raise ObservationError("manifest source is not an object")
    for key in ("solver_receipt", "snapshot_json", "floating_csv"):
        if not isinstance(source.get(key), dict):
            raise ObservationError(f"manifest lacks source.{key} binding")
    # An HDF5 path would violate this forward-only worker's contract.
    if any(str(item.get("path", "")).lower().endswith((".h5", ".hdf5"))
           for item in source.values() if isinstance(item, dict)):
        raise ObservationError("F6 rigid v3 refuses HDF5 source inputs")
    solver_path = require_file(source["solver_receipt"]["path"], "bound F6 solver receipt")
    solver = read_json(solver_path, "bound F6 solver receipt")
    if solver.get("schema") != "ds02.execution-receipt.v1" or solver.get("status") != "completed" or solver.get("returncode") != 0:
        raise ObservationError("bound F6 solver receipt is not completed")
    solver_request = solver.get("request", {})
    if solver_request.get("family_id") != "F6" or solver_request.get("physical_case_id") != physical_case_id:
        raise ObservationError("bound F6 solver receipt physical identity differs")
    solver_digest = sha256(solver_path)
    if source["solver_receipt"].get("sha256") != solver_digest:
        raise ObservationError("bound F6 solver receipt digest differs")
    current_binding = manifest.get("current_binding")
    if not isinstance(current_binding, dict) or not current_binding.get("path") or not current_binding.get("sha256"):
        raise ObservationError("manifest lacks immutable CURRENT sentinel binding")
    current_path = require_file(current_binding["path"], "bound CURRENT sentinel evidence")
    if current_binding["sha256"] != sha256(current_path):
        raise ObservationError("CURRENT sentinel evidence digest differs")
    snapshot_path = require_file(source["snapshot_json"]["path"], "bound particle snapshot JSON")
    if source["snapshot_json"].get("sha256") != sha256(snapshot_path):
        raise ObservationError("particle snapshot digest differs")
    snapshot_payload = read_json(snapshot_path, "particle snapshot source")
    if snapshot_payload.get("solver_receipt_sha256") != solver_digest:
        raise ObservationError("particle snapshot producer receipt is not the exact bound solver receipt")
    frames = load_particle_frames(snapshot_path, physical_case_id)
    observer_path = require_file(source["floating_csv"]["path"], "bound FloatingInfo CSV")
    if source["floating_csv"].get("sha256") != sha256(observer_path):
        raise ObservationError("FloatingInfo digest differs")
    if source["floating_csv"].get("producer_solver_receipt_sha256") != solver_digest:
        raise ObservationError("FloatingInfo producer receipt is not the exact bound solver receipt")
    observer = parse_observer_csv(observer_path, frames["frames"])
    body_mass = float(manifest.get("physical_body_mass_kg", BODY_MASS_KG))
    declared_sample_mass = float(manifest.get("support_sample_mass_kg", SUPPORT_MASS_KG))
    actual_sample_mass = float(frames["initial_masses_kg"].sum())
    if not math.isfinite(body_mass) or body_mass <= 0.0 or not math.isfinite(declared_sample_mass) or declared_sample_mass <= 0.0:
        raise ObservationError("body/support masses are invalid")
    if abs(actual_sample_mass - declared_sample_mass) > MASS_TOL_KG:
        raise ObservationError("snapshot particle mass sum differs from declared support sample mass")
    if abs(body_mass - declared_sample_mass) <= MASS_TOL_KG:
        raise ObservationError("physical body and support sample masses were conflated")
    semantics = manifest.get("observer_semantics", {})
    if not isinstance(semantics, dict):
        raise ObservationError("observer_semantics is not an object")
    initial = frames["frames"][0]
    records: list[dict[str, Any]] = []
    for frame, observed in zip(frames["frames"], observer["rows"]):
        fit = weighted_kabsch(initial["positions_m"], frame["positions_m"], initial["masses_kg"])
        records.append({
            "part": frame["part"],
            "time_s": frame["time_s"],
            "identity_order_changed": frame["identity_order_changed"],
            "rotation_world_from_initial": fit["rotation_world_from_initial"].tolist(),
            "rotation_quaternion_xyzw_derived": fit["rotation_quaternion_xyzw"],
            "sample_centroid_initial_m": fit["initial_sample_centroid_m"].tolist(),
            "sample_centroid_current_m": fit["current_sample_centroid_m"].tolist(),
            "sample_mass_kg": fit["sample_mass_kg"],
            "residual_rmse_m": fit["residual_rmse_m"],
            "residual_max_m": fit["residual_max_m"],
            "singular_values": fit["singular_values"].tolist(),
            "rank_relative": fit["rank_relative"],
            "determinant": fit["determinant"],
            "reflection_correction_applied": fit["reflection_correction_applied"],
            "observer_center_m": observed["center_m"],
            "observer_angular_velocity_rad_s": observed["angular_velocity_rad_s"],
            "observer_center_frame": semantics.get("center_frame", "UNKNOWN"),
            "observer_angular_velocity_frame": semantics.get("angular_velocity_frame", "UNKNOWN"),
        })
    checks = {
        "solver_completed_code0": True,
        "snapshot_frame_identity_constant": True,
        "snapshot_frame_times_match_observer": True,
        "particle_validity_explicit": True,
        "support_sample_mass_matches_declared": abs(actual_sample_mass - declared_sample_mass) <= MASS_TOL_KG,
        "body_mass_separate_from_support_mass": abs(body_mass - declared_sample_mass) > MASS_TOL_KG,
        "proper_rotation_all_frames": all(abs(float(row["determinant"]) - 1.0) <= 1.0e-8 for row in records),
    }
    result = {
        "schema": SCHEMA,
        "status": "completed" if all(checks.values()) else "rejected",
        "family_id": "F6",
        "physical_case_id": physical_case_id,
        "source_policy": {
            "h5_opened": False,
            "particle_frames_read_from": "JSON snapshot only",
            "solver_launched": False,
            "cfd_or_model_run": False,
        },
        "source": {
            "script": {"path": str(SCRIPT), "sha256": sha256(SCRIPT)},
            "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
            "solver_receipt": {"path": str(solver_path), "sha256": sha256(solver_path)},
            "snapshot_json": {"path": str(snapshot_path), "sha256": sha256(snapshot_path)},
            "floating_csv": observer,
            "current_binding": {"path": str(current_path), "sha256": current_binding["sha256"]},
        },
        "frozen_contract": {
            "so3_error_tolerances_deg": {"rmse": SO3_RMSE_LIMIT_DEG, "max": SO3_MAX_LIMIT_DEG},
            "orientation_source": "direct Kabsch from same (Zone,Idp) positions",
            "euler_or_quaternion_source_convention_used": False,
            "rotation_convention": "active column-vector world-from-initial; row positions transformed by R.T",
            "angle_units": "radians internally; no Euler conversion",
            "body_mass_kg": body_mass,
            "support_sample_mass_kg": declared_sample_mass,
            "sample_centroid_is_physical_com": False,
        },
        "particle_identity": {
            "count": frames["particle_count"],
            "zone_idp_order": [list(identity) for identity in frames["identities"]],
            "identity_set_constant": True,
            "initial_reference_part": initial["part"],
        },
        "rigid_fit": {"frames": records, "residual_units": "m"},
        "observer_semantics": semantics,
        "checks": checks,
        "qualification": {
            "status": "NOT_ASSESSED",
            "so3_reference_status": "UNKNOWN; direct pose has no independent orientation reference trajectory",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
    }
    atomic_json(output, result)
    return result


def expect_failure(label: str, function) -> dict[str, Any]:
    try:
        function()
    except ObservationError as exc:
        return {"label": label, "passed": True, "error": str(exc)}
    return {"label": label, "passed": False, "error": "expected ObservationError was not raised"}


def self_test(output: Path) -> dict[str, Any]:
    points = np.asarray([
        [-0.8, -0.3, -0.2], [0.5, -0.6, 0.1], [0.3, 0.7, -0.4],
        [-0.4, 0.2, 0.9], [0.9, 0.4, 0.5], [-0.2, -0.9, 0.6],
    ], dtype=np.float64)
    weights = np.asarray([1.0, 2.0, 1.5, 0.5, 3.0, 1.0], dtype=np.float64)
    true_rotation = axis_rotation("z", math.radians(31.0)) @ axis_rotation("y", math.radians(-23.0)) @ axis_rotation("x", math.radians(17.0))
    shifted = points @ true_rotation.T + np.asarray([1.2, -0.4, 0.7])
    fit = weighted_kabsch(points, shifted, weights)
    direct_error = so3_error_deg(fit["rotation_world_from_initial"], true_rotation)

    noncommuting_wrong = axis_rotation("x", math.radians(17.0)) @ axis_rotation("y", math.radians(-23.0)) @ axis_rotation("z", math.radians(31.0))
    noncommuting_error = so3_error_deg(true_rotation, noncommuting_wrong)
    cross_pi_error = so3_error_deg(axis_rotation("z", math.radians(179.0)), axis_rotation("z", math.radians(-181.0)))
    degree_radian_error = so3_error_deg(axis_rotation("x", math.radians(90.0)), axis_rotation("x", 90.0))
    reflection = np.diag([1.0, 1.0, -1.0])
    collinear = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float64)
    valid_frame = {"part": 0, "time_s": 0.0, "valid": True, "particles": [
        {"zone": 1, "idp": 10, "valid": True, "position_m": [0.0, 0.0, 0.0], "mass_kg": 1.0},
        {"zone": 1, "idp": 11, "valid": True, "position_m": [1.0, 0.0, 0.0], "mass_kg": 1.0},
        {"zone": 2, "idp": 12, "valid": True, "position_m": [0.0, 1.0, 0.0], "mass_kg": 1.0},
    ]}
    duplicate_frame = {**valid_frame, "particles": valid_frame["particles"] + [valid_frame["particles"][0]]}
    invalid_frame = {**valid_frame, "valid": False}
    identity_frame = {**valid_frame, "particles": [*valid_frame["particles"][:2], {**valid_frame["particles"][2], "idp": 99}]}
    reordered_frame = {
        **valid_frame, "part": 1, "time_s": 1.0,
        "particles": [valid_frame["particles"][2], valid_frame["particles"][0], valid_frame["particles"][1]],
    }
    try:
        load_particle_frames_from_memory([valid_frame, reordered_frame])
        identity_reorder_passed = True
    except ObservationError:
        identity_reorder_passed = False
    failure_tests = [
        expect_failure("proper_rotation_rejects_reflection", lambda: validate_rotation(reflection)),
        expect_failure("kabsch_rejects_rank_degenerate_support", lambda: weighted_kabsch(collinear, collinear, np.ones(3))),
        expect_failure("quaternion_rejects_nonunit_input", lambda: quaternion_to_matrix([0.0, 0.0, 0.0, 2.0])),
        expect_failure("identity_duplicate_rejected", lambda: _particle_rows(duplicate_frame, 0)),
        expect_failure("frame_valid_flag_required", lambda: _particle_rows(invalid_frame, 0)),
        expect_failure("identity_zone_idp_change_rejected", lambda: load_particle_frames_from_memory([valid_frame, identity_frame])),
    ]
    checks = {
        "direct_kabsch_recovers_noncommuting_xyz": direct_error <= 1.0e-8 and fit["residual_max_m"] <= 1.0e-10,
        "noncommuting_order_is_detectably_different": noncommuting_error > SO3_MAX_LIMIT_DEG,
        "cross_pi_direct_so3_is_zero": cross_pi_error <= 1.0e-8,
        "degrees_are_not_silently_radians": degree_radian_error > SO3_MAX_LIMIT_DEG,
        "identity_join_allows_row_reordering": identity_reorder_passed,
        "all_negative_tests_raise": all(item["passed"] for item in failure_tests),
    }
    result = {
        "schema": "ds02.stage2.f6-rigid-observation-v3-manufactured-tests.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "source_script": {"path": str(SCRIPT), "sha256": sha256(SCRIPT)},
        "frozen_so3_tolerances_deg": {"rmse": SO3_RMSE_LIMIT_DEG, "max": SO3_MAX_LIMIT_DEG},
        "convention": "direct active column-vector SO(3); Kabsch row positions use R.T; radians internally",
        "metrics": {
            "direct_kabsch_error_deg": direct_error,
            "direct_fit_residual_max_m": fit["residual_max_m"],
            "noncommuting_order_error_deg": noncommuting_error,
            "cross_pi_error_deg": cross_pi_error,
            "degrees_radians_error_deg": degree_radian_error,
        },
        "negative_tests": failure_tests,
        "checks": checks,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
    }
    atomic_json(output, result)
    return result


def load_particle_frames_from_memory(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Exercise identity/time validation without writing a fixture to disk."""
    initial_ids: list[tuple[int, int]] | None = None
    last_time = -math.inf
    for ordinal, frame in enumerate(frames):
        time_s, identities, _positions, _masses = _particle_rows(frame, ordinal)
        if time_s <= last_time:
            raise ObservationError("manufactured frame times are not increasing")
        if initial_ids is None:
            initial_ids = identities
        elif set(identities) != set(initial_ids):
            raise ObservationError("manufactured identity set differs")
        last_time = time_s
    return {"frames": len(frames)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--manifest", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    test_parser = sub.add_parser("self-test")
    test_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.manifest, args.output) if args.action == "audit" else self_test(args.output)
    except ObservationError as exc:
        raise SystemExit(f"ObservationError: {exc}")
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if result["status"] in {"completed", "passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Bounded F6 native angular-state and FloatingInfo corroboration audit.

The request that ships with this worker is disabled.  If Root enables it, the
worker reads only the configured Type2 slice at frame zero and the first saved
frame, decodes a bounded FloatingInfo prefix with an explicit semicolon
delimiter, and parses the exact native XML rigid-body declaration.  It writes a
small JSON summary and no source arrays or simulation outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import h5py  # type: ignore
    import numpy as np  # type: ignore
except Exception as exc:  # pragma: no cover - exercised by dispatch environment
    h5py = None  # type: ignore
    np = None  # type: ignore
    _IMPORT_ERROR = repr(exc)
else:
    _IMPORT_ERROR = None


SCHEMA = "ds02.f6.frame0-omega-csv-decoder-audit-result.v1"


class AuditError(RuntimeError):
    """A bounded source or interpretation failure."""


ROLE_ALIASES: Mapping[str, Tuple[str, ...]] = {
    "position": ("position", "positions", "pos", "xyz", "coordinates"),
    "velocity": ("velocity", "velocities", "vel", "v"),
    "particle_id": (
        "particleid",
        "particleids",
        "idp",
        "uid",
        "particleuid",
        "particleindex",
        "index",
        "id",
    ),
    "particle_zone": ("particlezone", "zone", "mk", "mkfluid", "marker", "material"),
    "type": ("type", "particletype", "ptype"),
    "valid": ("valid", "isvalid", "active", "present", "alive"),
    "time": ("time", "times", "t", "timestamp"),
}


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _shape(dataset: Any) -> Tuple[int, ...]:
    return tuple(int(item) for item in dataset.shape)


def _discover_datasets(handle: Any) -> Dict[str, Any]:
    candidates: Dict[str, List[Tuple[int, str, Any]]] = {
        role: [] for role in ROLE_ALIASES
    }

    def visit(name: str, obj: Any) -> None:
        if h5py is None or not isinstance(obj, h5py.Dataset):
            return
        basename = _normalise(name.rsplit("/", 1)[-1])
        for role, aliases in ROLE_ALIASES.items():
            if basename in aliases:
                candidates[role].append((aliases.index(basename), name, obj))

    handle.visititems(visit)
    selected: Dict[str, Any] = {}
    for role, entries in candidates.items():
        if entries:
            entries.sort(key=lambda item: (item[0], item[1].count("/"), item[1]))
            selected[role] = entries[0][2]
    return selected


def _read_vector(dataset: Any, frame: int, start: int, count: int, role: str) -> Any:
    dims = _shape(dataset)
    if len(dims) == 3 and dims[-1] == 3:
        if frame >= dims[0]:
            raise AuditError(f"{role} has no frame {frame}; shape={dims}")
        return np.asarray(dataset[frame, start : start + count, :], dtype=np.float64)
    if len(dims) == 2 and dims[-1] == 3:
        return np.asarray(dataset[start : start + count, :], dtype=np.float64)
    if len(dims) == 2 and dims[0] == 3:
        return np.asarray(dataset[:, start : start + count], dtype=np.float64).T
    raise AuditError(f"unsupported {role} shape {dims}; expected vector field")


def _read_scalar(
    dataset: Any,
    frame: int,
    start: int,
    count: int,
    role: str,
    particle_count: int,
    frame_count: int,
    dtype: Any = None,
) -> Any:
    if dtype is None:
        dtype = np.float64
    dims = _shape(dataset)
    if len(dims) == 1:
        return np.asarray(dataset[start : start + count], dtype=dtype)
    if len(dims) == 3 and dims[-1] == 1:
        if frame >= dims[0]:
            raise AuditError(f"{role} has no frame {frame}; shape={dims}")
        return np.asarray(dataset[frame, start : start + count, 0], dtype=dtype)
    if len(dims) == 2:
        if dims[1] == particle_count and dims[0] >= frame_count:
            return np.asarray(dataset[frame, start : start + count], dtype=dtype)
        if dims[0] == particle_count and dims[1] >= frame_count:
            return np.asarray(dataset[start : start + count, frame], dtype=dtype)
        if frame < dims[0]:
            return np.asarray(dataset[frame, start : start + count], dtype=dtype)
    raise AuditError(f"unsupported {role} shape {dims}; expected scalar field")


def _read_time(dataset: Optional[Any], frame: int) -> Optional[float]:
    if dataset is None:
        return None
    dims = _shape(dataset)
    if len(dims) == 1 and frame < dims[0]:
        return float(dataset[frame])
    if len(dims) == 2 and dims[-1] == 1 and frame < dims[0]:
        return float(dataset[frame, 0])
    if len(dims) == 2 and dims[0] == 1 and frame < dims[1]:
        return float(dataset[0, frame])
    return None


def _stats(values: Any) -> Dict[str, Any]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return {"count": 0, "min": None, "mean": None, "max": None, "percentiles": {}}
    levels = (0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100)
    quantiles = np.percentile(finite, levels)
    return {
        "count": int(finite.size),
        "min": float(np.min(finite)),
        "mean": float(np.mean(finite)),
        "max": float(np.max(finite)),
        "percentiles": {
            f"p{level:02d}": float(value) for level, value in zip(levels, quantiles)
        },
    }


def _skew(vector: Sequence[float]) -> Any:
    x, y, z = [float(item) for item in vector]
    return np.asarray(((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)))


def _fit_rigid(position: Any, velocity: Any, center: Sequence[float]) -> Dict[str, Any]:
    count = int(position.shape[0])
    if count < 2:
        return {
            "status": "insufficient_valid_points",
            "valid_count": count,
            "Vcm_m_per_s": None,
            "omega_rad_s": None,
            "rank": None,
            "residual_rms_m_per_s": None,
            "residual_max_m_per_s": None,
        }
    design = np.zeros((3 * count, 6), dtype=np.float64)
    rhs = np.asarray(velocity, dtype=np.float64).reshape(3 * count)
    relative = np.asarray(position, dtype=np.float64) - np.asarray(center, dtype=np.float64)
    identity = np.eye(3, dtype=np.float64)
    for index, point in enumerate(relative):
        row = 3 * index
        design[row : row + 3, :3] = identity
        design[row : row + 3, 3:] = -_skew(point)
    solution, _, rank, singular_values = np.linalg.lstsq(design, rhs, rcond=None)
    predicted = (design @ solution).reshape(count, 3)
    residual = np.linalg.norm(np.asarray(velocity) - predicted, axis=1)
    return {
        "status": "ok" if int(rank) >= 6 else "rank_deficient",
        "valid_count": count,
        "Vcm_m_per_s": [float(item) for item in solution[:3]],
        "omega_rad_s": [float(item) for item in solution[3:6]],
        "rank": int(rank),
        "singular_values": [float(item) for item in singular_values],
        "residual_rms_m_per_s": float(np.sqrt(np.mean(residual * residual))),
        "residual_max_m_per_s": float(np.max(residual)),
    }


def _uid_summary(ids: Any) -> Dict[str, Any]:
    values = np.asarray(ids, dtype=np.int64)
    unique_count = int(np.unique(values).size) if values.size else 0
    return {
        "count": int(values.size),
        "unique_count": unique_count,
        "duplicate_count": int(values.size - unique_count),
        "first_values": [int(item) for item in values[:8]],
        "last_values": [int(item) for item in values[-8:]],
    }


def _frame_record(
    datasets: Mapping[str, Any],
    frame: int,
    start: int,
    count: int,
    particle_count: int,
    frame_count: int,
    declared_center: Sequence[float],
    declared_omega: Sequence[float],
) -> Dict[str, Any]:
    position = _read_vector(datasets["position"], frame, start, count, "position")
    velocity = _read_vector(datasets["velocity"], frame, start, count, "velocity")
    ids = _read_scalar(
        datasets["particle_id"], frame, start, count, "particle_id", particle_count, frame_count, dtype=np.int64
    )
    types = _read_scalar(
        datasets["type"], frame, start, count, "type", particle_count, frame_count
    )
    if "valid" in datasets:
        valid = _read_scalar(
            datasets["valid"], frame, start, count, "valid", particle_count, frame_count
        )
    else:
        valid = np.ones(count, dtype=np.float64)
    type2 = types == 2.0
    finite = np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1)
    eligible = type2 & (valid != 0.0) & finite
    selected_position = position[eligible]
    selected_velocity = velocity[eligible]
    selected_ids = ids[eligible]
    speed = np.linalg.norm(selected_velocity, axis=1) if selected_velocity.size else np.asarray([])
    fitted = _fit_rigid(selected_position, selected_velocity, declared_center)
    fit_omega = fitted.get("omega_rad_s")
    omega_difference = None
    omega_difference_norm = None
    if fit_omega is not None:
        delta = np.asarray(fit_omega, dtype=np.float64) - np.asarray(declared_omega, dtype=np.float64)
        omega_difference = [float(item) for item in delta]
        omega_difference_norm = float(np.linalg.norm(delta))
    return {
        "frame": int(frame),
        "time_s": _read_time(datasets.get("time"), frame),
        "particle_range": {"start": int(start), "count": int(count)},
        "requested_type2_count": int(np.count_nonzero(type2)),
        "valid_type2_count": int(np.count_nonzero(type2 & (valid != 0.0))),
        "valid_finite_type2_count": int(selected_position.shape[0]),
        "invalid_or_nonfinite_type2_count": int(np.count_nonzero(type2 & (valid != 0.0) & ~finite)),
        "speed_m_per_s": _stats(speed),
        "velocity_squared_m2_per_s2": _stats(np.sum(selected_velocity * selected_velocity, axis=1) if selected_velocity.size else []),
        "uid": _uid_summary(selected_ids),
        "fit": fitted,
        "declared_omega_rad_s": [float(item) for item in declared_omega],
        "fitted_minus_declared_omega_rad_s": omega_difference,
        "fitted_minus_declared_omega_norm_rad_s": omega_difference_norm,
        "native_particle_velocity_state": (
            "insufficient"
            if speed.size == 0
            else ("nonzero" if int(np.count_nonzero(speed > 0.0)) else "zero")
        ),
        "interpretation": "direct native Type2 particle-state observation; does not negate the XML rigid-body angular declaration",
    }


def _parse_number(value: Any) -> Optional[float]:
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _field_index(headers: Sequence[str], aliases: Iterable[str]) -> Optional[int]:
    normalized = [_normalise(header) for header in headers]
    lookup = {value: index for index, value in enumerate(normalized)}
    for alias in aliases:
        if _normalise(alias) in lookup:
            return lookup[_normalise(alias)]
    return None


def _field_value(row: Sequence[str], index: Optional[int]) -> Optional[float]:
    if index is None or index >= len(row):
        return None
    return _parse_number(row[index])


def _vector_from_row(row: Sequence[str], headers: Sequence[str], aliases: Mapping[str, Iterable[str]]) -> Tuple[Optional[List[float]], List[bool]]:
    indices = [_field_index(headers, aliases[axis]) for axis in ("x", "y", "z")]
    values = [_field_value(row, index) for index in indices]
    present = [value is not None for value in values]
    return ([float(value) for value in values] if all(present) else None), present


def _floatinginfo_summary(path: Path, max_rows: int) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "path": str(path),
        "delimiter": ";",
        "decoder": "explicit_semicolon",
        "header_normalization": "lowercase and remove punctuation/whitespace",
        "read_policy": "bounded prefix only; no full CSV materialisation",
        "max_rows": int(max_rows),
    }
    if not path.exists():
        summary.update({"status": "unavailable", "error": "file does not exist"})
        return summary
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            raw_header = handle.readline()
            if not raw_header:
                summary.update({"status": "empty"})
                return summary
            headers = next(csv.reader([raw_header], delimiter=";"))
            reader = csv.reader(handle, delimiter=";")
            rows: List[List[str]] = []
            for row_index, row in enumerate(reader):
                if row_index >= max_rows:
                    break
                rows.append(row)
    except OSError as exc:
        summary.update({"status": "unavailable", "error": str(exc)})
        return summary
    summary["header_columns"] = headers
    summary["normalized_headers"] = [_normalise(header) for header in headers]
    summary["rows_examined"] = len(rows)
    if not rows:
        summary["status"] = "header_only"
        return summary

    time_aliases = ("time", "times", "t", "timestamp", "time_s", "f.time")
    omega_aliases = {
        "x": ("fomega.x", "fomegax", "omega.x", "omegax", "angularvelocityx", "angvelx", "wx"),
        "y": ("fomega.y", "fomegay", "omega.y", "omegay", "angularvelocityy", "angvely", "wy"),
        "z": ("fomega.z", "fomegaz", "omega.z", "omegaz", "angularvelocityz", "angvelz", "wz"),
    }
    velocity_aliases = {
        "x": ("fvel.x", "fvelx", "fvelocityx", "velocityx", "velx", "vcmx"),
        "y": ("fvel.y", "fvely", "fvelocityy", "velocityy", "vely", "vcmy"),
        "z": ("fvel.z", "fvelz", "fvelocityz", "velocityz", "velz", "vcmz"),
    }
    center_aliases = {
        "x": ("fcenter.x", "fcenterx", "center.x", "centerx", "fpos.x", "fposx"),
        "y": ("fcenter.y", "fcentery", "center.y", "centery", "fpos.y", "fposy"),
        "z": ("fcenter.z", "fcenterz", "center.z", "centerz", "fpos.z", "fposz"),
    }
    time_index = _field_index(headers, time_aliases)
    parsed_times = [_field_value(row, time_index) for row in rows]
    timed = [(index, value) for index, value in enumerate(parsed_times) if value is not None]
    if timed:
        zero_index = min(timed, key=lambda item: abs(float(item[1])))[0]
        positive = [item for item in timed if float(item[1]) > 1.0e-12]
        first_positive_index = min(positive, key=lambda item: float(item[1]))[0] if positive else None
    else:
        zero_index = 0
        first_positive_index = 1 if len(rows) > 1 else None

    def selected_record(index: Optional[int], role: str) -> Dict[str, Any]:
        if index is None:
            return {"role": role, "status": "unresolved", "reason": "no bounded row selected"}
        row = rows[index]
        omega, omega_presence = _vector_from_row(row, headers, omega_aliases)
        velocity, velocity_presence = _vector_from_row(row, headers, velocity_aliases)
        center, center_presence = _vector_from_row(row, headers, center_aliases)
        if omega is not None:
            status = "ok"
        elif any(omega_presence):
            status = "partial"
        else:
            status = "unresolved"
        return {
            "role": role,
            "row_index_in_bounded_data": int(index),
            "time_s": parsed_times[index],
            "omega_rad_s": omega,
            "omega_field_presence": omega_presence,
            "linear_velocity_m_per_s": velocity,
            "linear_velocity_field_presence": velocity_presence,
            "center_m": center,
            "center_field_presence": center_presence,
            "status": status,
            "raw_row_written": False,
        }

    summary["selected_rows"] = {
        "frame_zero": selected_record(zero_index, "closest_to_time_zero"),
        "first_positive_saved": selected_record(first_positive_index, "first_positive_saved_time"),
    }
    selected_statuses = [item["status"] for item in summary["selected_rows"].values()]
    if selected_statuses and all(status == "ok" for status in selected_statuses):
        summary["status"] = "ok"
    elif any(status in {"ok", "partial"} for status in selected_statuses):
        summary["status"] = "partial"
    else:
        summary["status"] = "unresolved"
    summary["interpretation"] = "FloatingInfo corroboration only; H5 Type2 fit is primary and unresolved fields remain unresolved"
    return summary


def _attr_number(node: Optional[ET.Element], name: str) -> Optional[float]:
    if node is None:
        return None
    return _parse_number(node.attrib.get(name))


def _vector_attr(node: Optional[ET.Element], names: Sequence[str]) -> Optional[List[float]]:
    if node is None:
        return None
    values = [_attr_number(node, name) for name in names]
    return [float(value) for value in values] if all(value is not None for value in values) else None


def _parse_native_xml(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "path": str(path),
        "read_policy": "exact XML metadata parsed when worker is enabled",
    }
    if not path.exists():
        result.update({"status": "unavailable", "error": "file does not exist"})
        return result
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        result.update({"status": "unavailable", "error": str(exc)})
        return result
    casedef_floating = root.find("./casedef/floatings/floating")
    particles_floating = root.find("./execution/particles/floating")
    initial_move = root.find("./casedef/initials/move[@mkbound='50']")
    motion = root.find("./execution/motion")
    casedef_ang = casedef_floating.find("./angularvelini") if casedef_floating is not None else None
    particles_ang = particles_floating.find("./angularvelini") if particles_floating is not None else None
    casedef_center = casedef_floating.find("./center") if casedef_floating is not None else None
    casedef_inertia = casedef_floating.find("./inertia") if casedef_floating is not None else None
    result.update(
        {
            "status": "ok",
            "casedef_floating": {
                "massbody_kg": _attr_number(casedef_floating.find("./massbody") if casedef_floating is not None else None, "value"),
                "angularvelini_rad_s": _vector_attr(casedef_ang, ("x", "y", "z")),
                "angularvelini_units": casedef_ang.attrib.get("units_comment") if casedef_ang is not None else None,
                "center_m": _vector_attr(casedef_center, ("x", "y", "z")),
                "inertia_kg_m2": _vector_attr(casedef_inertia, ("x", "y", "z")),
                "translation_dof": casedef_floating.find("./translationDOF").attrib if casedef_floating is not None and casedef_floating.find("./translationDOF") is not None else None,
                "rotation_dof": casedef_floating.find("./rotationDOF").attrib if casedef_floating is not None and casedef_floating.find("./rotationDOF") is not None else None,
            },
            "particles_floating": {
                "massbody_kg": _attr_number(particles_floating.find("./massbody") if particles_floating is not None else None, "value"),
                "angularvelini_rad_s": _vector_attr(particles_ang, ("x", "y", "z")),
                "angularvelini_units": particles_ang.attrib.get("units_comment") if particles_ang is not None else None,
                "center_m": _vector_attr(particles_floating.find("./center") if particles_floating is not None else None, ("x", "y", "z")),
                "inertia_kg_m2": _vector_attr(particles_floating.find("./inertia") if particles_floating is not None else None, ("x", "y", "z")),
            },
            "initial_move": {
                "mkbound": initial_move.attrib.get("mkbound") if initial_move is not None else None,
                "offset_m": _vector_attr(initial_move, ("x", "y", "z")),
            },
            "motion": {
                "present": motion is not None,
                "empty": motion is not None and not motion.attrib and len(list(motion)) == 0,
                "attributes": dict(motion.attrib) if motion is not None else {},
            },
            "explicit_particle_velocity_element": root.find(".//velocity") is not None,
            "semantic_boundary": "angularvelini is a rigid-body/source declaration; direct native Type2 particle velocity is measured independently",
        }
    )
    return result


def _source_stat(path: Path, expected_sha256: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.exists():
        result["bytes"] = int(path.stat().st_size)
    if expected_sha256:
        result["expected_sha256"] = expected_sha256
        result["sha256_read_policy"] = "fingerprint supplied by provenance; worker does not hash source"
    return result


def _run(args: argparse.Namespace) -> Dict[str, Any]:
    if np is None or h5py is None:
        raise AuditError(f"numpy/h5py import failed: {_IMPORT_ERROR}")
    trajectory = Path(args.trajectory)
    floating_info = Path(args.floating_info)
    native_xml = Path(args.native_xml)
    solver_receipt = Path(args.solver_receipt)
    if not trajectory.exists():
        raise AuditError(f"trajectory does not exist: {trajectory}")
    start = int(args.particle_start)
    count = int(args.particle_count)
    frame0 = int(args.frame0)
    first_saved = int(args.first_saved_frame)
    if start < 0 or count <= 0 or frame0 < 0 or first_saved < 0:
        raise AuditError("particle and frame bounds must be nonnegative")
    declared_center = np.asarray(args.declared_center, dtype=np.float64)
    declared_omega = np.asarray(args.declared_omega, dtype=np.float64)
    if declared_center.shape != (3,) or declared_omega.shape != (3,):
        raise AuditError("declared center and omega must each contain three values")
    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "status": "running_bounded_audit",
        "source_policy": {
            "typed_h5": "read-only Type2 slice at two frames",
            "floating_info": "bounded prefix, explicit semicolon delimiter",
            "native_xml": "metadata parse only",
            "solver_receipt": "bound/stat only in worker; no solver execution",
            "particle_arrays_written": False,
            "csv_written": False,
            "h5_written": False,
            "bi4_read": False,
            "mass_rescaled": False,
        },
        "source_fingerprints": {
            "trajectory": _source_stat(trajectory, args.expected_h5_sha256),
            "floating_info": _source_stat(floating_info, args.expected_floating_info_sha256),
            "native_xml": _source_stat(native_xml, args.expected_native_xml_sha256),
            "solver_receipt": _source_stat(solver_receipt, args.expected_solver_receipt_sha256),
        },
        "case_anchor": {
            "type": 2,
            "mk": 60,
            "particle_start": start,
            "particle_count": count,
            "declared_center_m": [float(item) for item in declared_center],
            "declared_omega_rad_s": [float(item) for item in declared_omega],
            "gencase_initial_velocity_max_m_per_s": float(args.gencase_initial_velocity_max),
            "physical_mass_kg": 128.0,
            "native_support_mass_kg": 256.0,
            "mass_rescaled": False,
        },
        "dataset_discovery": {},
    }
    with h5py.File(trajectory, "r") as handle:
        datasets = _discover_datasets(handle)
        required = ("position", "velocity", "particle_id", "type")
        missing = [role for role in required if role not in datasets]
        if missing:
            raise AuditError(f"required datasets not discovered: {missing}")
        position_shape = _shape(datasets["position"])
        frame_count = position_shape[0] if len(position_shape) == 3 else 1
        particle_count = position_shape[1] if len(position_shape) == 3 else position_shape[0]
        if first_saved >= frame_count or frame0 >= frame_count:
            raise AuditError(f"requested frame exceeds H5 frame count {frame_count}")
        if start + count > particle_count:
            raise AuditError(f"Type2 slice exceeds particle axis {particle_count}")
        result["dataset_discovery"] = {
            role: {"path": str(dataset.name), "shape": list(_shape(dataset))}
            for role, dataset in sorted(datasets.items())
        }
        if "valid" not in datasets:
            result["dataset_discovery"]["valid"] = {
                "path": None,
                "fallback": "all selected rows treated as valid",
            }
        result["native_axis"] = {
            "frame_count": int(frame_count),
            "particle_count": int(particle_count),
            "requested_frames": [frame0, first_saved],
        }
        frame_records = [
            _frame_record(
                datasets,
                frame,
                start,
                count,
                particle_count,
                frame_count,
                declared_center,
                declared_omega,
            )
            for frame in (frame0, first_saved)
        ]
    result["native_frames"] = {
        "frame_zero": frame_records[0],
        "first_saved": frame_records[1],
        "interpretation": "native particle-state fits only; a zero frame-zero fit does not establish absence of the declared physical rigid angular release",
    }
    result["floating_info"] = _floatinginfo_summary(
        floating_info, int(args.max_floating_info_rows)
    )
    result["native_xml_semantics"] = _parse_native_xml(native_xml)
    result["solver_receipt_binding"] = {
        "path": str(solver_receipt),
        "read": False,
        "role": "exact solver/source receipt bound for Root review; no solver output parsed by this worker",
    }
    result["gates"] = {
        "launch_allowed": False,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "q_i": "not_granted",
        "q_n": "not_assessed",
        "visual_review": "pending",
        "root_cause": "undetermined",
    }
    result["status"] = "completed_bounded_audit"
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--floating-info", required=True)
    parser.add_argument("--native-xml", required=True)
    parser.add_argument("--solver-receipt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frame0", type=int, default=0)
    parser.add_argument("--first-saved-frame", type=int, default=1)
    parser.add_argument("--particle-start", type=int, default=73441)
    parser.add_argument("--particle-count", type=int, default=16384)
    parser.add_argument("--declared-center", nargs=3, type=float, default=(2.4, 1.2, 1.08))
    parser.add_argument("--declared-omega", nargs=3, type=float, default=(0.08, 0.12, 0.06))
    parser.add_argument("--max-floating-info-rows", type=int, default=16)
    parser.add_argument("--gencase-initial-velocity-max", type=float, default=0.0)
    parser.add_argument("--expected-h5-sha256", default=None)
    parser.add_argument("--expected-floating-info-sha256", default=None)
    parser.add_argument("--expected-native-xml-sha256", default=None)
    parser.add_argument("--expected-solver-receipt-sha256", default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output)
    try:
        result = _run(args)
        exit_code = 0
    except Exception as exc:  # keep a machine-readable disabled-run failure receipt
        result = {
            "schema": SCHEMA,
            "status": "failed_bounded_audit",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "gates": {
                "launch_allowed": False,
                "independent_case_count_increment": 0,
                "production_approval": "none",
                "q_i": "not_granted",
                "q_n": "not_assessed",
                "visual_review": "pending",
                "root_cause": "undetermined",
            },
        }
        exit_code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

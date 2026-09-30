#!/usr/bin/env python3
"""Bounded-memory DS-DATA-02 HDF5 Q-I integrity auditor.

The auditor consumes the normalized HDF5 files already present in the lab.  It
does not invoke a solver, a model, a GPU worker, or a queue.  The particle axis
is visited in bounded chunks for every saved frame; the full trajectory is
never materialized in memory.  Results describe Q-I evidence only.  Q-N,
external validation, and production eligibility are deliberately left
unassessed.

The historical normalized files pre-date the DS-DATA-02 contract.  A file can
therefore have structurally valid arrays while still returning an incomplete
Q-I result because units, a coordinate frame, geometry, control, or lifecycle
semantics are absent.  Missing information is reported as missing evidence,
never silently inferred from a filename or from non-zero z coordinates.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import resource
import time as wall_time
from typing import Any, Mapping

import h5py
import numpy as np


SCHEMA = "ds-data-02.integrity-audit.v1"
PROTOCOL_SCHEMA = "ds-data-02.hdf5-schema.v1"
MAX_LOG_BYTES = 16 * 1024 * 1024
DEFAULT_PARTICLE_CHUNK = 65536

REQUIRED_DATASETS = (
    "time",
    "particle_id",
    "particle_zone",
    "valid",
    "position",
    "velocity",
    "density",
    "mass",
    "type",
)
OPTIONAL_DATASETS = ("pressure", "mk")
PHYSICAL_UNITS = {
    "time": ("s",),
    "position": ("m",),
    "velocity": ("m/s",),
    "density": ("kg/m^3", "kg/m3"),
    "mass": ("kg",),
    "pressure": ("Pa",),
}
UNIT_ALIASES = {
    "sec": "s",
    "second": "s",
    "seconds": "s",
    "metre": "m",
    "meter": "m",
    "metres": "m",
    "meters": "m",
    "m/s": "m/s",
    "m s-1": "m/s",
    "m/s^1": "m/s",
    "kg/m3": "kg/m^3",
    "kg/m**3": "kg/m^3",
    "kg m-3": "kg/m^3",
    "pa": "Pa",
}

_NUMBER_RE = re.compile(r"(?<![A-Za-z])([0-9][0-9_,]*)(?![A-Za-z])")


def _json_value(value: Any) -> Any:
    """Convert HDF5/numpy values to JSON-safe Python values."""
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = _json_value(value)
    if isinstance(value, str):
        return value
    return str(value)


def _normalise_unit(value: Any) -> str | None:
    raw = _text(value)
    if raw is None:
        return None
    value = raw.strip().replace("µ", "u").replace("·", " ")
    value = re.sub(r"\s+", " ", value)
    return UNIT_ALIASES.get(value.lower(), UNIT_ALIASES.get(value, value))


def _mapping_from_value(value: Any) -> Mapping[str, Any] | None:
    value = _json_value(value)
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return decoded if isinstance(decoded, Mapping) else None
    return None


def _metadata_mapping(metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return metadata if isinstance(metadata, Mapping) else {}


def _root_attr(handle: h5py.File, *names: str) -> Any:
    for name in names:
        if name in handle.attrs:
            return _json_value(handle.attrs[name])
    return None


def _unit_for(handle: h5py.File, field: str, metadata: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Return a unit and a source, checking explicit metadata only."""
    for key in ("units", "field_units", "unit_map"):
        mapping = _mapping_from_value(metadata.get(key))
        if mapping is not None and field in mapping:
            return _normalise_unit(mapping[field]), f"metadata.{key}.{field}"
    for key in (f"units_{field}", f"{field}_units", f"unit_{field}"):
        if key in metadata:
            return _normalise_unit(metadata[key]), f"metadata.{key}"
    for key in ("units", "field_units", "unit_map"):
        mapping = _mapping_from_value(_root_attr(handle, key))
        if mapping is not None and field in mapping:
            return _normalise_unit(mapping[field]), f"root_attr.{key}.{field}"
    for key in (f"units_{field}", f"{field}_units", f"unit_{field}"):
        value = _root_attr(handle, key)
        if value is not None:
            return _normalise_unit(value), f"root_attr.{key}"
    if field in handle and isinstance(handle[field], h5py.Dataset):
        for key in ("units", "unit"):
            if key in handle[field].attrs:
                return _normalise_unit(handle[field].attrs[key]), f"dataset_attr.{field}.{key}"
    return None, None


def _semantic_value(handle: h5py.File, metadata: Mapping[str, Any], *names: str) -> tuple[Any, str | None]:
    for name in names:
        if name in metadata and metadata[name] not in (None, ""):
            return _json_value(metadata[name]), f"metadata.{name}"
        if name in handle.attrs:
            return _json_value(handle.attrs[name]), f"root_attr.{name}"
    return None, None


def _read_log(path: str | os.PathLike[str] | None) -> tuple[str | None, str | None, str | None]:
    if path is None:
        return None, None, None
    log_path = Path(path)
    try:
        with log_path.open("rb") as stream:
            raw = stream.read(MAX_LOG_BYTES + 1)
    except OSError as error:
        return str(log_path), None, f"solver log could not be read: {error}"
    truncated = len(raw) > MAX_LOG_BYTES
    text = raw[:MAX_LOG_BYTES].decode("utf-8", errors="replace")
    if truncated:
        text += "\n[truncated after 16 MiB]"
    return str(log_path), text, None


def _first_number(pattern: re.Pattern[str], text: str) -> int | float | None:
    match = pattern.search(text)
    if not match:
        return None
    raw = match.group(1).replace(",", "").replace("_", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def _solver_log_evidence(solver_log: str | os.PathLike[str] | None) -> dict[str, Any]:
    path, text, error = _read_log(solver_log)
    result: dict[str, Any] = {
        "path": path,
        "available": text is not None,
        "parse_error": error,
        "dimension": {
            "status": "missing",
            "solver_dimension": None,
            "source": None,
            "evidence_lines": [],
            "coordinate_components": 3,
            "inference_from_coordinate_values": False,
        },
        "counts": {
            "initial_total": None,
            "initial_fluid_type3": None,
            "initial_floating_type2": None,
            "excluded_particles": None,
        },
    }
    if text is None:
        return result
    dimensions: set[int] = set()
    evidence_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        # These expressions require a solver-produced simulation banner or
        # Simulate2D option.  A case name containing "3D" is not evidence.
        if re.search(r"\*\*\s*([23])D\s*[- ]?Simulation\b", stripped, re.I):
            dimensions.add(int(re.search(r"([23])D", stripped, re.I).group(1)))
            evidence_lines.append(stripped[:400])
        elif re.search(r"\bSimulate2D(?:PosY)?\s*=", stripped, re.I):
            dimensions.add(2)
            evidence_lines.append(stripped[:400])
        elif re.search(r"\b(?:simulation|solver)\b.{0,80}\b([23])D\b", stripped, re.I):
            match = re.search(r"\b([23])D\b", stripped, re.I)
            if match:
                dimensions.add(int(match.group(1)))
                evidence_lines.append(stripped[:400])
    if len(dimensions) == 1:
        dimension = next(iter(dimensions))
        result["dimension"] = {
            "status": "pass",
            "solver_dimension": dimension,
            "source": "solver_log_explicit_banner",
            "evidence_lines": evidence_lines[:8],
            "coordinate_components": 3,
            "inference_from_coordinate_values": False,
        }
    elif len(dimensions) > 1:
        result["dimension"] = {
            "status": "fail",
            "solver_dimension": None,
            "source": "solver_log_conflicting_banners",
            "evidence_lines": evidence_lines[:8],
            "coordinate_components": 3,
            "inference_from_coordinate_values": False,
        }
    counts = result["counts"]
    counts["initial_total"] = _first_number(
        re.compile(r"Particles\s+of\s+simulation\s*\(initial\)\s*:\s*([0-9_,]+)", re.I), text,
    )
    counts["initial_fluid_type3"] = _first_number(
        re.compile(r"CaseNfluid\s*=\s*([0-9_,]+)", re.I), text,
    )
    counts["initial_floating_type2"] = _first_number(
        re.compile(r"CaseNfloat\s*=\s*([0-9_,]+)", re.I), text,
    )
    counts["excluded_particles"] = _first_number(
        re.compile(r"Excluded\s+particles[^:]*:\s*([0-9_,]+)", re.I), text,
    )
    return result


def _dataset_nbytes(dataset: h5py.Dataset) -> int:
    try:
        return int(dataset.nbytes)
    except (AttributeError, TypeError, ValueError):
        return int(np.prod(dataset.shape, dtype=np.int64)) * int(dataset.dtype.itemsize)


def estimate_hdf5_audit(path: str | os.PathLike[str], *, particle_chunk: int = DEFAULT_PARTICLE_CHUNK) -> dict[str, Any]:
    """Estimate read volume and peak working memory without reading trajectories."""
    if not isinstance(particle_chunk, int) or particle_chunk <= 0:
        raise ValueError("particle_chunk must be a positive integer")
    input_path = Path(path)
    with h5py.File(input_path, "r") as handle:
        dataset_bytes = {
            name: _dataset_nbytes(obj)
            for name, obj in handle.items()
            if isinstance(obj, h5py.Dataset)
        }
        particle_count = None
        frame_count = None
        if "particle_id" in handle and handle["particle_id"].ndim == 1:
            particle_count = int(handle["particle_id"].shape[0])
        if "time" in handle and handle["time"].ndim == 1:
            frame_count = int(handle["time"].shape[0])
        per_chunk = 0
        if particle_count is not None:
            width = min(particle_chunk, particle_count)
            for name in REQUIRED_DATASETS + OPTIONAL_DATASETS:
                if name not in handle or name in {"time", "particle_id", "particle_zone"}:
                    continue
                dataset = handle[name]
                if dataset.ndim >= 2:
                    per_chunk += width * int(dataset.dtype.itemsize) * (3 if dataset.ndim == 3 else 1)
        # The estimate is an upper bound for one particle chunk plus static
        # identity axes and lifecycle booleans.  It intentionally excludes
        # Python interpreter/HDF5 cache overhead.
        lifecycle_bytes = 8 * (particle_count or 0) + 8 * (particle_count or 0)
        return {
            "path": str(input_path),
            "file_bytes": int(input_path.stat().st_size),
            "frames": frame_count,
            "particles": particle_count,
            "particle_chunk": particle_chunk,
            "logical_dataset_bytes": int(sum(dataset_bytes.values())),
            "dataset_storage_bytes": int(sum(int(obj.id.get_storage_size()) for obj in handle.values()
                                               if isinstance(obj, h5py.Dataset))),
            "dataset_bytes": dataset_bytes,
            "estimated_read_bytes": int(sum(dataset_bytes.get(name, 0) for name in
                                             REQUIRED_DATASETS + OPTIONAL_DATASETS)),
            "estimated_peak_working_set_bytes": int(per_chunk + lifecycle_bytes),
            "full_trajectory_materialized": False,
            "method": "dataset metadata plus one particle chunk per frame",
        }


def _shape_status(handle: h5py.File, frames: int, particles: int) -> tuple[dict[str, Any], list[str], list[str]]:
    checks: dict[str, Any] = {}
    structural_failures: list[str] = []
    missing: list[str] = []
    expected: dict[str, tuple[int, ...] | None] = {
        "time": (frames,),
        "particle_id": (particles,),
        "particle_zone": (particles,),
        "valid": (frames, particles),
        "type": (frames, particles),
        "position": (frames, particles, 3),
        "velocity": (frames, particles, 3),
        "density": (frames, particles),
        "mass": (frames, particles),
        "pressure": (frames, particles),
        "mk": (frames, particles),
    }
    for name in REQUIRED_DATASETS + OPTIONAL_DATASETS:
        if name not in handle:
            if name in REQUIRED_DATASETS:
                structural_failures.append(f"missing_dataset:{name}")
                checks[name] = {"status": "fail", "reason": "missing_required_dataset"}
            else:
                missing.append(f"dataset:{name}")
                checks[name] = {"status": "missing", "reason": "optional_dataset_absent"}
            continue
        dataset = handle[name]
        actual = tuple(int(value) for value in dataset.shape)
        expected_shape = expected[name]
        shape_ok = actual == expected_shape
        checks[name] = {
            "status": "pass" if shape_ok else "fail",
            "shape": list(actual),
            "expected_shape": list(expected_shape) if expected_shape is not None else None,
            "dtype": str(dataset.dtype),
            "chunks": list(dataset.chunks) if dataset.chunks else None,
        }
        if not shape_ok:
            if name in REQUIRED_DATASETS:
                structural_failures.append(f"shape:{name}")
            else:
                missing.append(f"shape:{name}")
    return checks, structural_failures, missing


def _read_frame(dataset: h5py.Dataset, frame: int, lo: int, hi: int) -> np.ndarray:
    if dataset.ndim == 1:
        return np.asarray(dataset[lo:hi])
    return np.asarray(dataset[frame, lo:hi])


def _identity_code(zone: np.ndarray, particle_id: np.ndarray) -> np.ndarray:
    """Make exact, compact typed keys where the common unsigned range allows it."""
    zone64 = np.asarray(zone, dtype=np.int64)
    id64 = np.asarray(particle_id, dtype=np.int64)
    if (zone64.size == 0 or (int(zone64.min()) >= 0 and int(zone64.max()) < 2**32
                             and int(id64.min()) >= 0 and int(id64.max()) < 2**32)):
        return (zone64.astype(np.uint64) << np.uint64(32)) ^ id64.astype(np.uint64)
    structured = np.empty(zone64.shape, dtype=[("zone", "<i8"), ("idp", "<i8")])
    structured["zone"] = zone64
    structured["idp"] = id64
    return structured


def _identity_axis(handle: h5py.File, particles: int) -> tuple[np.ndarray | None, np.ndarray | None, dict[str, Any], list[str]]:
    failures: list[str] = []
    details: dict[str, Any] = {"mode": "static", "unique": None, "frame_unique": None}
    try:
        ids = np.asarray(handle["particle_id"][:])
        zones = np.asarray(handle["particle_zone"][:])
    except (KeyError, OSError, ValueError):
        return None, None, {"mode": "static", "unique": False}, ["identity_axis_unreadable"]
    if ids.ndim != 1 or zones.ndim != 1 or ids.shape != (particles,) or zones.shape != (particles,):
        return ids, zones, {"mode": "static", "unique": False}, ["identity_axis_shape"]
    if ids.dtype.kind not in "iu" or zones.dtype.kind not in "iu":
        failures.append("identity_axis_non_integer")
    codes = _identity_code(zones, ids)
    unique = bool(np.unique(codes).size == particles)
    details.update({
        "mode": "static",
        "identity_key": "(Zone,Idp)",
        "unique": unique,
        "count": particles,
        "zone_values": [int(value) for value in np.unique(zones).tolist()],
        "id_min": int(ids.min()) if ids.size else None,
        "id_max": int(ids.max()) if ids.size else None,
    })
    if not unique:
        failures.append("identity_axis_duplicate_typed_key")
    if "particle_id_by_frame" in handle or "particle_zone_by_frame" in handle:
        details["mode"] = "static_plus_per_frame"
        if "particle_id_by_frame" not in handle or "particle_zone_by_frame" not in handle:
            failures.append("per_frame_identity_pair_incomplete")
        else:
            idf, zf = handle["particle_id_by_frame"], handle["particle_zone_by_frame"]
            expected = (int(handle["time"].shape[0]), particles)
            if tuple(idf.shape) != expected or tuple(zf.shape) != expected:
                failures.append("per_frame_identity_shape")
            else:
                details["mode"] = "per_frame"
    return ids, zones, details, failures


def _per_frame_identity_check(handle: h5py.File, frame: int, particles: int) -> tuple[bool | None, bool]:
    if "particle_id_by_frame" not in handle or "particle_zone_by_frame" not in handle:
        return None, False
    ids = np.asarray(handle["particle_id_by_frame"][frame, :])
    zones = np.asarray(handle["particle_zone_by_frame"][frame, :])
    if ids.dtype.kind not in "iu" or zones.dtype.kind not in "iu":
        return False, False
    codes = _identity_code(zones, ids)
    return bool(np.unique(codes).size == particles), False


def _check_units_and_semantics(handle: h5py.File, metadata: Mapping[str, Any], type2_seen: bool) -> tuple[dict[str, Any], list[str]]:
    units: dict[str, Any] = {}
    missing: list[str] = []
    for field, expected in PHYSICAL_UNITS.items():
        if field not in handle and field != "time":
            continue
        found, source = _unit_for(handle, field, metadata)
        canonical_expected = [_normalise_unit(value) for value in expected]
        if found is None:
            units[field] = {"status": "missing", "expected": list(expected), "value": None, "source": None}
            missing.append(f"units:{field}")
        else:
            ok = found in canonical_expected
            units[field] = {
                "status": "pass" if ok else "fail",
                "expected": list(expected),
                "value": found,
                "source": source,
            }
            if not ok:
                missing.append(f"units_mismatch:{field}")
    coordinate_frame, coordinate_source = _semantic_value(
        handle, metadata, "coordinate_frame", "position_coordinate_frame",
    )
    coordinate = {
        "status": "pass" if coordinate_frame not in (None, "") else "missing",
        "coordinate_components": 3,
        "coordinate_frame": coordinate_frame,
        "source": coordinate_source,
        "inference_from_z_values": False,
    }
    if coordinate["status"] == "missing":
        missing.append("coordinate_frame")
    geometry, geometry_source = _semantic_value(handle, metadata, "geometry", "geometry_description", "geometry_source")
    control, control_source = _semantic_value(handle, metadata, "control", "control_definition", "control_source")
    geometry_check = {"status": "pass" if geometry not in (None, "") else "missing", "value": geometry, "source": geometry_source}
    control_check = {"status": "pass" if control not in (None, "") else "missing", "value": control, "source": control_source}
    if geometry_check["status"] == "missing":
        missing.append("geometry")
    if control_check["status"] == "missing":
        missing.append("control")
    boundary_mode, boundary_source = _semantic_value(handle, metadata, "boundary_mode", "lifecycle_mode", "closed_system")
    boundary_check = {
        "status": "pass" if boundary_mode not in (None, "") else "missing",
        "value": boundary_mode,
        "source": boundary_source,
    }
    if boundary_check["status"] == "missing":
        missing.append("boundary_or_lifecycle_semantics")
    rigid_state, rigid_source = _semantic_value(
        handle, metadata, "rigid_body_state", "rigid_body_state_source", "floating_state_dataset",
    )
    has_rigid_dataset = any(name in handle for name in ("rigid_body_state", "body_state", "float_state"))
    rigid_check = {
        "status": "pass" if rigid_state not in (None, "") or has_rigid_dataset or not type2_seen else "missing",
        "source": rigid_source if rigid_state not in (None, "") else ("dataset" if has_rigid_dataset else None),
        "required": bool(type2_seen),
    }
    if rigid_check["status"] == "missing":
        missing.append("rigid_body_state_for_type2")
    return {
        "units": units,
        "coordinate": coordinate,
        "geometry": geometry_check,
        "control": control_check,
        "boundary": boundary_check,
        "rigid_body_state": rigid_check,
    }, sorted(set(missing))


def _resource_snapshot() -> dict[str, Any]:
    def usage(which: int) -> dict[str, Any]:
        value = resource.getrusage(which)
        return {
            "user_cpu_seconds": float(value.ru_utime),
            "system_cpu_seconds": float(value.ru_stime),
            "max_rss_kib": int(value.ru_maxrss),
            "minor_page_faults": int(value.ru_minflt),
            "major_page_faults": int(value.ru_majflt),
            "in_block": int(value.ru_inblock),
            "out_block": int(value.ru_oublock),
            "voluntary_context_switches": int(value.ru_nvcsw),
            "involuntary_context_switches": int(value.ru_nivcsw),
        }
    return {"self": usage(resource.RUSAGE_SELF), "children": usage(resource.RUSAGE_CHILDREN)}


def _safe_float(value: float | np.floating[Any] | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def audit_hdf5(
    path: str | os.PathLike[str],
    *,
    solver_log: str | os.PathLike[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    particle_chunk: int = DEFAULT_PARTICLE_CHUNK,
) -> dict[str, Any]:
    """Audit one HDF5 file and return JSON-serializable Q-I evidence.

    ``metadata`` is an explicit caller-supplied binding for information absent
    from legacy HDF5 files.  It is recorded with its source and never inferred
    from case names, coordinate values, or filename conventions.
    """
    if not isinstance(particle_chunk, int) or particle_chunk <= 0:
        raise ValueError("particle_chunk must be a positive integer")
    input_path = Path(path)
    metadata_map = _metadata_mapping(metadata)
    started = wall_time.perf_counter()
    log_evidence = _solver_log_evidence(solver_log)
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "protocol_schema": PROTOCOL_SCHEMA,
        "path": str(input_path),
        "exists": input_path.is_file(),
        "q_i_status": "Q-I-audit-error",
        "q_n_status": "not_assessed",
        "scientific_acceptance": "not_assessed",
        "production_eligibility": "not_evaluated",
        "solver_log": log_evidence,
        "missing_requirements": [],
        "structural_failures": [],
        "warnings": [],
        "audit_parameters": {
            "particle_chunk": particle_chunk,
            "full_trajectory_materialized": False,
        },
    }
    if not input_path.is_file():
        report["structural_failures"] = ["file_missing"]
        report["q_i_status"] = "Q-I-structure-fail"
        report["audit_seconds"] = _safe_float(wall_time.perf_counter() - started)
        return _json_value(report)
    try:
        with h5py.File(input_path, "r") as handle:
            root_attrs = {str(key): _json_value(value) for key, value in handle.attrs.items()}
            report["root_attributes"] = root_attrs
            report["datasets"] = sorted(str(key) for key in handle.keys())
            if "time" not in handle or not isinstance(handle["time"], h5py.Dataset) or handle["time"].ndim != 1:
                report["structural_failures"] = ["time_axis_shape"]
                report["q_i_status"] = "Q-I-structure-fail"
                report["missing_requirements"] = ["time_axis"]
                report["audit_seconds"] = _safe_float(wall_time.perf_counter() - started)
                return _json_value(report)
            time_axis = np.asarray(handle["time"][:])
            frames = int(time_axis.shape[0])
            if "particle_id" not in handle or not isinstance(handle["particle_id"], h5py.Dataset) or handle["particle_id"].ndim != 1:
                report["structural_failures"] = ["particle_id_axis_shape"]
                report["q_i_status"] = "Q-I-structure-fail"
                report["missing_requirements"] = ["particle_identity_axis"]
                report["audit_seconds"] = _safe_float(wall_time.perf_counter() - started)
                return _json_value(report)
            particles = int(handle["particle_id"].shape[0])
            report["dimensions"] = {"frames": frames, "particles": particles, "coordinate_components": 3}
            report["cost_estimate"] = estimate_hdf5_audit(input_path, particle_chunk=particle_chunk)
            shape_checks, shape_failures, optional_missing = _shape_status(handle, frames, particles)
            report["shape_checks"] = shape_checks
            structural_failures = list(shape_failures)
            missing_requirements = list(optional_missing)
            ids, zones, identity_details, identity_failures = _identity_axis(handle, particles)
            report["identity"] = identity_details
            structural_failures.extend(identity_failures)
            if ids is None or zones is None or ids.shape != (particles,) or zones.shape != (particles,):
                report["structural_failures"] = sorted(set(structural_failures))
                report["q_i_status"] = "Q-I-structure-fail"
                report["missing_requirements"] = sorted(set(missing_requirements))
                report["audit_seconds"] = _safe_float(wall_time.perf_counter() - started)
                return _json_value(report)
            time_finite = bool(np.isfinite(time_axis).all())
            time_increasing = bool(frames >= 2 and np.all(np.diff(time_axis.astype(np.float64)) > 0))
            report["time"] = {
                "status": "pass" if time_finite and time_increasing else "fail",
                "finite": time_finite,
                "strictly_increasing": time_increasing,
                "count": frames,
                "start_s": _safe_float(time_axis[0]) if frames else None,
                "end_s": _safe_float(time_axis[-1]) if frames else None,
            }
            if not time_finite:
                structural_failures.append("time_nonfinite")
            if not time_increasing:
                structural_failures.append("time_not_strictly_increasing")
            valid_ds = handle.get("valid")
            valid_binary = True
            valid_dtype = str(valid_ds.dtype) if isinstance(valid_ds, h5py.Dataset) else None
            finite_active = {name: True for name in ("position", "velocity", "density", "mass", "pressure") if name in handle}
            positive_mass = True
            positive_density = True
            type2_seen = False
            type3_seen = False
            per_frame_identity_unique = True
            per_frame_identity_checked = False
            type_counts: list[dict[str, int]] = []
            fluid_mass: list[float | None] = []
            floating_mass: list[float | None] = []
            active_count: list[int] = []
            fluid_count: list[int] = []
            floating_count: list[int] = []
            static_identity_valid = isinstance(valid_ds, h5py.Dataset) and tuple(valid_ds.shape) == (frames, particles)
            initial_active = np.zeros(particles, dtype=bool)
            previous_active = np.zeros(particles, dtype=bool)
            ever_seen = np.zeros(particles, dtype=bool)
            missing_observed = np.zeros(particles, dtype=bool)
            revived = np.zeros(particles, dtype=bool)
            initial_fluid = np.zeros(particles, dtype=bool)
            initial_floating = np.zeros(particles, dtype=bool)
            initial_fluid_mass = np.zeros(particles, dtype=np.float64)
            initial_floating_mass = np.zeros(particles, dtype=np.float64)
            last_active = np.zeros(particles, dtype=bool)
            previous_type = np.full(particles, -1, dtype=np.int64)
            type_changed = np.zeros(particles, dtype=bool)
            frame_id_changed = 0
            if static_identity_valid:
                for frame in range(frames):
                    frame_unique, _ = _per_frame_identity_check(handle, frame, particles)
                    if frame_unique is not None:
                        per_frame_identity_checked = True
                        per_frame_identity_unique &= bool(frame_unique)
                        if frame_unique is False:
                            structural_failures.append(f"per_frame_identity_duplicate:{frame}")
                    lo = 0
                    frame_active_total = 0
                    frame_fluid_count = 0
                    frame_float_count = 0
                    frame_fluid_mass = 0.0
                    frame_float_mass = 0.0
                    frame_type_counts: dict[str, int] = {}
                    while lo < particles:
                        hi = min(particles, lo + particle_chunk)
                        raw_valid = np.asarray(valid_ds[frame, lo:hi])
                        if raw_valid.dtype.kind == "f":
                            valid_binary &= bool(np.isfinite(raw_valid).all())
                        if raw_valid.dtype.kind not in "?biuf":
                            valid_binary = False
                        valid_values = np.asarray(raw_valid, dtype=np.float64)
                        valid_binary &= bool(np.all((valid_values == 0) | (valid_values == 1)))
                        active = valid_values.astype(bool)
                        frame_active_total += int(active.sum())
                        prior_seen = ever_seen[lo:hi].copy()
                        if frame == 0:
                            initial_active[lo:hi] = active
                        missing_observed[lo:hi] |= prior_seen & ~active
                        revived[lo:hi] |= prior_seen & ~previous_active[lo:hi] & active
                        ever_seen[lo:hi] |= active
                        previous_active[lo:hi] = active
                        last_active[lo:hi] = active
                        type_values = _read_frame(handle["type"], frame, lo, hi)
                        if type_values.dtype.kind not in "iu":
                            structural_failures.append("type_non_integer")
                        type_values = np.asarray(type_values, dtype=np.int64)
                        active_type = type_values[active]
                        if active_type.size:
                            values, counts = np.unique(active_type, return_counts=True)
                            for value, count in zip(values.tolist(), counts.tolist()):
                                frame_type_counts[str(int(value))] = frame_type_counts.get(str(int(value)), 0) + int(count)
                        type3 = active & (type_values == 3)
                        type2 = active & (type_values == 2)
                        frame_fluid_count += int(type3.sum())
                        frame_float_count += int(type2.sum())
                        type3_seen |= bool(type3.any())
                        type2_seen |= bool(type2.any())
                        changed = active & (previous_type[lo:hi] >= 0) & (previous_type[lo:hi] != type_values)
                        type_changed[lo:hi] |= changed
                        previous_type_slice = previous_type[lo:hi]
                        previous_type_slice[active] = type_values[active]
                        previous_type[lo:hi] = previous_type_slice
                        if frame == 0:
                            initial_fluid[lo:hi] = type3
                            initial_floating[lo:hi] = type2
                        for field in finite_active:
                            if field not in handle:
                                continue
                            field_shape = tuple(handle[field].shape)
                            expected_field_shape = ((frames, particles, 3)
                                                    if field in ("position", "velocity")
                                                    else (frames, particles))
                            if field_shape != expected_field_shape:
                                continue
                            values = _read_frame(handle[field], frame, lo, hi)
                            if active.any():
                                finite_active[field] &= bool(np.isfinite(values[active]).all())
                        mass_values = _read_frame(handle["mass"], frame, lo, hi)
                        density_values = _read_frame(handle["density"], frame, lo, hi)
                        if active.any():
                            positive_mass &= bool(np.all(mass_values[active] > 0))
                            positive_density &= bool(np.all(density_values[active] > 0))
                        if frame == 0:
                            fluid_mass_slice = initial_fluid_mass[lo:hi]
                            floating_mass_slice = initial_floating_mass[lo:hi]
                            fluid_mass_slice[type3] = np.asarray(mass_values[type3], dtype=np.float64)
                            floating_mass_slice[type2] = np.asarray(mass_values[type2], dtype=np.float64)
                            initial_fluid_mass[lo:hi] = fluid_mass_slice
                            initial_floating_mass[lo:hi] = floating_mass_slice
                        frame_fluid_mass += float(np.sum(np.asarray(mass_values[type3], dtype=np.float64)))
                        frame_float_mass += float(np.sum(np.asarray(mass_values[type2], dtype=np.float64)))
                        if "particle_id_by_frame" in handle and "particle_zone_by_frame" in handle:
                            static_codes = _identity_code(zones[lo:hi], ids[lo:hi])
                            frame_codes = _identity_code(
                                np.asarray(handle["particle_zone_by_frame"][frame, lo:hi]),
                                np.asarray(handle["particle_id_by_frame"][frame, lo:hi]),
                            )
                            frame_id_changed += int(np.count_nonzero(frame_codes != static_codes))
                        lo = hi
                    type_counts.append(frame_type_counts)
                    active_count.append(frame_active_total)
                    fluid_count.append(frame_fluid_count)
                    floating_count.append(frame_float_count)
                    fluid_mass.append(_safe_float(frame_fluid_mass))
                    floating_mass.append(_safe_float(frame_float_mass))
            else:
                structural_failures.append("trajectory_shape_prevents_chunk_audit")
            units_semantics, semantic_missing = _check_units_and_semantics(handle, metadata_map, type2_seen)
            missing_requirements.extend(semantic_missing)
            dimension = log_evidence["dimension"]
            metadata_dimension = metadata_map.get("solver_dimension")
            if dimension["status"] == "missing" and metadata_dimension in (2, 3, "2", "3"):
                dimension = {
                    "status": "pass",
                    "solver_dimension": int(metadata_dimension),
                    "source": "metadata.solver_dimension",
                    "evidence_lines": [],
                    "coordinate_components": 3,
                    "inference_from_coordinate_values": False,
                }
            elif dimension["status"] == "missing":
                missing_requirements.append("solver_dimension_actual_evidence")
            elif dimension["status"] == "fail":
                structural_failures.append("solver_dimension_conflicting_evidence")
            if not valid_binary:
                structural_failures.append("valid_not_binary")
            if not all(finite_active.values()):
                structural_failures.extend(f"active_nonfinite:{name}" for name, ok in finite_active.items() if not ok)
            if not positive_mass:
                structural_failures.append("active_mass_not_positive_finite")
            if not positive_density:
                structural_failures.append("active_density_not_positive_finite")
            if per_frame_identity_checked and not per_frame_identity_unique:
                structural_failures.append("typed_identity_not_unique_in_frame")
            if "pressure" not in handle:
                missing_requirements.append("dataset:pressure")
            if "mk" not in handle:
                missing_requirements.append("dataset:mk")
            if frame_id_changed:
                missing_requirements.append("changing_per_frame_identity_requires_lineage")
            final_fluid = initial_fluid & last_active
            final_floating = initial_floating & last_active
            fluid_initial_mass_total = float(np.sum(initial_fluid_mass))
            floating_initial_mass_total = float(np.sum(initial_floating_mass))
            fluid_missing_mass = float(np.sum(initial_fluid_mass[initial_fluid & ~last_active]))
            floating_missing_mass = float(np.sum(initial_floating_mass[initial_floating & ~last_active]))
            lifecycle = {
                "identity_axis": "(Zone,Idp)",
                "initial_active_count": int(initial_active.sum()),
                "final_active_count": int(last_active.sum()),
                "ever_seen_count": int(ever_seen.sum()),
                "introduced_after_initial_count": int((ever_seen & ~initial_active).sum()),
                "missing_at_any_later_frame_count": int(missing_observed.sum()),
                "revived_identity_count": int(revived.sum()),
                "initial_missing_at_final_count": int((initial_active & ~last_active).sum()),
                "initial_to_final_retention": float((initial_active & last_active).sum() / max(1, int(initial_active.sum()))),
                "type_changed_identity_count": int(type_changed.sum()),
                "per_frame_identity_changed_rows": int(frame_id_changed),
                "full_timeline_checked": bool(static_identity_valid),
            }
            boundary_value = units_semantics["boundary"].get("value")
            boundary_text = str(boundary_value).lower() if boundary_value is not None else ""
            closed_declared = boundary_text in {"closed", "closed_system", "true", "fixed_mass_closed"} or boundary_value is True
            open_declared = boundary_text in {"open", "open_system", "open_boundary"}
            if closed_declared:
                closed_status = lifecycle["missing_at_any_later_frame_count"] == 0 and lifecycle["introduced_after_initial_count"] == 0 and lifecycle["revived_identity_count"] == 0
                closed_check = {"status": "pass" if closed_status else "fail", "declared": True, "mass_conservation_not_q_n": True}
                if not closed_status:
                    structural_failures.append("closed_lifecycle_missing_or_revival")
            elif open_declared:
                closed_check = {"status": "not_applicable", "declared": False, "open_boundary": True}
                missing_requirements.append("open_boundary_birth_exit_and_flux_ledger")
            else:
                closed_check = {"status": "missing", "declared": None}
                missing_requirements.append("closed_or_open_lifecycle_declaration")
            fluid_ledger = {
                "type_code": 3,
                "status": "pass" if type3_seen else "missing",
                "initial_count": int(initial_fluid.sum()),
                "initial_mass_kg": _safe_float(fluid_initial_mass_total),
                "active_count_by_frame": fluid_count,
                "active_mass_kg_by_frame": fluid_mass,
                "final_initial_cohort_retained_count": int(final_fluid.sum()),
                "initial_cohort_missing_at_final_count": int((initial_fluid & ~last_active).sum()),
                "initial_cohort_missing_mass_kg": _safe_float(fluid_missing_mass),
                "solver_excluded_particles": log_evidence["counts"].get("excluded_particles"),
                "separate_from_type2": True,
            }
            floating_ledger = {
                "type_code": 2,
                "status": "pass" if type2_seen else "not_present",
                "initial_count": int(initial_floating.sum()),
                "initial_mass_kg": _safe_float(floating_initial_mass_total),
                "active_count_by_frame": floating_count,
                "active_mass_kg_by_frame": floating_mass,
                "final_initial_cohort_retained_count": int(final_floating.sum()),
                "initial_cohort_missing_at_final_count": int((initial_floating & ~last_active).sum()),
                "initial_cohort_missing_mass_kg": _safe_float(floating_missing_mass),
                "excluded_from_fluid_ledger": True,
            }
            solver_consistency = {
                "status": "unknown",
                "comparisons": [],
            }
            log_counts = log_evidence["counts"]
            if log_counts.get("initial_fluid_type3") is not None:
                ok = int(log_counts["initial_fluid_type3"]) == int(initial_fluid.sum())
                solver_consistency["comparisons"].append({"field": "initial_fluid_type3", "log": log_counts["initial_fluid_type3"], "hdf5": int(initial_fluid.sum()), "match": ok})
            if log_counts.get("initial_floating_type2") is not None:
                ok = int(log_counts["initial_floating_type2"]) == int(initial_floating.sum())
                solver_consistency["comparisons"].append({"field": "initial_floating_type2", "log": log_counts["initial_floating_type2"], "hdf5": int(initial_floating.sum()), "match": ok})
            if solver_consistency["comparisons"]:
                solver_consistency["status"] = "pass" if all(item["match"] for item in solver_consistency["comparisons"]) else "fail"
            report.update({
                "shape_checks": shape_checks,
                "units_and_semantics": units_semantics,
                "dimension_evidence": dimension,
                "valid": {"dtype": valid_dtype, "binary": valid_binary, "status": "pass" if valid_binary else "fail"},
                "finite_active": finite_active,
                "positive_active_mass": positive_mass,
                "positive_active_density": positive_density,
                "active_count_by_frame": active_count,
                "type_counts_by_frame": type_counts,
                "fluid_mass_ledger": fluid_ledger,
                "floating_mass_ledger": floating_ledger,
                "lifecycle": lifecycle,
                "closed_lifecycle_check": closed_check,
                "solver_log_consistency": solver_consistency,
            })
            report["structural_failures"] = sorted(set(structural_failures))
            report["missing_requirements"] = sorted(set(missing_requirements))
            if report["structural_failures"]:
                report["q_i_status"] = "Q-I-structure-fail"
            elif report["missing_requirements"]:
                report["q_i_status"] = "Q-I-incomplete"
            else:
                report["q_i_status"] = "Q-I-structure-pass"
    except (OSError, KeyError, TypeError, ValueError, IndexError, RuntimeError) as error:
        report["structural_failures"] = sorted(set(report.get("structural_failures", []) + ["audit_exception"]))
        report["audit_error"] = f"{type(error).__name__}: {error}"
        report["q_i_status"] = "Q-I-audit-error"
    report["audit_seconds"] = _safe_float(wall_time.perf_counter() - started)
    return _json_value(report)


def _load_metadata(path: Path | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("metadata JSON must contain an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--solver-log", type=Path)
    parser.add_argument("--metadata-json", type=Path)
    parser.add_argument("--particle-chunk", type=int, default=DEFAULT_PARTICLE_CHUNK)
    parser.add_argument("--estimate-only", action="store_true",
                        help="report bounded read/memory estimates without reading trajectory data")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    before = _resource_snapshot()
    if args.estimate_only:
        report = {
            "schema": SCHEMA,
            "protocol_schema": PROTOCOL_SCHEMA,
            "path": str(args.path),
            "mode": "estimate_only",
            "q_i_status": "not_run",
            "q_n_status": "not_assessed",
            "scientific_acceptance": "not_assessed",
            "production_eligibility": "not_evaluated",
            "cost_estimate": estimate_hdf5_audit(args.path, particle_chunk=args.particle_chunk),
        }
    else:
        report = audit_hdf5(
            args.path,
            solver_log=args.solver_log,
            metadata=_load_metadata(args.metadata_json),
            particle_chunk=args.particle_chunk,
        )
    after = _resource_snapshot()
    report["resource_usage"] = {"before": before, "after": after}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report.get("q_i_status") not in {"Q-I-structure-fail", "Q-I-audit-error"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

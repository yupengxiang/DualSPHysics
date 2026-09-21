#!/usr/bin/env python3
"""Read-only streaming audit for terminal F3 native CFD source H5 files.

This is deliberately a separate audit version from the source runner.  It can
re-audit a terminal ``trajectory.h5`` after a worker has finished without
changing the frozen runner, its prepared record, or the worker's product
files.  The complete trajectory is never loaded into memory: one saved frame
is read at a time and the mass reference is compared particle by particle.

The F3 physical wall is finite: the bottom and four side faces close the
container, while the top is open.  The top is therefore reported as an open
face observation and is never turned into a wall violation.  Saved-frame
chord crossings are reported as a diagnostic in addition to endpoint
violations; they do not claim to recover the solver's substep path.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any

import h5py
import numpy as np

try:
    from scripts.finite_wall_audit import outside_closed_face_masks, segment_crossing_events
except ModuleNotFoundError:  # pragma: no cover - direct script entrypoint
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.finite_wall_audit import outside_closed_face_masks, segment_crossing_events


SCHEMA = "core.f3.cfd.native_volume_mls.source_audit.v2"
AUDIT_CODE = Path(__file__).resolve()
FRAME_PARTICLE_CHUNK = 65536
WALL_TOLERANCE_M = 1e-8
MASS_RELATIVE_TOLERANCE = 1e-8
# DualSPHysics saves the nearest completed solver state at each requested
# TimeOut.  The source contract is therefore a scheduling cadence, rather
# than an exact decimal timestamp.  One percent of the registered output
# interval is a structural serialization bound; it is not a scientific
# qualification tolerance.  The report also retains the exact timestamp
# error for review.
TIME_CADENCE_RELATIVE_TOLERANCE = 1e-2
TIME_CADENCE_ABSOLUTE_FLOOR_S = 1e-7
F3_WALL_LOW_M = np.asarray([-.45, -.09, 0.0], dtype=np.float64)
F3_WALL_HIGH_M = np.asarray([.45, .09, .51], dtype=np.float64)
F3_CLOSED_FACES = ("bottom", "left", "right", "front", "back")
F3_OPEN_FACES = ("top",)
REQUIRED_DATASETS = (
    "particle_id", "particle_zone", "source_label_initial_mk", "time", "position",
    "velocity", "density", "mass", "pressure", "valid", "type", "mk",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(f"audit output is immutable and already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def _registered_wall_spec(*, source: str = "registered_f3_recipe_geometry_v1",
                          binding_pass: bool = False) -> dict[str, Any]:
    return {
        "container_interior": {
            "xmin": float(F3_WALL_LOW_M[0]), "xmax": float(F3_WALL_HIGH_M[0]),
            "ymin": float(F3_WALL_LOW_M[1]), "ymax": float(F3_WALL_HIGH_M[1]),
            "zmin": float(F3_WALL_LOW_M[2]), "zmax": float(F3_WALL_HIGH_M[2]),
        },
        "closed_faces": list(F3_CLOSED_FACES),
        "open_faces": list(F3_OPEN_FACES),
        "geometry_source": source,
        "geometry_binding_pass": bool(binding_pass),
        "geometry_source_path": None,
        "geometry_source_sha256": None,
    }


def _xml_geometry(path: Path) -> tuple[np.ndarray, np.ndarray, bool] | None:
    """Read the finite F3 normal wall box and its open-top marker."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    for drawbox in root.findall(".//list[@name='GeometryForNormals']/drawbox"):
        fill = "".join((drawbox.findtext("boxfill") or "").split()).lower()
        point = drawbox.find("point")
        size = drawbox.find("size")
        if point is None or size is None or fill != "all^top":
            continue
        try:
            low = np.asarray([float(point.get(axis)) for axis in "xyz"], dtype=np.float64)
            extent = np.asarray([float(size.get(axis)) for axis in "xyz"], dtype=np.float64)
        except (TypeError, ValueError):
            continue
        if np.isfinite(low).all() and np.isfinite(extent).all() and (extent > 0).all():
            return low, low + extent, True
    return None


def wall_spec_from_prepared(prepared: dict[str, Any], prepared_path: Path | None = None) -> dict[str, Any]:
    """Bind the audit wall to the copied F3 XML when available.

    A scheduler snapshot can relocate the prepared input while retaining the
    same registered F3 recipe.  If the copied XML is unavailable, the
    registered geometry is retained only as diagnostic context and the binding
    gate remains false.  An XML mismatch is a hard audit failure rather than
    silently changing the wall.
    """
    candidates: list[Path] = []
    prefix = prepared.get("generated_prefix")
    if prefix:
        candidates.append(Path(prefix).with_suffix(".xml"))
        if prepared_path is not None:
            candidates.append(Path(prepared_path).resolve().parent / (Path(prefix).name + ".xml"))
    candidates = list(dict.fromkeys(path.resolve() for path in candidates))
    registered = _registered_wall_spec()
    input_hashes = {
        str(Path(path).resolve()): str(value)
        for path, value in (prepared.get("inputs") or {}).items()
    }
    for path in candidates:
        if not path.is_file():
            continue
        expected_hash = input_hashes.get(str(path))
        actual_hash = digest(path)
        if expected_hash is None:
            result = _registered_wall_spec(source="prepared_geometry_xml_not_registered")
            result.update({
                "geometry_source_path": str(path),
                "geometry_source_sha256": actual_hash,
                "geometry_binding_error": "geometry XML is not listed in prepared.inputs",
            })
            return result
        if actual_hash != expected_hash:
            result = _registered_wall_spec(source="prepared_geometry_xml_hash_mismatch")
            result.update({
                "geometry_source_path": str(path),
                "geometry_source_sha256": actual_hash,
                "geometry_expected_sha256": expected_hash,
                "geometry_binding_error": "geometry XML hash differs from prepared.inputs",
            })
            return result
        geometry = _xml_geometry(path)
        if geometry is None:
            result = _registered_wall_spec(source="prepared_geometry_xml_unrecognized")
            result.update({
                "geometry_source_path": str(path),
                "geometry_source_sha256": actual_hash,
                "geometry_binding_error": "XML is invalid or lacks the expected finite all^top F3 wall box",
            })
            return result
        low, high, open_top = geometry
        expected_low = F3_WALL_LOW_M
        expected_high = F3_WALL_HIGH_M
        matches = bool(np.allclose(low, expected_low, rtol=0.0, atol=1e-12)
                       and np.allclose(high, expected_high, rtol=0.0, atol=1e-12)
                       and open_top)
        result = _registered_wall_spec(source="prepared_geometry_normals_xml")
        result.update({
            "geometry_source_path": str(path),
            "geometry_source_sha256": actual_hash,
            "geometry_expected_sha256": expected_hash,
            "xml_low_m": low.tolist(),
            "xml_high_m": high.tolist(),
            "xml_open_top": bool(open_top),
            "geometry_binding_pass": matches,
        })
        if matches:
            result["container_interior"] = {
                "xmin": float(low[0]), "xmax": float(high[0]),
                "ymin": float(low[1]), "ymax": float(high[1]),
                "zmin": float(low[2]), "zmax": float(high[2]),
            }
        return result
    registered["geometry_binding_error"] = (
        "no prepared.inputs-bound F3 geometry XML was available; registered geometry is diagnostic only"
    )
    return registered


def _case_expectations(prepared: dict[str, Any]) -> dict[str, Any]:
    case = prepared.get("case", {})
    config = prepared.get("config", {})
    frames = int(case.get("expected_native_frames", config.get("expected_native_frames", 0)))
    particles = int(case.get("fluid_particles", 0))
    interval = float(case.get("output_interval_s", config.get("output_interval_s", math.nan)))
    time_max = float(case.get("time_max_s", config.get("time_max_s", math.nan)))
    if frames < 2 or particles < 1 or not np.isfinite(interval) or interval <= 0 or not np.isfinite(time_max):
        raise ValueError("prepared record lacks finite F3 frame/cadence expectations")
    return {
        "expected_frames": frames,
        "expected_particles": particles,
        "output_interval_s": interval,
        "time_max_s": time_max,
        "case_id": str(case.get("case_id", config.get("case_id", "unknown"))),
        "source_asset_id": str(case.get("source_asset_id", "unknown")),
    }


def _dataset_shape_errors(handle: h5py.File, expected: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors = [f"missing:{name}" for name in REQUIRED_DATASETS if name not in handle]
    shapes = {name: list(handle[name].shape) for name in handle.keys() if hasattr(handle[name], "shape")}
    if errors:
        return errors, shapes
    nt = expected["expected_frames"]
    n = expected["expected_particles"]
    checks = {
        "particle_id": handle["particle_id"].shape == (n,),
        "particle_zone": handle["particle_zone"].shape == (n,),
        "source_label_initial_mk": handle["source_label_initial_mk"].shape == (n,),
        "time": handle["time"].shape == (nt,),
        "position": handle["position"].shape == (nt, n, 3),
        "velocity": handle["velocity"].shape == (nt, n, 3),
        "density": handle["density"].shape == (nt, n),
        "pressure": handle["pressure"].shape == (nt, n),
        "valid": handle["valid"].shape == (nt, n),
        "type": handle["type"].shape == (nt, n),
        "mk": handle["mk"].shape == (nt, n),
        "mass": handle["mass"].shape in ((n,), (nt, n)),
    }
    errors.extend([f"shape:{name}" for name, okay in checks.items() if not okay])
    if not (np.issubdtype(handle["valid"].dtype, np.bool_) or np.issubdtype(handle["valid"].dtype, np.integer)):
        errors.append("valid:dtype")
    return errors, shapes


def _mass_row(dataset: h5py.Dataset, frame: int, n: int) -> np.ndarray:
    if dataset.ndim == 1:
        return np.asarray(dataset[:], dtype=np.float64)
    return np.asarray(dataset[frame, :], dtype=np.float64)


def _finish_provenance(report: dict[str, Any], hdf5: Path) -> dict[str, Any]:
    if hdf5.is_file():
        report["hdf5_sha256"] = digest(hdf5)
        report["hdf5_bytes"] = hdf5.stat().st_size
    report["audit_code_path"] = str(AUDIT_CODE)
    report["audit_code_sha256"] = digest(AUDIT_CODE)
    report["read_only"] = True
    report["central_ledger_mutation"] = 0
    report["gpu_started"] = False
    return report


def audit_hdf5(
    prepared: dict[str, Any],
    hdf5: Path,
    *,
    wall_spec: dict[str, Any] | None = None,
    prepared_path: Path | None = None,
) -> dict[str, Any]:
    """Stream a terminal source H5 and return a versioned independent report."""
    hdf5 = Path(hdf5).resolve()
    expected = _case_expectations(prepared)
    wall = wall_spec or wall_spec_from_prepared(prepared, prepared_path=prepared_path)
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "audit_version": 2,
        "audited_at_utc": utc_now(),
        "hdf5": str(hdf5),
        "hdf5_exists": hdf5.is_file(),
        "case_id": expected["case_id"],
        "source_asset_id": expected["source_asset_id"],
        "qualification_claim": "none; source integrity re-audit only",
        "qualification_gate_changed": False,
        "tolerances": {
            "wall_endpoint_m": WALL_TOLERANCE_M,
            "mass_relative": MASS_RELATIVE_TOLERANCE,
            "time_cadence_relative": TIME_CADENCE_RELATIVE_TOLERANCE,
            "time_cadence_absolute_floor_s": TIME_CADENCE_ABSOLUTE_FLOOR_S,
            "semantics": "one-percent saved-output scheduling bound; exact timestamp error is retained; no scientific qualification threshold changed",
        },
        "expected": expected,
        "wall_geometry": wall,
        "streaming": {
            "frame_by_frame": True,
            "trajectory_whole_slice_reads": False,
            "frame_particle_chunk": FRAME_PARTICLE_CHUNK,
            "mass_checked_per_particle": True,
        },
        "errors": [],
    }
    if not hdf5.is_file():
        report["errors"] = ["missing_hdf5"]
        report["hard_integrity_pass"] = False
        return _finish_provenance(report, hdf5)

    with h5py.File(hdf5, "r") as handle:
        errors, shapes = _dataset_shape_errors(handle, expected)
        report["datasets"] = shapes
        conversion_attribute = handle.attrs.get("conversion_complete", False)
        if isinstance(conversion_attribute, np.generic):
            conversion_attribute = conversion_attribute.item()
        report["conversion_complete"] = bool(conversion_attribute)
        report["conversion_complete_attribute"] = conversion_attribute
        if not report["conversion_complete"]:
            errors.append("conversion:incomplete_or_missing_attribute")
        if errors:
            report["errors"] = errors
            report["hard_integrity_pass"] = False
            return _finish_provenance(report, hdf5)

        particle_ids = np.asarray(handle["particle_id"][:])
        unique_ids = len(np.unique(particle_ids)) == len(particle_ids)
        report["particle_ids_unique"] = bool(unique_ids)
        if not unique_ids:
            errors.append("particle_id:duplicate")
        n = expected["expected_particles"]
        nt = expected["expected_frames"]
        times = handle["time"]
        mass_dataset = handle["mass"]
        reference_mass = _mass_row(mass_dataset, 0, n)
        reference_mass_finite = bool(np.isfinite(reference_mass).all() and (reference_mass > 0).all())
        mass_changed_ids: set[int] = set()
        first_mass_change: dict[str, Any] | None = None
        mass_change_max_relative = 0.0
        mass_change_max_particle: int | None = None
        mass_change_max_frame: int | None = None
        valid_false_count = 0
        valid_nonbinary_count = 0
        active_nonfinite_counts = {name: 0 for name in ("position", "velocity", "density", "pressure", "mass")}
        active_nonpositive_mass_count = 0
        finite_active = {name: True for name in active_nonfinite_counts}
        time_monotone = True
        cadence_bad_indices: list[int] = []
        cadence_max_abs_error = 0.0
        cadence_max_exact_abs_error = 0.0
        first_time = math.nan
        last_time = math.nan
        endpoint_by_face = {face: 0 for face in F3_CLOSED_FACES}
        endpoint_mass_by_face = {face: 0.0 for face in F3_CLOSED_FACES}
        wall_violation_count = 0
        first_wall_violation: dict[str, Any] | None = None
        chord_crossing_count = 0
        first_chord_crossing: dict[str, Any] | None = None
        open_top_count = 0
        open_top_max_z = -math.inf
        previous_time: float | None = None
        previous_position: np.ndarray | None = None
        previous_valid: np.ndarray | None = None

        for frame in range(nt):
            current_time = float(times[frame])
            if frame == 0:
                first_time = current_time
            last_time = current_time
            expected_time = frame * expected["output_interval_s"]
            cadence_error = abs(current_time - expected_time) if np.isfinite(current_time) else math.inf
            cadence_max_abs_error = max(cadence_max_abs_error, float(cadence_error))
            cadence_max_exact_abs_error = max(cadence_max_exact_abs_error, float(cadence_error))
            cadence_tolerance = max(
                TIME_CADENCE_ABSOLUTE_FLOOR_S,
                TIME_CADENCE_RELATIVE_TOLERANCE * expected["output_interval_s"],
            )
            if not np.isfinite(current_time) or cadence_error > cadence_tolerance:
                if len(cadence_bad_indices) < 64:
                    cadence_bad_indices.append(frame)
            if previous_time is not None and not (np.isfinite(current_time) and current_time > previous_time):
                time_monotone = False
            previous_time = current_time

            # Keep one frame for the saved-chord diagnostic, but stream every
            # field inside that frame in bounded particle chunks.  In
            # particular, the .002 source never materializes [frames, n, 3].
            position = np.empty((n, 3), dtype=np.float64)
            finite_position = np.zeros(n, dtype=bool)
            valid = np.zeros(n, dtype=bool)
            for start in range(0, n, FRAME_PARTICLE_CHUNK):
                stop = min(start + FRAME_PARTICLE_CHUNK, n)
                position_chunk = np.asarray(handle["position"][frame, start:stop], dtype=np.float64)
                velocity_chunk = np.asarray(handle["velocity"][frame, start:stop], dtype=np.float64)
                density_chunk = np.asarray(handle["density"][frame, start:stop], dtype=np.float64)
                pressure_chunk = np.asarray(handle["pressure"][frame, start:stop], dtype=np.float64)
                mass_chunk = (
                    np.asarray(mass_dataset[start:stop], dtype=np.float64)
                    if mass_dataset.ndim == 1
                    else np.asarray(mass_dataset[frame, start:stop], dtype=np.float64)
                )
                raw_valid = np.asarray(handle["valid"][frame, start:stop])
                if np.issubdtype(raw_valid.dtype, np.integer):
                    valid_nonbinary_count += int((~np.isin(raw_valid, (0, 1))).sum())
                valid_chunk = raw_valid.astype(bool)
                valid[start:stop] = valid_chunk
                position[start:stop] = position_chunk
                finite_position_chunk = np.isfinite(position_chunk).all(axis=1)
                finite_position[start:stop] = finite_position_chunk
                valid_false_count += int((~valid_chunk).sum())
                fields = {
                    "position": finite_position_chunk,
                    "velocity": np.isfinite(velocity_chunk).all(axis=1),
                    "density": np.isfinite(density_chunk),
                    "pressure": np.isfinite(pressure_chunk),
                    "mass": np.isfinite(mass_chunk),
                }
                for name, finite_mask in fields.items():
                    bad = valid_chunk & ~finite_mask
                    active_nonfinite_counts[name] += int(bad.sum())
                    finite_active[name] = finite_active[name] and not bool(bad.any())
                nonpositive = valid_chunk & (~np.isfinite(mass_chunk) | (mass_chunk <= 0))
                active_nonpositive_mass_count += int(nonpositive.sum())

                reference_chunk = reference_mass[start:stop]
                valid_mass = valid_chunk & np.isfinite(mass_chunk) & np.isfinite(reference_chunk) & (reference_chunk > 0)
                if valid_mass.any():
                    denominator = np.maximum(np.abs(reference_chunk[valid_mass]), 1e-30)
                    relative = np.abs(mass_chunk[valid_mass] - reference_chunk[valid_mass]) / denominator
                    local_indices = np.flatnonzero(valid_mass)
                    local_max_index = int(np.argmax(relative))
                    local_max = float(relative[local_max_index])
                    if local_max > mass_change_max_relative:
                        mass_change_max_relative = local_max
                        mass_change_max_particle = int(start + local_indices[local_max_index])
                        mass_change_max_frame = frame
                    changed = local_indices[relative > MASS_RELATIVE_TOLERANCE]
                    for local_particle in changed:
                        particle = int(start + local_particle)
                        mass_changed_ids.add(particle)
                        if first_mass_change is None:
                            relative_index = int(np.flatnonzero(local_indices == local_particle)[0])
                            first_mass_change = {
                                "frame": frame,
                                "time_s": current_time,
                                "particle_index": particle,
                                "particle_id": int(particle_ids[particle]),
                                "relative_change": float(relative[relative_index]),
                            }

                wall_active = valid_chunk & finite_position_chunk
                if wall_active.any():
                    selected_local = np.flatnonzero(wall_active)
                    selected_points = position_chunk[selected_local]
                    masks = outside_closed_face_masks(selected_points, wall, WALL_TOLERANCE_M)
                    for face, mask in masks.items():
                        count = int(mask.sum())
                        endpoint_by_face[face] += count
                        if count:
                            selected_bad = selected_local[mask]
                            global_bad = start + selected_bad
                            endpoint_mass_by_face[face] += float(np.sum(mass_chunk[selected_bad], dtype=np.float64))
                            wall_violation_count += count
                            if first_wall_violation is None:
                                first = int(global_bad[0])
                                first_wall_violation = {
                                    "frame": frame,
                                    "time_s": current_time,
                                    "face": face,
                                    "particle_index": first,
                                    "particle_id": int(particle_ids[first]),
                                    "position_m": position[first].tolist(),
                                }
                    top = selected_points[:, 2] > float(wall["container_interior"]["zmax"]) + WALL_TOLERANCE_M
                    open_top_count += int(top.sum())
                    if top.any():
                        open_top_max_z = max(open_top_max_z, float(np.max(selected_points[top, 2])))

            if previous_position is not None and previous_valid is not None:
                common = previous_valid & valid & np.isfinite(previous_position).all(axis=1) & finite_position
                if common.any():
                    events = segment_crossing_events(
                        previous_position[common], position[common], wall, WALL_TOLERANCE_M
                    )
                    chord_crossing_count += len(events)
                    if events and first_chord_crossing is None:
                        event = dict(events[0])
                        local_index = int(event["point_index"])
                        global_indices = np.flatnonzero(common)
                        event["frame_start"] = frame - 1
                        event["frame_end"] = frame
                        event["time_start_s"] = float(times[frame - 1])
                        event["time_end_s"] = current_time
                        event["particle_index"] = int(global_indices[local_index])
                        event["particle_id"] = int(particle_ids[event["particle_index"]])
                        first_chord_crossing = event
            previous_position = position
            previous_valid = valid.copy()

        wall_bound = bool(wall.get("geometry_binding_pass", False))
        cadence_pass = bool(
            not cadence_bad_indices and time_monotone
            and abs(first_time) <= max(TIME_CADENCE_ABSOLUTE_FLOOR_S,
                                       TIME_CADENCE_RELATIVE_TOLERANCE * expected["output_interval_s"])
            and abs(last_time - expected["time_max_s"]) <= max(TIME_CADENCE_ABSOLUTE_FLOOR_S,
                                                                 TIME_CADENCE_RELATIVE_TOLERANCE * expected["output_interval_s"])
        )
        all_valid = valid_false_count == 0 and valid_nonbinary_count == 0
        mass_constant_pass = bool(reference_mass_finite and not mass_changed_ids
                                  and mass_change_max_relative <= MASS_RELATIVE_TOLERANCE)
        finite_pass = bool(all(finite_active.values()) and active_nonpositive_mass_count == 0)
        wall_pass = bool(wall_bound and wall_violation_count == 0 and chord_crossing_count == 0)
        report.update({
            "particle_ids_unique": bool(unique_ids),
            "initial_mass_finite_positive": reference_mass_finite,
            "frames_scanned": nt,
            "particles_scanned_per_frame": n,
            "time": {
                "first_s": first_time,
                "last_s": last_time,
                "expected_first_s": 0.0,
                "expected_last_s": expected["time_max_s"],
                "monotone": time_monotone,
                "cadence_max_abs_error_s": cadence_max_abs_error,
                "cadence_max_exact_abs_error_s": cadence_max_exact_abs_error,
                "cadence_tolerance_s": max(TIME_CADENCE_ABSOLUTE_FLOOR_S,
                                             TIME_CADENCE_RELATIVE_TOLERANCE * expected["output_interval_s"]),
                "cadence_bad_count_capped": len(cadence_bad_indices),
                "cadence_bad_indices_first64": cadence_bad_indices,
                "first_pass": abs(first_time) <= max(TIME_CADENCE_ABSOLUTE_FLOOR_S,
                                                       TIME_CADENCE_RELATIVE_TOLERANCE * expected["output_interval_s"]),
                "last_pass": abs(last_time - expected["time_max_s"]) <= max(TIME_CADENCE_ABSOLUTE_FLOOR_S,
                                                                              TIME_CADENCE_RELATIVE_TOLERANCE * expected["output_interval_s"]),
                "cadence_pass": cadence_pass,
            },
            "validity": {
                "all_entries_valid": all_valid,
                "valid_false_count": valid_false_count,
                "nonbinary_count": valid_nonbinary_count,
            },
            "finite_active": finite_active,
            "active_nonfinite_counts": active_nonfinite_counts,
            "active_nonpositive_mass_count": active_nonpositive_mass_count,
            "mass_per_particle": {
                "mode": "static_1d" if mass_dataset.ndim == 1 else "per_frame_2d",
                "constant_pass": mass_constant_pass,
                "max_relative_change": mass_change_max_relative,
                "max_change_particle_index": mass_change_max_particle,
                "max_change_frame": mass_change_max_frame,
                "changed_particle_count": len(mass_changed_ids),
                "first_change": first_mass_change,
                "tolerance_relative": MASS_RELATIVE_TOLERANCE,
            },
            "wall": {
                "closed_faces": list(F3_CLOSED_FACES),
                "open_faces": list(F3_OPEN_FACES),
                "endpoint_violation_count": wall_violation_count,
                "endpoint_violation_count_by_face": endpoint_by_face,
                "endpoint_violation_mass_kg_by_face": endpoint_mass_by_face,
                "first_endpoint_violation": first_wall_violation,
                "saved_chord_crossing_count": chord_crossing_count,
                "first_saved_chord_crossing": first_chord_crossing,
                "open_top_observed_particle_frames": open_top_count,
                "open_top_max_z_m": None if open_top_max_z == -math.inf else open_top_max_z,
                "endpoint_pass": wall_violation_count == 0,
                "chord_pass": chord_crossing_count == 0,
                "finite_geometry_binding_pass": wall_bound,
                "pass": wall_pass,
            },
        })
        if not unique_ids:
            errors.append("particle_id:duplicate")
        if not cadence_pass:
            errors.append("time:saved_cadence_or_window")
        if not all_valid:
            errors.append("valid:fluid_frame_not_complete")
        if not finite_pass:
            errors.append("state:active_nonfinite_or_nonpositive_mass")
        if not mass_constant_pass:
            errors.append("mass:per_particle_not_constant")
        if not wall_pass:
            errors.append("wall:finite_geometry_or_crossing")
        report["errors"] = errors
        report["hard_integrity_pass"] = bool(
            report["conversion_complete"] and unique_ids and cadence_pass and all_valid
            and finite_pass and mass_constant_pass and wall_pass
        )
    return _finish_provenance(report, hdf5)


def audit_file(
    prepared_path: Path,
    hdf5: Path,
    output: Path,
    *,
    wall_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prepared_path = Path(prepared_path).resolve()
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    report = audit_hdf5(prepared, hdf5, wall_spec=wall_spec, prepared_path=prepared_path)
    report["prepared_json"] = str(prepared_path)
    report["prepared_json_sha256"] = digest(prepared_path)
    atomic_json(output, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--hdf5", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--wall-spec-json", type=Path,
        help="explicit trusted finite-wall spec; must declare geometry_binding_pass=true",
    )
    args = parser.parse_args(argv)
    wall_spec = None
    if args.wall_spec_json is not None:
        wall_spec = json.loads(args.wall_spec_json.read_text(encoding="utf-8"))
    report = audit_file(args.prepared, args.hdf5, args.output, wall_spec=wall_spec)
    print(json.dumps({
        "schema": report["schema"],
        "hard_integrity_pass": report["hard_integrity_pass"],
        "hdf5_sha256": report.get("hdf5_sha256"),
        "errors": report["errors"],
    }, indent=2))
    return 0 if report["hard_integrity_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build native F2 source/destination and boundary-event observations.

This is a read-only scientific audit of a converted native DualSPHysics
trajectory.  It does not infer particles, fill missing identities, or replace
the saved moving boundary with prescribed kinematics.  The finite cup,
receiver, and tray tests are evaluated in SI coordinates, with the cup
position transformed by the actual moving-node rigid pose saved by
``ds_data02_convert.py``.

The output HDF5 is a sidecar label product.  It deliberately keeps
``unknown`` separate from spill/tray mass, including identities excluded by
the open-top solver.  The report is a Q-I/event-evidence artifact; it never
grants Q-N or production eligibility.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.ds_data02_integrity import audit_hdf5  # noqa: E402


SCHEMA = "ds-data-02.f2-native-observations.v1"
DESTINATION_CODES = {
    "unknown": 0,
    "cup": 1,
    "receiver": 2,
    "tray": 3,
    "inflight": 4,
}
EVENT_CODES = {
    "cup_departure": 1,
    "cup_return": 2,
    "receiver_entry": 3,
    "receiver_exit": 4,
    "tray_entry": 5,
    "tray_exit": 6,
}
EVENT_DTYPE = np.dtype([
    ("time_s", "<f8"),
    ("event_code", "<i2"),
    ("direction", "<i1"),
    ("particle_index", "<i8"),
    ("zone", "<i8"),
    ("idp", "<i8"),
    ("source_mk", "<i4"),
    ("source_layer_index", "<i4"),
    ("mass_kg", "<f8"),
    ("frame_before", "<i8"),
    ("frame_after", "<i8"),
])


class ObservationError(RuntimeError):
    """Raised when native observation inputs are incomplete or inconsistent."""


def _json_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ObservationError(f"{label} cannot be read as JSON: {path}") from error
    if not isinstance(value, dict):
        raise ObservationError(f"{label} must be a JSON object: {path}")
    return value


def _box_signed_margin(points: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Signed distance surrogate: positive inside, negative outside, in m."""
    distances = np.minimum(points - low, high - points)
    return distances.min(axis=-1)


def _inverse_rotate(points: np.ndarray, origin: np.ndarray, axis: np.ndarray,
                    angle: float) -> np.ndarray:
    shifted = np.asarray(points, dtype=np.float64) - origin
    cosine, sine = float(np.cos(-angle)), float(np.sin(-angle))
    cross = np.cross(axis, shifted)
    parallel = shifted @ axis
    return origin + cosine * shifted + sine * cross + (1.0 - cosine) * parallel[..., None] * axis


def _event_rows(*, code: int, direction: int, times: np.ndarray, margin: np.ndarray,
                aperture: np.ndarray | None, valid: np.ndarray, mass: np.ndarray,
                zone: np.ndarray, idp: np.ndarray, source_mk: np.ndarray,
                source_layer: np.ndarray, start_time: float) -> list[tuple[Any, ...]]:
    """Return interpolated boundary crossings for one finite region."""
    rows: list[tuple[Any, ...]] = []
    # ``margin`` is the signed surface/box margin.  A crossing tolerance is
    # applied to aperture geometry and time interpolation, while the physical
    # event surface itself is the zero-margin boundary specified by F2.
    entering = direction > 0
    for frame in range(1, len(times)):
        if times[frame] < start_time:
            continue
        previous = margin[frame - 1]
        current = margin[frame]
        previous_valid = valid[frame - 1]
        current_valid = valid[frame]
        if entering:
            crossed = (previous <= 0.0) & (current > 0.0)
        else:
            crossed = (previous > 0.0) & (current <= 0.0)
        crossed &= previous_valid & current_valid
        if aperture is not None:
            crossed &= aperture[frame]
        for particle in np.flatnonzero(crossed):
            denominator = float(current[particle] - previous[particle])
            alpha = 0.0 if denominator == 0.0 else float(np.clip(-previous[particle] / denominator, 0.0, 1.0))
            event_time = float(times[frame - 1] + alpha * (times[frame] - times[frame - 1]))
            # A segment that straddles the static-hold endpoint may cross the
            # surface before the declared event window.  Do not relabel that
            # pre-window crossing as a post-hold event merely because its
            # right endpoint was saved after ``start_time``.
            if event_time < start_time:
                continue
            rows.append((
                event_time, code, direction, int(particle), int(zone[particle]), int(idp[particle]),
                int(source_mk[particle]), int(source_layer[particle]), float(mass[particle]),
                frame - 1, frame,
            ))
    return rows


def _finite_geometry(owner: Mapping[str, Any]) -> dict[str, np.ndarray | float]:
    geometry = owner.get("geometry")
    if not isinstance(geometry, Mapping):
        raise ObservationError("F2 owner metadata has no structured geometry")
    required = ("cup_low_m", "cup_size_m", "receiver_low_m", "receiver_size_m",
                "tray_low_m", "tray_size_m")
    if any(key not in geometry for key in required):
        raise ObservationError(f"F2 geometry is missing finite regions: {required}")
    result: dict[str, np.ndarray | float] = {}
    for name in ("cup", "receiver", "tray"):
        low = np.asarray(geometry[f"{name}_low_m"], dtype=np.float64)
        size = np.asarray(geometry[f"{name}_size_m"], dtype=np.float64)
        if low.shape != (3,) or size.shape != (3,) or not np.all(np.isfinite(low)) or not np.all(np.isfinite(size)) or np.any(size <= 0):
            raise ObservationError(f"F2 {name} geometry is not a finite positive 3D box")
        result[f"{name}_low_m"] = low
        result[f"{name}_high_m"] = low + size
    result["crossing_tolerance_m"] = float(owner.get("quality_contract", {}).get("event_thresholds", {}).get("cup_mouth", {}).get("crossing_tolerance_m", 0.0125))
    if not np.isfinite(result["crossing_tolerance_m"]) or result["crossing_tolerance_m"] <= 0:
        raise ObservationError("F2 crossing tolerance must be finite and positive")
    return result


def _physical_and_numerical_hashes(owner: Mapping[str, Any], trajectory_attrs: Mapping[str, Any]) -> dict[str, str]:
    geometry = owner.get("geometry", {})
    physical = {
        "family_id": owner.get("family_id"),
        "physical_case_id": owner.get("physical_case_id"),
        "geometry_family_id": owner.get("geometry_family_id"),
        "geometry": geometry,
        "parameter_values": owner.get("parameter_values", {}),
        "event_window": owner.get("event_window", {}),
        "control_family_id": owner.get("control_family_id"),
        "motion_control_sha256": trajectory_attrs.get("motion_control_copied_sha256", ""),
    }
    numerical = {
        "resolution": owner.get("resolution"),
        "solver_parameters": owner.get("solver_parameters", {}),
        "trajectory_resolution": trajectory_attrs.get("resolution", ""),
        "source_format": trajectory_attrs.get("source_format", ""),
    }
    return {
        "physical_condition_sha256": _canonical_sha256(physical),
        "numerical_recipe_sha256": _canonical_sha256(numerical),
        "physical_condition_fields_json": json.dumps(_json_value(physical), ensure_ascii=False, sort_keys=True),
        "numerical_recipe_fields_json": json.dumps(_json_value(numerical), ensure_ascii=False, sort_keys=True),
    }


def observe(*, trajectory: Path, owner_metadata: Path, output: Path, report: Path,
            conversion_report: Path | None = None) -> dict[str, Any]:
    owner = _load_json(owner_metadata, "F2 owner metadata")
    if owner.get("family_id") != "F2" or not str(owner.get("schema", "")).endswith("generator.v1"):
        raise ObservationError("owner metadata is not a DS-DATA-02 F2 generator record")
    if not trajectory.is_file():
        raise ObservationError(f"trajectory HDF5 is missing: {trajectory}")
    geometry = _finite_geometry(owner)
    tolerance = float(geometry["crossing_tolerance_m"])
    event_window = owner.get("event_window", {})
    start_time = float(event_window.get("hold_start_s", 0.0))
    # These are frozen before loading any result-dependent arrays.
    thresholds = {
        "crossing_tolerance_m": tolerance,
        "boundary_surface_definition": "zero signed margin; interpolation between native saved frames",
        "cup_mouth_local_x_m": float(np.asarray(geometry["cup_low_m"])[0] + np.asarray(owner["geometry"]["cup_size_m"])[0] - 0.05),
        "cup_mouth_aperture": "cup body y/z bounds expanded by +/- crossing_tolerance_m",
        "event_start_time_s": start_time,
        "unknown_definition": "invalid native identity or outside cup/receiver/tray at frame",
        "mass_denominator": "initial native Type=3 fluid cohort, source Mk layers retained",
    }
    with h5py.File(trajectory, "r") as source:
        required = ("time", "position", "velocity", "mass", "mk", "type", "valid", "particle_zone", "particle_id", "rigid_body_state")
        missing = [name for name in required if name not in source]
        if missing:
            raise ObservationError(f"converted trajectory is missing required state datasets: {missing}")
        times = np.asarray(source["time"][:], dtype=np.float64)
        if len(times) < 2 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
            raise ObservationError("trajectory time axis is not finite and strictly increasing")
        type_initial = np.asarray(source["type"][0, :], dtype=np.int64)
        fluid_indices = np.flatnonzero(type_initial == 3)
        if not len(fluid_indices):
            raise ObservationError("trajectory has no initial native Type=3 fluid particles")
        rigid = np.asarray(source["rigid_body_state"][:])
        if len(rigid) != len(times) or not np.all(np.isfinite(rigid["actual_angle_rad"])):
            raise ObservationError("rigid_body_state is not frame-aligned and finite")
        zone = np.asarray(source["particle_zone"][fluid_indices], dtype=np.int64)
        idp = np.asarray(source["particle_id"][fluid_indices], dtype=np.int64)
        source_mk = np.asarray(source["mk"][0, fluid_indices], dtype=np.int64)
        unique_mk = sorted(int(value) for value in np.unique(source_mk))
        source_layer = np.asarray([unique_mk.index(int(value)) for value in source_mk], dtype=np.int32)
        source_mass = np.asarray(source["mass"][0, fluid_indices], dtype=np.float64)
        if not np.all(np.isfinite(source_mass)) or np.any(source_mass <= 0):
            raise ObservationError("initial fluid mass is not finite and positive")
        fluid_count = len(fluid_indices)
        frames = len(times)
        destination = np.zeros((frames, fluid_count), dtype=np.int8)
        valid_out = np.zeros((frames, fluid_count), dtype=np.uint8)
        cup_margin = np.full((frames, fluid_count), np.nan, dtype=np.float32)
        receiver_margin = np.full((frames, fluid_count), np.nan, dtype=np.float32)
        tray_margin = np.full((frames, fluid_count), np.nan, dtype=np.float32)
        mouth_margin = np.full((frames, fluid_count), np.nan, dtype=np.float32)
        # The actual rigid pose is fitted from saved Type=1 moving nodes.  A
        # sign selected for the copied control is not used to rotate fluid;
        # the observed actual pose is the sole frame transform here.
        cup_low = np.asarray(geometry["cup_low_m"], dtype=np.float64)
        cup_high = np.asarray(geometry["cup_high_m"], dtype=np.float64)
        receiver_low = np.asarray(geometry["receiver_low_m"], dtype=np.float64)
        receiver_high = np.asarray(geometry["receiver_high_m"], dtype=np.float64)
        tray_low = np.asarray(geometry["tray_low_m"], dtype=np.float64)
        tray_high = np.asarray(geometry["tray_high_m"], dtype=np.float64)
        origin = np.asarray([0.0, -1.0, 0.65], dtype=np.float64)
        axis = np.asarray([0.0, 1.0, 0.0], dtype=np.float64)
        parsed = owner.get("geometry", {}).get("motion_axis", "")
        if isinstance(parsed, str) and "axisp1=" in parsed:
            # The XML/rigid dataset remains authoritative.  This metadata
            # check only records the F2 axis convention; it is not inferred
            # from fluid coordinates.
            pass
        cup_low_inner = cup_low + tolerance
        cup_high_inner = cup_high - tolerance
        receiver_low_inner = receiver_low + tolerance
        receiver_high_inner = receiver_high - tolerance
        tray_low_inner = tray_low + tolerance
        tray_high_inner = tray_high - tolerance
        aperture_low = cup_low[1:] - tolerance
        aperture_high = cup_high[1:] + tolerance
        mouth_x = float(cup_low[0] + (cup_high[0] - cup_low[0]) - 0.05)
        for frame in range(frames):
            with_frame = np.asarray(source["position"][frame, fluid_indices, :], dtype=np.float64)
            valid = np.asarray(source["valid"][frame, fluid_indices], dtype=bool)
            valid_out[frame, :] = valid.astype(np.uint8)
            body = _inverse_rotate(with_frame, origin, axis, float(rigid[frame]["actual_angle_rad"]))
            c_margin = _box_signed_margin(body, cup_low_inner, cup_high_inner)
            r_margin = _box_signed_margin(with_frame, receiver_low_inner, receiver_high_inner)
            t_margin = _box_signed_margin(with_frame, tray_low_inner, tray_high_inner)
            m_margin = body[:, 0] - mouth_x
            cup = valid & (c_margin > 0.0)
            receiver = valid & ~cup & (r_margin > 0.0)
            tray = valid & ~cup & ~receiver & (t_margin > 0.0)
            inflight = valid & ~cup & ~receiver & ~tray
            destination[frame, cup] = DESTINATION_CODES["cup"]
            destination[frame, receiver] = DESTINATION_CODES["receiver"]
            destination[frame, tray] = DESTINATION_CODES["tray"]
            destination[frame, inflight] = DESTINATION_CODES["inflight"]
            cup_margin[frame, :] = c_margin.astype(np.float32)
            receiver_margin[frame, :] = r_margin.astype(np.float32)
            tray_margin[frame, :] = t_margin.astype(np.float32)
            mouth_margin[frame, :] = m_margin.astype(np.float32)

        aperture = np.zeros_like(destination, dtype=bool)
        # Reconstruct aperture from saved state using the same actual pose.
        for frame in range(frames):
            points = np.asarray(source["position"][frame, fluid_indices, :], dtype=np.float64)
            body = _inverse_rotate(points, origin, axis, float(rigid[frame]["actual_angle_rad"]))
            aperture[frame] = (
                (body[:, 1] >= aperture_low[0]) & (body[:, 1] <= aperture_high[0]) &
                (body[:, 2] >= aperture_low[1]) & (body[:, 2] <= aperture_high[1]) &
                (valid_out[frame] > 0)
            )
        event_rows: list[tuple[Any, ...]] = []
        event_rows.extend(_event_rows(
            code=EVENT_CODES["cup_departure"], direction=1, times=times,
            margin=mouth_margin, aperture=aperture, valid=valid_out.astype(bool),
            mass=source_mass, zone=zone, idp=idp, source_mk=source_mk,
            source_layer=source_layer, start_time=start_time,
        ))
        event_rows.extend(_event_rows(
            code=EVENT_CODES["cup_return"], direction=-1, times=times,
            margin=mouth_margin, aperture=aperture, valid=valid_out.astype(bool),
            mass=source_mass, zone=zone, idp=idp, source_mk=source_mk,
            source_layer=source_layer, start_time=start_time,
        ))
        event_rows.extend(_event_rows(
            code=EVENT_CODES["receiver_entry"], direction=1, times=times,
            margin=receiver_margin, aperture=None, valid=valid_out.astype(bool),
            mass=source_mass, zone=zone, idp=idp, source_mk=source_mk,
            source_layer=source_layer, start_time=start_time,
        ))
        event_rows.extend(_event_rows(
            code=EVENT_CODES["receiver_exit"], direction=-1, times=times,
            margin=receiver_margin, aperture=None, valid=valid_out.astype(bool),
            mass=source_mass, zone=zone, idp=idp, source_mk=source_mk,
            source_layer=source_layer, start_time=start_time,
        ))
        event_rows.extend(_event_rows(
            code=EVENT_CODES["tray_entry"], direction=1, times=times,
            margin=tray_margin, aperture=None, valid=valid_out.astype(bool),
            mass=source_mass, zone=zone, idp=idp, source_mk=source_mk,
            source_layer=source_layer, start_time=start_time,
        ))
        event_rows.extend(_event_rows(
            code=EVENT_CODES["tray_exit"], direction=-1, times=times,
            margin=tray_margin, aperture=None, valid=valid_out.astype(bool),
            mass=source_mass, zone=zone, idp=idp, source_mk=source_mk,
            source_layer=source_layer, start_time=start_time,
        ))
        events = np.asarray(event_rows, dtype=EVENT_DTYPE) if event_rows else np.empty(0, dtype=EVENT_DTYPE)
        order = np.argsort(events["time_s"], kind="stable")
        events = events[order]
        destination_mass = np.zeros((frames, len(DESTINATION_CODES)), dtype=np.float64)
        for code in DESTINATION_CODES.values():
            destination_mass[:, code] = np.sum(np.where(destination == code, source_mass[None, :], 0.0), axis=1)
        source_mass_by_layer = {str(layer): float(source_mass[source_layer == layer].sum()) for layer in sorted(set(source_layer.tolist()))}
        final_mass_by_destination = {name: float(destination_mass[-1, code]) for name, code in DESTINATION_CODES.items()}
        initial_mass = float(source_mass.sum())
        unknown_mass = float(destination_mass[:, DESTINATION_CODES["unknown"]].max())
        attrs = {str(key): source.attrs[key] for key in source.attrs.keys()}
        hash_fields = _physical_and_numerical_hashes(owner, attrs)
        # The converter's report carries the solver Run.out binding and the
        # authoritative source Q-I audit.  A direct fallback audit remains
        # useful for callers that only have an HDF5 path, but it cannot invent
        # the external solver log provenance.
        source_conversion_report: dict[str, Any] | None = None
        if conversion_report is not None and conversion_report.is_file():
            source_conversion_report = _load_json(conversion_report, "conversion report")
        q_i_audit = (source_conversion_report or {}).get("q_i_audit") if source_conversion_report else None
        if not isinstance(q_i_audit, Mapping):
            q_i_audit = audit_hdf5(trajectory)
        output.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(output, "w") as labels:
            labels.create_dataset("time", data=times)
            labels.create_dataset("particle_zone", data=zone)
            labels.create_dataset("particle_id", data=idp)
            labels.create_dataset("source_mk", data=source_mk)
            labels.create_dataset("source_layer_index", data=source_layer)
            labels.create_dataset("source_mass_kg", data=source_mass)
            labels.create_dataset("valid", data=valid_out, compression="gzip")
            labels.create_dataset("destination_code", data=destination, compression="gzip")
            labels.create_dataset("cup_body_signed_margin_m", data=cup_margin, compression="gzip")
            labels.create_dataset("cup_mouth_signed_margin_m", data=mouth_margin, compression="gzip")
            labels.create_dataset("receiver_signed_margin_m", data=receiver_margin, compression="gzip")
            labels.create_dataset("tray_signed_margin_m", data=tray_margin, compression="gzip")
            labels.create_dataset("rigid_body_angle_rad", data=np.asarray(rigid["actual_angle_rad"], dtype=np.float64))
            labels.create_dataset("destination_mass_kg", data=destination_mass)
            labels.create_dataset("events", data=events, compression="gzip")
            labels.attrs["schema"] = SCHEMA
            labels.attrs["case_id"] = str(owner.get("case_id", ""))
            labels.attrs["trajectory_sha256"] = _sha256(trajectory)
            labels.attrs["owner_metadata_sha256"] = _sha256(owner_metadata)
            labels.attrs["destination_codes_json"] = json.dumps(DESTINATION_CODES, sort_keys=True)
            labels.attrs["event_codes_json"] = json.dumps(EVENT_CODES, sort_keys=True)
            labels.attrs["thresholds_json"] = json.dumps(_json_value(thresholds), sort_keys=True)
            labels.attrs["physical_condition_sha256"] = hash_fields["physical_condition_sha256"]
            labels.attrs["numerical_recipe_sha256"] = hash_fields["numerical_recipe_sha256"]
            labels.attrs["source_semantics"] = "initial native Type=3 fluid cohort; source Mk retained; no synthetic births"
            labels.attrs["unknown_semantics"] = "invalid native identities and outside finite declared regions; excluded from spill/tray"
        report_payload: dict[str, Any] = {
            "schema": SCHEMA,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "case_id": owner.get("case_id"),
            "family_id": "F2",
            "mechanism_id": owner.get("mechanism_id"),
            "trajectory": {"path": str(trajectory.resolve()), "sha256": _sha256(trajectory)},
            "owner_metadata": {"path": str(owner_metadata.resolve()), "sha256": _sha256(owner_metadata)},
            "conversion_report": ({"path": str(conversion_report.resolve()), "sha256": _sha256(conversion_report)}
                                  if conversion_report is not None and conversion_report.is_file() else None),
            "output": {"path": str(output.resolve()), "sha256": _sha256(output)},
            "thresholds_frozen_before_observation": thresholds,
            "geometry_evidence": {
                "finite_3d_boxes": {name: {"low_m": _json_value(geometry[f"{name}_low_m"]), "high_m": _json_value(geometry[f"{name}_high_m"])} for name in ("cup", "receiver", "tray")},
                "motion_axis_origin_m": _json_value(origin),
                "motion_axis_unit": _json_value(axis),
                "actual_rigid_body_dataset": "rigid_body_state.actual_angle_rad",
                "control_sign_applied": float(source.attrs.get("rigid_body_state_control_sign_applied", np.nan)),
            },
            "physical_condition_hash": hash_fields["physical_condition_sha256"],
            "physical_condition_fields": json.loads(hash_fields["physical_condition_fields_json"]),
            "numerical_recipe_hash": hash_fields["numerical_recipe_sha256"],
            "numerical_recipe_fields": json.loads(hash_fields["numerical_recipe_fields_json"]),
            "dimensions": {"frames": frames, "initial_fluid_particles": fluid_count, "coordinate_components": 3},
            "source_population": {
                "source_mk_codes": unique_mk,
                "source_layer_mapping": {str(code): index for index, code in enumerate(unique_mk)},
                "source_count_by_layer": {str(layer): int((source_layer == layer).sum()) for layer in sorted(set(source_layer.tolist()))},
                "source_mass_kg_by_layer": source_mass_by_layer,
                "initial_fluid_mass_kg": initial_mass,
                "final_valid_fluid_count": int(valid_out[-1].sum()),
                "final_missing_fluid_count": int((valid_out[0] > 0).sum() - valid_out[-1].sum()),
            },
            "destination_codes": DESTINATION_CODES,
            "destination_mass_kg_by_frame": destination_mass.tolist(),
            "final_mass_kg_by_destination": final_mass_by_destination,
            "unknown_mass_kg_max": unknown_mass,
            "event_ledger": {
                "status": "complete_for_saved_native_frames",
                "event_codes": EVENT_CODES,
                "event_count": int(len(events)),
                "counts_by_code": {name: int((events["event_code"] == code).sum()) for name, code in EVENT_CODES.items()},
                "mass_kg_by_code": {name: float(events["mass_kg"][events["event_code"] == code].sum()) for name, code in EVENT_CODES.items()},
                "first_time_s_by_code": {name: (float(events["time_s"][events["event_code"] == code].min()) if np.any(events["event_code"] == code) else None) for name, code in EVENT_CODES.items()},
                "net_flux_kg_by_region": {
                    "cup": float(events["mass_kg"][events["event_code"] == EVENT_CODES["cup_departure"]].sum() - events["mass_kg"][events["event_code"] == EVENT_CODES["cup_return"]].sum()),
                    "receiver": float(events["mass_kg"][events["event_code"] == EVENT_CODES["receiver_entry"]].sum() - events["mass_kg"][events["event_code"] == EVENT_CODES["receiver_exit"]].sum()),
                    "tray": float(events["mass_kg"][events["event_code"] == EVENT_CODES["tray_entry"]].sum() - events["mass_kg"][events["event_code"] == EVENT_CODES["tray_exit"]].sum()),
                },
                "unknown_is_separate_from_spill_or_tray": True,
            },
            "lifecycle": {
                "initial_ids_retained": True,
                "introduced_after_initial_count": 0,
                "native_invalid_rows": int((valid_out == 0).sum()),
                "open_boundary_births_inferred": 0,
                "excluded_identities_remain_unknown": True,
            },
            "q_i": {
                "converted_trajectory_audit": q_i_audit,
                "finite_geometry": "pass",
                "3d_actual_state": bool(int(attrs.get("solver_dimension", -1)) == 3),
                "nonzero_fluid_and_positive_initial_mass": bool(fluid_count > 0 and initial_mass > 0),
                "motion_pose_actual_saved_nodes": bool(np.isfinite(rigid["actual_angle_rad"]).all()),
                "event_ledger_native_frame_coverage": True,
                "status": ("Q-I-event-evidence-ready; source conversion audit still records open-boundary ledger pending"
                           if q_i_audit.get("q_i_status") == "Q-I-incomplete" else "Q-I-event-evidence-ready"),
            },
            "q_n": {"status": "not_assessed", "reason": "requires paired resolutions plus independent integration and save studies"},
            "production_eligibility": "not_evaluated",
        }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(_json_value(report_payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # The output hash is deliberately reported after writing the report's
    # content; labels remain immutable for downstream scheduling.
    return report_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--owner-metadata", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        observe(trajectory=args.trajectory.resolve(), owner_metadata=args.owner_metadata.resolve(),
                conversion_report=(args.conversion_report.resolve() if args.conversion_report else None),
                output=args.output.resolve(), report=args.report.resolve())
    except (ObservationError, OSError, ValueError, KeyError) as error:
        print(f"f2_native_observations: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

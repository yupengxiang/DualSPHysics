#!/usr/bin/env python3
"""Generate the independent F2 v6 event observation product.

The consumed F2 labels use a local-x mouth predicate.  F2's cup is open on
its local-z top face, so this module is a separate observation operator.  It
uses the saved ``rigid_body_state.actual_angle_rad`` at every frame and keeps
the source physical condition hash separate from this operator hash.

The operator has four deliberate rules:

* cup departure and return are crossings of the moving local-z top face;
  aperture membership is tested at the interpolated crossing pose, so a
  diagonal path may have an endpoint outside the footprint;
* a tray entry is a spill observation only after a top departure;
* an invalid native identity stays ``unknown`` and receives a reason code;
* a native exclusion is never silently called physical spill.  The optional
  PartVTKOut exclusion ledger is used only to distinguish a legal tray
  candidate, a closed finite-wall crossing, and an open-top/domain candidate.

This is an evidence producer.  It does not grant Q-N or production status.
The ``batch-old-six`` command reads the six already converted legacy H5
trajectories and writes new v6 labels and a real cross-resolution comparison
under the data root.  It never edits the consumed v1 labels.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping

import h5py
import numpy as np


SCHEMA = "ds-data-02.f2.event-semantics.v6"
OPERATOR_VERSION = "f2-moving-cup-local-z-top-v6"
DESTINATION_CODES = {
    "unknown": 0,
    "cup": 1,
    "receiver": 2,
    "tray": 3,
    "inflight": 4,
}
EVENT_CODES = {
    "cup_top_departure": 1,
    "cup_top_return": 2,
    "receiver_entry": 3,
    "receiver_exit": 4,
    "tray_entry": 5,
    "tray_exit": 6,
}
UNKNOWN_REASON_CODES = {
    "none": 0,
    "native_invalid": 1,
    "native_invalid_closed_wall_crossing": 2,
    "native_invalid_legal_tray_candidate": 3,
    "native_invalid_after_open_top_or_domain": 4,
    "native_invalid_unclassified": 5,
    "lifecycle_type_change": 6,
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

# These are the frozen F2 budgets.  They are copied from the campaign
# quality_contract.json by ``_quality_contract_binding`` and asserted before
# reading result-dependent arrays.
EVENT_TIME_ABSOLUTE_BUDGET_S = 0.0036681953999691376
SAVE_FRACTION_MAX = 0.2
SAVE_HALF_WIDTH_BUDGET_S = EVENT_TIME_ABSOLUTE_BUDGET_S * SAVE_FRACTION_MAX
MASS_REFERENCE_RELATIVE_BUDGET = 1.0e-12


class ObservationError(RuntimeError):
    """Raised when a v6 observation input is incomplete."""


def _json_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, Path):
        return str(value)
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
        raise ObservationError(f"{label} cannot be read: {path}") from error
    if not isinstance(value, dict):
        raise ObservationError(f"{label} must be a JSON object: {path}")
    return value


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _inverse_rotate(points: np.ndarray, origin: np.ndarray, axis: np.ndarray,
                    angle: float) -> np.ndarray:
    """Transform world points into the cup's body-frame coordinates."""
    shifted = np.asarray(points, dtype=np.float64) - origin
    cosine, sine = float(np.cos(-angle)), float(np.sin(-angle))
    cross = np.cross(axis, shifted)
    parallel = shifted @ axis
    return origin + cosine * shifted + sine * cross + (1.0 - cosine) * parallel[..., None] * axis


def _inverse_rotate_variable(points: np.ndarray, origin: np.ndarray, axis: np.ndarray,
                             angles: np.ndarray) -> np.ndarray:
    """Inverse-rotate a batch of points with one saved pose angle per point."""
    shifted = np.asarray(points, dtype=np.float64) - origin
    angles = np.asarray(angles, dtype=np.float64)
    cosine, sine = np.cos(-angles)[:, None], np.sin(-angles)[:, None]
    cross = np.cross(axis, shifted)
    parallel = shifted @ axis
    return origin + cosine * shifted + sine * cross + (1.0 - cosine) * parallel[:, None] * axis


def _box_margin(points: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    distances = np.minimum(points - low, high - points)
    return distances.min(axis=-1)


def _owner_geometry(owner: Mapping[str, Any], attrs: Mapping[str, Any]) -> dict[str, np.ndarray | float]:
    geometry = owner.get("geometry")
    if not isinstance(geometry, Mapping):
        raise ObservationError("owner metadata has no geometry object")
    result: dict[str, np.ndarray | float] = {}
    for name in ("cup", "receiver", "tray"):
        low_key, size_key = f"{name}_low_m", f"{name}_size_m"
        if low_key not in geometry or size_key not in geometry:
            raise ObservationError(f"owner geometry is missing {name} low/size")
        low = np.asarray(geometry[low_key], dtype=np.float64)
        size = np.asarray(geometry[size_key], dtype=np.float64)
        if low.shape != (3,) or size.shape != (3,) or not np.all(np.isfinite(low)) or not np.all(np.isfinite(size)) or np.any(size <= 0):
            raise ObservationError(f"{name} is not a finite positive 3D box")
        result[f"{name}_low_m"] = low
        result[f"{name}_high_m"] = low + size
    try:
        tolerance = float(owner["quality_contract"]["event_thresholds"]["cup_mouth"]["crossing_tolerance_m"])
    except (KeyError, TypeError, ValueError):
        tolerance = 0.0125
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ObservationError("event crossing tolerance must be finite and positive")
    result["crossing_tolerance_m"] = tolerance

    binding = owner.get("physical_binding")
    parameters = binding.get("parameters", {}) if isinstance(binding, Mapping) else {}
    origin = np.asarray(parameters.get("motion_axis_origin_m", [0.0, -1.0, 0.65]), dtype=np.float64)
    axis = np.asarray(parameters.get("motion_axis_unit", [0.0, 1.0, 0.0]), dtype=np.float64)
    if origin.shape != (3,) or axis.shape != (3,) or not np.all(np.isfinite(origin)) or not np.all(np.isfinite(axis)):
        raise ObservationError("motion axis origin/unit are not finite 3D values")
    norm = float(np.linalg.norm(axis))
    if norm <= 0:
        raise ObservationError("motion axis unit has zero norm")
    result["motion_axis_origin_m"] = origin
    result["motion_axis_unit"] = axis / norm
    # The source H5 stores the axis too.  A disagreement is evidence of an
    # input binding problem and must not be silently corrected by this operator.
    if "rigid_body_state_axis_origin_m" in attrs:
        saved_origin = np.asarray(attrs["rigid_body_state_axis_origin_m"], dtype=np.float64)
        if saved_origin.shape == (3,) and not np.allclose(saved_origin, origin, atol=1e-12, rtol=0):
            raise ObservationError("owner motion origin disagrees with saved rigid-body axis")
    if "rigid_body_state_axis_unit" in attrs:
        saved_axis = np.asarray(attrs["rigid_body_state_axis_unit"], dtype=np.float64)
        if saved_axis.shape == (3,) and not np.allclose(saved_axis / np.linalg.norm(saved_axis), axis / norm, atol=1e-12, rtol=0):
            raise ObservationError("owner motion axis disagrees with saved rigid-body axis")
    return result


def _quality_contract_binding() -> dict[str, Any]:
    path = Path(__file__).with_name("quality_contract.json")
    if not path.is_file():
        raise ObservationError(f"frozen quality contract is missing: {path}")
    contract = _load_json(path, "F2 quality contract")
    values: list[float] = []
    for record in contract.get("background_contracts", {}).values():
        qn = record.get("q_n", {}) if isinstance(record, Mapping) else {}
        values.append(float(qn.get("event_time_absolute_budget_s", -1.0)))
    if not values or any(abs(value - EVENT_TIME_ABSOLUTE_BUDGET_S) > 1e-15 for value in values):
        raise ObservationError("frozen quality contract event budget is not the v6 budget")
    return {"path": str(path.resolve()), "sha256": _sha256(path),
            "event_time_absolute_budget_s": EVENT_TIME_ABSOLUTE_BUDGET_S,
            "save_fraction_max": SAVE_FRACTION_MAX,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "mass_reference_relative_budget": MASS_REFERENCE_RELATIVE_BUDGET}


def operator_spec() -> dict[str, Any]:
    """Return the frozen observation semantics whose hash is independent of case resolution."""
    return {
        "schema": SCHEMA,
        "operator_version": OPERATOR_VERSION,
        "cup_opening": {
            "surface": "moving finite cup local-z=body-frame cup_high_z face",
            "aperture": "body-frame x/y inside cup footprint expanded by crossing_tolerance_m at interpolated crossing pose",
            "departure": "outward signed local-z crossing, previous<=0 and current>0",
            "return": "inward signed local-z crossing after a prior departure, previous>0 and current<=0",
            "pose": "saved rigid_body_state.actual_angle_rad only",
            "crossing_pose": "linear interpolation of world particle position and saved body angle at the signed-margin crossing",
        },
        "destination_precedence": ["unknown_invalid", "cup", "receiver", "tray_after_departure", "inflight"],
        "receiver": "finite world receiver interior after one boundary tolerance; repeated crossings retained",
        "tray": "finite world tray interior after one boundary tolerance and only after top departure",
        "unknown": {
            "invalid_native_identity": "unknown; never relabeled as spill",
            "closed_wall_crossing": "separate reason from legal tray candidate",
            "open_top_or_domain": "separate reason; native Motive is retained",
            "births": "not inferred; initial Type=3 cohort only",
        },
        "finite_wall_policy": "cup/receiver/tray bottom and side faces are closed; top faces are open; domain exits remain native exclusions",
        "event_time": "linear interpolation between consecutive native saved frames",
        "thresholds": {
            "event_time_absolute_budget_s": EVENT_TIME_ABSOLUTE_BUDGET_S,
            "save_fraction_max": SAVE_FRACTION_MAX,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
        },
    }


def operator_hash() -> str:
    return _canonical_sha256(operator_spec())


def _parse_exclusion_csv(path: Path | None) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    if path is None:
        return {}, {"path": None, "sha256": None, "rows": 0, "motive_counts": {}}
    if not path.is_file():
        raise ObservationError(f"native exclusion CSV is missing: {path}")
    rows: dict[int, dict[str, Any]] = {}
    motive_counts: dict[str, int] = {}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = [item.strip() for item in next(reader)]
        except StopIteration as error:
            raise ObservationError(f"native exclusion CSV is empty: {path}") from error
        names = {name: index for index, name in enumerate(header)}
        required = ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "PartOut", "Motive", "Idp")
        missing_columns = [name for name in required if name not in names]
        # The native PartVTKOut helper writes a position-only header when no
        # particle was excluded.  That is a valid zero-row ledger, while a
        # non-empty ledger with that header is malformed and must fail.
        remaining = list(reader)
        if missing_columns and not any(row and any(item.strip() for item in row) for row in remaining):
            return {}, {"path": str(path.resolve()), "sha256": _sha256(path), "rows": 0,
                        "motive_counts": {}, "empty_header_only": True}
        if missing_columns:
            raise ObservationError(f"native exclusion CSV lacks required columns: {required}")
        for raw in remaining:
            if not raw or not any(item.strip() for item in raw):
                continue
            try:
                idp = int(float(raw[names["Idp"]].strip()))
                record = {
                    "position_m": [float(raw[names[f"Pos.{axis} [m]"]].strip()) for axis in ("x", "y", "z")],
                    "partout": int(float(raw[names["PartOut"]].strip())),
                    "motive": int(float(raw[names["Motive"]].strip())),
                }
                for axis in ("x", "y", "z"):
                    key = f"Vel.{axis} [m/s]"
                    if key in names:
                        record.setdefault("velocity_m_s", []).append(float(raw[names[key]].strip()))
                if "Rhop [kg/m^3]" in names:
                    record["density_kg_m3"] = float(raw[names["Rhop [kg/m^3]"]].strip())
            except (IndexError, ValueError) as error:
                raise ObservationError(f"native exclusion CSV has an invalid row: {raw}") from error
            previous = rows.get(idp)
            if previous is None or int(record["partout"]) < int(previous["partout"]):
                rows[idp] = record
            motive = str(record["motive"])
            motive_counts[motive] = motive_counts.get(motive, 0) + 1
    return rows, {"path": str(path.resolve()), "sha256": _sha256(path),
                  "rows": sum(motive_counts.values()), "motive_counts": motive_counts}


def _source_layer(source_mk: np.ndarray) -> np.ndarray:
    codes = sorted(int(value) for value in np.unique(source_mk))
    mapping = {code: index for index, code in enumerate(codes)}
    return np.asarray([mapping[int(value)] for value in source_mk], dtype=np.int32)


def _native_mass_reference(owner: Mapping[str, Any], fluid_count: int,
                           adapter_mass: np.ndarray) -> dict[str, Any]:
    """Bind exact decimal MassFluid from generated XML and quantify H5 adapter error.

    ``initial_mass`` in the converted H5 is float32 for compatibility with the
    native fields.  The generated XML's decimal ``massfluid`` value is the
    frozen source authority for this sidecar, so the two values are reported
    separately and never silently normalized.
    """
    continuous = owner.get("mass_reference", {}).get("continuous_mass_kg")
    if continuous is None:
        continuous = owner.get("physical_binding", {}).get("initial_state", {}).get("initial_mass_total_kg")
    continuous_decimal = Decimal(str(continuous)) if continuous is not None else None
    definition = owner.get("definition", {})
    xml_path = Path(str(definition.get("path", ""))) if isinstance(definition, Mapping) else Path()
    xml_text = ""
    xml_sha = None
    mass_text = None
    if xml_path.is_file():
        xml_text = xml_path.read_text(encoding="utf-8", errors="replace")
        xml_sha = _sha256(xml_path)
        match = re.search(r"<massfluid\b[^>]*\bvalue\s*=\s*[\"']([^\"']+)[\"']", xml_text, flags=re.IGNORECASE)
        if match:
            mass_text = match.group(1)
    exact_status = "unavailable"
    massfluid_decimal = None
    if mass_text is not None:
        try:
            massfluid_decimal = Decimal(mass_text)
        except InvalidOperation:
            massfluid_decimal = None
    native_total_decimal = massfluid_decimal * Decimal(fluid_count) if massfluid_decimal is not None else None
    if native_total_decimal is not None and continuous_decimal is not None:
        relative = abs(native_total_decimal - continuous_decimal) / abs(continuous_decimal) if continuous_decimal else None
        exact_status = "pass" if relative is not None and relative <= Decimal(str(MASS_REFERENCE_RELATIVE_BUDGET)) else "fail"
    else:
        relative = None
    adapter_total = Decimal(str(float(np.asarray(adapter_mass, dtype=np.float64).sum())))
    adapter_relative = (abs(adapter_total - native_total_decimal) / abs(native_total_decimal)
                        if native_total_decimal is not None and native_total_decimal else None)
    return {
        "generated_xml_path": str(xml_path.resolve()) if xml_path.is_file() else str(xml_path),
        "generated_xml_sha256": xml_sha,
        "massfluid_decimal_text": mass_text,
        "massfluid_kg_per_particle": float(massfluid_decimal) if massfluid_decimal is not None else None,
        "fluid_particle_count": int(fluid_count),
        "native_header_cohort_mass_decimal_kg": str(native_total_decimal) if native_total_decimal is not None else None,
        "native_header_cohort_mass_kg": float(native_total_decimal) if native_total_decimal is not None else None,
        "continuous_mass_decimal_kg": str(continuous_decimal) if continuous_decimal is not None else None,
        "continuous_mass_kg": float(continuous_decimal) if continuous_decimal is not None else None,
        "native_vs_continuous_relative_error": float(relative) if relative is not None else None,
        "strict_native_vs_continuous_status": exact_status,
        "h5_float32_adapter_mass_kg": float(adapter_total),
        "h5_adapter_relative_error_to_native": float(adapter_relative) if adapter_relative is not None else None,
        "authority": "generated XML MassFluid decimal bound to source BI4; H5 initial_mass is an adapter representation",
    }


def _event_tuple(event_time: float, code: int, direction: int, particle: int,
                 frame_before: int, frame_after: int, zone: np.ndarray,
                 idp: np.ndarray, source_mk: np.ndarray, source_layer: np.ndarray,
                 source_mass: np.ndarray) -> tuple[Any, ...]:
    return (float(event_time), int(code), int(direction), int(particle), int(zone[particle]),
            int(idp[particle]), int(source_mk[particle]), int(source_layer[particle]),
            float(source_mass[particle]), int(frame_before), int(frame_after))


def _interp_crossing(prev_margin: float, curr_margin: float, prev_time: float,
                     curr_time: float) -> float:
    denominator = float(curr_margin - prev_margin)
    alpha = 0.0 if denominator == 0.0 else float(np.clip(-prev_margin / denominator, 0.0, 1.0))
    return float(prev_time + alpha * (curr_time - prev_time))


def _open_top_mask(prev_body: np.ndarray, current_body: np.ndarray,
                   cup_low: np.ndarray, cup_high: np.ndarray,
                   tolerance: float) -> np.ndarray:
    """Return endpoints that can cross the open top instead of a closed wall."""
    current_inside_xy = (
        (current_body[:, 0] >= cup_low[0] - tolerance) &
        (current_body[:, 0] <= cup_high[0] + tolerance) &
        (current_body[:, 1] >= cup_low[1] - tolerance) &
        (current_body[:, 1] <= cup_high[1] + tolerance)
    )
    previous_inside_xy = (
        (prev_body[:, 0] >= cup_low[0] - tolerance) &
        (prev_body[:, 0] <= cup_high[0] + tolerance) &
        (prev_body[:, 1] >= cup_low[1] - tolerance) &
        (prev_body[:, 1] <= cup_high[1] + tolerance)
    )
    return previous_inside_xy & current_inside_xy & (current_body[:, 2] > cup_high[2])


def _interpolated_top_aperture(prev_world: np.ndarray, current_world: np.ndarray,
                               prev_top_margin: np.ndarray, current_top_margin: np.ndarray,
                               prev_angle: float, current_angle: float,
                               origin: np.ndarray, axis: np.ndarray,
                               cup_low: np.ndarray, cup_high: np.ndarray,
                               tolerance: float) -> np.ndarray:
    """Evaluate cup aperture at the signed top-plane crossing.

    Endpoint footprint membership is insufficient for a diagonal trajectory:
    the particle can cross the finite top face between two saved poses while
    being outside the footprint at the later endpoint.  Interpolate the world
    particle segment and the saved rigid pose at the margin crossing, then
    evaluate the point in that interpolated body frame.
    """
    denominator = current_top_margin - prev_top_margin
    alpha = np.zeros_like(denominator, dtype=np.float64)
    finite = np.isfinite(prev_top_margin) & np.isfinite(current_top_margin)
    nonzero = finite & (denominator != 0.0)
    alpha[nonzero] = np.clip(-prev_top_margin[nonzero] / denominator[nonzero], 0.0, 1.0)
    crossing_world = prev_world + alpha[:, None] * (current_world - prev_world)
    crossing_angle = float(prev_angle) + alpha * (float(current_angle) - float(prev_angle))
    result = np.zeros(len(prev_world), dtype=bool)
    finite_world = finite & np.all(np.isfinite(crossing_world), axis=1)
    if np.any(finite_world):
        body = _inverse_rotate_variable(crossing_world[finite_world], origin, axis,
                                        crossing_angle[finite_world])
        result[finite_world] = (
            (body[:, 0] >= cup_low[0] - tolerance) & (body[:, 0] <= cup_high[0] + tolerance) &
            (body[:, 1] >= cup_low[1] - tolerance) & (body[:, 1] <= cup_high[1] + tolerance)
        )
    return result


def _interpolated_world_top_aperture(prev_world: np.ndarray, current_world: np.ndarray,
                                     prev_margin: np.ndarray, current_margin: np.ndarray,
                                     low: np.ndarray, high: np.ndarray,
                                     tolerance: float) -> np.ndarray:
    """Evaluate a fixed receiver/tray top aperture at its crossing point."""
    denominator = current_margin - prev_margin
    alpha = np.zeros_like(denominator, dtype=np.float64)
    finite = np.isfinite(prev_margin) & np.isfinite(current_margin)
    nonzero = finite & (denominator != 0.0)
    alpha[nonzero] = np.clip(-prev_margin[nonzero] / denominator[nonzero], 0.0, 1.0)
    crossing = prev_world + alpha[:, None] * (current_world - prev_world)
    finite_crossing = finite & np.all(np.isfinite(crossing), axis=1)
    return finite_crossing & (crossing[:, 0] >= low[0] - tolerance) & (crossing[:, 0] <= high[0] + tolerance) & \
        (crossing[:, 1] >= low[1] - tolerance) & (crossing[:, 1] <= high[1] + tolerance)


def _open_top_world_mask(prev_world: np.ndarray, current_world: np.ndarray,
                         low: np.ndarray, high: np.ndarray,
                         tolerance: float) -> np.ndarray:
    previous_inside_xy = (
        (prev_world[:, 0] >= low[0] - tolerance) & (prev_world[:, 0] <= high[0] + tolerance) &
        (prev_world[:, 1] >= low[1] - tolerance) & (prev_world[:, 1] <= high[1] + tolerance)
    )
    current_inside_xy = (
        (current_world[:, 0] >= low[0] - tolerance) & (current_world[:, 0] <= high[0] + tolerance) &
        (current_world[:, 1] >= low[1] - tolerance) & (current_world[:, 1] <= high[1] + tolerance)
    )
    return previous_inside_xy & current_inside_xy & (current_world[:, 2] > high[2])


def _wall_crossing(prev_margin: np.ndarray, current_margin: np.ndarray,
                   prev_valid: np.ndarray, endpoint_valid: np.ndarray,
                   open_face: np.ndarray) -> np.ndarray:
    return prev_valid & endpoint_valid & (prev_margin > 0.0) & (current_margin <= 0.0) & ~open_face


def _flush_events(dataset: h5py.Dataset, buffer: list[tuple[Any, ...]]) -> None:
    if not buffer:
        return
    old_size = int(dataset.shape[0])
    dataset.resize((old_size + len(buffer),))
    dataset[old_size:] = np.asarray(buffer, dtype=EVENT_DTYPE)
    buffer.clear()


def _destination_mass(destination: np.ndarray, source_mass: np.ndarray) -> np.ndarray:
    result = np.zeros(len(DESTINATION_CODES), dtype=np.float64)
    for code in DESTINATION_CODES.values():
        result[code] = float(source_mass[destination == code].sum())
    return result


def _first_events(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    names = {value: key for key, value in EVENT_CODES.items()}
    for row in events:
        name = names[int(row["event_code"])]
        result.setdefault(name, row)
    for name in EVENT_CODES:
        result.setdefault(name, {"observed": False, "status": "right_censored_or_not_observed"})
    return result


def _record_bracket_stat(stats: dict[str, dict[str, Any]], name: str, width: float) -> None:
    record = stats[name]
    record["count"] += 1
    record["min_s"] = float(width) if record["min_s"] is None else min(float(record["min_s"]), float(width))
    record["max_s"] = float(width) if record["max_s"] is None else max(float(record["max_s"]), float(width))
    if float(width) > SAVE_HALF_WIDTH_BUDGET_S:
        record["all_within_budget"] = False


def _write_event_json_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def observe(*, trajectory: Path, owner_metadata: Path, output: Path, report: Path,
            exclusion_csv: Path | None = None, legacy_labels: Path | None = None,
            force: bool = False, definition_override: Path | None = None,
            numerical_recipe_hash_override: str | None = None,
            case_id_override: str | None = None) -> dict[str, Any]:
    """Generate one v6 label product from a converted full-state H5."""
    if output.exists() and not force:
        raise ObservationError(f"refusing to overwrite existing v6 labels: {output}")
    owner = _load_json(owner_metadata, "F2 owner metadata")
    owner_overrides: dict[str, Any] = {}
    if definition_override is not None:
        if not definition_override.is_file():
            raise ObservationError(f"definition override is missing: {definition_override}")
        owner["definition"] = {"path": str(definition_override.resolve()), "sha256": _sha256(definition_override)}
        owner_overrides["definition"] = owner["definition"]
    if numerical_recipe_hash_override:
        owner["numerical_recipe_hash_declared"] = str(numerical_recipe_hash_override)
        owner_overrides["numerical_recipe_hash_declared"] = str(numerical_recipe_hash_override)
    if case_id_override:
        owner["case_id"] = str(case_id_override)
        owner_overrides["case_id"] = str(case_id_override)
    if owner.get("family_id") != "F2":
        raise ObservationError("owner metadata is not an F2 record")
    if not trajectory.is_file():
        raise ObservationError(f"trajectory HDF5 is missing: {trajectory}")
    quality_binding = _quality_contract_binding()
    exclusions, exclusion_binding = _parse_exclusion_csv(exclusion_csv)
    op_spec = operator_spec()
    op_hash = _canonical_sha256(op_spec)
    output.parent.mkdir(parents=True, exist_ok=True)

    event_rows: list[dict[str, Any]] = []
    event_buffer: list[tuple[Any, ...]] = []
    event_counts = {name: 0 for name in EVENT_CODES}
    event_mass = {name: 0.0 for name in EVENT_CODES}
    first_event_time: dict[str, float | None] = {name: None for name in EVENT_CODES}
    bracket_half_width: dict[str, float | None] = {name: None for name in EVENT_CODES}
    observed_bracket_stats: dict[str, dict[str, Any]] = {
        name: {"count": 0, "min_s": None, "max_s": None, "all_within_budget": True}
        for name in EVENT_CODES
    }
    residence_mass_time = np.zeros(len(DESTINATION_CODES), dtype=np.float64)
    residence_time = np.zeros(len(DESTINATION_CODES), dtype=np.float64)
    unknown_reason_counts: dict[str, int] = {name: 0 for name in UNKNOWN_REASON_CODES}
    wall_crossing_count = 0
    nan_valid_count = 0
    lifecycle_type_change_count = 0
    destination_final: dict[str, float] = {}
    final_destination = np.empty(0, dtype=np.int8)
    initial_mass = 0.0
    initial_type_count = 0
    source_mk_codes: list[int] = []
    source_mass: np.ndarray
    native_mass_binding: dict[str, Any]
    source_layer: np.ndarray
    zone: np.ndarray
    idp: np.ndarray
    times: np.ndarray
    rigid: np.ndarray
    trajectory_attrs: dict[str, Any] = {}

    with h5py.File(trajectory, "r") as source:
        required = ("time", "position", "initial_mass", "initial_mk", "initial_type",
                    "particle_zone", "particle_id", "valid", "type", "rigid_body_state")
        missing = [name for name in required if name not in source]
        if missing:
            raise ObservationError(f"converted trajectory is missing required state: {missing}")
        trajectory_attrs = {str(key): source.attrs[key] for key in source.attrs.keys()}
        geometry = _owner_geometry(owner, trajectory_attrs)
        times = np.asarray(source["time"][:], dtype=np.float64)
        if len(times) < 2 or not np.all(np.isfinite(times)) or not np.all(np.diff(times) > 0):
            raise ObservationError("trajectory time axis is not finite and strictly increasing")
        rigid = np.asarray(source["rigid_body_state"][:])
        if len(rigid) != len(times) or not np.all(np.isfinite(rigid["actual_angle_rad"])):
            raise ObservationError("saved actual rigid pose is not frame aligned and finite")
        initial_type = np.asarray(source["initial_type"][:], dtype=np.int64)
        fluid_indices = np.flatnonzero(initial_type == 3)
        if not len(fluid_indices):
            raise ObservationError("trajectory has no initial Type=3 fluid cohort")
        initial_type_count = int(len(fluid_indices))
        zone = np.asarray(source["particle_zone"][:], dtype=np.int64)[fluid_indices]
        idp = np.asarray(source["particle_id"][:], dtype=np.int64)[fluid_indices]
        source_mk = np.asarray(source["initial_mk"][:], dtype=np.int64)[fluid_indices]
        source_layer = _source_layer(source_mk)
        adapter_mass = np.asarray(source["initial_mass"][:], dtype=np.float64)[fluid_indices]
        if not np.all(np.isfinite(adapter_mass)) or np.any(adapter_mass <= 0):
            raise ObservationError("initial native fluid mass is not finite and positive")
        native_mass_binding = _native_mass_reference(owner, len(fluid_indices), adapter_mass)
        native_particle_mass = native_mass_binding.get("massfluid_kg_per_particle")
        if native_particle_mass is None or not np.isfinite(native_particle_mass) or native_particle_mass <= 0:
            raise ObservationError("generated XML does not provide a finite positive MassFluid authority")
        source_mass = np.full(len(fluid_indices), float(native_particle_mass), dtype=np.float64)
        initial_mass = float(source_mass.sum())
        source_mk_codes = sorted(int(value) for value in np.unique(source_mk))
        frames, total_particles = source["position"].shape[:2]
        if total_particles != len(initial_type):
            raise ObservationError("trajectory particle axis disagrees with initial_type")
        n = len(fluid_indices)
        tolerance = float(geometry["crossing_tolerance_m"])
        cup_low = np.asarray(geometry["cup_low_m"], dtype=np.float64)
        cup_high = np.asarray(geometry["cup_high_m"], dtype=np.float64)
        receiver_low = np.asarray(geometry["receiver_low_m"], dtype=np.float64)
        receiver_high = np.asarray(geometry["receiver_high_m"], dtype=np.float64)
        tray_low = np.asarray(geometry["tray_low_m"], dtype=np.float64)
        tray_high = np.asarray(geometry["tray_high_m"], dtype=np.float64)
        origin = np.asarray(geometry["motion_axis_origin_m"], dtype=np.float64)
        axis = np.asarray(geometry["motion_axis_unit"], dtype=np.float64)
        cup_low_inner, cup_high_inner = cup_low + tolerance, cup_high - tolerance
        receiver_low_inner, receiver_high_inner = receiver_low + tolerance, receiver_high - tolerance
        tray_low_inner, tray_high_inner = tray_low + tolerance, tray_high - tolerance
        start_time = float(owner.get("event_window", {}).get("hold_start_s", 0.5))
        if start_time < 0 or not np.isfinite(start_time):
            raise ObservationError("event-window hold start is invalid")

        chunks = (1, min(n, 65536))
        with h5py.File(output, "w") as labels:
            labels.create_dataset("time", data=times)
            labels.create_dataset("particle_zone", data=zone)
            labels.create_dataset("particle_id", data=idp)
            labels.create_dataset("source_mk", data=source_mk)
            labels.create_dataset("source_layer_index", data=source_layer)
            labels.create_dataset("source_mass_kg", data=source_mass)
            valid_ds = labels.create_dataset("valid", shape=(frames, n), dtype="u1", chunks=chunks, compression="gzip")
            type_change_ds = labels.create_dataset("lifecycle_type_change", shape=(frames, n), dtype="u1", chunks=chunks, compression="gzip")
            destination_ds = labels.create_dataset("destination_code", shape=(frames, n), dtype="i1", chunks=chunks, compression="gzip")
            reason_ds = labels.create_dataset("unknown_reason_code", shape=(frames, n), dtype="u1", chunks=chunks, compression="gzip")
            top_margin_ds = labels.create_dataset("cup_top_signed_margin_m", shape=(frames, n), dtype="f4", chunks=chunks, compression="gzip")
            top_aperture_ds = labels.create_dataset("cup_top_aperture", shape=(frames, n), dtype="u1", chunks=chunks, compression="gzip")
            top_crossing_aperture_ds = labels.create_dataset("cup_top_crossing_aperture", shape=(frames, n), dtype="u1", chunks=chunks, compression="gzip")
            cup_margin_ds = labels.create_dataset("cup_body_signed_margin_m", shape=(frames, n), dtype="f4", chunks=chunks, compression="gzip")
            receiver_margin_ds = labels.create_dataset("receiver_signed_margin_m", shape=(frames, n), dtype="f4", chunks=chunks, compression="gzip")
            tray_margin_ds = labels.create_dataset("tray_signed_margin_m", shape=(frames, n), dtype="f4", chunks=chunks, compression="gzip")
            angle_ds = labels.create_dataset("rigid_body_angle_rad", data=np.asarray(rigid["actual_angle_rad"], dtype=np.float64))
            destination_mass_ds = labels.create_dataset("destination_mass_kg", shape=(frames, len(DESTINATION_CODES)), dtype="f8")
            events_ds = labels.create_dataset("events", shape=(0,), maxshape=(None,), dtype=EVENT_DTYPE,
                                              chunks=(max(1, min(65536, n)),), compression="gzip")
            first_invalid_frame = np.full(n, -1, dtype=np.int32)
            exclusion_motive = np.full(n, -1, dtype=np.int16)
            exclusion_pos = np.full((n, 3), np.nan, dtype=np.float64)
            exclusion_vel = np.full((n, 3), np.nan, dtype=np.float64)
            exclusion_density = np.full(n, np.nan, dtype=np.float64)
            id_to_index = {int(value): index for index, value in enumerate(idp.tolist())}
            for index, value in enumerate(idp.tolist()):
                record = exclusions.get(int(value))
                if record is not None:
                    first_invalid_frame[index] = int(record["partout"])
                    exclusion_motive[index] = int(record["motive"])
                    exclusion_pos[index, :] = np.asarray(record["position_m"], dtype=np.float64)
                    if "velocity_m_s" in record:
                        exclusion_vel[index, :] = np.asarray(record["velocity_m_s"], dtype=np.float64)
                    if "density_kg_m3" in record:
                        exclusion_density[index] = float(record["density_kg_m3"])
            previous_valid = np.zeros(n, dtype=bool)
            previous_position = np.full((n, 3), np.nan, dtype=np.float64)
            previous_body = np.full((n, 3), np.nan, dtype=np.float64)
            previous_top_margin = np.full(n, np.nan, dtype=np.float64)
            previous_top_aperture = np.zeros(n, dtype=bool)
            previous_receiver_margin = np.full(n, np.nan, dtype=np.float64)
            previous_tray_margin = np.full(n, np.nan, dtype=np.float64)
            departure_seen = np.zeros(n, dtype=bool)
            legal_tray_seen = np.zeros(n, dtype=bool)
            tray_event_seen = np.zeros(n, dtype=bool)
            closed_wall_seen = np.zeros(n, dtype=bool)
            event_buffer.clear()

            for frame in range(frames):
                raw_position = np.asarray(source["position"][frame, fluid_indices, :], dtype=np.float64)
                raw_valid = np.asarray(source["valid"][frame, fluid_indices], dtype=bool)
                raw_type = np.asarray(source["type"][frame, fluid_indices], dtype=np.int64)
                finite_position = np.all(np.isfinite(raw_position), axis=1)
                valid = raw_valid & finite_position & (raw_type == 3)
                type_change = raw_valid & (raw_type != 3)
                nan_valid_count += int(np.sum(raw_valid & ~finite_position))
                lifecycle_type_change_count += int(np.sum(type_change))
                if frame > 0:
                    if np.any(type_change):
                        lifecycle_type_change_count += 0
                position = raw_position
                body = np.full((n, 3), np.nan, dtype=np.float64)
                if np.any(finite_position):
                    body[finite_position] = _inverse_rotate(position[finite_position], origin, axis,
                                                            float(rigid[frame]["actual_angle_rad"]))
                cup_margin = np.full(n, np.nan, dtype=np.float64)
                receiver_margin = np.full(n, np.nan, dtype=np.float64)
                tray_margin = np.full(n, np.nan, dtype=np.float64)
                top_margin = np.full(n, np.nan, dtype=np.float64)
                if np.any(finite_position):
                    cup_margin[finite_position] = _box_margin(body[finite_position], cup_low_inner, cup_high_inner)
                    receiver_margin[finite_position] = _box_margin(position[finite_position], receiver_low_inner, receiver_high_inner)
                    tray_margin[finite_position] = _box_margin(position[finite_position], tray_low_inner, tray_high_inner)
                    top_margin[finite_position] = body[finite_position, 2] - cup_high[2]
                top_aperture = np.zeros(n, dtype=bool)
                top_aperture[finite_position] = (
                    (body[finite_position, 0] >= cup_low[0] - tolerance) &
                    (body[finite_position, 0] <= cup_high[0] + tolerance) &
                    (body[finite_position, 1] >= cup_low[1] - tolerance) &
                    (body[finite_position, 1] <= cup_high[1] + tolerance) & valid[finite_position]
                )
                top_crossing_aperture = np.zeros(n, dtype=bool)

                current_closed_wall = np.zeros(n, dtype=bool)
                endpoint_valid = valid.copy()
                endpoint_position = position.copy()
                missing_position = ~finite_position
                # PartVTKOut is the last native position before a converted
                # identity becomes invalid; it is diagnostic evidence only.
                if np.any(missing_position):
                    for particle in np.flatnonzero(missing_position):
                        record = exclusions.get(int(idp[particle]))
                        if record is not None and int(record["partout"]) == frame:
                            candidate = np.asarray(record["position_m"], dtype=np.float64)
                            if np.all(np.isfinite(candidate)):
                                endpoint_position[particle] = candidate
                                endpoint_valid[particle] = True
                endpoint_body = np.full((n, 3), np.nan, dtype=np.float64)
                if np.any(endpoint_valid):
                    endpoint_body[endpoint_valid] = _inverse_rotate(endpoint_position[endpoint_valid], origin, axis,
                                                                     float(rigid[frame]["actual_angle_rad"]))
                endpoint_cup_margin = np.full(n, np.nan, dtype=np.float64)
                endpoint_top_margin = np.full(n, np.nan, dtype=np.float64)
                endpoint_receiver_margin = np.full(n, np.nan, dtype=np.float64)
                endpoint_tray_margin = np.full(n, np.nan, dtype=np.float64)
                if np.any(endpoint_valid):
                    endpoint_cup_margin[endpoint_valid] = _box_margin(endpoint_body[endpoint_valid], cup_low, cup_high)
                    endpoint_top_margin[endpoint_valid] = endpoint_body[endpoint_valid, 2] - cup_high[2]
                    endpoint_receiver_margin[endpoint_valid] = _box_margin(endpoint_position[endpoint_valid], receiver_low, receiver_high)
                    endpoint_tray_margin[endpoint_valid] = _box_margin(endpoint_position[endpoint_valid], tray_low, tray_high)

                new_top_departure = np.zeros(n, dtype=bool)
                if frame > 0:
                    segment_valid = previous_valid & valid
                    top_crossing_aperture = segment_valid & _interpolated_top_aperture(
                        previous_position, position, previous_top_margin, top_margin,
                        float(rigid[frame - 1]["actual_angle_rad"]), float(rigid[frame]["actual_angle_rad"]),
                        origin, axis, cup_low, cup_high, tolerance)
                    outward = segment_valid & (previous_top_margin <= 0.0) & (top_margin > 0.0) & top_crossing_aperture
                    inward = segment_valid & (previous_top_margin > 0.0) & (top_margin <= 0.0) & top_crossing_aperture & departure_seen
                    for particle in np.flatnonzero(outward | inward):
                        is_outward = bool(outward[particle])
                        event_time = _interp_crossing(float(previous_top_margin[particle]), float(top_margin[particle]),
                                                      float(times[frame - 1]), float(times[frame]))
                        if event_time < start_time:
                            continue
                        code_name = "cup_top_departure" if is_outward else "cup_top_return"
                        _record_bracket_stat(observed_bracket_stats, code_name,
                                             float((times[frame] - times[frame - 1]) / 2.0))
                        code = EVENT_CODES[code_name]
                        event_buffer.append(_event_tuple(event_time, code, 1 if is_outward else -1, particle,
                                                         frame - 1, frame, zone, idp, source_mk,
                                                         source_layer, source_mass))
                        event_counts[code_name] += 1
                        event_mass[code_name] += float(source_mass[particle])
                        if first_event_time[code_name] is None:
                            first_event_time[code_name] = event_time
                            bracket_half_width[code_name] = float((times[frame] - times[frame - 1]) / 2.0)
                            event_rows.append({"time_s": event_time, "event_code": code,
                                               "frame_before": frame - 1, "frame_after": frame,
                                               "idp": int(idp[particle]), "zone": int(zone[particle])})
                        if is_outward:
                            new_top_departure[particle] = True
                    departure_seen |= new_top_departure

                    receiver_entry = segment_valid & (previous_receiver_margin <= 0.0) & (receiver_margin > 0.0)
                    receiver_exit = segment_valid & (previous_receiver_margin > 0.0) & (receiver_margin <= 0.0)
                    tray_entry = segment_valid & (previous_tray_margin <= 0.0) & (tray_margin > 0.0) & departure_seen
                    tray_exit = segment_valid & (previous_tray_margin > 0.0) & (tray_margin <= 0.0) & tray_event_seen
                    crossing_specs = (
                        ("receiver_entry", 1, receiver_entry, previous_receiver_margin, receiver_margin),
                        ("receiver_exit", -1, receiver_exit, previous_receiver_margin, receiver_margin),
                        ("tray_entry", 1, tray_entry, previous_tray_margin, tray_margin),
                        ("tray_exit", -1, tray_exit, previous_tray_margin, tray_margin),
                    )
                    for code_name, direction, mask, previous_margin, current_margin in crossing_specs:
                        code = EVENT_CODES[code_name]
                        for particle in np.flatnonzero(mask):
                            event_time = _interp_crossing(float(previous_margin[particle]), float(current_margin[particle]),
                                                          float(times[frame - 1]), float(times[frame]))
                            if event_time < start_time:
                                continue
                            _record_bracket_stat(observed_bracket_stats, code_name,
                                                 float((times[frame] - times[frame - 1]) / 2.0))
                            event_buffer.append(_event_tuple(event_time, code, direction, particle,
                                                             frame - 1, frame, zone, idp, source_mk,
                                                             source_layer, source_mass))
                            event_counts[code_name] += 1
                            event_mass[code_name] += float(source_mass[particle])
                            if first_event_time[code_name] is None:
                                first_event_time[code_name] = event_time
                                bracket_half_width[code_name] = float((times[frame] - times[frame - 1]) / 2.0)
                                event_rows.append({"time_s": event_time, "event_code": code,
                                                   "frame_before": frame - 1, "frame_after": frame,
                                                   "idp": int(idp[particle]), "zone": int(zone[particle])})

                    # A closed-face crossing is evidence of wall penetration;
                    # cup/receiver/tray top faces are intentionally open.
                    prev_cup_outer = _box_margin(previous_body, cup_low, cup_high)
                    curr_cup_outer = np.where(endpoint_valid, endpoint_cup_margin, np.nan)
                    prev_receiver_outer = _box_margin(previous_position, receiver_low, receiver_high)
                    curr_receiver_outer = np.where(endpoint_valid, endpoint_receiver_margin, np.nan)
                    prev_tray_outer = _box_margin(previous_position, tray_low, tray_high)
                    curr_tray_outer = np.where(endpoint_valid, endpoint_tray_margin, np.nan)
                    cup_open = _interpolated_top_aperture(
                        previous_position, endpoint_position, previous_top_margin, endpoint_top_margin,
                        float(rigid[frame - 1]["actual_angle_rad"]), float(rigid[frame]["actual_angle_rad"]),
                        origin, axis, cup_low, cup_high, tolerance)
                    previous_receiver_top = previous_position[:, 2] - receiver_high[2]
                    current_receiver_top = endpoint_position[:, 2] - receiver_high[2]
                    previous_tray_top = previous_position[:, 2] - tray_high[2]
                    current_tray_top = endpoint_position[:, 2] - tray_high[2]
                    receiver_open = _interpolated_world_top_aperture(
                        previous_position, endpoint_position, previous_receiver_top, current_receiver_top,
                        receiver_low, receiver_high, tolerance)
                    tray_open = _interpolated_world_top_aperture(
                        previous_position, endpoint_position, previous_tray_top, current_tray_top,
                        tray_low, tray_high, tolerance)
                    cup_wall = _wall_crossing(prev_cup_outer, curr_cup_outer, previous_valid, endpoint_valid, cup_open)
                    receiver_wall = _wall_crossing(prev_receiver_outer, curr_receiver_outer, previous_valid, endpoint_valid, receiver_open)
                    tray_wall = _wall_crossing(prev_tray_outer, curr_tray_outer, previous_valid, endpoint_valid, tray_open)
                    current_closed_wall = cup_wall | receiver_wall | tray_wall
                    wall_crossing_count += int(np.sum(current_closed_wall))
                    closed_wall_seen |= current_closed_wall

                tray_after_departure = valid & (cup_margin <= 0.0) & (receiver_margin <= 0.0) & (tray_margin > 0.0) & departure_seen
                cup_destination = valid & (cup_margin > 0.0)
                receiver_destination = valid & ~cup_destination & (receiver_margin > 0.0)
                inflight_destination = valid & ~cup_destination & ~receiver_destination & ~tray_after_departure
                tray_destination = tray_after_departure
                destination = np.full(n, DESTINATION_CODES["unknown"], dtype=np.int8)
                destination[cup_destination] = DESTINATION_CODES["cup"]
                destination[receiver_destination] = DESTINATION_CODES["receiver"]
                destination[tray_destination] = DESTINATION_CODES["tray"]
                destination[inflight_destination] = DESTINATION_CODES["inflight"]
                legal_tray_seen |= tray_destination
                tray_event_seen |= tray_destination

                reason = np.zeros(n, dtype=np.uint8)
                invalid = ~valid
                reason[invalid] = UNKNOWN_REASON_CODES["native_invalid"]
                if np.any(invalid):
                    reason[invalid & (closed_wall_seen | current_closed_wall)] = UNKNOWN_REASON_CODES["native_invalid_closed_wall_crossing"]
                    legal_candidate = invalid & ~(closed_wall_seen | current_closed_wall) & (legal_tray_seen | (endpoint_tray_margin > 0.0))
                    reason[legal_candidate] = UNKNOWN_REASON_CODES["native_invalid_legal_tray_candidate"]
                    # Motive=1 is retained as a numerical-domain exclusion
                    # candidate even when the saved H5 sequence does not
                    # bracket its top crossing.  This is deliberately called
                    # open-top/domain evidence, never physical spill.
                    motive_domain = np.zeros(n, dtype=bool)
                    motive_domain[exclusion_motive == 1] = True
                    open_candidate = invalid & ~(closed_wall_seen | current_closed_wall) & ~legal_candidate & (departure_seen | motive_domain)
                    reason[open_candidate] = UNKNOWN_REASON_CODES["native_invalid_after_open_top_or_domain"]
                    reason[invalid & (reason == UNKNOWN_REASON_CODES["native_invalid"])] = UNKNOWN_REASON_CODES["native_invalid_unclassified"]
                reason[type_change] = UNKNOWN_REASON_CODES["lifecycle_type_change"]
                for code_name, code in UNKNOWN_REASON_CODES.items():
                    unknown_reason_counts[code_name] += int(np.sum(reason == code))

                mass_row = _destination_mass(destination, source_mass)
                destination_mass_ds[frame, :] = mass_row
                if frame > 0:
                    dt = float(times[frame] - times[frame - 1])
                    previous_destination = previous_destination_for_residence
                    for code in DESTINATION_CODES.values():
                        old_mass = float(source_mass[previous_destination == code].sum())
                        new_mass = float(source_mass[destination == code].sum())
                        residence_mass_time[code] += 0.5 * (old_mass + new_mass) * dt
                        residence_time[code] += 0.5 * (float(np.sum(previous_destination == code)) / n + float(np.sum(destination == code)) / n) * dt
                previous_destination_for_residence = destination.copy()
                valid_ds[frame, :] = valid.astype(np.uint8)
                type_change_ds[frame, :] = type_change.astype(np.uint8)
                destination_ds[frame, :] = destination
                reason_ds[frame, :] = reason
                top_margin_ds[frame, :] = top_margin.astype(np.float32)
                top_aperture_ds[frame, :] = top_aperture.astype(np.uint8)
                top_crossing_aperture_ds[frame, :] = top_crossing_aperture.astype(np.uint8)
                cup_margin_ds[frame, :] = cup_margin.astype(np.float32)
                receiver_margin_ds[frame, :] = receiver_margin.astype(np.float32)
                tray_margin_ds[frame, :] = tray_margin.astype(np.float32)
                if len(event_buffer) >= 65536:
                    _flush_events(events_ds, event_buffer)

                previous_valid = valid
                previous_position = position
                previous_body = body
                previous_top_margin = top_margin
                previous_top_aperture = top_aperture
                previous_receiver_margin = receiver_margin
                previous_tray_margin = tray_margin
            _flush_events(events_ds, event_buffer)
            final_destination = previous_destination_for_residence.copy()
            destination_final = {name: float(destination_mass_ds[frames - 1, code]) for name, code in DESTINATION_CODES.items()}
            labels.create_dataset("first_invalid_frame", data=first_invalid_frame)
            labels.create_dataset("exclusion_motive", data=exclusion_motive)
            labels.create_dataset("exclusion_position_m", data=exclusion_pos)
            labels.create_dataset("exclusion_velocity_m_s", data=exclusion_vel)
            labels.create_dataset("exclusion_density_kg_m3", data=exclusion_density)
            labels.attrs["schema"] = SCHEMA
            labels.attrs["operator_version"] = OPERATOR_VERSION
            labels.attrs["operator_sha256"] = op_hash
            labels.attrs["operator_spec_json"] = json.dumps(_json_value(op_spec), sort_keys=True)
            labels.attrs["case_id"] = str(owner.get("case_id", ""))
            labels.attrs["trajectory_sha256"] = _sha256(trajectory)
            labels.attrs["owner_metadata_sha256"] = _sha256(owner_metadata)
            labels.attrs["source_exclusion_csv_sha256"] = exclusion_binding.get("sha256") or ""
            labels.attrs["destination_codes_json"] = json.dumps(DESTINATION_CODES, sort_keys=True)
            labels.attrs["event_codes_json"] = json.dumps(EVENT_CODES, sort_keys=True)
            labels.attrs["unknown_reason_codes_json"] = json.dumps(UNKNOWN_REASON_CODES, sort_keys=True)
            labels.attrs["physical_condition_sha256"] = str(owner.get("physical_condition_hash_declared", ""))
            labels.attrs["physical_binding_sha256"] = str(owner.get("physical_binding_sha256", ""))
            labels.attrs["source_h5_physical_condition_sha256"] = _as_text(trajectory_attrs.get("physical_condition_sha256", ""))
            labels.attrs["numerical_recipe_sha256"] = str(owner.get("numerical_recipe_hash_declared", trajectory_attrs.get("numerical_parameters_sha256", "")))
            labels.attrs["source_h5_geometry_sha256"] = _as_text(trajectory_attrs.get("geometry_sha256", ""))
            labels.attrs["source_h5_control_sha256"] = _as_text(trajectory_attrs.get("control_sha256", ""))
            labels.attrs["rigid_body_state_control_sha256"] = _as_text(trajectory_attrs.get("rigid_body_state_control_sha256", ""))
            labels.attrs["units_json"] = _as_text(trajectory_attrs.get("units_json", ""))
            labels.attrs["native_mass_reference_json"] = json.dumps(_json_value(native_mass_binding), sort_keys=True)
            labels.attrs["source_semantics"] = "initial native Type=3 fluid cohort; fixed (Zone,Idp); no births or identity repair"
            labels.attrs["unknown_semantics"] = "native invalid identities remain unknown; reason distinguishes closed-wall, legal-tray candidate, and open-top/domain"
            labels.attrs["physical_hash_excludes_operator"] = True
            labels.attrs["physical_hash_excludes_numerical_recipe"] = True

    source_mass_by_layer = {str(layer): float(source_mass[source_layer == layer].sum()) for layer in sorted(set(source_layer.tolist()))}
    continuous_mass = native_mass_binding.get("continuous_mass_kg")
    native_header_mass = native_mass_binding.get("native_header_cohort_mass_kg")
    relative_mass_error = native_mass_binding.get("native_vs_continuous_relative_error")
    first_excluded = first_invalid_frame >= 0
    first_exclusion_motive_counts: dict[str, int] = {}
    for motive in exclusion_motive[first_excluded].tolist():
        key = str(int(motive))
        first_exclusion_motive_counts[key] = first_exclusion_motive_counts.get(key, 0) + 1
    legacy = None
    if legacy_labels is not None and legacy_labels.is_file():
        with h5py.File(legacy_labels, "r") as old:
            old_events = np.asarray(old["events"][:]) if "events" in old else np.empty(0, dtype=EVENT_DTYPE)
            old_event_names = {1: "cup_departure", 2: "cup_return"}
            legacy = {
                "path": str(legacy_labels.resolve()),
                "sha256": _sha256(legacy_labels),
                "cup_departure_count": int(np.sum(old_events["event_code"] == 1)) if len(old_events) else 0,
                "cup_return_count": int(np.sum(old_events["event_code"] == 2)) if len(old_events) else 0,
                "operator_semantics": "consumed local-x mouth labels; retained for discrepancy evidence only",
            }
    report_payload: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": owner.get("case_id"),
        "family_id": "F2",
        "mechanism_id": owner.get("mechanism_id"),
        "resolution": owner.get("resolution"),
        "trajectory": {"path": str(trajectory.resolve()), "sha256": _sha256(trajectory)},
        "owner_metadata": {"path": str(owner_metadata.resolve()), "sha256": _sha256(owner_metadata)},
        "owner_overrides": owner_overrides,
        "native_exclusion_ledger": exclusion_binding,
        "output": {"path": str(output.resolve()), "sha256": _sha256(output)},
        "quality_contract_binding": quality_binding,
        "operator": {"version": OPERATOR_VERSION, "sha256": op_hash, "spec": op_spec},
        "physical_binding": {
            "physical_condition_hash_declared": owner.get("physical_condition_hash_declared"),
            "physical_binding_sha256": owner.get("physical_binding_sha256"),
            "source_h5_physical_condition_sha256": _as_text(trajectory_attrs.get("physical_condition_sha256", "")),
            "source_h5_geometry_sha256": _as_text(trajectory_attrs.get("geometry_sha256", "")),
            "source_h5_control_sha256": _as_text(trajectory_attrs.get("control_sha256", "")),
            "motion_control_sha256": _as_text(trajectory_attrs.get("rigid_body_state_control_sha256", "")),
            "physical_hash_is_independent_of_operator": True,
        },
        "geometry_and_pose": {
            "cup_low_m": _json_value(geometry["cup_low_m"]),
            "cup_high_m": _json_value(geometry["cup_high_m"]),
            "receiver_low_m": _json_value(geometry["receiver_low_m"]),
            "receiver_high_m": _json_value(geometry["receiver_high_m"]),
            "tray_low_m": _json_value(geometry["tray_low_m"]),
            "tray_high_m": _json_value(geometry["tray_high_m"]),
            "motion_axis_origin_m": _json_value(geometry["motion_axis_origin_m"]),
            "motion_axis_unit": _json_value(geometry["motion_axis_unit"]),
            "pose_source": "rigid_body_state.actual_angle_rad from converted native moving-node fit",
            "cup_open_face": "local-z high face; x/y aperture uses moving body frame",
        },
        "dimensions": {"frames": int(len(times)), "initial_fluid_particles": int(initial_type_count), "coordinate_components": 3},
        "source_population": {
            "source_mk_codes": source_mk_codes,
            "source_mass_kg_by_layer": source_mass_by_layer,
            "initial_native_mass_kg": native_header_mass,
            "h5_float32_adapter_mass_kg": native_mass_binding.get("h5_float32_adapter_mass_kg"),
            "continuous_mass_kg": continuous_mass,
            "native_header_mass_reference": native_mass_binding,
            "relative_mass_error_native_to_continuous": relative_mass_error,
            "strict_mass_reference_budget": MASS_REFERENCE_RELATIVE_BUDGET,
            "mass_reference_status": native_mass_binding.get("strict_native_vs_continuous_status", "unavailable"),
            "initial_type3_ids_retained": True,
            "introduced_ids_inferred": 0,
        },
        "destination_codes": DESTINATION_CODES,
        "final_mass_kg_by_destination": destination_final,
        "residence": {
            "mass_time_kg_s_by_destination": {name: float(residence_mass_time[code]) for name, code in DESTINATION_CODES.items()},
            "fractional_cohort_time_by_destination": {name: float(residence_time[code]) for name, code in DESTINATION_CODES.items()},
            "time_window_s": float(times[-1] - times[0]),
        },
        "event_ledger": {
            "event_codes": EVENT_CODES,
            "counts_by_code": event_counts,
            "mass_kg_by_code": event_mass,
            "first_event_time_s_by_code": first_event_time,
            "first_event_bracket_half_width_s_by_code": bracket_half_width,
            "observed_event_bracket_stats_s_by_code": observed_bracket_stats,
            "all_observed_save_brackets_within_budget": all(
                bool(record["all_within_budget"]) for record in observed_bracket_stats.values()
            ),
            "first_event_rows": event_rows,
            "save_half_width_budget_s": SAVE_HALF_WIDTH_BUDGET_S,
            "save_bracket_status_by_code": {
                name: ("pass" if bracket_half_width[name] is not None and bracket_half_width[name] <= SAVE_HALF_WIDTH_BUDGET_S else
                       "fail" if bracket_half_width[name] is not None else "not_observed")
                for name in EVENT_CODES
            },
            "semantics": "cup_top departure/return and finite-wall top tests use the interpolated crossing pose; receiver/tray crossings remain finite world boxes",
        },
            "native_exclusion_and_boundary": {
                "unknown_reason_codes": UNKNOWN_REASON_CODES,
                "unknown_reason_counts_by_frame_particle": unknown_reason_counts,
                "first_excluded_identity_count": int(np.sum(first_excluded)),
                "first_excluded_identity_motive_counts": first_exclusion_motive_counts,
                "first_excluded_frame_min": (int(first_invalid_frame[first_excluded].min()) if np.any(first_excluded) else None),
                "first_excluded_frame_max": (int(first_invalid_frame[first_excluded].max()) if np.any(first_excluded) else None),
                "closed_wall_crossing_segment_count": int(wall_crossing_count),
            "native_invalid_rows": int(unknown_reason_counts["native_invalid"] + unknown_reason_counts["native_invalid_closed_wall_crossing"] + unknown_reason_counts["native_invalid_legal_tray_candidate"] + unknown_reason_counts["native_invalid_after_open_top_or_domain"] + unknown_reason_counts["native_invalid_unclassified"]),
            "physical_spill_inferred_from_invalid": False,
            "motive_is_preserved_separately": True,
            "interpretation": "PartVTKOut Motive and position are source evidence; invalid identities are not promoted to legal spill or wall penetration without the segment test",
        },
        "legacy_semantics_comparison": legacy,
        "qi_evidence": {
            "actual_3d_coordinate_state": True,
            "actual_saved_rigid_pose": True,
            "fixed_initial_identity_lifecycle": True,
            "finite_geometry_and_top_opening_operator": True,
            "status": "v6-observation-evidence-ready; Q-N and production eligibility not assessed",
        },
        "q_n": {"status": "not_assessed", "reason": "requires independent native integration and save studies using this same operator"},
        "production_eligibility": "not_evaluated",
    }
    _write_event_json_report(report, report_payload)
    return report_payload


def _find_single(root: Path, pattern: str, label: str) -> Path:
    candidates = sorted(root.glob(pattern))
    if len(candidates) != 1:
        raise ObservationError(f"expected one {label} under {root}, found {len(candidates)}")
    return candidates[0]


def _old_six_entries(data_root: Path, owner_root: Path) -> list[dict[str, Path | str]]:
    entries: list[dict[str, Path | str]] = []
    for background in ("CENTER", "OFFSET"):
        for resolution in ("COARSE", "MEDIUM", "FINE"):
            case = f"F2H10V2_{background}_V1_{resolution}"
            case_root = data_root / "families" / "F2" / case
            trajectory = _find_single(case_root, "conversion*/trajectory.h5", "trajectory")
            owner = owner_root / f"{case}.generator.v2.metadata.json"
            if not owner.is_file():
                raise ObservationError(f"owner metadata is missing: {owner}")
            exclusion_candidates = sorted(case_root.glob("native-ledger*/partvtkout/excluded_particles.csv"))
            exclusion = exclusion_candidates[-1] if exclusion_candidates else None
            legacy_candidates = sorted(case_root.glob("labels*/f2-native-labels.h5"))
            legacy = legacy_candidates[-1] if legacy_candidates else None
            entries.append({"case_id": case, "trajectory": trajectory, "owner": owner,
                            "exclusion": exclusion, "legacy": legacy, "background": background.lower(),
                            "resolution": resolution.lower()})
    return entries


def compare_reports(reports: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    report_list = list(reports)
    by_mechanism: dict[str, list[Mapping[str, Any]]] = {}
    for record in report_list:
        by_mechanism.setdefault(str(record.get("mechanism_id")), []).append(record)
    comparison: dict[str, Any] = {
        "schema": "ds-data-02.f2.event-semantics.v6-comparison",
        "operator_version": OPERATOR_VERSION,
        "operator_sha256": operator_hash(),
        "physical_hashes_by_mechanism": {},
        "mechanisms": {},
        "scientific_verdict": "observed spatial/time comparison only; Q-N and production remain pending",
    }
    for mechanism, records in sorted(by_mechanism.items()):
        records = sorted(records, key=lambda row: (str(row.get("resolution")), str(row.get("case_id"))))
        physical_hashes = sorted({str(row.get("physical_binding", {}).get("physical_condition_hash_declared")) for row in records})
        comparison["physical_hashes_by_mechanism"][mechanism] = physical_hashes
        by_resolution = {str(row.get("resolution")): row for row in records}
        medium = by_resolution.get("medium")
        rows: dict[str, Any] = {}
        for resolution, row in by_resolution.items():
            event = row.get("event_ledger", {})
            rows[resolution] = {
                "case_id": row.get("case_id"),
                "final_mass_kg_by_destination": row.get("final_mass_kg_by_destination", {}),
                "residence_mass_time_kg_s_by_destination": row.get("residence", {}).get("mass_time_kg_s_by_destination", {}),
                "first_event_time_s_by_code": event.get("first_event_time_s_by_code", {}),
                "first_event_bracket_half_width_s_by_code": event.get("first_event_bracket_half_width_s_by_code", {}),
                "save_bracket_status_by_code": event.get("save_bracket_status_by_code", {}),
                "legacy_semantics": row.get("legacy_semantics_comparison"),
            }
            if medium is not None and row is not medium:
                final = row.get("final_mass_kg_by_destination", {})
                base = medium.get("final_mass_kg_by_destination", {})
                rows[resolution]["delta_vs_medium_kg"] = {name: float(final.get(name, 0.0) - base.get(name, 0.0)) for name in DESTINATION_CODES}
                row_events = row.get("event_ledger", {}).get("first_event_time_s_by_code", {})
                base_events = medium.get("event_ledger", {}).get("first_event_time_s_by_code", {})
                rows[resolution]["delta_vs_medium_time_s"] = {
                    name: (None if row_events.get(name) is None or base_events.get(name) is None else float(row_events[name] - base_events[name]))
                    for name in EVENT_CODES
                }
        comparison["mechanisms"][mechanism] = {
            "physical_hash_consistent_across_resolutions": len(physical_hashes) == 1 and physical_hashes[0] not in ("", "None"),
            "operator_hash_separate_from_physical_hash": True,
            "resolutions": rows,
        }
    return comparison


def run_old_six(*, data_root: Path, owner_root: Path, output_root: Path,
                comparison_report: Path, force: bool = False) -> dict[str, Any]:
    entries = _old_six_entries(data_root, owner_root)
    reports: list[dict[str, Any]] = []
    for entry in entries:
        case = str(entry["case_id"])
        case_out = output_root / case
        labels = case_out / "f2-v6-labels.h5"
        report = case_out / "f2-v6-observations.json"
        reports.append(observe(trajectory=Path(entry["trajectory"]), owner_metadata=Path(entry["owner"]),
                               exclusion_csv=(Path(entry["exclusion"]) if entry["exclusion"] else None),
                               legacy_labels=(Path(entry["legacy"]) if entry["legacy"] else None),
                               output=labels, report=report, force=force))
    comparison = compare_reports(reports)
    comparison["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    comparison["inputs"] = [{"case_id": row.get("case_id"), "report": row.get("output"),
                              "report_sha256": _sha256(output_root / str(row.get("case_id")) / "f2-v6-observations.json")}
                             for row in reports]
    _write_event_json_report(comparison_report, comparison)
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("observe")
    one.add_argument("--trajectory", type=Path, required=True)
    one.add_argument("--owner-metadata", type=Path, required=True)
    one.add_argument("--exclusion-csv", type=Path)
    one.add_argument("--legacy-labels", type=Path)
    one.add_argument("--output", type=Path, required=True)
    one.add_argument("--report", type=Path, required=True)
    one.add_argument("--force", action="store_true")
    one.add_argument("--definition-override", type=Path)
    one.add_argument("--numerical-recipe-hash")
    one.add_argument("--case-id-override")
    batch = sub.add_parser("batch-old-six")
    batch.add_argument("--data-root", type=Path, default=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02"))
    batch.add_argument("--owner-root", type=Path, default=Path(__file__).parent / "handoff_20261002/postsolver/owner_metadata")
    batch.add_argument("--output-root", type=Path, default=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_EVENT_SEMANTICS_V6/old-six"))
    batch.add_argument("--comparison-report", type=Path, default=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_EVENT_SEMANTICS_V6/f2-v6-sixview-comparison.json"))
    batch.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "observe":
            observe(trajectory=args.trajectory.resolve(), owner_metadata=args.owner_metadata.resolve(),
                    exclusion_csv=(args.exclusion_csv.resolve() if args.exclusion_csv else None),
                    legacy_labels=(args.legacy_labels.resolve() if args.legacy_labels else None),
                    output=args.output.resolve(), report=args.report.resolve(), force=args.force,
                    definition_override=(args.definition_override.resolve() if args.definition_override else None),
                    numerical_recipe_hash_override=args.numerical_recipe_hash,
                    case_id_override=args.case_id_override)
        else:
            run_old_six(data_root=args.data_root.resolve(), owner_root=args.owner_root.resolve(),
                        output_root=args.output_root.resolve(), comparison_report=args.comparison_report.resolve(),
                        force=args.force)
    except (ObservationError, OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"f2_event_semantics_v6: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

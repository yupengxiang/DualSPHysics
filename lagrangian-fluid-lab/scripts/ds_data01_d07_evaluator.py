#!/usr/bin/env python3
"""D07 read-only trajectory alignment and model-free scoring interface.

This module deliberately contains no model, optimizer, checkpoint, solver, or
GPU path.  It reads native HDF5 or DualSPHysics/PartVTK CSV trajectories,
aligns common identities and saved times, applies explicit lifecycle masks,
and reports numerical reference-agreement diagnostics.  A numerical reference
trajectory is not external ground truth, so this evaluator never emits
scientific acceptance.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys
import tempfile

import numpy as np

try:
    import h5py
except ImportError:  # pragma: no cover - the supported runtime includes h5py
    h5py = None


CONTRACT_SCHEMA = "ds-data-01.d07.evaluator-contract.v1"
RESULT_SCHEMA = "ds-data-01.d07.evaluation-result.v1"
VIEW_SCHEMA = "ds-data-01.d07.trajectory-view.v1"
DEFAULT_TIME_TOLERANCE_S = 1e-6
REQUIRED_FIELDS = ("position", "velocity")
OPTIONAL_FIELDS = ("density", "pressure", "mass", "type", "mk")
MISSING = object()


def _json_value(value):
    """Convert HDF5/numpy metadata to JSON-safe scalar values."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    return str(value)


def _finite_float(value, *, label):
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is not numeric") from error
    if not np.isfinite(result):
        raise ValueError(f"{label} is not finite")
    return result


def _normalise_header(value):
    return str(value).strip().lstrip("\ufeff")


def _natural_key(path):
    return [int(piece) if piece.isdigit() else piece.lower()
            for piece in re.split(r"(\d+)", str(path))]


def _safe_float(value, *, label):
    text = str(value).strip()
    if text == "":
        raise ValueError(f"{label} is empty")
    return _finite_float(text, label=label)


def _safe_int(value, *, label):
    text = str(value).strip()
    if text == "":
        raise ValueError(f"{label} is empty")
    try:
        result = int(float(text))
    except ValueError as error:
        raise ValueError(f"{label} is not an integer") from error
    if float(text) != result:
        raise ValueError(f"{label} is not an integer")
    return result


def _column(columns, *names):
    normalised = {_normalise_header(name): name for name in columns}
    for name in names:
        if name in normalised:
            return normalised[name]
    lowered = {key.lower(): value for key, value in normalised.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _require_columns(columns, names, *, label):
    missing = [name for name in names if _column(columns, name) is None]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")


def _validate_time_axis(time, *, label):
    time = np.asarray(time, dtype=np.float64)
    if time.ndim != 1 or len(time) < 2:
        raise ValueError(f"{label} time must be one-dimensional with at least two frames")
    if not np.all(np.isfinite(time)) or not np.all(np.diff(time) > 0):
        raise ValueError(f"{label} time must be finite and strictly increasing")
    return time


def _validate_valid(valid, *, label):
    valid = np.asarray(valid)
    if valid.ndim != 2:
        raise ValueError(f"{label} valid must have shape [T,N]")
    if valid.dtype != np.bool_:
        values = np.unique(valid)
        if not np.all(np.isin(values, [0, 1])):
            raise ValueError(f"{label} valid must be binary")
    return valid.astype(bool, copy=False)


def _validate_field(array, valid, *, label, vector=False):
    array = np.asarray(array)
    t_count, n_count = valid.shape
    expected = (t_count, n_count, 3) if vector else None
    if vector:
        if array.shape != expected:
            raise ValueError(f"{label} must have shape [T,N,3]")
        finite_mask = np.broadcast_to(valid[..., None], array.shape)
    else:
        if array.shape not in ((t_count, n_count), (n_count,)):
            raise ValueError(f"{label} must have shape [T,N] or [N]")
        finite_mask = valid if array.ndim == 2 else valid.any(axis=0)
    if np.any(finite_mask) and not np.all(np.isfinite(array[finite_mask])):
        raise ValueError(f"{label} contains non-finite values under valid=true")
    return array


def _identity_keys(zone, particle_id, *, label):
    zone = np.asarray(zone)
    particle_id = np.asarray(particle_id)
    if zone.ndim != 1 or particle_id.ndim != 1 or len(zone) != len(particle_id):
        raise ValueError(f"{label} identity axes must be one-dimensional and equal length")
    keys = tuple((int(z), int(pid)) for z, pid in zip(zone, particle_id))
    if len(set(keys)) != len(keys):
        raise ValueError(f"{label} contains duplicate (particle_zone, particle_id) identities")
    return keys


class Trajectory:
    """In-memory read-only view of a trajectory source."""

    def __init__(self, *, source, source_format, metadata, time, keys, valid, fields):
        self.source = str(source)
        self.source_format = source_format
        self.metadata = metadata
        self.time = _validate_time_axis(time, label=self.source)
        self.keys = tuple(keys)
        self.valid = _validate_valid(valid, label=self.source)
        if self.valid.shape != (len(self.time), len(self.keys)):
            raise ValueError(f"{self.source} valid shape does not match time and identity axes")
        self.fields = dict(fields)
        self._validate_fields()

    @property
    def frame_count(self):
        return len(self.time)

    @property
    def particle_count(self):
        return len(self.keys)

    def _validate_fields(self):
        for field in REQUIRED_FIELDS:
            if field not in self.fields:
                raise ValueError(f"{self.source} is missing required field {field}")
        _validate_field(self.fields["position"], self.valid,
                        label=f"{self.source}:position", vector=True)
        _validate_field(self.fields["velocity"], self.valid,
                        label=f"{self.source}:velocity", vector=True)
        for field in OPTIONAL_FIELDS:
            if field in self.fields and self.fields[field] is not None:
                _validate_field(self.fields[field], self.valid,
                                label=f"{self.source}:{field}")

    def field_at(self, name, frame, indices=None):
        value = self.fields.get(name)
        if value is None:
            return None
        selected = value[frame] if value.ndim == 2 or value.ndim == 3 else value
        if indices is not None:
            selected = selected[np.asarray(indices, dtype=np.int64)]
        return selected

    def summary(self):
        return {
            "source": self.source,
            "format": self.source_format,
            "case_id": self.metadata.get("case_id"),
            "family": self.metadata.get("family"),
            "schema_version": self.metadata.get("schema_version"),
            "frame_count": self.frame_count,
            "particle_count": self.particle_count,
            "time_start_s": float(self.time[0]),
            "time_end_s": float(self.time[-1]),
            "active_count_by_frame": [int(row.sum()) for row in self.valid],
            "identity_key": "(particle_zone, particle_id)",
            "fields": sorted(self.fields),
        }


def _load_hdf5(path):
    if h5py is None:
        raise RuntimeError("h5py is required for HDF5 trajectory input")
    path = Path(path)
    required = {"time", "particle_id", "particle_zone", "valid", "position", "velocity"}
    with h5py.File(path, "r") as handle:
        missing = sorted(required - set(handle))
        if missing:
            raise ValueError(f"{path} is missing HDF5 datasets: {', '.join(missing)}")
        time = np.asarray(handle["time"][:], dtype=np.float64)
        valid = _validate_valid(handle["valid"][:], label=str(path))
        ids = np.asarray(handle["particle_id"][:])
        zones = np.asarray(handle["particle_zone"][:])
        keys = _identity_keys(zones, ids, label=str(path))
        fields = {
            "position": np.asarray(handle["position"][:]),
            "velocity": np.asarray(handle["velocity"][:]),
        }
        for field in OPTIONAL_FIELDS:
            if field in handle:
                fields[field] = np.asarray(handle[field][:])
        metadata = {str(key): _json_value(value) for key, value in handle.attrs.items()}
        metadata.setdefault("case_id", path.stem)
        metadata.setdefault("source_path", str(path))
        return Trajectory(source=path, source_format="hdf5", metadata=metadata,
                          time=time, keys=keys, valid=valid, fields=fields)


def _rows_from_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="", errors="replace") as stream:
        return [[_normalise_header(value) for value in row] for row in csv.reader(stream)]


def _row_mapping(header, row):
    values = list(row) + [""] * max(0, len(header) - len(row))
    return {header[index]: values[index].strip() for index in range(len(header))}


def _find_data_header(rows):
    for index, row in enumerate(rows):
        columns = set(row)
        if {"Idp", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]"} <= columns:
            return index, "partvtk"
        if _column(row, "particle_id", "id", "Idp") is not None and _column(
                row, "time", "time_s", "Time [s]", "TimeStep [s]") is not None:
            return index, "long"
    raise ValueError("CSV does not contain a recognised PartVTK or long-form trajectory header")


def _summary_time(rows, header_index, path):
    for row in reversed(rows[:header_index]):
        if row:
            try:
                return _safe_float(row[0], label=f"{path}:frame time")
            except ValueError:
                continue
    raise ValueError(f"{path} does not contain a numeric PartVTK frame time")


def _parse_partvtk(rows, header_index, path):
    header = rows[header_index]
    required = ["Idp", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]",
                "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]"]
    _require_columns(header, required, label=str(path))
    time = _summary_time(rows, header_index, path)
    records = []
    for row_index, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(str(item).strip() for item in row):
            continue
        record = _row_mapping(header, row)
        if not record.get("Idp", "").strip():
            continue
        records.append(record)
    if not records:
        raise ValueError(f"{path} contains no particle rows")
    return [_frame_from_records(records, time=time, path=path, partvtk=True)]


def _parse_long(rows, header_index, path):
    header = rows[header_index]
    required_aliases = (
        ("time", "time_s", "Time [s]", "TimeStep [s]"),
        ("particle_id", "id", "Idp"),
        ("position_x", "x", "Pos.x [m]"),
        ("position_y", "y", "Pos.y [m]"),
        ("position_z", "z", "Pos.z [m]"),
        ("velocity_x", "vx", "Vel.x [m/s]"),
        ("velocity_y", "vy", "Vel.y [m/s]"),
        ("velocity_z", "vz", "Vel.z [m/s]"),
    )
    if any(_column(header, *names) is None for names in required_aliases):
        raise ValueError(f"{path} is missing one or more long-form trajectory columns")
    records_by_time = {}
    for row_index, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(str(item).strip() for item in row):
            continue
        record = _row_mapping(header, row)
        time_name = _column(header, "time", "time_s", "Time [s]", "TimeStep [s]")
        time = _safe_float(record[time_name], label=f"{path}:{row_index}:time")
        records_by_time.setdefault(time, []).append(record)
    if not records_by_time:
        raise ValueError(f"{path} contains no long-form trajectory rows")
    return [_frame_from_records(records, time=time, path=path, partvtk=False)
            for time, records in sorted(records_by_time.items())]


def _record_value(record, header, names, *, label, default=MISSING):
    name = _column(header, *names)
    if name is None:
        if default is MISSING:
            raise ValueError(f"{label} is missing CSV column {names[0]}")
        return default
    return record.get(name, "")


def _frame_from_records(records, *, time, path, partvtk):
    header = list(records[0])
    # The keys of a mapping are the normalized CSV header.  All records in a
    # frame come from the same header, so this is sufficient for both layouts.
    zone_names = ("Zone", "particle_zone", "zone")
    id_names = ("Idp", "particle_id", "id")
    position_names = (("Pos.x [m]", "position_x", "x"),
                      ("Pos.y [m]", "position_y", "y"),
                      ("Pos.z [m]", "position_z", "z"))
    velocity_names = (("Vel.x [m/s]", "velocity_x", "vx"),
                      ("Vel.y [m/s]", "velocity_y", "vy"),
                      ("Vel.z [m/s]", "velocity_z", "vz"))
    keys = []
    arrays = {"position": [], "velocity": []}
    optional_columns = {
        "density": ("Rhop [kg/m^3]", "density", "rho"),
        "mass": ("Mass [kg]", "mass"),
        "pressure": ("Press [Pa]", "pressure", "press"),
        "type": ("Type", "type"),
        "mk": ("Mk", "mk"),
    }
    optional_values = {name: [] for name in optional_columns}
    valid_values = []
    for row_index, record in enumerate(records):
        zone_text = _record_value(record, header, zone_names, label=f"{path}:Zone", default="0")
        id_text = _record_value(record, header, id_names, label=f"{path}:Idp")
        zone = _safe_int(zone_text, label=f"{path}:row {row_index}:Zone")
        particle_id = _safe_int(id_text, label=f"{path}:row {row_index}:Idp")
        keys.append((zone, particle_id))
        arrays["position"].append([
            _safe_float(_record_value(record, header, names, label=f"{path}:position"),
                        label=f"{path}:row {row_index}:position")
            for names in position_names])
        arrays["velocity"].append([
            _safe_float(_record_value(record, header, names, label=f"{path}:velocity"),
                        label=f"{path}:row {row_index}:velocity")
            for names in velocity_names])
        valid_text = _record_value(record, header, ("valid",), label=f"{path}:valid", default="1")
        valid_values.append(bool(_safe_int(valid_text, label=f"{path}:row {row_index}:valid")))
        for name, names in optional_columns.items():
            column = _column(header, *names)
            if column is None:
                continue
            text = record.get(column, "")
            if text.strip() == "":
                optional_values[name].append(np.nan)
            elif name in {"type", "mk"}:
                optional_values[name].append(_safe_int(text, label=f"{path}:row {row_index}:{name}"))
            else:
                optional_values[name].append(_safe_float(text, label=f"{path}:row {row_index}:{name}"))
    if len(set(keys)) != len(keys):
        raise ValueError(f"{path} contains duplicate (particle_zone, particle_id) identities")
    fields = {
        "position": np.asarray(arrays["position"], dtype=np.float64),
        "velocity": np.asarray(arrays["velocity"], dtype=np.float64),
    }
    for name, values in optional_values.items():
        if values:
            dtype = np.int64 if name in {"type", "mk"} else np.float64
            fields[name] = np.asarray(values, dtype=dtype)
    return {"time": float(time), "keys": tuple(keys), "valid": np.asarray(valid_values, dtype=bool),
            "fields": fields}


def _resolve_csv_paths(source):
    if isinstance(source, (list, tuple)):
        paths = [Path(item) for item in source]
    else:
        path = Path(source)
        if path.is_dir():
            paths = sorted(path.glob("Particles_*.csv"), key=_natural_key)
            if not paths:
                paths = sorted(path.glob("*.csv"), key=_natural_key)
        else:
            paths = [path]
    if not paths or any(not path.is_file() for path in paths):
        raise ValueError("CSV source must resolve to one or more files")
    return paths


def _load_csv(source):
    paths = _resolve_csv_paths(source)
    frames = []
    for path in paths:
        rows = _rows_from_csv(path)
        header_index, kind = _find_data_header(rows)
        if kind == "partvtk":
            frames.extend(_parse_partvtk(rows, header_index, path))
        else:
            frames.extend(_parse_long(rows, header_index, path))
    frames.sort(key=lambda frame: frame["time"])
    times = np.asarray([frame["time"] for frame in frames], dtype=np.float64)
    _validate_time_axis(times, label="CSV trajectory")
    all_keys = sorted({key for frame in frames for key in frame["keys"]})
    key_to_index = {key: index for index, key in enumerate(all_keys)}
    t_count, n_count = len(frames), len(all_keys)
    valid = np.zeros((t_count, n_count), dtype=bool)
    position = np.full((t_count, n_count, 3), np.nan, dtype=np.float64)
    velocity = np.full((t_count, n_count, 3), np.nan, dtype=np.float64)
    optional_present = set().union(*(frame["fields"] for frame in frames)) - {"position", "velocity"}
    fields = {"position": position, "velocity": velocity}
    for name in optional_present:
        fill = -1 if name in {"type", "mk"} else np.nan
        dtype = np.int64 if name in {"type", "mk"} else np.float64
        fields[name] = np.full((t_count, n_count), fill, dtype=dtype)
    for frame_index, frame in enumerate(frames):
        indices = np.asarray([key_to_index[key] for key in frame["keys"]], dtype=np.int64)
        active = frame["valid"]
        valid[frame_index, indices] = active
        position[frame_index, indices] = frame["fields"]["position"]
        velocity[frame_index, indices] = frame["fields"]["velocity"]
        for name in optional_present:
            if name in frame["fields"]:
                fields[name][frame_index, indices] = frame["fields"][name]
    metadata = {
        "case_id": paths[0].stem,
        "source_path": str(source),
        "schema_version": "csv-frame-v1",
        "identity_key": "(particle_zone, particle_id)",
        "trajectory_semantics": "native CSV particle rows; material lineage is not inferred",
    }
    return Trajectory(source=source, source_format="csv_frames", metadata=metadata,
                      time=times, keys=all_keys, valid=valid, fields=fields)


def load_trajectory(source):
    """Load HDF5 or CSV as a validated read-only trajectory view."""
    if isinstance(source, (list, tuple)):
        return _load_csv(source)
    path = Path(source)
    if path.suffix.lower() in {".h5", ".hdf5"}:
        return _load_hdf5(path)
    return _load_csv(path)


def load_reference_cards(path=None):
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cards = payload.get("cards") if isinstance(payload, dict) else None
    if not isinstance(cards, list):
        raise ValueError("D03 reference cards must contain a cards list")
    result = {}
    for card in cards:
        if not isinstance(card, dict) or not isinstance(card.get("case_id"), str):
            raise ValueError("D03 reference card is missing case_id")
        result[card["case_id"]] = card
    return result


def _case_id(trajectory):
    return trajectory.metadata.get("case_id") or Path(trajectory.source).stem


def _scope_from_card(trajectory, reference_card=None):
    card = reference_card or {}
    decision = str(card.get("scope_decision", ""))
    if "exclude_from_core" in decision:
        scope = "diagnostic_excluded_from_core"
    elif "calibration_only" in decision:
        scope = "diagnostic_calibration_only"
    elif "open_lifecycle" in decision:
        scope = "diagnostic_open_lifecycle"
    elif "variable_resolution" in decision:
        scope = "diagnostic_variable_resolution"
    else:
        scope = "reference_agreement_only"
    inferred_open = bool(np.any(trajectory.valid.sum(axis=1) != trajectory.particle_count))
    return {
        "case_id": _case_id(trajectory),
        "family": card.get("family", trajectory.metadata.get("family")),
        "scope_decision": decision or None,
        "scope": scope,
        "open_lifecycle": bool("open_lifecycle" in decision or inferred_open),
        "q_e_status": card.get("q_e_status", "not_assessed_no_external_measurement_or_ground_truth_bound"),
        "card_scientific_acceptance": card.get("scientific_acceptance", "not_assessed"),
    }


def _frame_field(trajectory, name, frame):
    value = trajectory.fields.get(name)
    if value is None:
        return None
    return value[frame] if value.ndim >= 2 else value


def _native_observable_row(trajectory, frame):
    valid = trajectory.valid[frame]
    result = {
        "time_s": float(trajectory.time[frame]),
        "active_particle_count": int(valid.sum()),
    }
    position = _frame_field(trajectory, "position", frame)
    velocity = _frame_field(trajectory, "velocity", frame)
    mass = _frame_field(trajectory, "mass", frame)
    if mass is not None:
        active_mass = np.asarray(mass)[valid]
        if np.all(np.isfinite(active_mass)):
            result["active_mass_kg"] = float(np.sum(active_mass))
        else:
            result["active_mass_kg"] = None
    else:
        result["active_mass_kg"] = None
    if valid.any():
        active_position = np.asarray(position)[valid]
        active_velocity = np.asarray(velocity)[valid]
        speeds = np.linalg.norm(active_velocity, axis=1)
        if mass is not None and np.all(np.isfinite(np.asarray(mass)[valid])) and np.all(np.asarray(mass)[valid] > 0):
            weights = np.asarray(mass)[valid]
            centroid = np.average(active_position, axis=0, weights=weights)
            centroid_method = "mass_weighted"
        else:
            centroid = np.mean(active_position, axis=0)
            centroid_method = "arithmetic_fallback"
        result["centroid_m"] = [float(value) for value in centroid]
        result["centroid_method"] = centroid_method
        result["max_speed_m_per_s"] = float(np.max(speeds))
    else:
        result["centroid_m"] = None
        result["centroid_method"] = None
        result["max_speed_m_per_s"] = None
    for field, prefix in (("density", "density_kg_per_m3"), ("pressure", "pressure_pa")):
        value = _frame_field(trajectory, field, frame)
        if value is None or not valid.any():
            result[prefix + "_min"] = None
            result[prefix + "_max"] = None
        else:
            values = np.asarray(value)[valid]
            finite = values[np.isfinite(values)]
            result[prefix + "_min"] = float(np.min(finite)) if len(finite) else None
            result[prefix + "_max"] = float(np.max(finite)) if len(finite) else None
    return result


def native_observables(trajectory):
    """Return native-field observables without any model or external truth."""
    return [_native_observable_row(trajectory, index)
            for index in range(trajectory.frame_count)]


def _nearest_time_pairs(reference_time, candidate_time, tolerance):
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("time_tolerance_s must be finite and non-negative")
    pairs = []
    used = set()
    for reference_index, value in enumerate(reference_time):
        insertion = int(np.searchsorted(candidate_time, value))
        candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(candidate_time)]
        candidates = [index for index in candidates if index not in used]
        if not candidates:
            continue
        candidate_index = min(candidates, key=lambda index: abs(candidate_time[index] - value))
        delta = abs(float(candidate_time[candidate_index] - value))
        if delta <= tolerance:
            pairs.append((reference_index, candidate_index, delta))
            used.add(candidate_index)
    return pairs


def align_trajectories(reference, candidate, *, time_tolerance_s=DEFAULT_TIME_TOLERANCE_S):
    """Align identity intersection and one-to-one saved-time pairs."""
    reference_index = {key: index for index, key in enumerate(reference.keys)}
    candidate_index = {key: index for index, key in enumerate(candidate.keys)}
    common_keys = tuple(sorted(set(reference_index) & set(candidate_index)))
    reference_common_indices = np.asarray([reference_index[key] for key in common_keys], dtype=np.int64)
    candidate_common_indices = np.asarray([candidate_index[key] for key in common_keys], dtype=np.int64)
    frame_pairs = _nearest_time_pairs(reference.time, candidate.time, time_tolerance_s)
    used_reference = {pair[0] for pair in frame_pairs}
    used_candidate = {pair[1] for pair in frame_pairs}
    return {
        "common_keys": common_keys,
        "reference_common_indices": reference_common_indices,
        "candidate_common_indices": candidate_common_indices,
        "frame_pairs": frame_pairs,
        "dropped_reference_frames": [index for index in range(reference.frame_count) if index not in used_reference],
        "dropped_candidate_frames": [index for index in range(candidate.frame_count) if index not in used_candidate],
    }


def _error_summary(reference_values, candidate_values, *, vector=False):
    reference_values = np.asarray(reference_values, dtype=np.float64)
    candidate_values = np.asarray(candidate_values, dtype=np.float64)
    if reference_values.size == 0 or candidate_values.size == 0:
        return {"status": "insufficient_common_active", "count": 0,
                "mae": None, "rmse": None, "max_abs": None}
    if vector:
        error = np.linalg.norm(candidate_values - reference_values, axis=-1)
    else:
        error = np.abs(candidate_values - reference_values)
    error = error[np.isfinite(error)]
    if not len(error):
        return {"status": "insufficient_common_active", "count": 0,
                "mae": None, "rmse": None, "max_abs": None}
    return {"status": "ok", "count": int(len(error)), "mae": float(np.mean(error)),
            "rmse": float(np.sqrt(np.mean(error ** 2))), "max_abs": float(np.max(error))}


def _observable_comparison(reference_rows, candidate_rows, frame_pairs):
    keys = ("active_particle_count", "active_mass_kg", "max_speed_m_per_s",
            "density_kg_per_m3_min", "density_kg_per_m3_max",
            "pressure_pa_min", "pressure_pa_max")
    result = {}
    for key in keys:
        ref_values, cand_values = [], []
        for reference_index, candidate_index, _ in frame_pairs:
            ref_value = reference_rows[reference_index].get(key)
            cand_value = candidate_rows[candidate_index].get(key)
            if ref_value is not None and cand_value is not None:
                ref_values.append(ref_value)
                cand_values.append(cand_value)
        result[key] = _error_summary(ref_values, cand_values)
    ref_centroid, cand_centroid = [], []
    for reference_index, candidate_index, _ in frame_pairs:
        ref_value = reference_rows[reference_index].get("centroid_m")
        cand_value = candidate_rows[candidate_index].get("centroid_m")
        if ref_value is not None and cand_value is not None:
            ref_centroid.append(ref_value)
            cand_centroid.append(cand_value)
    result["centroid_m"] = _error_summary(ref_centroid, cand_centroid, vector=True)
    return result


def _mass_at(trajectory, frame, indices):
    mass = _frame_field(trajectory, "mass", frame)
    if mass is None:
        return None
    return np.asarray(mass)[np.asarray(indices, dtype=np.int64)]


def score_trajectories(reference, candidate, *, time_tolerance_s=DEFAULT_TIME_TOLERANCE_S,
                       dp=None, reference_card=None):
    """Compare two trajectories using common IDs, common times, and valid masks."""
    alignment = align_trajectories(reference, candidate, time_tolerance_s=time_tolerance_s)
    frame_pairs = alignment["frame_pairs"]
    if not frame_pairs:
        raise ValueError("no reference/candidate frame pair falls within time tolerance")
    reference_indices = alignment["reference_common_indices"]
    candidate_indices = alignment["candidate_common_indices"]
    position_errors, velocity_errors = [], []
    per_frame = []
    mask_union = 0
    mask_xor = 0
    ref_mass_series, cand_mass_series, common_ref_mass_series, common_cand_mass_series = [], [], [], []
    for reference_frame, candidate_frame, delta in frame_pairs:
        ref_valid = reference.valid[reference_frame, reference_indices]
        cand_valid = candidate.valid[candidate_frame, candidate_indices]
        common_active = ref_valid & cand_valid
        reference_only = ref_valid & ~cand_valid
        candidate_only = cand_valid & ~ref_valid
        mask_union += int(np.count_nonzero(ref_valid | cand_valid))
        mask_xor += int(np.count_nonzero(ref_valid ^ cand_valid))
        if common_active.any():
            ref_pos = reference.fields["position"][reference_frame, reference_indices[common_active]]
            cand_pos = candidate.fields["position"][candidate_frame, candidate_indices[common_active]]
            ref_vel = reference.fields["velocity"][reference_frame, reference_indices[common_active]]
            cand_vel = candidate.fields["velocity"][candidate_frame, candidate_indices[common_active]]
            position_errors.extend(np.linalg.norm(cand_pos - ref_pos, axis=1).tolist())
            velocity_errors.extend(np.linalg.norm(cand_vel - ref_vel, axis=1).tolist())
        ref_mass = _mass_at(reference, reference_frame, reference_indices[ref_valid])
        cand_mass = _mass_at(candidate, candidate_frame, candidate_indices[cand_valid])
        common_ref_mass = _mass_at(reference, reference_frame, reference_indices[common_active])
        common_cand_mass = _mass_at(candidate, candidate_frame, candidate_indices[common_active])
        for series, value in ((ref_mass_series, ref_mass), (cand_mass_series, cand_mass),
                              (common_ref_mass_series, common_ref_mass),
                              (common_cand_mass_series, common_cand_mass)):
            series.append(float(np.sum(value)) if value is not None and len(value) else None)
        per_frame.append({
            "reference_frame": int(reference_frame),
            "candidate_frame": int(candidate_frame),
            "reference_time_s": float(reference.time[reference_frame]),
            "candidate_time_s": float(candidate.time[candidate_frame]),
            "time_delta_s": float(delta),
            "common_identity_count": int(len(alignment["common_keys"])),
            "reference_active_count_on_common_ids": int(ref_valid.sum()),
            "candidate_active_count_on_common_ids": int(cand_valid.sum()),
            "common_active_count": int(common_active.sum()),
            "reference_only_active_count": int(reference_only.sum()),
            "candidate_only_active_count": int(candidate_only.sum()),
            "position_common_active_count": int(common_active.sum()),
            "position_rmse_m": float(np.sqrt(np.mean(np.linalg.norm(
                candidate.fields["position"][candidate_frame, candidate_indices[common_active]] -
                reference.fields["position"][reference_frame, reference_indices[common_active]], axis=1) ** 2)))
            if common_active.any() else None,
            "velocity_rmse_m_per_s": float(np.sqrt(np.mean(np.linalg.norm(
                candidate.fields["velocity"][candidate_frame, candidate_indices[common_active]] -
                reference.fields["velocity"][reference_frame, reference_indices[common_active]], axis=1) ** 2)))
            if common_active.any() else None,
        })
    position_errors = np.asarray(position_errors, dtype=np.float64)
    velocity_errors = np.asarray(velocity_errors, dtype=np.float64)
    metrics = {
        "position_rmse_m": float(np.sqrt(np.mean(position_errors ** 2))) if len(position_errors) else None,
        "position_mae_m": float(np.mean(position_errors)) if len(position_errors) else None,
        "velocity_rmse_m_per_s": float(np.sqrt(np.mean(velocity_errors ** 2))) if len(velocity_errors) else None,
        "velocity_mae_m_per_s": float(np.mean(velocity_errors)) if len(velocity_errors) else None,
        "common_active_samples": int(len(position_errors)),
        "status": "ok" if len(position_errors) else "insufficient_common_active",
    }
    if dp is not None:
        dp = _finite_float(dp, label="dp")
        if dp <= 0:
            raise ValueError("dp must be positive")
        metrics["position_rmse_over_dp"] = metrics["position_rmse_m"] / dp if metrics["position_rmse_m"] is not None else None
    else:
        metrics["position_rmse_over_dp"] = None
    ref_mass_array = np.asarray([value for value in ref_mass_series if value is not None], dtype=float)
    cand_mass_array = np.asarray([value for value in cand_mass_series if value is not None], dtype=float)
    mass_comparable = min(len(ref_mass_array), len(cand_mass_array))
    lifecycle = {
        "mask_policy": "common_active_for_state_metrics",
        "mask_disagreement_fraction": float(mask_xor / mask_union) if mask_union else None,
        "identity_overlap_fraction": float(len(alignment["common_keys"]) /
                                            max(1, max(reference.particle_count, candidate.particle_count))),
        "reference_identity_count": int(reference.particle_count),
        "candidate_identity_count": int(candidate.particle_count),
        "common_identity_count": int(len(alignment["common_keys"])),
        "reference_only_identity_count": int(reference.particle_count - len(alignment["common_keys"])),
        "candidate_only_identity_count": int(candidate.particle_count - len(alignment["common_keys"])),
        "reference_active_mass_kg_by_frame": [float(value) if value is not None else None for value in ref_mass_series],
        "candidate_active_mass_kg_by_frame": [float(value) if value is not None else None for value in cand_mass_series],
        "common_reference_mass_kg_by_frame": [float(value) if value is not None else None for value in common_ref_mass_series],
        "common_candidate_mass_kg_by_frame": [float(value) if value is not None else None for value in common_cand_mass_series],
        "active_count_mae": float(np.mean([abs(row["reference_active_count_on_common_ids"] -
                                               row["candidate_active_count_on_common_ids"])
                                            for row in per_frame])),
        "active_mass_mae_kg": float(np.mean(np.abs(ref_mass_array[:mass_comparable] - cand_mass_array[:mass_comparable])))
        if mass_comparable else None,
    }
    reference_observables = native_observables(reference)
    candidate_observables = native_observables(candidate)
    scope = _scope_from_card(reference, reference_card)
    result = {
        "schema": RESULT_SCHEMA,
        "mode": "model_free_trajectory_reference_agreement",
        "reference": reference.summary(),
        "candidate": candidate.summary(),
        "scope": scope,
        "alignment": {
            "identity_key": "(particle_zone, particle_id)",
            "time_tolerance_s": float(time_tolerance_s),
            "frame_pairs": [{"reference_frame": int(a), "candidate_frame": int(b), "time_delta_s": float(c)}
                            for a, b, c in frame_pairs],
            "matched_frame_count": int(len(frame_pairs)),
            "reference_frame_count": int(reference.frame_count),
            "candidate_frame_count": int(candidate.frame_count),
            "common_identity_count": int(len(alignment["common_keys"])),
            "reference_only_identity_count": int(reference.particle_count - len(alignment["common_keys"])),
            "candidate_only_identity_count": int(candidate.particle_count - len(alignment["common_keys"])),
            "dropped_reference_frames": alignment["dropped_reference_frames"],
            "dropped_candidate_frames": alignment["dropped_candidate_frames"],
        },
        "metrics": metrics,
        "lifecycle": lifecycle,
        "per_frame": per_frame,
        "native_observables": {
            "reference": reference_observables,
            "candidate": candidate_observables,
            "comparison": _observable_comparison(reference_observables, candidate_observables, frame_pairs),
        },
        "scientific_acceptance": {
            "status": "not_assessed",
            "emitted": False,
            "reason_code": "NO_EXTERNAL_GROUND_TRUTH",
            "reason": "The evaluator compared a numerical trajectory to another trajectory; no external measurement or authenticated ground truth was supplied.",
        },
        "execution_guards": {
            "training_started": False,
            "inference_started": False,
            "checkpoint_read": False,
            "solver_started": False,
            "gpu_started": False,
        },
    }
    return result


def inspect_trajectory(trajectory, *, reference_card=None):
    return {
        "schema": RESULT_SCHEMA,
        "mode": "model_free_trajectory_inspection",
        "trajectory": trajectory.summary(),
        "scope": _scope_from_card(trajectory, reference_card),
        "native_observables": native_observables(trajectory),
        "scientific_acceptance": {
            "status": "not_assessed",
            "emitted": False,
            "reason_code": "NO_EXTERNAL_GROUND_TRUTH",
        },
        "execution_guards": {
            "training_started": False,
            "inference_started": False,
            "checkpoint_read": False,
            "solver_started": False,
            "gpu_started": False,
        },
    }


def _write_synthetic_hdf5(path):
    if h5py is None:
        raise RuntimeError("h5py is required for the synthetic test")
    time = np.asarray([0.0, 1.0, 2.0])
    keys = [(0, 10), (0, 20), (0, 30)]
    position = np.asarray([
        [[0, 0, 0], [1, 0, 0], [2, 0, 0]],
        [[0.1, 0, 0], [1.1, 0, 0], [np.nan, np.nan, np.nan]],
        [[0.2, 0, 0], [1.2, 0, 0], [np.nan, np.nan, np.nan]],
    ], dtype=np.float64)
    velocity = np.asarray([
        [[0.1, 0, 0], [0.1, 0, 0], [0.1, 0, 0]],
        [[0.1, 0, 0], [0.1, 0, 0], [np.nan, np.nan, np.nan]],
        [[0.1, 0, 0], [0.1, 0, 0], [np.nan, np.nan, np.nan]],
    ], dtype=np.float64)
    valid = np.asarray([[1, 1, 1], [1, 1, 0], [1, 1, 0]], dtype=bool)
    with h5py.File(path, "w") as handle:
        handle.attrs.update({"schema_version": 3, "case_id": "synthetic_reference",
                             "family": "F1", "identity_key": "particle_id",
                             "trajectory_semantics": "synthetic numerical identity"})
        handle.create_dataset("time", data=time)
        handle.create_dataset("particle_id", data=np.asarray([key[1] for key in keys], dtype=np.int64))
        handle.create_dataset("particle_zone", data=np.asarray([key[0] for key in keys], dtype=np.int16))
        handle.create_dataset("valid", data=valid)
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("mass", data=np.full((3, 3), 1.0))
        handle.create_dataset("density", data=np.full((3, 3), 1000.0))
        handle.create_dataset("pressure", data=np.zeros((3, 3)))
        handle.create_dataset("type", data=np.full((3, 3), 3, dtype=np.int8))
        handle.create_dataset("mk", data=np.full((3, 3), 1, dtype=np.int16))


def _write_synthetic_partvtk(directory):
    directory.mkdir()
    header = "Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3],Mass [kg],Press [Pa],Type,Mk,\n"
    frames = [
        (0.0, [(0.1, 10), (1.1, 20), (2.1, 30), (9.0, 40)]),
        (1.0000001, [(0.2, 10), (1.2, 20)]),
        (2.0, [(0.3, 10), (1.3, 20)]),
    ]
    for frame_index, (time, rows) in enumerate(frames):
        lines = ["TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid,\n",
                 f"{time},{len(rows)},0,0,0,0,{len(rows)},\n", header]
        for x, particle_id in rows:
            lines.append(f"{x},0,0,0,{particle_id},0.1,0,0,1000,1,0,3,1,\n")
        (directory / f"Particles_{frame_index:04d}.csv").write_text("".join(lines), encoding="utf-8")


def synthetic_test():
    """Exercise HDF5/CSV loading, common-ID/time alignment, and open masking."""
    with tempfile.TemporaryDirectory(prefix="ds-data-01-d07-") as directory:
        root = Path(directory)
        reference_path = root / "reference.h5"
        csv_path = root / "candidate_csv"
        _write_synthetic_hdf5(reference_path)
        _write_synthetic_partvtk(csv_path)
        reference = load_trajectory(reference_path)
        candidate = load_trajectory(csv_path)
        result = score_trajectories(reference, candidate, time_tolerance_s=1e-3, dp=0.1)
        assert reference.source_format == "hdf5"
        assert candidate.source_format == "csv_frames"
        assert result["alignment"]["matched_frame_count"] == 3
        assert result["alignment"]["common_identity_count"] == 3
        assert result["alignment"]["candidate_only_identity_count"] == 1
        assert result["scope"]["open_lifecycle"] is True
        assert result["lifecycle"]["mask_disagreement_fraction"] is not None
        assert result["metrics"]["position_rmse_m"] is not None
        assert abs(result["metrics"]["position_rmse_over_dp"] - 1.0) < 1e-12
        assert result["native_observables"]["comparison"]["active_particle_count"]["status"] == "ok"
        assert result["scientific_acceptance"]["status"] == "not_assessed"
        assert result["scientific_acceptance"]["emitted"] is False
        return {
            "status": "pass",
            "test": "hdf5_reference_vs_partvtk_csv_open_lifecycle",
            "matched_frames": result["alignment"]["matched_frame_count"],
            "common_identities": result["alignment"]["common_identity_count"],
            "candidate_only_identities": result["alignment"]["candidate_only_identity_count"],
            "scientific_acceptance": result["scientific_acceptance"],
        }


def _contract_path():
    return Path(__file__).resolve().parents[1] / "campaigns/ds-data-01/D07_EVALUATOR_CONTRACT.json"


def _print_json(payload):
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("synthetic-test", help="run the temporary read-only synthetic test")
    subparsers.add_parser("contract", help="print the D07 JSON contract")
    inspect_parser = subparsers.add_parser("inspect", help="inspect one HDF5 or CSV trajectory")
    inspect_parser.add_argument("--input", required=True, type=Path)
    inspect_parser.add_argument("--reference-cards", type=Path)
    score_parser = subparsers.add_parser("score", help="score two aligned trajectories")
    score_parser.add_argument("--reference", required=True, type=Path)
    score_parser.add_argument("--candidate", required=True, type=Path)
    score_parser.add_argument("--time-tolerance-s", type=float, default=DEFAULT_TIME_TOLERANCE_S)
    score_parser.add_argument("--dp", type=float)
    score_parser.add_argument("--reference-cards", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "synthetic-test":
            _print_json(synthetic_test())
        elif args.command == "contract":
            _print_json(json.loads(_contract_path().read_text(encoding="utf-8")))
        elif args.command == "inspect":
            trajectory = load_trajectory(args.input)
            cards = load_reference_cards(args.reference_cards)
            _print_json(inspect_trajectory(trajectory, reference_card=cards.get(_case_id(trajectory))))
        elif args.command == "score":
            reference = load_trajectory(args.reference)
            candidate = load_trajectory(args.candidate)
            cards = load_reference_cards(args.reference_cards)
            card = cards.get(_case_id(reference))
            _print_json(score_trajectories(reference, candidate,
                                           time_tolerance_s=args.time_tolerance_s,
                                           dp=args.dp, reference_card=card))
        return 0
    except (AssertionError, OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"D07 evaluator error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

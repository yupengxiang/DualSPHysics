#!/usr/bin/env python3
"""Read DS-DATA-02 typed trajectories without assuming a grid or frame count.

This is a bounded consumer-side reader for converted ``trajectory.h5`` files.
It obtains the particle and time axes from the file itself, checks the typed
identity contract, and optionally reads only explicitly selected frame slices.
It does not invoke a solver or decoder, and it never hashes an HDF5 payload.
The resulting sidecar is structural evidence only; it does not grant Q-I,
Q-N, Q-E, or reference eligibility.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "ds-data-02.stage2.generic-typed-reader.v1"
REQUIRED_STATIC = (
    "particle_id",
    "particle_zone",
    "initial_type",
    "initial_mk",
    "initial_mass",
)
REQUIRED_DYNAMIC = (
    "time",
    "position",
    "velocity",
    "density",
    "mass",
    "pressure",
    "valid",
    "type",
    "mk",
)
VECTOR_FIELDS = {"position", "velocity"}
SCALAR_FIELDS = {"density", "mass", "pressure", "valid", "type", "mk"}
DEFAULT_SAMPLE_FIELDS = ("position", "velocity", "density", "mass", "valid")


class ReaderError(RuntimeError):
    """Raised when the typed trajectory violates its structural contract."""


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _existing_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ReaderError(f"{label} is missing: {path}")
    return path


def _attribute_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        return [_attribute_value(item) for item in value.tolist()]
    return _json_default(value) if isinstance(value, (np.generic, Path)) else value


def _dataset_description(dataset: h5py.Dataset) -> dict[str, Any]:
    result: dict[str, Any] = {
        "shape": [int(item) for item in dataset.shape],
        "dtype": str(dataset.dtype),
        "chunks": None if dataset.chunks is None else [int(item) for item in dataset.chunks],
        "compression": dataset.compression,
    }
    units = dataset.attrs.get("units")
    if units is not None:
        result["units"] = _attribute_value(units)
    return result


def _parse_units(handle: h5py.File) -> Mapping[str, Any] | None:
    raw = handle.attrs.get("units_json")
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"raw": _attribute_value(raw), "parse_status": "UNKNOWN"}
    return value if isinstance(value, Mapping) else {"value": value}


def _check_shape_contract(handle: h5py.File) -> tuple[int, int, dict[str, Any]]:
    names = set(handle.keys())
    missing = [name for name in (*REQUIRED_STATIC, *REQUIRED_DYNAMIC) if name not in names]
    if missing:
        raise ReaderError(f"trajectory is missing required datasets: {missing}")
    time = handle["time"]
    if time.ndim != 1 or time.shape[0] == 0:
        raise ReaderError(f"time must be a non-empty one-dimensional dataset: {time.shape}")
    frames = int(time.shape[0])
    particle_id = handle["particle_id"]
    zone = handle["particle_zone"]
    if particle_id.ndim != 1 or zone.ndim != 1 or particle_id.shape != zone.shape:
        raise ReaderError("particle_id and particle_zone must be one-dimensional axes of equal length")
    particles = int(particle_id.shape[0])
    if particles == 0:
        raise ReaderError("particle axis is empty")

    descriptions: dict[str, Any] = {}
    for name in (*REQUIRED_STATIC, *REQUIRED_DYNAMIC):
        descriptions[name] = _dataset_description(handle[name])
    for name in REQUIRED_DYNAMIC[1:]:
        dataset = handle[name]
        if name in VECTOR_FIELDS:
            expected = (frames, particles, 3)
        else:
            expected = (frames, particles)
        if dataset.shape != expected:
            raise ReaderError(f"{name} has shape {dataset.shape}; expected {expected}")
    for name in ("initial_type", "initial_mk", "initial_mass"):
        if handle[name].shape != (particles,):
            raise ReaderError(f"{name} has shape {handle[name].shape}; expected {(particles,)}")
    if not np.issubdtype(time.dtype, np.number):
        raise ReaderError(f"time dtype is not numeric: {time.dtype}")
    times = np.asarray(time[...], dtype=np.float64)
    if not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0):
        raise ReaderError("time must be finite and strictly increasing")
    descriptions["time_values_s"] = {
        "first": float(times[0]),
        "last": float(times[-1]),
        "count": frames,
        "strictly_increasing": True,
    }
    return frames, particles, descriptions


def _identity_summary(handle: h5py.File, particles: int) -> dict[str, Any]:
    # Identity and initial arrays are bounded metadata (O(particles)); no
    # frame-dependent payload is touched here.
    ids = np.asarray(handle["particle_id"][...])
    zones = np.asarray(handle["particle_zone"][...])
    pairs = np.empty(particles, dtype=[("zone", zones.dtype), ("id", ids.dtype)])
    pairs["zone"] = zones
    pairs["id"] = ids
    unique_count = int(np.unique(pairs).size)
    if unique_count != particles:
        raise ReaderError(f"typed identity is not unique: {unique_count} of {particles} pairs")
    initial_type = np.asarray(handle["initial_type"][...])
    initial_mk = np.asarray(handle["initial_mk"][...])
    initial_mass = np.asarray(handle["initial_mass"][...], dtype=np.float64)
    if not np.all(np.isfinite(initial_mass)):
        raise ReaderError("initial_mass contains non-finite values")
    return {
        "key": "(particle_zone, particle_id)",
        "unique": True,
        "particle_count": particles,
        "zone_values": [int(value) for value in np.unique(zones)],
        "particle_id_min": int(np.min(ids)),
        "particle_id_max": int(np.max(ids)),
        "initial_type_counts": {str(int(k)): int(v) for k, v in sorted(Counter(initial_type.tolist()).items())},
        "initial_mk_counts": {str(int(k)): int(v) for k, v in sorted(Counter(initial_mk.tolist()).items())},
        "initial_mass_total_kg": float(np.sum(initial_mass, dtype=np.float64)),
        "initial_mass_min_kg": float(np.min(initial_mass)),
        "initial_mass_max_kg": float(np.max(initial_mass)),
    }


def _bracket(times: np.ndarray, query: float) -> dict[str, Any]:
    if not np.isfinite(query):
        raise ReaderError(f"query time is not finite: {query}")
    if query < float(times[0]) or query > float(times[-1]):
        return {"query_time_s": float(query), "status": "OUTSIDE_SAVED_WINDOW"}
    right = int(np.searchsorted(times, query, side="left"))
    if right == 0:
        return {"query_time_s": float(query), "status": "EXACT_OR_LEFT", "lower_index": 0, "upper_index": 0,
                "lower_time_s": float(times[0]), "upper_time_s": float(times[0])}
    if right == len(times):
        right -= 1
    left = right - 1 if times[right] > query else right
    exact = bool(times[left] == query)
    upper = left if exact else right
    return {
        "query_time_s": float(query),
        "status": "EXACT" if exact else "BRACKETED",
        "lower_index": int(left),
        "upper_index": int(upper),
        "lower_time_s": float(times[left]),
        "upper_time_s": float(times[upper]),
        "interpolation_fraction": 0.0 if exact else float((query - times[left]) / (times[upper] - times[left])),
    }


def _numeric_summary(values: np.ndarray) -> dict[str, Any]:
    array = np.asarray(values)
    finite = np.isfinite(array) if np.issubdtype(array.dtype, np.number) else np.ones(array.shape, dtype=bool)
    result: dict[str, Any] = {
        "shape": [int(item) for item in array.shape],
        "dtype": str(array.dtype),
        "finite_count": int(np.count_nonzero(finite)),
        "value_count": int(array.size),
    }
    if np.any(finite):
        selected = array[finite]
        result.update(min=float(np.min(selected)), max=float(np.max(selected)))
    return result


def _selected_frame_summary(handle: h5py.File, frame_indices: Sequence[int], sample_count: int,
                            fields: Sequence[str], full_frame: bool) -> list[dict[str, Any]]:
    frames = int(handle["time"].shape[0])
    particles = int(handle["particle_id"].shape[0])
    for name in fields:
        if name not in SCALAR_FIELDS and name not in VECTOR_FIELDS:
            raise ReaderError(f"unsupported selected field: {name}")
    result = []
    count = particles if full_frame else min(max(int(sample_count), 1), particles)
    for frame in frame_indices:
        if frame < 0 or frame >= frames:
            raise ReaderError(f"frame index outside [0,{frames}): {frame}")
        entry: dict[str, Any] = {
            "frame_index": int(frame),
            "time_s": float(handle["time"][frame]),
            "read_scope": "full_frame" if full_frame else f"first_{count}_particles",
            "fields": {},
        }
        for name in fields:
            dataset = handle[name]
            values = np.asarray(dataset[frame, ...] if full_frame else dataset[frame, :count, ...])
            entry["fields"][name] = _numeric_summary(values)
        result.append(entry)
    return result


def inspect_trajectory(trajectory: Path, *, conversion_report: Path | None = None,
                       frame_indices: Sequence[int] = (), query_times: Sequence[float] = (),
                       sample_count: int = 16, fields: Sequence[str] = DEFAULT_SAMPLE_FIELDS,
                       full_frame: bool = False) -> dict[str, Any]:
    trajectory = _existing_file(trajectory, "trajectory")
    stat = trajectory.stat()
    report_info: dict[str, Any] | None = None
    if conversion_report is not None:
        report_path = _existing_file(conversion_report, "conversion report")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ReaderError(f"conversion report is not valid JSON: {report_path}") from error
        expected = report.get("output_hdf5")
        if expected and Path(str(expected)).expanduser().resolve() != trajectory:
            raise ReaderError("conversion report output_hdf5 does not identify the supplied trajectory")
        provenance = report.get("source_provenance")
        decoder = provenance.get("decoder") if isinstance(provenance, Mapping) else None
        if not isinstance(decoder, Mapping) or not decoder.get("path") or not decoder.get("sha256"):
            raise ReaderError("conversion report has no source_provenance.decoder binding")
        decoder_path = _existing_file(str(decoder["path"]), "reported decoder")
        actual_decoder_sha = _sha256_file(decoder_path)
        if actual_decoder_sha != decoder["sha256"]:
            raise ReaderError("reported decoder digest differs from the accessible decoder")
        report_info = {
            "path": str(report_path),
            "sha256": _sha256_file(report_path),
            "schema": report.get("schema"),
            "conversion_status": report.get("conversion_status"),
            "output_sha256_declared": report.get("output_sha256"),
            "source_provenance_decoder": {"path": str(decoder_path), "sha256": actual_decoder_sha},
            "source_provenance_raw_tree": provenance.get("raw_tree") if isinstance(provenance, Mapping) else None,
        }

    with h5py.File(trajectory, "r") as handle:
        frames, particles, datasets = _check_shape_contract(handle)
        identity = _identity_summary(handle, particles)
        times = np.asarray(handle["time"][...], dtype=np.float64)
        selected = _selected_frame_summary(handle, frame_indices, sample_count, fields, full_frame) if frame_indices else []
        brackets = [_bracket(times, float(query)) for query in query_times]
        attrs = {str(key): _attribute_value(value) for key, value in handle.attrs.items()
                 if str(key) in {"schema", "identity_key", "coordinate_frame", "conversion_complete",
                                 "q_i_status", "q_n_status", "production_eligibility", "mass_semantics"}}
        return {
            "schema": SCHEMA,
            "status": "STRUCTURAL_READ_PASS",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "trajectory": {
                "path": str(trajectory),
                "bytes": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
                "producer_declared_sha256": _attribute_value(handle.attrs.get("output_sha256")),
                "full_payload_sha256": "NOT_COMPUTED",
            },
            "read_scope": {
                "header_and_time_axis": True,
                "identity_and_initial_arrays": True,
                "selected_frame_payload": bool(frame_indices),
                "full_trajectory_payload": False,
                "selected_frame_policy": "explicit indices only; no implicit full-time scan",
            },
            "shape_contract": {"frames": frames, "particles": particles, "datasets": datasets,
                               "units": _parse_units(handle)},
            "identity": identity,
            "trajectory_attributes": attrs,
            "query_time_brackets": brackets,
            "selected_frames": selected,
            "conversion_report": report_info,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame-index", type=int, action="append", default=[])
    parser.add_argument("--query-time", type=float, action="append", default=[])
    parser.add_argument("--sample-count", type=int, default=16)
    parser.add_argument("--field", dest="fields", action="append", default=None)
    parser.add_argument("--full-frame", action="store_true")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = inspect_trajectory(
            args.trajectory,
            conversion_report=args.conversion_report,
            frame_indices=args.frame_index,
            query_times=args.query_time,
            sample_count=args.sample_count,
            fields=tuple(args.fields) if args.fields else DEFAULT_SAMPLE_FIELDS,
            full_frame=args.full_frame,
        )
        encoded = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default) + "\n"
        temporary = output.with_name(output.name + f".{__import__('os').getpid()}.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(output)
    except ReaderError as error:
        raise SystemExit(f"reader error: {error}") from error
    print(json.dumps({"status": result["status"], "output": str(output),
                      "frames": result["shape_contract"]["frames"],
                      "particles": result["shape_contract"]["particles"],
                      "full_payload_sha256": result["trajectory"]["full_payload_sha256"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

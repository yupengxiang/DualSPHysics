#!/usr/bin/env python3
"""Derive a direct cadence-matched F4 source from a native dense HDF5.

This tool copies saved rows from a completed native ``.002 s`` trajectory.  It
never interpolates fields and it never runs a solver.  The output is a derived
``.02 s`` reference whose provenance records the exact source frame indices,
requested times, selected native times, and both file hashes.  An independently
solved ``.02 s`` trajectory may be recorded for comparison, but is never used
as the input to this copy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import h5py
import numpy as np


SCHEMA = "core.material.f4.native_cadence_downsample.v1"
REQUIRED_DATASETS = ("time", "position", "velocity", "valid")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _nearest_indices(times: np.ndarray, targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    right = np.searchsorted(times, targets, side="left")
    right = np.clip(right, 0, len(times) - 1)
    left = np.maximum(0, right - 1)
    choose_left = np.abs(times[left] - targets) <= np.abs(times[right] - targets)
    indices = np.where(choose_left, left, right).astype(np.int64)
    errors = times[indices] - targets
    return indices, errors


def select_indices(
    times: np.ndarray,
    *,
    target_interval_s: float,
    target_time_max_s: float | None = None,
    tolerance_s: float | None = None,
    minimum_source_to_target_ratio: float = 2.0,
) -> dict:
    """Select native rows nearest a target cadence without interpolation."""
    times = np.asarray(times, dtype=np.float64)
    if times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("source time must be finite, strictly increasing, and contain at least two frames")
    target_interval_s = float(target_interval_s)
    if not np.isfinite(target_interval_s) or target_interval_s <= 0:
        raise ValueError("target_interval_s must be positive and finite")
    if target_time_max_s is None:
        target_time_max_s = float(times[-1])
    target_time_max_s = float(target_time_max_s)
    if not np.isfinite(target_time_max_s) or target_time_max_s < times[0]:
        raise ValueError("target_time_max_s must be finite and at or after source start")
    if target_time_max_s > times[-1] + 1e-9:
        raise ValueError("source does not reach requested target_time_max_s")
    source_steps = np.diff(times)
    source_median = float(np.median(source_steps))
    if source_median >= target_interval_s / float(minimum_source_to_target_ratio):
        raise ValueError(
            "source cadence is not demonstrably denser than target; refusing an independent native .02 source"
        )
    count = int(np.floor((target_time_max_s - times[0]) / target_interval_s + 1e-9)) + 1
    targets = times[0] + np.arange(count, dtype=np.float64) * target_interval_s
    indices, errors = _nearest_indices(times, targets)
    if len(np.unique(indices)) != len(indices) or np.any(np.diff(indices) <= 0):
        raise ValueError("target cadence maps to duplicate or non-monotone native frames")
    tolerance = float(0.25 * target_interval_s if tolerance_s is None else tolerance_s)
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance_s must be finite and non-negative")
    if np.max(np.abs(errors)) > tolerance:
        raise ValueError("native frame is too far from requested target cadence")
    return {
        "source_frame_indices": indices.tolist(),
        "requested_target_times_s": targets.tolist(),
        "selected_source_times_s": times[indices].tolist(),
        "selection_error_s": errors.tolist(),
        "target_interval_s": target_interval_s,
        "target_time_max_s": target_time_max_s,
        "selection_tolerance_s": tolerance,
        "source_median_interval_s": source_median,
        "source_min_interval_s": float(np.min(source_steps)),
        "source_max_interval_s": float(np.max(source_steps)),
        "source_to_target_interval_ratio": float(target_interval_s / source_median),
    }


def _copy_attrs(source: h5py.Group, target: h5py.Group) -> None:
    for key, value in source.attrs.items():
        target.attrs[key] = value


def _copy_group(source: h5py.Group, target: h5py.Group, selected: np.ndarray, frame_count: int) -> None:
    for name, item in source.items():
        if isinstance(item, h5py.Group):
            group = target.create_group(name)
            _copy_attrs(item, group)
            _copy_group(item, group, selected, frame_count)
            continue
        if not isinstance(item, h5py.Dataset):
            raise ValueError(f"unsupported HDF5 object at {item.name}")
        is_frame_axis = item.ndim >= 1 and item.shape[0] == frame_count
        if not is_frame_axis:
            source.copy(item, target, name=name)
            continue
        shape = (len(selected),) + item.shape[1:]
        chunks = item.chunks
        if chunks is not None:
            chunks = (1,) + tuple(chunks[1:])
            chunks = tuple(min(a, b) for a, b in zip(chunks, shape))
        created = target.create_dataset(name, shape=shape, dtype=item.dtype, chunks=chunks)
        for output_index, source_index in enumerate(selected):
            created[output_index] = item[int(source_index)]
        _copy_attrs(item, created)


def downsample(
    source: Path,
    output: Path,
    *,
    target_interval_s: float = 0.02,
    target_time_max_s: float | None = None,
    tolerance_s: float | None = None,
    independent_native_source: Path | None = None,
) -> dict:
    """Copy direct native rows and publish a hash-bound provenance receipt."""
    source = Path(source).resolve()
    output = Path(output).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists() or output.with_suffix(output.suffix + ".partial").exists():
        raise FileExistsError(f"output or partial output already exists: {output}")
    source_sha256 = digest(source)
    with h5py.File(source, "r") as source_h5:
        missing = [name for name in REQUIRED_DATASETS if name not in source_h5]
        if missing:
            raise ValueError("native trajectory is missing datasets: " + ", ".join(missing))
        complete = source_h5.attrs.get("conversion_complete", True)
        if isinstance(complete, (bytes, np.bytes_)):
            complete = complete.decode("utf-8").strip().lower() == "true"
        else:
            complete = bool(complete)
        if not complete:
            raise ValueError("source native trajectory is not marked conversion_complete")
        times = np.asarray(source_h5["time"], dtype=np.float64)
        frame_count = len(times)
        layout = source_h5["position"].shape
        if source_h5["position"].ndim != 3 or layout[0] != frame_count or layout[2:] != (3,):
            raise ValueError("source position must have shape [frames, particles, 3]")
        if source_h5["velocity"].shape != layout or source_h5["valid"].shape != layout[:2]:
            raise ValueError("source velocity/valid axes do not match position")
        selection = select_indices(
            times,
            target_interval_s=target_interval_s,
            target_time_max_s=target_time_max_s,
            tolerance_s=tolerance_s,
        )
        selected = np.asarray(selection["source_frame_indices"], dtype=np.int64)
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_suffix(output.suffix + ".partial")
        with h5py.File(partial, "w") as output_h5:
            _copy_attrs(source_h5, output_h5)
            _copy_group(source_h5, output_h5, selected, frame_count)
            output_h5.attrs["schema"] = SCHEMA
            output_h5.attrs["cadence_derived_from_native_dense"] = True
            output_h5.attrs["cadence_derivation_interpolation"] = False
            output_h5.attrs["cadence_source_sha256"] = source_sha256
            output_h5.attrs["cadence_source_frame_indices"] = json.dumps(selected.tolist())
            output_h5.attrs["cadence_target_interval_s"] = float(target_interval_s)
            output_h5.attrs["cadence_target_time_max_s"] = float(selection["target_time_max_s"])
            output_h5.flush()
        os.replace(partial, output)
    independent = None
    if independent_native_source is not None:
        independent_native_source = Path(independent_native_source).resolve()
        if not independent_native_source.is_file():
            raise FileNotFoundError(independent_native_source)
        if independent_native_source == source:
            raise ValueError("independent native source must differ from dense source")
        independent = {
            "path": str(independent_native_source),
            "sha256": digest(independent_native_source),
            "used_as_downsample_input": False,
            "role": "independent_native_002s_comparison_only",
        }
    output_sha256 = digest(output)
    receipt = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {"path": str(source), "sha256": source_sha256, "frame_count": frame_count},
        "output": {"path": str(output), "sha256": output_sha256,
                    "frame_count": len(selection["source_frame_indices"])},
        "selection": selection,
        "independent_native_comparison": independent,
        "copy_contract": {
            "direct_saved_row_copy": True,
            "field_interpolation": False,
            "solver_started": False,
            "ledger_touched": False,
            "source_frame_indices_are_authoritative": True,
        },
    }
    atomic_json(output.with_suffix(".json"), receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-interval-s", type=float, default=0.02)
    parser.add_argument("--target-time-max-s", type=float, default=0.3)
    parser.add_argument("--tolerance-s", type=float)
    parser.add_argument("--independent-native-source", type=Path)
    args = parser.parse_args()
    receipt = downsample(
        args.source,
        args.output,
        target_interval_s=args.target_interval_s,
        target_time_max_s=args.target_time_max_s,
        tolerance_s=args.tolerance_s,
        independent_native_source=args.independent_native_source,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

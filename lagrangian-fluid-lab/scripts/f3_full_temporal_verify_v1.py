#!/usr/bin/env python3
"""Bounded full-temporal F3 reader/oracle verification.

The registered ``core.dataset.v2`` manifest and its known-input/source hash
contracts are still checked by :class:`CoreDataset`.  The expensive temporal
pass deliberately does not call ``CoreDataset.read_state``: it opens one
registered HDF5 source read-only and processes only bounded frame chunks.
Future frames are used only by the privileged reference oracle below; no
predictor or learning path receives them.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

# A command-line verification is read-only; do not leave Python bytecode in
# the registered input tree as a side effect of importing this entrypoint.
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import h5py
import numpy as np

# Make both ``python scripts/f3_full_temporal_verify_v1.py`` and
# ``python -m scripts.f3_full_temporal_verify_v1`` resolve the lab package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_dataset import COMPACT_SCHEMA, CoreDataset, sha256_file


SCHEMA = "core.f3.full_temporal_verification.v1"
SCHEMA_VERSION = 1
ORACLE_ERROR_TOLERANCE = 1.0e-10
DEFAULT_FRAME_CHUNK_SIZE = 8
MAX_FRAME_CHUNK_SIZE = 1024
DEFAULT_MAX_CHUNK_BYTES = 512 * 1024 * 1024

_REQUIRED_DATASETS = frozenset({
    "time", "position", "velocity", "particle_id", "particle_zone", "mass", "valid",
})


def _positive_int(value, *, name, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    value = int(value)
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


def _manifest_and_root(manifest, data_root):
    if not isinstance(manifest, (str, Path)):
        raise ValueError("an explicit core.dataset.v2 manifest path is required")
    if data_root is None:
        raise ValueError("an explicit data_root is required")
    manifest_path = Path(manifest).expanduser().resolve()
    root = Path(data_root).expanduser().resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    if not root.is_dir():
        raise FileNotFoundError(root)
    return manifest_path, root


def _source_path(root, row):
    relative = Path(row["hdf5"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"nonportable HDF5 source path: {row['case_id']}")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"HDF5 source escapes data_root: {row['case_id']}") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _read_float64_block(dataset, start, stop, tail_shape):
    """Read a bounded HDF5 slab with the State-compatible float64 dtype."""
    shape = (stop - start, *tail_shape)
    result = np.empty(shape, dtype=np.float64)
    source_sel = (slice(start, stop),) + (slice(None),) * len(tail_shape)
    dataset.read_direct(result, source_sel=source_sel)
    return result


def _read_identity(dataset, *, name, particle_count):
    values = np.asarray(dataset[...])
    if values.shape != (particle_count,) or values.dtype.kind not in "iu":
        raise ValueError(f"{name} must be a one-dimensional integer identity axis")
    if values.dtype.kind == "u" and values.size:
        if int(np.max(values)) > np.iinfo(np.int64).max:
            raise ValueError(f"{name} exceeds the State int64 identity range")
    values = values.astype(np.int64, copy=False)
    return np.array(values, dtype=np.int64, copy=True)


def _validate_composite_identity(particle_id, particle_zone):
    """Validate the full composite identity once, not once per frame."""
    order = np.lexsort((particle_id, particle_zone))
    duplicate = ((particle_id[order[1:]] == particle_id[order[:-1]])
                 & (particle_zone[order[1:]] == particle_zone[order[:-1]]))
    if np.any(duplicate):
        raise ValueError("duplicate composite particle identity (particle_zone, particle_id)")


def _validate_chunk_memory(*, particle_count, transition_count, mass_is_temporal,
                           max_chunk_bytes):
    """Return the declared numeric-buffer bound for one transition chunk.

    Position and velocity are read as float64 state-compatible slabs.  One
    scratch slab is reused for the position and velocity commit oracles.  The
    valid/mass terms are conservatively charged at eight bytes per value even
    when their HDF5 dtypes are smaller.
    """
    state_bytes = (particle_count * 3 * 8 * 2)  # position + velocity
    valid_bytes = particle_count * 8
    mass_bytes = particle_count * 8 if mass_is_temporal else 0
    scratch_bytes = particle_count * 3 * 8
    bound = (transition_count + 1) * (state_bytes + valid_bytes + mass_bytes) + scratch_bytes * transition_count
    if bound > max_chunk_bytes:
        raise ValueError(
            "requested frame chunk exceeds max_chunk_bytes: "
            f"estimated {bound} > {max_chunk_bytes}")
    return int(bound)


def _commit_oracle_max_error(current, following, scratch, active_indices):
    """Vectorized reference-increment + commit error for one field.

    ``following`` is a privileged oracle target.  It is never passed to a
    predictor, and only active rows contribute to the maximum error.
    """
    np.subtract(following, current, out=scratch)
    np.add(current, scratch, out=scratch)
    np.subtract(scratch, following, out=scratch)
    np.abs(scratch, out=scratch)
    if active_indices.size == current.shape[1]:
        return float(np.max(scratch))
    return float(np.max(scratch[:, active_indices, :]))


def _validate_active_frame(position, velocity, mass, active_indices, *, case_id, frame):
    if not np.isfinite(position[active_indices]).all():
        raise ValueError(f"nonfinite active position: {case_id} frame {frame}")
    if not np.isfinite(velocity[active_indices]).all():
        raise ValueError(f"nonfinite active velocity: {case_id} frame {frame}")
    active_mass = mass[active_indices]
    if (not np.isfinite(active_mass).all()) or np.any(active_mass <= 0):
        raise ValueError(f"active mass must be finite and positive: {case_id} frame {frame}")


def _verify_case(data, case_id, *, source_sha256, frame_chunk_size, max_chunk_bytes):
    row = data.record(case_id)
    source_path = _source_path(data.data_root, row)

    with h5py.File(source_path, "r") as handle:
        missing = _REQUIRED_DATASETS - set(handle)
        if missing:
            raise ValueError(f"missing native HDF5 fields for {case_id}: {sorted(missing)}")

        time_dataset = handle["time"]
        position_dataset = handle["position"]
        velocity_dataset = handle["velocity"]
        particle_id_dataset = handle["particle_id"]
        particle_zone_dataset = handle["particle_zone"]
        mass_dataset = handle["mass"]
        valid_dataset = handle["valid"]

        if len(time_dataset.shape) != 1 or time_dataset.shape[0] < 2:
            raise ValueError(f"time must contain at least two samples: {case_id}")
        frame_count = int(time_dataset.shape[0])
        times = np.asarray(time_dataset[...], dtype=np.float64)
        if (times.shape != (frame_count,) or not np.isfinite(times).all()
                or np.any(np.diff(times) <= 0)):
            raise ValueError(f"time must be finite and strictly increasing: {case_id}")

        if len(position_dataset.shape) != 3 or position_dataset.shape[0] != frame_count:
            raise ValueError(f"invalid position shape: {case_id}")
        if (len(velocity_dataset.shape) != 3
                or velocity_dataset.shape != position_dataset.shape):
            raise ValueError(f"invalid velocity shape: {case_id}")
        particle_count = int(position_dataset.shape[1])
        if position_dataset.shape[2] != 3 or particle_count < 1:
            raise ValueError(f"position must have shape [frames, particles, 3]: {case_id}")

        particle_id = _read_identity(
            particle_id_dataset, name="particle_id", particle_count=particle_count)
        particle_zone = _read_identity(
            particle_zone_dataset, name="particle_zone", particle_count=particle_count)
        _validate_composite_identity(particle_id, particle_zone)

        if valid_dataset.shape != (frame_count, particle_count):
            raise ValueError(f"invalid valid shape: {case_id}")
        if valid_dataset.dtype.kind not in "biu":
            raise ValueError(f"valid must be an explicit binary mask: {case_id}")

        if mass_dataset.shape not in ((particle_count,), (frame_count, particle_count)):
            raise ValueError(f"invalid mass shape: {case_id}")
        mass_is_temporal = len(mass_dataset.shape) == 2
        if mass_is_temporal:
            mass_reference = _read_float64_block(mass_dataset, 0, 1, (particle_count,))[0]
        else:
            mass_reference = np.asarray(mass_dataset[...], dtype=np.float64)
        if mass_reference.shape != (particle_count,):
            raise ValueError(f"invalid mass particle axis: {case_id}")

        transitions = frame_count - 1
        effective_chunk = min(frame_chunk_size, transitions)
        estimated_bound = _validate_chunk_memory(
            particle_count=particle_count,
            transition_count=effective_chunk,
            mass_is_temporal=mass_is_temporal,
            max_chunk_bytes=max_chunk_bytes,
        )

        reference_valid = None
        active_indices = None
        max_position_error = 0.0
        max_velocity_error = 0.0
        checked_transitions = 0

        for start in range(0, transitions, effective_chunk):
            stop = min(start + effective_chunk, transitions)
            block_stop = stop + 1
            position = _read_float64_block(
                position_dataset, start, block_stop, (particle_count, 3))
            velocity = _read_float64_block(
                velocity_dataset, start, block_stop, (particle_count, 3))
            raw_valid = np.asarray(valid_dataset[start:block_stop])
            if (raw_valid.shape != (block_stop - start, particle_count)
                    or not np.isin(raw_valid, (0, 1)).all()):
                raise ValueError(f"valid must contain only binary values: {case_id}")
            valid = np.asarray(raw_valid, dtype=bool)
            if reference_valid is None:
                reference_valid = np.array(valid[0], dtype=bool, copy=True)
                if not reference_valid.any():
                    raise ValueError(f"at least one active particle is required: {case_id}")
                active_indices = np.flatnonzero(reference_valid)
                reference_mass = mass_reference[active_indices]
                if (not np.isfinite(reference_mass).all()) or np.any(reference_mass <= 0):
                    raise ValueError(f"active mass must be finite and positive: {case_id} frame 0")

            mass = (mass_reference[None, :]
                    if not mass_is_temporal else
                    _read_float64_block(mass_dataset, start, block_stop, (particle_count,)))
            scratch = np.empty((stop - start, particle_count, 3), dtype=np.float64)

            for local_frame in range(block_stop - start):
                absolute_frame = start + local_frame
                if not np.array_equal(valid[local_frame], reference_valid):
                    raise ValueError(f"valid lifecycle changed: {case_id} frame {absolute_frame}")
                mass_row = mass[0] if not mass_is_temporal else mass[local_frame]
                if not np.array_equal(mass_row[active_indices], reference_mass):
                    raise ValueError(f"mass lifecycle changed: {case_id} frame {absolute_frame}")
                _validate_active_frame(
                    position[local_frame], velocity[local_frame], mass_row,
                    active_indices, case_id=case_id, frame=absolute_frame)

            current_position = position[:-1]
            following_position = position[1:]
            current_velocity = velocity[:-1]
            following_velocity = velocity[1:]
            max_position_error = max(
                max_position_error,
                _commit_oracle_max_error(
                    current_position, following_position, scratch, active_indices),
            )
            max_velocity_error = max(
                max_velocity_error,
                _commit_oracle_max_error(
                    current_velocity, following_velocity, scratch, active_indices),
            )
            checked_transitions += stop - start

        if checked_transitions != transitions:
            raise ValueError(
                f"full temporal coverage failure: {case_id} "
                f"{checked_transitions} != {transitions}")

    passed = (max_position_error <= ORACLE_ERROR_TOLERANCE
              and max_velocity_error <= ORACLE_ERROR_TOLERANCE)
    return {
        "case_id": case_id,
        "family": row["family"],
        "split": row["split"],
        "source_sha256": source_sha256,
        "known_inputs_sha256": row["known_inputs_sha256"],
        "frame_count": frame_count,
        "particle_count": particle_count,
        "transition_count": transitions,
        "checked_transition_count": checked_transitions,
        "full_temporal_scan": True,
        "oracle": {
            "reference_displacement": "following_position - current_position",
            "native_velocity_increment": "following_velocity - current_velocity",
            "position_max_abs_error": max_position_error,
            "native_velocity_max_abs_error": max_velocity_error,
            "error_tolerance": ORACLE_ERROR_TOLERANCE,
            "privileged_reference_only": True,
            "predictor_received_future_state": False,
        },
        "passed": passed,
        "chunk_bound": {
            "frame_chunk_size": effective_chunk,
            "max_chunk_bytes": max_chunk_bytes,
            "estimated_numeric_buffer_bytes": estimated_bound,
            "max_open_hdf5_files": 1,
        },
    }


def verify_f3_full_temporal(
    manifest,
    data_root,
    *,
    case_ids=None,
    frame_chunk_size=DEFAULT_FRAME_CHUNK_SIZE,
    max_chunk_bytes=DEFAULT_MAX_CHUNK_BYTES,
):
    """Run a read-only, full ``n_frames - 1`` F3 temporal verification."""
    manifest_path, root = _manifest_and_root(manifest, data_root)
    frame_chunk_size = _positive_int(
        frame_chunk_size, name="frame_chunk_size", maximum=MAX_FRAME_CHUNK_SIZE)
    max_chunk_bytes = _positive_int(max_chunk_bytes, name="max_chunk_bytes")
    started = time.monotonic()
    manifest_sha256 = sha256_file(manifest_path)

    with CoreDataset(manifest_path, root, max_open_files=1, strict=True) as data:
        if data.manifest.get("schema") != COMPACT_SCHEMA:
            raise ValueError(
                f"F3 full temporal verification requires {COMPACT_SCHEMA} manifest")
        registered = tuple(data.case_ids())
        selected = registered if case_ids is None else tuple(case_ids)
        if not selected:
            raise ValueError("at least one case must be selected")
        if len(set(selected)) != len(selected):
            raise ValueError("case selection contains duplicates")
        unknown = sorted(set(selected) - set(registered))
        if unknown:
            raise ValueError(f"unknown case IDs: {unknown}")

        records = []
        source_hashes = {}
        for case_id in selected:
            # These calls are the existing manifest, known-input contract and
            # source SHA-256 boundary.  No State is materialized here.
            source_hashes.update(data.verify_sources([case_id]))
            data.known_inputs(case_id)
            records.append(_verify_case(
                data, case_id, source_sha256=source_hashes[case_id],
                frame_chunk_size=frame_chunk_size, max_chunk_bytes=max_chunk_bytes))

        total_transitions = sum(item["transition_count"] for item in records)
        bounds = {
            "requested_frame_chunk_size": frame_chunk_size,
            "max_frame_chunk_size": MAX_FRAME_CHUNK_SIZE,
            "max_chunk_bytes": max_chunk_bytes,
            "max_open_hdf5_files": 1,
            "state_materialization": "none; direct float64 HDF5 slabs",
            "future_state_buffer_scope": "privileged oracle target only",
            "per_case": {item["case_id"]: item["chunk_bound"] for item in records},
        }
        return {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "dataset_schema": COMPACT_SCHEMA,
            "dataset_id": data.manifest.get("dataset_id"),
            "manifest_sha256": manifest_sha256,
            "canonical_manifest_sha256": data.manifest_sha256,
            "source_manifest_sha256": data.manifest.get("source_manifest_sha256"),
            "source_hashes": source_hashes,
            "case_count": len(records),
            "transition_count": total_transitions,
            "cases": records,
            "full_temporal_scan": True,
            "qualification_inferred": False,
            "formal_training": False,
            "T1_numerical": False,
            "native_integrity_evaluated": False,
            "gate_decision_eligible": False,
            "qualification_credit": 0,
            "verification_mode": "diagnostic_only",
            "chunk_bounds": bounds,
            "passed": all(item["passed"] for item in records),
            "wall_seconds": time.monotonic() - started,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--case-id", action="append", default=None)
    parser.add_argument("--frame-chunk-size", type=int, default=DEFAULT_FRAME_CHUNK_SIZE)
    parser.add_argument("--max-chunk-bytes", type=int, default=DEFAULT_MAX_CHUNK_BYTES)
    args = parser.parse_args(argv)
    result = verify_f3_full_temporal(
        args.manifest,
        args.data_root,
        case_ids=args.case_id,
        frame_chunk_size=args.frame_chunk_size,
        max_chunk_bytes=args.max_chunk_bytes,
    )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

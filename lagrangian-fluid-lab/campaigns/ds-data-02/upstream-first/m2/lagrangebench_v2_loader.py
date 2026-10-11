#!/usr/bin/env python3
"""Small, dependency-light reader for the pinned LagrangeBench v2 2D LDC data.

The upstream archive is an HDF5 data product, not a DualSPHysics trajectory.
This module intentionally exposes only the fields that are present in the raw
archive.  In particular it never synthesises time, velocity, mass, pressure,
or particle IDs.  The latter distinction is useful when this data is used as
an external comparison source for the M2 bundle.

The implementation is deliberately independent of LagrangeBench's training
stack.  Only NumPy and h5py are needed for inspection and bounded window reads.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import h5py
import numpy as np


RECORD_URL = "https://zenodo.org/records/10491868"
ARCHIVE_NAME = "2D_LDC_2708_10kevery100.zip"
ARCHIVE_URL = f"{RECORD_URL}/files/{ARCHIVE_NAME}?download=1"
ARCHIVE_API_URL = f"https://zenodo.org/api/records/10491868/files/{ARCHIVE_NAME}/content"
ARCHIVE_BYTES = 358_811_551
ARCHIVE_MD5 = "f527ab73f69afc0d176a229f4b812cd5"
DATASET_DIRNAME = "2D_LDC_2708_10kevery100"
SCHEMA = "ds-data-02.lagrangebench-v2-ldc-loader.v1"

# These are the only fields stored in the archive's trajectory groups.  The
# unlisted fields are intentionally reported as unavailable rather than
# inferred from neighbouring positions or metadata.
AVAILABLE_FIELDS = ("position", "particle_type")
UNAVAILABLE_FIELDS = (
    "time",
    "particle_id",
    "velocity",
    "density",
    "mass",
    "pressure",
    "valid",
    "geometry",
    "control",
    "labels",
)
_GROUP_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_REQUIRED_METADATA = {
    "case",
    "solver",
    "dim",
    "dx",
    "dt",
    "write_every",
    "sequence_length_train",
    "sequence_length_test",
    "num_particles_max",
    "bounds",
}


class LagrangeBenchError(ValueError):
    """Raised when the pinned archive does not have the expected raw schema."""


def archive_spec() -> dict[str, Any]:
    """Return the immutable public source specification used by the worker."""

    return {
        "record_url": RECORD_URL,
        "file_name": ARCHIVE_NAME,
        "download_url": ARCHIVE_URL,
        "api_content_url": ARCHIVE_API_URL,
        "bytes": ARCHIVE_BYTES,
        "md5": f"md5:{ARCHIVE_MD5}",
    }


def _safe_relative(value: str, *, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value:
        raise LagrangeBenchError(f"{label} must be a non-empty relative path: {value!r}")
    return path


def _check_no_symlink(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise LagrangeBenchError(f"{label} must not be a symlink: {path}")


def _required_file(root: Path, relative: str) -> Path:
    rel = _safe_relative(relative, label="dataset member")
    candidate = root.joinpath(*rel.parts)
    _check_no_symlink(candidate, label=relative)
    if not candidate.is_file():
        raise LagrangeBenchError(f"missing dataset member: {relative}")
    return candidate


def read_metadata(dataset_root: str | Path) -> dict[str, Any]:
    """Read and validate metadata.json without loading any trajectory arrays."""

    root = Path(dataset_root)
    if not root.is_dir():
        raise LagrangeBenchError(f"dataset root is not a directory: {root}")
    metadata_path = _required_file(root, "metadata.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LagrangeBenchError(f"invalid metadata JSON: {metadata_path}") from exc
    if not isinstance(metadata, dict):
        raise LagrangeBenchError("metadata.json must contain an object")
    missing = sorted(_REQUIRED_METADATA.difference(metadata))
    if missing:
        raise LagrangeBenchError(f"metadata missing required keys: {missing}")
    if metadata.get("case") != "LDC" or metadata.get("solver") != "SPH":
        raise LagrangeBenchError("metadata is not the LagrangeBench LDC/SPH case")
    if metadata.get("dim") != 2:
        raise LagrangeBenchError(f"expected dim=2, got {metadata.get('dim')!r}")
    if metadata.get("num_particles_max") != 2708:
        raise LagrangeBenchError(
            f"expected num_particles_max=2708, got {metadata.get('num_particles_max')!r}"
        )
    if metadata.get("write_every") != 100:
        raise LagrangeBenchError(
            f"expected write_every=100, got {metadata.get('write_every')!r}"
        )
    if metadata.get("sequence_length_train") != 10001:
        raise LagrangeBenchError("unexpected train sequence length")
    if metadata.get("sequence_length_test") != 5001:
        raise LagrangeBenchError("unexpected test sequence length")
    return metadata


def _numeric_kind(dtype: np.dtype[Any]) -> bool:
    return dtype.kind in "fiu"


def _finite_position_scan(dataset: h5py.Dataset, *, chunk_frames: int = 8) -> None:
    """Scan positions with a small frame bound, never materialising a trajectory."""

    if dataset.ndim != 3 or dataset.shape[-1] != 2:
        raise LagrangeBenchError(
            f"position must have shape (time, particles, 2), got {dataset.shape}"
        )
    if not _numeric_kind(dataset.dtype):
        raise LagrangeBenchError(f"position must be numeric, got {dataset.dtype}")
    for start in range(0, dataset.shape[0], chunk_frames):
        stop = min(dataset.shape[0], start + chunk_frames)
        if not np.isfinite(dataset[start:stop]).all():
            raise LagrangeBenchError(f"position contains non-finite values near frame {start}")


def _inspect_split(path: Path, split: str, metadata: dict[str, Any]) -> dict[str, Any]:
    expected_frames = (
        metadata["sequence_length_train"] if split == "train" else metadata["sequence_length_test"]
    )
    trajectory_shapes: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    with h5py.File(path, "r") as handle:
        groups = sorted(handle.keys())
        if not groups:
            raise LagrangeBenchError(f"{split}.h5 contains no trajectory groups")
        for name in groups:
            if not _GROUP_NAME.fullmatch(name):
                raise LagrangeBenchError(f"unsafe trajectory group name: {name!r}")
            group = handle[name]
            if not isinstance(group, h5py.Group):
                raise LagrangeBenchError(f"top-level member is not a group: {split}/{name}")
            if "position" not in group or "particle_type" not in group:
                raise LagrangeBenchError(f"{split}/{name} lacks position or particle_type")
            position = group["position"]
            particle_type = group["particle_type"]
            if position.shape[0] != expected_frames:
                raise LagrangeBenchError(
                    f"{split}/{name} has {position.shape[0]} frames; expected {expected_frames}"
                )
            if position.ndim != 3 or position.shape[-1] != 2:
                raise LagrangeBenchError(
                    f"{split}/{name}/position has unsupported shape {position.shape}"
                )
            if position.shape[1] > metadata["num_particles_max"]:
                raise LagrangeBenchError(f"{split}/{name} exceeds num_particles_max")
            if particle_type.ndim != 1 or particle_type.shape[0] != position.shape[1]:
                raise LagrangeBenchError(
                    f"{split}/{name}/particle_type shape {particle_type.shape} does not match"
                )
            if not _numeric_kind(particle_type.dtype):
                raise LagrangeBenchError(f"particle_type must be numeric: {split}/{name}")
            _finite_position_scan(position)
            if not np.isfinite(particle_type[:]).all():
                raise LagrangeBenchError(f"particle_type contains non-finite values: {split}/{name}")
            trajectory_shapes[name] = {
                "frames": int(position.shape[0]),
                "particles": int(position.shape[1]),
                "position_dtype": str(position.dtype),
                "particle_type_dtype": str(particle_type.dtype),
                "available_fields": list(AVAILABLE_FIELDS),
            }
        total_bytes = path.stat().st_size
    return {
        "path": path.name,
        "bytes": total_bytes,
        "trajectory_count": len(trajectory_shapes),
        "trajectories": trajectory_shapes,
        "raw_fields": {
            "available": list(AVAILABLE_FIELDS),
            "unavailable": list(UNAVAILABLE_FIELDS),
        },
    }


def inspect_dataset(dataset_root: str | Path) -> dict[str, Any]:
    """Boundedly inspect all split metadata and return a JSON-safe report.

    The scanner visits each frame in small slices to check finiteness, but its
    peak array allocation is bounded by ``8 * num_particles * 2`` values.  It
    does not retain trajectory arrays or import any training framework.
    """

    root = Path(dataset_root)
    metadata = read_metadata(root)
    splits: dict[str, Any] = {}
    for split in ("train", "valid", "test"):
        split_path = _required_file(root, f"{split}.h5")
        splits[split] = _inspect_split(split_path, split, metadata)
    return {
        "schema": SCHEMA,
        "dataset_dirname": root.name,
        "metadata": metadata,
        "splits": splits,
        "fields": {"available": list(AVAILABLE_FIELDS), "unavailable": list(UNAVAILABLE_FIELDS)},
        "native_time": {
            "available": False,
            "reason": "the raw archive has no time dataset; dt and write_every are metadata only",
            "frame_interval_s": None,
        },
        "source": archive_spec(),
    }


def read_window(
    dataset_root: str | Path,
    split: str,
    trajectory: str,
    start: int,
    stop: int,
    *,
    max_bytes: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    """Read one bounded raw window and preserve the archive's field semantics."""

    if split not in {"train", "valid", "test"}:
        raise LagrangeBenchError(f"unsupported split: {split!r}")
    if not isinstance(start, int) or not isinstance(stop, int) or start < 0 or stop < start:
        raise LagrangeBenchError("window bounds must satisfy 0 <= start <= stop")
    _safe_relative(trajectory, label="trajectory")
    if not _GROUP_NAME.fullmatch(trajectory):
        raise LagrangeBenchError(f"unsafe trajectory group name: {trajectory!r}")
    root = Path(dataset_root)
    metadata = read_metadata(root)
    path = _required_file(root, f"{split}.h5")
    with h5py.File(path, "r") as handle:
        if trajectory not in handle:
            raise LagrangeBenchError(f"unknown trajectory {split}/{trajectory}")
        group = handle[trajectory]
        position = group["position"]
        particle_type = group["particle_type"]
        if stop > position.shape[0]:
            raise LagrangeBenchError(
                f"window {start}:{stop} exceeds {split}/{trajectory} length {position.shape[0]}"
            )
        estimated = (stop - start) * position.shape[1] * position.shape[2] * position.dtype.itemsize
        estimated += particle_type.shape[0] * particle_type.dtype.itemsize
        if estimated > max_bytes:
            raise LagrangeBenchError(
                f"requested window is {estimated} bytes, above max_bytes={max_bytes}"
            )
        positions = np.asarray(position[start:stop])
        particle_types = np.asarray(particle_type[:])
    return {
        "split": split,
        "trajectory": trajectory,
        "start": start,
        "stop": stop,
        "position": positions,
        "particle_type": particle_types,
        "available_fields": list(AVAILABLE_FIELDS),
        "unavailable_fields": list(UNAVAILABLE_FIELDS),
        "metadata": metadata,
    }


def verify_archive(path: str | Path, *, chunk_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    """Verify the pinned archive size and MD5 without extracting it."""

    archive = Path(path)
    size = archive.stat().st_size
    digest = hashlib.md5(usedforsecurity=False)
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_bytes), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if size != ARCHIVE_BYTES or actual != ARCHIVE_MD5:
        raise LagrangeBenchError(
            f"archive mismatch: bytes={size} md5={actual}; expected {ARCHIVE_BYTES}/{ARCHIVE_MD5}"
        )
    return {"bytes": size, "md5": f"md5:{actual}", "path_name": archive.name}


__all__ = [
    "ARCHIVE_API_URL",
    "ARCHIVE_BYTES",
    "ARCHIVE_MD5",
    "ARCHIVE_NAME",
    "ARCHIVE_URL",
    "DATASET_DIRNAME",
    "LagrangeBenchError",
    "AVAILABLE_FIELDS",
    "UNAVAILABLE_FIELDS",
    "archive_spec",
    "inspect_dataset",
    "read_metadata",
    "read_window",
    "verify_archive",
]

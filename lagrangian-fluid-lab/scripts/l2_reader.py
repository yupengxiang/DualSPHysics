"""Small read-only reader for the L2 campaign manifest.

The reader deliberately does not copy or mutate source HDF5 files.  It gives
the starter a stable way to resolve a case and inspect a frame while keeping
the source path, recipe and identity semantics in the manifest.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Iterator

import h5py


def load_manifest(path: str | Path) -> dict:
    """Load a canonical L2 manifest and validate its minimum shape."""

    manifest_path = Path(path).resolve()
    payload = json.loads(manifest_path.read_text())
    if payload.get("schema") != "l2.f3.canonical_manifest.v1":
        raise ValueError(f"unsupported L2 manifest schema: {payload.get('schema')!r}")
    if not isinstance(payload.get("cases"), list):
        raise ValueError("L2 manifest cases must be a list")
    payload["_manifest_path"] = str(manifest_path)
    return payload


def case_record(manifest: dict, case_id: str) -> dict:
    """Return one case record by immutable physical case ID."""

    for record in manifest["cases"]:
        if record.get("case_id") == case_id:
            return record
    raise KeyError(f"unknown L2 case: {case_id}")


def resolve_case_path(manifest: dict, record: dict) -> Path:
    """Resolve a case path relative to the repository root recorded by A0."""

    root = Path(manifest["repository_root"]).resolve()
    path = (root / record["hdf5"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"case path escapes repository root: {path}") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


@contextmanager
def open_case(manifest: dict, case_id: str) -> Iterator[h5py.File]:
    """Open one source case read-only."""

    record = case_record(manifest, case_id)
    with h5py.File(resolve_case_path(manifest, record), "r") as handle:
        yield handle


def read_frame(manifest: dict, case_id: str, frame: int,
               fields: tuple[str, ...] = ("position", "velocity", "valid")) -> dict:
    """Read a single frame without loading an entire trajectory."""

    with open_case(manifest, case_id) as handle:
        time = float(handle["time"][frame])
        result = {"time": time}
        for field in fields:
            if field not in handle:
                raise KeyError(f"{case_id}: missing HDF5 field {field!r}")
            dataset = handle[field]
            if dataset.ndim == 1:
                result[field] = dataset[:]
            else:
                result[field] = dataset[frame]
        return result


def case_metadata(manifest: dict, case_id: str) -> dict:
    """Return immutable metadata without reading trajectory arrays."""

    record = case_record(manifest, case_id)
    path = resolve_case_path(manifest, record)
    with h5py.File(path, "r") as handle:
        return {
            "case_id": case_id,
            "path": str(path),
            "hdf5_sha256": record.get("sha256"),
            "datasets": {name: list(dataset.shape) for name, dataset in handle.items()
                         if hasattr(dataset, "shape")},
            "attrs": {str(key): str(value) for key, value in handle.attrs.items()},
        }

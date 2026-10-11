"""Small read-only reader for the L2 campaign manifest.

The reader deliberately does not copy or mutate source HDF5 files.  It gives
the starter a stable way to resolve a case and inspect a frame while keeping
the source path, recipe and identity semantics in the manifest.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
from typing import Iterator

import h5py


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _case_binding(record: dict) -> tuple[str, int | None]:
    """Return the trajectory hash/size from either supported manifest shape."""

    nested = record.get("file")
    nested_hash = nested.get("sha256") if isinstance(nested, dict) else None
    top_hash = record.get("sha256")
    expected_hash = nested_hash or top_hash
    if (not isinstance(expected_hash, str)
            or not _SHA256.fullmatch(expected_hash)):
        raise ValueError(
            f"{record.get('case_id', '<unknown>')}: manifest HDF5 SHA-256 is missing or malformed"
        )
    if nested_hash is not None and top_hash is not None and nested_hash.lower() != top_hash.lower():
        raise ValueError(f"{record.get('case_id', '<unknown>')}: manifest HDF5 hashes disagree")

    nested_bytes = nested.get("bytes") if isinstance(nested, dict) else None
    top_bytes = record.get("bytes")
    expected_bytes = nested_bytes if nested_bytes is not None else top_bytes
    if expected_bytes is not None and (
            type(expected_bytes) is not int or expected_bytes <= 0):
        raise ValueError(
            f"{record.get('case_id', '<unknown>')}: manifest HDF5 byte count is invalid"
        )
    if nested_bytes is not None and top_bytes is not None and nested_bytes != top_bytes:
        raise ValueError(f"{record.get('case_id', '<unknown>')}: manifest HDF5 byte counts disagree")
    return expected_hash.lower(), expected_bytes


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: str | Path) -> dict:
    """Load a canonical L2 manifest and validate portable case bindings."""

    manifest_path = Path(path).resolve()
    payload = json.loads(manifest_path.read_text())
    if payload.get("schema") != "l2.f3.canonical_manifest.v1":
        raise ValueError(f"unsupported L2 manifest schema: {payload.get('schema')!r}")
    if not isinstance(payload.get("cases"), list):
        raise ValueError("L2 manifest cases must be a list")
    if not isinstance(payload.get("repository_root"), str) or not payload["repository_root"]:
        raise ValueError("L2 manifest repository_root must be a non-empty string")
    seen_case_ids: set[str] = set()
    for record in payload["cases"]:
        if not isinstance(record, dict):
            raise ValueError("L2 manifest cases must contain objects")
        case_id = record.get("case_id")
        hdf5 = record.get("hdf5")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("L2 manifest case_id must be a non-empty string")
        if case_id in seen_case_ids:
            raise ValueError(f"duplicate L2 case: {case_id}")
        seen_case_ids.add(case_id)
        if not isinstance(hdf5, str) or not hdf5:
            raise ValueError(f"{case_id}: L2 manifest hdf5 must be a non-empty string")
        hdf5_path = Path(hdf5)
        if hdf5_path.is_absolute() or ".." in hdf5_path.parts:
            raise ValueError(f"{case_id}: L2 manifest hdf5 path is not portable")
        _case_binding(record)
    payload["_manifest_path"] = str(manifest_path)
    payload["_verified_case_hashes"] = {}
    return payload


def case_record(manifest: dict, case_id: str) -> dict:
    """Return one case record by immutable physical case ID."""

    for record in manifest["cases"]:
        if record.get("case_id") == case_id:
            return record
    raise KeyError(f"unknown L2 case: {case_id}")


def resolve_case_path(
    manifest: dict,
    record: dict,
    *,
    data_root: str | Path | None = None,
) -> Path:
    """Resolve a case below an explicit deployment root or the manifest root."""

    if data_root is None:
        root = Path(manifest["repository_root"])
        if not root.is_absolute() and manifest.get("_manifest_path"):
            root = Path(manifest["_manifest_path"]).parent / root
    else:
        root = Path(data_root)
    root = root.expanduser().resolve()
    relative = Path(record["hdf5"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{record.get('case_id', '<unknown>')}: case path is not portable")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"case path escapes repository root: {path}") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def verify_case_integrity(
    manifest: dict,
    case_id: str,
    *,
    data_root: str | Path | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    """Verify one manifest-bound trajectory without changing it."""

    record = case_record(manifest, case_id)
    path = resolve_case_path(manifest, record, data_root=data_root)
    expected_hash, expected_bytes = _case_binding(record)
    stat = path.stat()
    if expected_bytes is not None and stat.st_size != expected_bytes:
        raise ValueError(
            f"{case_id}: HDF5 integrity failure: byte count {stat.st_size} != {expected_bytes}"
        )

    cache = manifest.setdefault("_verified_case_hashes", {})
    cache_key = str(path)
    signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    cached = cache.get(cache_key)
    if (not force and isinstance(cached, dict)
            and cached.get("signature") == signature
            and cached.get("sha256") == expected_hash):
        observed_hash = cached["sha256"]
    else:
        observed_hash = _sha256_file(path)
        if observed_hash != expected_hash:
            raise ValueError(f"{case_id}: HDF5 integrity failure: SHA-256 mismatch")
        cache[cache_key] = {"signature": signature, "sha256": observed_hash}
    return {"path": str(path), "bytes": stat.st_size, "sha256": observed_hash}


@contextmanager
def open_case(
    manifest: dict,
    case_id: str,
    *,
    data_root: str | Path | None = None,
) -> Iterator[h5py.File]:
    """Open one source case read-only."""

    record = case_record(manifest, case_id)
    verify_case_integrity(manifest, case_id, data_root=data_root)
    with h5py.File(resolve_case_path(manifest, record, data_root=data_root), "r") as handle:
        yield handle


def read_frame(
    manifest: dict,
    case_id: str,
    frame: int,
    fields: tuple[str, ...] = ("position", "velocity", "valid"),
    *,
    data_root: str | Path | None = None,
) -> dict:
    """Read a single frame without loading an entire trajectory."""

    with open_case(manifest, case_id, data_root=data_root) as handle:
        if type(frame) is not int or frame < 0 or frame >= len(handle["time"]):
            raise IndexError(f"{case_id}: frame outside trajectory")
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


def case_metadata(
    manifest: dict,
    case_id: str,
    *,
    data_root: str | Path | None = None,
) -> dict:
    """Return immutable metadata without reading trajectory arrays."""

    integrity = verify_case_integrity(manifest, case_id, data_root=data_root)
    path = Path(integrity["path"])
    with h5py.File(path, "r") as handle:
        return {
            "case_id": case_id,
            "path": str(path),
            "hdf5_bytes": integrity["bytes"],
            "hdf5_sha256": integrity["sha256"],
            "datasets": {name: list(dataset.shape) for name, dataset in handle.items()
                         if hasattr(dataset, "shape")},
            "attrs": {str(key): str(value) for key, value in handle.attrs.items()},
        }

#!/usr/bin/env python3
"""Bounded download, safe extraction, and raw-schema inspection worker.

The parent runner should execute this worker on the NAS.  It performs no
solver work and has no dependency on JAX, PyTorch, or the LagrangeBench
training package.  Downloading is opt-in, and every operation is bounded by
the byte and wall-clock limits supplied on the command line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

try:
    from . import lagrangebench_v2_loader as loader
except ImportError:  # direct execution by the NAS runner
    _M2_ROOT = Path(__file__).resolve().parent
    if str(_M2_ROOT) not in sys.path:
        sys.path.insert(0, str(_M2_ROOT))
    import lagrangebench_v2_loader as loader


SCHEMA = "ds-data-02.lagrangebench-v2-download-inspect-worker.v1"
DEFAULT_MAX_ARCHIVE_BYTES = 4 * 1024**3
DEFAULT_MAX_EXTRACT_BYTES = 10 * 1024**3
DEFAULT_MAX_WALL_SECONDS = 30 * 60
_COPY_CHUNK = 8 * 1024 * 1024


class WorkerError(RuntimeError):
    """Raised for a bounded-worker failure."""


class Deadline:
    def __init__(self, seconds: float) -> None:
        if seconds <= 0:
            raise WorkerError("max wall seconds must be positive")
        self.end = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() >= self.end:
            raise WorkerError("bounded worker wall-clock limit exceeded")


def _md5(path: Path, deadline: Deadline) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_COPY_CHUNK), b""):
            deadline.check()
            digest.update(chunk)
    return digest.hexdigest()


def _verify_existing_archive(path: Path, deadline: Deadline) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise WorkerError(f"archive is not a regular file: {path}")
    size = path.stat().st_size
    digest = _md5(path, deadline)
    expected = loader.archive_spec()
    expected_md5 = expected["md5"].split(":", 1)[1]
    if size != expected["bytes"] or digest != expected_md5:
        raise WorkerError(
            f"archive does not match pinned source: bytes={size}, md5={digest}; "
            f"expected {expected['bytes']}, {expected_md5}"
        )
    return {"bytes": size, "md5": f"md5:{digest}", "file_name": path.name}


def download_archive(
    destination: Path,
    *,
    max_bytes: int,
    deadline: Deadline,
    url: str = loader.ARCHIVE_URL,
) -> dict[str, Any]:
    """Download to a sibling partial file, verify, then atomically publish."""

    expected = loader.archive_spec()
    if max_bytes < expected["bytes"]:
        raise WorkerError("max archive bytes is below the pinned archive size")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return {"downloaded": False, "reused": True, **_verify_existing_archive(destination, deadline)}
    partial = destination.with_name(destination.name + ".partial")
    if partial.exists() or partial.is_symlink():
        raise WorkerError(f"stale partial archive exists; inspect or remove it: {partial}")

    digest = hashlib.md5(usedforsecurity=False)
    total = 0
    request = urllib.request.Request(url, headers={"User-Agent": "ds-data-02-m2-worker/1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, partial.open("xb") as target:
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    advertised = int(content_length)
                except ValueError as exc:
                    raise WorkerError(f"invalid Content-Length: {content_length!r}") from exc
                if advertised > max_bytes:
                    raise WorkerError("server Content-Length exceeds max archive bytes")
            while True:
                deadline.check()
                chunk = response.read(_COPY_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise WorkerError("download exceeds max archive bytes")
                target.write(chunk)
                digest.update(chunk)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        # Keep an incomplete file for post-mortem/restart diagnostics, but do
        # not make it look like a usable archive.
        raise
    actual = digest.hexdigest()
    expected_md5 = expected["md5"].split(":", 1)[1]
    if total != expected["bytes"] or actual != expected_md5:
        raise WorkerError(
            f"download checksum mismatch: bytes={total}, md5={actual}; "
            f"expected {expected['bytes']}, {expected_md5}"
        )
    os.replace(partial, destination)
    return {"downloaded": True, "reused": False, "bytes": total, "md5": f"md5:{actual}", "file_name": destination.name}


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not name or ".." in path.parts:
        raise WorkerError(f"unsafe zip member path: {name!r}")
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _copy_member(source: BinaryIO, target: BinaryIO, expected: int, deadline: Deadline) -> None:
    written = 0
    while True:
        deadline.check()
        chunk = source.read(_COPY_CHUNK)
        if not chunk:
            break
        written += len(chunk)
        if written > expected:
            raise WorkerError("zip member expanded beyond its declared size")
        target.write(chunk)
    if written != expected:
        raise WorkerError(f"zip member size mismatch: wrote {written}, expected {expected}")


def extract_archive(
    archive: Path,
    dataset_root: Path,
    *,
    max_bytes: int,
    deadline: Deadline,
) -> dict[str, Any]:
    """Extract with path traversal, symlink, and total-size checks."""

    if dataset_root.exists() or dataset_root.is_symlink():
        raise WorkerError(f"dataset root already exists; use --inspect for it: {dataset_root}")
    # Extract beside the requested dataset directory, then publish the
    # archive's single top-level directory at exactly ``dataset_root``.  This
    # avoids leaving an accidental ``dataset/dataset/...`` nesting behind.
    temporary = dataset_root.with_name(dataset_root.name + f".partial-{os.getpid()}")
    dataset_root.parent.mkdir(parents=True, exist_ok=True)
    if temporary.exists() or temporary.is_symlink():
        raise WorkerError(f"stale partial extraction exists: {temporary}")
    temporary.mkdir(parents=True)
    total = 0
    members = 0
    try:
        with zipfile.ZipFile(archive, "r") as bundle:
            seen: set[str] = set()
            for info in bundle.infolist():
                deadline.check()
                relative = _safe_member_path(info.filename)
                if info.filename in seen:
                    raise WorkerError(f"duplicate zip member: {info.filename}")
                seen.add(info.filename)
                if _is_symlink(info):
                    raise WorkerError(f"symlink zip member is not allowed: {info.filename}")
                total += info.file_size
                if total > max_bytes:
                    raise WorkerError("extracted size exceeds max extract bytes")
                target = temporary.joinpath(*relative.parts)
                target_parent = target.parent
                target_parent.mkdir(parents=True, exist_ok=True)
                if info.is_dir() or info.filename.endswith("/"):
                    target.mkdir(exist_ok=True)
                    continue
                if target.exists() or target.is_symlink():
                    raise WorkerError(f"zip member collides with existing path: {info.filename}")
                with bundle.open(info, "r") as source, target.open("xb") as output:
                    _copy_member(source, output, info.file_size, deadline)
                members += 1
        # The archive contains one stable top-level directory.  Require it so
        # a future unrelated archive cannot be accidentally inspected.
        expected_root = temporary / loader.DATASET_DIRNAME
        if not expected_root.is_dir():
            raise WorkerError(f"archive lacks expected directory {loader.DATASET_DIRNAME}")
        os.replace(expected_root, dataset_root)
        temporary.rmdir()
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {"members": members, "uncompressed_bytes": total, "dataset_dirname": dataset_root.name}


def _relative_name(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.name


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise WorkerError(f"refusing to overwrite report: {path}")
    partial = path.with_name(path.name + ".partial")
    if partial.is_symlink():
        raise WorkerError(f"partial report is a symlink: {partial}")
    with partial.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    deadline = Deadline(args.max_wall_seconds)
    archive_path = Path(args.archive) if args.archive else None
    dataset_root = Path(args.dataset_root)
    if args.download and archive_path is None:
        raise WorkerError("--download requires --archive")
    if args.download:
        archive_result = download_archive(
            archive_path,
            max_bytes=args.max_archive_bytes,
            deadline=deadline,
        )
    elif archive_path is not None and archive_path.exists():
        archive_result = _verify_existing_archive(archive_path, deadline)
        archive_result["downloaded"] = False
        archive_result["reused"] = True
    else:
        archive_result = {"downloaded": False, "reused": False, "verification": "not_requested"}

    extraction_result: dict[str, Any] | None = None
    if not dataset_root.exists():
        if archive_path is None:
            raise WorkerError("dataset root is missing and no archive was supplied")
        extraction_result = extract_archive(
            archive_path,
            dataset_root,
            max_bytes=args.max_extract_bytes,
            deadline=deadline,
        )
    elif not dataset_root.is_dir() or dataset_root.is_symlink():
        raise WorkerError(f"dataset root is not a regular directory: {dataset_root}")

    inspection = loader.inspect_dataset(dataset_root)
    deadline.check()
    base = Path(args.report).parent
    report = {
        "schema": SCHEMA,
        "status": "completed",
        "source": loader.archive_spec(),
        "limits": {
            "max_archive_bytes": args.max_archive_bytes,
            "max_extract_bytes": args.max_extract_bytes,
            "max_wall_seconds": args.max_wall_seconds,
        },
        "archive": archive_result,
        "extraction": extraction_result,
        "dataset_root": _relative_name(dataset_root, base),
        "inspection": inspection,
        "dependencies": {
            "runtime": "Python 3.10+",
            "required": ["numpy", "h5py"],
            "intentionally_not_required": ["jax", "torch", "lagrangebench"],
        },
        "heavy_work": {"solver": False, "training": False, "conversion": False},
    }
    write_report(Path(args.report), report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="download the pinned archive")
    parser.add_argument("--archive", help="archive destination or existing archive path")
    parser.add_argument("--dataset-root", required=True, help="extracted dataset directory")
    parser.add_argument("--report", required=True, help="new JSON inspection report path")
    parser.add_argument("--max-archive-bytes", type=int, default=DEFAULT_MAX_ARCHIVE_BYTES)
    parser.add_argument("--max-extract-bytes", type=int, default=DEFAULT_MAX_EXTRACT_BYTES)
    parser.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run(args)
    except (OSError, ValueError, WorkerError, loader.LagrangeBenchError) as exc:
        print(f"m2-worker: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

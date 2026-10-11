#!/usr/bin/env python3
"""Copy a portable bundle into a fresh attempt and validate it in isolation.

This worker is intentionally small and standard-library-only.  It performs a
bounded regular-file copy, refuses symlinks and special files, atomically
publishes the relocated directory, and then delegates the namespace proof to
``portable_isolated_validate.py``.  The child validator reads its evaluator
and L2 reader from the copied bundle's ``runtime`` directory.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


SCHEMA = "ds-data-02.m2.portable-relocation-worker.v1"
CHUNK_BYTES = 8 * 1024 * 1024


class RelocationError(RuntimeError):
    """Raised when a bounded relocation or isolated validation fails."""


def _deadline(max_wall_seconds: float) -> float:
    if not isinstance(max_wall_seconds, (int, float)) or max_wall_seconds <= 0:
        raise RelocationError("max-wall-seconds must be positive")
    return time.monotonic() + float(max_wall_seconds)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise RelocationError("relocation wall limit exceeded")


def _regular_files(root: Path, *, deadline: float) -> list[tuple[Path, int]]:
    """Return sorted regular files while rejecting links/special files."""

    if not root.is_dir() or root.is_symlink():
        raise RelocationError(f"source bundle is not a regular directory: {root}")
    records: list[tuple[Path, int]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        _check_deadline(deadline)
        current_path = Path(current)
        for name in sorted(directories):
            directory = current_path / name
            if directory.is_symlink():
                raise RelocationError(f"bundle contains a symlinked directory: {directory}")
            if not directory.is_dir():
                raise RelocationError(f"bundle contains a non-directory entry: {directory}")
        for name in sorted(files):
            file_path = current_path / name
            if file_path.is_symlink() or not file_path.is_file():
                raise RelocationError(f"bundle contains a non-regular file: {file_path}")
            records.append((file_path, file_path.stat().st_size))
    records.sort(key=lambda item: item[0].relative_to(root).as_posix())
    return records


def _copy_file(source: Path, destination: Path, *, deadline: float) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied = 0
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        while True:
            _check_deadline(deadline)
            block = input_stream.read(CHUNK_BYTES)
            if not block:
                break
            output_stream.write(block)
            copied += len(block)
    shutil.copystat(source, destination, follow_symlinks=False)
    return copied


def relocate_bundle(
    source_bundle: Path,
    destination_bundle: Path,
    *,
    max_bytes: int,
    max_wall_seconds: float,
) -> dict[str, Any]:
    """Copy ``source_bundle`` to a previously absent destination atomically."""

    if type(max_bytes) is not int or max_bytes <= 0:
        raise RelocationError("max-bytes must be a positive integer")
    source = source_bundle.resolve()
    destination = destination_bundle.absolute()
    if source == destination or destination.is_relative_to(source):
        raise RelocationError("destination must be outside the source bundle")
    if destination.exists() or destination.is_symlink():
        raise RelocationError(f"fresh destination already exists: {destination}")
    deadline = _deadline(max_wall_seconds)
    records = _regular_files(source, deadline=deadline)
    total_bytes = sum(size for _, size in records)
    if total_bytes > max_bytes:
        raise RelocationError(
            f"bundle size {total_bytes} exceeds relocation limit {max_bytes}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".partial-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise RelocationError(f"stale relocation partial exists: {temporary}")
    temporary.mkdir()
    copied_bytes = 0
    try:
        for source_file, expected_bytes in records:
            _check_deadline(deadline)
            relative = source_file.relative_to(source)
            copied = _copy_file(source_file, temporary / relative, deadline=deadline)
            if copied != expected_bytes:
                raise RelocationError(f"source changed during copy: {source_file}")
            copied_bytes += copied
        _check_deadline(deadline)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "source_bundle": str(source),
        "destination_bundle": str(destination),
        "file_count": len(records),
        "bytes": copied_bytes,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise RelocationError(f"refusing to overwrite worker receipt: {path}")
    partial = path.with_name(path.name + f".partial-{os.getpid()}")
    if partial.exists() or partial.is_symlink():
        raise RelocationError(f"stale worker receipt exists: {partial}")
    try:
        with partial.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def run(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_bundle)
    destination = Path(args.relocated_bundle)
    wrapper = Path(args.isolation_wrapper).resolve()
    python_path = Path(args.python).absolute()
    if not wrapper.is_file() or wrapper.is_symlink():
        raise RelocationError(f"isolation wrapper is not a regular file: {wrapper}")
    if not python_path.is_file():
        raise RelocationError(f"Python runtime is not a regular file: {python_path}")
    started = time.monotonic()
    copied = relocate_bundle(
        source,
        destination,
        max_bytes=args.max_bytes,
        max_wall_seconds=args.max_wall_seconds,
    )
    remaining = float(args.max_wall_seconds) - (time.monotonic() - started)
    if remaining <= 0:
        raise RelocationError("relocation exhausted the worker wall limit")
    command = [
        str(python_path),
        str(wrapper),
        "--bundle-root",
        str(destination),
        "--python",
        str(python_path),
        "--output",
        str(Path(args.validation_output)),
        "--max-wall-seconds",
        str(remaining),
    ]
    for denied in args.denied_path:
        command.extend(("--denied-path", str(denied)))
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=remaining,
    )
    if completed.returncode != 0:
        raise RelocationError(
            f"isolated validation failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()[-2000:]}"
        )
    validation_path = Path(args.validation_output)
    if not validation_path.is_file():
        raise RelocationError(f"isolated validation did not write {validation_path}")
    try:
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RelocationError("isolated validation report is not JSON") from exc
    if validation.get("status") != "completed":
        raise RelocationError("isolated validation report is not completed")
    receipt = {
        "schema": SCHEMA,
        "status": "completed",
        "elapsed_seconds": time.monotonic() - started,
        "copy": copied,
        "validation_output": str(validation_path),
        "validation": {
            "schema": validation.get("schema"),
            "portable": validation.get("validation", {}).get("portable")
            if isinstance(validation.get("validation"), dict)
            else None,
            "denied_probes_passed": validation.get("namespace", {}).get("denied_probes_passed"),
        },
    }
    if args.receipt is not None:
        _write_json(Path(args.receipt), receipt)
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", required=True, type=Path)
    parser.add_argument("--relocated-bundle", required=True, type=Path)
    parser.add_argument("--isolation-wrapper", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--validation-output", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--max-bytes", type=int, default=2 * 1024**3)
    parser.add_argument("--max-wall-seconds", type=float, default=1800)
    parser.add_argument("--denied-path", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(run(args), indent=2, sort_keys=True))
    except (OSError, subprocess.SubprocessError, RelocationError, ValueError) as exc:
        print(f"portable-relocate: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

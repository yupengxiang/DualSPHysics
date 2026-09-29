#!/usr/bin/env python3
"""Small no-follow, bounded readers for independent-reproduction evidence.

The A8 evidence boundary is diagnostic-only, but it still must not turn a
path name into an identity by opening a different object after validation.
This module keeps the path walk and the bytes read on descriptors opened with
``O_NOFOLLOW``.  Every bounded read is checked with ``fstat`` before and
after consumption; repeated identity checks can cheaply re-open and compare
the descriptor fingerprint without re-reading large artifacts.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any


class SecureReadError(ValueError):
    """A fail-closed secure-file or bounded-JSON error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def absolute_path(path: str | os.PathLike[str]) -> Path:
    """Return an absolute lexical path without resolving symlinks."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if ".." in candidate.parts:
        raise SecureReadError("NON_PORTABLE_PATH", f"parent path component is forbidden: {path}")
    return Path(os.path.abspath(candidate))


def _fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _open_regular(path: str | os.PathLike[str], *, label: str) -> tuple[int, Path, os.stat_result]:
    """Open a regular file through a descriptor-relative no-follow walk."""
    candidate = absolute_path(path)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None or not hasattr(os, "open"):
        raise SecureReadError(
            "SAFE_OPEN_UNAVAILABLE",
            f"{label} cannot enforce descriptor-relative no-follow open",
        )
    parts = candidate.parts
    if not candidate.is_absolute() or len(parts) < 2:
        raise SecureReadError("FILE_PATH_INVALID", f"{label} is not a regular-file path")

    cloexec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | directory | nofollow | cloexec
    file_flags = os.O_RDONLY | nofollow | cloexec
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(os.sep, directory_flags)
        for component in parts[1:-1]:
            if component in ("", ".", ".."):
                raise SecureReadError("FILE_PATH_INVALID", f"{label} has an invalid component")
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        final_component = parts[-1]
        if final_component in ("", ".", ".."):
            raise SecureReadError("FILE_PATH_INVALID", f"{label} has an invalid final component")
        file_fd = os.open(final_component, file_flags, dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise SecureReadError("FILE_NOT_REGULAR", f"{label} is not a regular file")
        return file_fd, candidate, info
    except SecureReadError:
        if file_fd is not None:
            os.close(file_fd)
        raise
    except OSError as error:
        if file_fd is not None:
            os.close(file_fd)
        raise SecureReadError("FILE_OPEN_FAILED", f"{label} cannot be opened: {error}") from error
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _read_fd(fd: int, *, label: str, max_bytes: int) -> tuple[bytes, os.stat_result]:
    if max_bytes < 1:
        raise SecureReadError("BYTE_LIMIT_INVALID", f"{label} has an invalid byte limit")
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise SecureReadError("FILE_NOT_REGULAR", f"{label} is not a regular file")
    if before.st_size > max_bytes:
        raise SecureReadError("INPUT_TOO_LARGE", f"{label} exceeds {max_bytes} bytes")
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    try:
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
    except OSError as error:
        raise SecureReadError("FILE_READ_FAILED", f"{label} cannot be read: {error}") from error
    raw = b"".join(chunks)
    if len(raw) > max_bytes or len(raw) != before.st_size or _fingerprint(before) != _fingerprint(after):
        raise SecureReadError("FILE_CHANGED_DURING_READ", f"{label} changed during bounded read")
    return raw, after


def read_bounded_bytes(
    path: str | os.PathLike[str], *, label: str, max_bytes: int
) -> tuple[bytes, Path, dict[str, Any]]:
    """Read bounded bytes and return their descriptor-bound identity."""
    file_fd, candidate, _ = _open_regular(path, label=label)
    try:
        raw, after = _read_fd(file_fd, label=label, max_bytes=max_bytes)
    finally:
        os.close(file_fd)
    return raw, candidate, {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "_fingerprint": _fingerprint(after),
    }


def file_identity(path: str | os.PathLike[str], *, label: str) -> dict[str, Any]:
    """Hash a regular file on one no-follow descriptor."""
    file_fd, candidate, before = _open_regular(path, label=label)
    digest = hashlib.sha256()
    count = 0
    try:
        while True:
            try:
                block = os.read(file_fd, 8 * 1024 * 1024)
            except OSError as error:
                raise SecureReadError("FILE_READ_FAILED", f"{label} cannot be read: {error}") from error
            if not block:
                break
            digest.update(block)
            count += len(block)
        after = os.fstat(file_fd)
    finally:
        os.close(file_fd)
    if count != before.st_size or _fingerprint(before) != _fingerprint(after):
        raise SecureReadError("FILE_CHANGED_DURING_READ", f"{label} changed during hashing")
    return {
        "path": candidate,
        "bytes": count,
        "sha256": digest.hexdigest(),
        "_fingerprint": _fingerprint(after),
    }


def probe_identity(path: str | os.PathLike[str], *, label: str) -> dict[str, Any]:
    """Check current descriptor identity without reading file contents."""
    file_fd, candidate, info = _open_regular(path, label=label)
    try:
        after = os.fstat(file_fd)
    finally:
        os.close(file_fd)
    if _fingerprint(info) != _fingerprint(after):
        raise SecureReadError("FILE_CHANGED_DURING_READ", f"{label} changed during identity probe")
    return {
        "path": candidate,
        "bytes": int(after.st_size),
        "_fingerprint": _fingerprint(after),
    }


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {token}")


def read_bounded_json_object(
    path: str | os.PathLike[str], *, label: str, max_bytes: int
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    """Read one strict, bounded JSON object on a descriptor-bound snapshot."""
    raw, candidate, identity = read_bounded_bytes(path, label=label, max_bytes=max_bytes)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            strict=True,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise SecureReadError("INVALID_JSON", f"{label} is not strict JSON: {error}") from error
    if not isinstance(value, dict):
        raise SecureReadError("JSON_OBJECT_REQUIRED", f"{label} top level must be an object")
    return value, candidate, identity

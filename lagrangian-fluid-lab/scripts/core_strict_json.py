"""Bounded strict JSON input helpers for Core manifest readers.

These helpers establish serialization and file-type boundaries only. They do
not authenticate a producer, root, runtime, or formal qualification claim.
"""
from __future__ import annotations

import errno
import hashlib
import json
import math
import os
from pathlib import Path
import stat


MAX_JSON_INPUT_BYTES = 67_108_864


def absolute_path_without_following_leaf(path: str | Path) -> Path:
    """Make a path absolute while preserving its final directory entry."""
    absolute = Path(os.path.abspath(Path(path).expanduser()))
    return absolute.parent.resolve() / absolute.name


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_duplicate_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _parse_finite_json_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("JSON number is outside the finite float domain")
    return value


def _reject_nonfinite_json_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {token}")


def _parse_bounded_json_int(token: str) -> int:
    digits = token[1:] if token.startswith("-") else token
    if len(digits) > 128:
        raise ValueError("JSON integer exceeds the 128-digit limit")
    return int(token)


def read_bounded_raw_json(path: str | Path, *, max_bytes: int = MAX_JSON_INPUT_BYTES,
                          label: str = "JSON input") -> bytes:
    """Read one stable regular file without blocking on special files."""
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("JSON byte limit must be a positive exact integer")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblocking = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or nonblocking is None:
        raise ValueError(f"{label}: platform lacks safe nonblocking no-follow open")
    flags = os.O_RDONLY | nonblocking | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError(f"{label} symlink is forbidden") from error
        raise
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{label} is not a regular file")
        if before.st_size > max_bytes:
            raise ValueError(f"{label} exceeds the byte limit")
        raw = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    before_identity = (
        before.st_dev, before.st_ino, before.st_size,
        before.st_mtime_ns, before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev, after.st_ino, after.st_size,
        after.st_mtime_ns, after.st_ctime_ns,
    )
    if len(raw) > max_bytes:
        raise ValueError(f"{label} exceeds the byte limit")
    if len(raw) != before.st_size or before_identity != after_identity:
        raise ValueError(f"{label} changed during bounded read")
    return raw


def strict_json_object(raw: bytes, *, label: str = "JSON input",
                       max_bytes: int = MAX_JSON_INPUT_BYTES) -> dict[str, object]:
    """Parse a bounded raw JSON object with unambiguous finite values."""
    if type(raw) is not bytes:
        raise ValueError(f"{label} must be exact bytes")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("JSON byte limit must be a positive exact integer")
    if len(raw) > max_bytes:
        raise ValueError(f"{label} exceeds the byte limit")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} is not strict UTF-8") from error
    try:
        value = json.loads(
            text,
            strict=True,
            object_pairs_hook=_reject_duplicate_json_pairs,
            parse_constant=_reject_nonfinite_json_constant,
            parse_float=_parse_finite_json_float,
            parse_int=_parse_bounded_json_int,
        )
    except (json.JSONDecodeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError(f"{label} is not valid strict JSON: {error}") from error
    if type(value) is not dict:
        raise ValueError(f"{label} top level must be a JSON object")
    return value

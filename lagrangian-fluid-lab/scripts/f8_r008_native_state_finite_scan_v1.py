"""Bounded, raw-dtype finite statistics for the F8 R008 required BI4 arrays.

This module consumes an already-held raw BI4 file descriptor and a structural
scan from ``f8_r008_safe_bi4_decoder_v1``. It does not open paths, trust caller
success booleans, adjudicate native integrity, or grant T1/qualification credit.
The caller remains responsible for binding the scan to the full B/C/D chain.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from typing import Any

import numpy as np

from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008_native_state_finite_scan.v1"
STREAM_CHUNK_BYTES = 1024 * 1024
HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class NativeStateFiniteScanError(ValueError):
    """The held BI4 descriptor or a required state array is invalid or changed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeStateFiniteScanError(message)


def _read_exact(fd: int, size: int, offset: int) -> bytes:
    pieces: list[bytes] = []
    remaining = size
    position = offset
    while remaining:
        piece = os.pread(fd, remaining, position)
        if not piece:
            raise NativeStateFiniteScanError("raw BI4 array became short during finite scan")
        pieces.append(piece)
        position += len(piece)
        remaining -= len(piece)
    return b"".join(pieces)


def _hash_frame(fd: int, byte_count: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < byte_count:
        block = os.pread(fd, min(decoder.IO_CHUNK_BYTES, byte_count - offset), offset)
        if not block:
            raise NativeStateFiniteScanError("raw BI4 frame became short while hashing")
        digest.update(block)
        offset += len(block)
    if os.pread(fd, 1, byte_count):
        raise NativeStateFiniteScanError("raw BI4 frame grew while hashing")
    return digest.hexdigest()


def _stat_identity(fd: int) -> tuple[int, int, int, int, int, int]:
    st = os.fstat(fd)
    _require(stat.S_ISREG(st.st_mode), "raw BI4 input must be a regular file")
    _require(st.st_nlink == 1, "raw BI4 input must have exactly one hard link")
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)


def _selected_arrays(scan: decoder.ScanResult, case_np: int) -> list[tuple[Any, str, np.dtype, int, int]]:
    _require(isinstance(case_np, int) and not isinstance(case_np, bool)
             and 0 < case_np <= decoder.MAX_ARRAY_COUNT,
             "CaseNp is outside the reviewed BI4 count bound")
    by_name: dict[str, list[decoder.ArrayRecord]] = {}
    for record in scan.arrays:
        if record.name in {"Pos", "Posd", "Vel", "Rhop"}:
            by_name.setdefault(record.name, []).append(record)
    for name in ("Vel", "Rhop"):
        _require(len(by_name.get(name, ())) == 1, f"raw BI4 must contain exactly one {name} array")
    _require((len(by_name.get("Pos", ())), len(by_name.get("Posd", ()))) in {(1, 0), (0, 1)},
             "raw BI4 must contain exactly one Pos or Posd array")

    position = by_name["Pos"][0] if by_name.get("Pos") else by_name["Posd"][0]
    records = [position, by_name["Vel"][0], by_name["Rhop"][0]]
    contracts = {
        "Pos": (22, np.dtype("<f4"), 3),
        "Posd": (23, np.dtype("<f8"), 3),
        "Vel": (22, np.dtype("<f4"), 3),
        "Rhop": (11, np.dtype("<f4"), 1),
    }
    selected: list[tuple[Any, str, np.dtype, int, int]] = []
    for record in records:
        type_code, dtype, components = contracts[record.name]
        _require(record.type_code == type_code,
                 f"raw BI4 {record.name} has an unsupported native type code")
        _require(record.count == case_np,
                 f"raw BI4 {record.name} count differs from B CaseNp")
        expected_bytes = case_np * components * dtype.itemsize
        _require(record.byte_count == expected_bytes
                 and 0 <= record.offset <= scan.input_bytes - expected_bytes,
                 f"raw BI4 {record.name} descriptor range or byte count is invalid")
        _require(expected_bytes <= decoder.MAX_ARRAY_BYTES,
                 f"raw BI4 {record.name} exceeds the reviewed array byte cap")
        selected.append((record, dtype.str, dtype, components, expected_bytes))
    return selected


def _summarize_array(
    fd: int,
    record: decoder.ArrayRecord,
    dtype_text: str,
    dtype: np.dtype,
    components: int,
    expected_bytes: int,
) -> dict[str, object]:
    itemsize = dtype.itemsize
    chunk_limit = max(itemsize, STREAM_CHUNK_BYTES - STREAM_CHUNK_BYTES % itemsize)
    digest = hashlib.sha256()
    finite_count = nan_count = positive_infinity_count = negative_infinity_count = 0
    minimum_value: np.floating[Any] | None = None
    maximum_value: np.floating[Any] | None = None
    minimum_bits: str | None = None
    maximum_bits: str | None = None
    minimum_ordinal: int | None = None
    maximum_ordinal: int | None = None
    scalar_ordinal = 0
    remaining = expected_bytes
    file_offset = record.offset

    while remaining:
        request_size = min(chunk_limit, remaining)
        request_size -= request_size % itemsize
        if request_size == 0:
            request_size = itemsize
        block = _read_exact(fd, request_size, file_offset)
        _require(len(block) % itemsize == 0, "finite-scan chunk is not scalar aligned")
        digest.update(block)
        values = np.frombuffer(block, dtype=dtype)
        finite = np.isfinite(values)
        finite_count += int(np.count_nonzero(finite))
        nan_count += int(np.count_nonzero(np.isnan(values)))
        positive_infinity_count += int(np.count_nonzero(np.isposinf(values)))
        negative_infinity_count += int(np.count_nonzero(np.isneginf(values)))

        finite_ordinals = np.flatnonzero(finite)
        if finite_ordinals.size:
            finite_values = values[finite]
            block_minimum = finite_values.min()
            local_minimum = int(np.flatnonzero(finite & (values == block_minimum))[0])
            candidate_ordinal = scalar_ordinal + local_minimum
            if minimum_value is None or block_minimum < minimum_value:
                minimum_value = block_minimum
                minimum_bits = block[local_minimum * itemsize:(local_minimum + 1) * itemsize].hex()
                minimum_ordinal = candidate_ordinal

            block_maximum = finite_values.max()
            local_maximum = int(np.flatnonzero(finite & (values == block_maximum))[0])
            candidate_ordinal = scalar_ordinal + local_maximum
            if maximum_value is None or block_maximum > maximum_value:
                maximum_value = block_maximum
                maximum_bits = block[local_maximum * itemsize:(local_maximum + 1) * itemsize].hex()
                maximum_ordinal = candidate_ordinal

        scalar_ordinal += int(values.size)
        file_offset += request_size
        remaining -= request_size

    scalar_count = record.count * components
    _require(scalar_ordinal == scalar_count
             and finite_count + nan_count + positive_infinity_count + negative_infinity_count == scalar_count,
             f"raw BI4 {record.name} finite-value counts do not cover its scalar extent")
    if finite_count == 0:
        _require(minimum_bits is None and maximum_bits is None
                 and minimum_ordinal is None and maximum_ordinal is None,
                 "empty finite subset has extrema")
    else:
        _require(minimum_bits is not None and maximum_bits is not None
                 and minimum_ordinal is not None and maximum_ordinal is not None,
                 "nonempty finite subset lacks source extrema")

    return {
        "array_name": record.name,
        "type_code": record.type_code,
        "dtype": dtype_text,
        "shape": [record.count, 3] if components == 3 else [record.count],
        "particle_count": record.count,
        "scalar_component_count": scalar_count,
        "raw_array_sha256": digest.hexdigest(),
        "finite_count": finite_count,
        "nan_count": nan_count,
        "positive_infinity_count": positive_infinity_count,
        "negative_infinity_count": negative_infinity_count,
        "minimum_finite_source_bits_le_hex": minimum_bits,
        "minimum_finite_component_ordinal": minimum_ordinal,
        "maximum_finite_source_bits_le_hex": maximum_bits,
        "maximum_finite_component_ordinal": maximum_ordinal,
        "required_state_values_finite": finite_count == scalar_count,
    }


def summarize_native_state_fd(
    raw_fd: int,
    expected_frame_sha256: str,
    scan: decoder.ScanResult,
    *,
    case_np: int,
) -> list[dict[str, object]]:
    """Stream required state arrays from a held raw BI4 descriptor.

    The returned array order is position, velocity, density. Values include
    every particle in each native array, not only the B fluid cohort.
    """
    _require(bool(HEX64.fullmatch(expected_frame_sha256)), "expected raw frame SHA-256 is malformed")
    _require(isinstance(scan, decoder.ScanResult), "a safe BI4 ScanResult is required")
    try:
        before_identity = _stat_identity(raw_fd)
        _require(before_identity[2] == scan.input_bytes
                 and before_identity[:5] == scan.input_identity
                 and _hash_frame(raw_fd, scan.input_bytes) == expected_frame_sha256
                 and scan.input_sha256 == expected_frame_sha256,
                 "held raw frame identity or SHA differs from the C/BI4 scan binding")
        selected = _selected_arrays(scan, case_np)
        summaries = [
            _summarize_array(raw_fd, record, dtype_text, dtype, components, byte_count)
            for record, dtype_text, dtype, components, byte_count in selected
        ]
        after_identity = _stat_identity(raw_fd)
        _require(after_identity == before_identity,
                 "held raw frame descriptor identity changed during finite scan")
        _require(_hash_frame(raw_fd, scan.input_bytes) == expected_frame_sha256,
                 "held raw frame SHA changed during finite scan")
        _require(all(bool(HEX64.fullmatch(str(item["raw_array_sha256"]))) for item in summaries),
                 "a streamed raw-array SHA-256 is malformed")
        return summaries
    except OSError as error:
        raise NativeStateFiniteScanError("I/O failure during bounded raw-state finite scan") from error


__all__ = ["NativeStateFiniteScanError", "SCHEMA", "STREAM_CHUNK_BYTES", "summarize_native_state_fd"]

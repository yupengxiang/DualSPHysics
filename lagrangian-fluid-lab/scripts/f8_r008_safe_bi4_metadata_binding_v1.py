"""Read-only exact metadata binding for the bounded F8 R008 BI4 parser.

This API does not invoke a native decoder or write files. It reuses the
reviewed safe BI4 scanner and binds typed JBinaryData metadata from the raw
input, including exact little-endian scalar bits for TimeStep and MassFluid.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from typing import Any

from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008.safe_bi4_metadata_binding.v1"
FLOAT_TYPES = {11, 12, 22, 23}


def _components(value: Any, *, triple: bool) -> tuple[Any, ...]:
    if triple:
        if not isinstance(value, tuple) or len(value) != 3:
            raise decoder.Bi4FormatError("typed BI4 vector metadata is malformed")
        return value
    return (value,)


def _record(item: decoder.ItemRecord, value: decoder.ValueRecord) -> dict[str, Any]:
    type_name, fmt, _size, triple = decoder.VALUE_INFO[value.type_code]
    components = _components(value.value, triple=triple) if value.type_code != 1 else ()

    if value.type_code == 1:
        if not isinstance(value.value, str):
            raise decoder.Bi4FormatError("typed BI4 text metadata is malformed")
        raw = value.value.encode("utf-8", errors="strict")
        canonical_value: Any = value.value
        float_hex: list[str] = []
    else:
        try:
            packed_values = tuple(int(part) if value.type_code == 2 else part for part in components)
            raw = struct.pack(fmt, *packed_values) if triple else struct.pack(fmt, packed_values[0])
        except (OverflowError, TypeError, struct.error) as error:
            raise decoder.Bi4FormatError("typed BI4 metadata cannot be canonically rebound") from error
        if value.type_code in FLOAT_TYPES:
            numeric = tuple(float(part) for part in components)
            if not all(math.isfinite(part) for part in numeric):
                raise decoder.Bi4FormatError("non-finite BI4 floating metadata is not accepted")
            float_hex = [part.hex() for part in numeric]
            canonical_value = None
        elif value.type_code == 2:
            canonical_value = bool(value.value)
            float_hex = []
        elif triple:
            canonical_value = [int(part) for part in components]
            float_hex = []
        else:
            canonical_value = int(value.value)
            float_hex = []

    return {
        "item_path": ["JPartDataBi4"] if item.name == "JPartDataBi4" else ["JPartDataBi4", item.name],
        "metadata_name": value.name,
        "type_code": value.type_code,
        "type_name": type_name,
        "raw_value_bytes_hex": raw.hex(),
        "canonical_value": canonical_value,
        "float_hex_components": float_hex,
    }


def _require_field(
    item: decoder.ItemRecord,
    name: str,
    type_code: int,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> decoder.ValueRecord:
    matches = [entry for entry in item.values if entry.name == name]
    if len(matches) != 1:
        raise decoder.Bi4FormatError(f"required metadata field is missing or ambiguous: {item.name}.{name}")
    entry = matches[0]
    if entry.type_code != type_code:
        raise decoder.Bi4FormatError(f"required metadata field has the wrong JBinaryData type: {item.name}.{name}")
    if type_code in (11, 12):
        number = float(entry.value)
        if not math.isfinite(number):
            raise decoder.Bi4FormatError(f"required metadata field must be finite: {item.name}.{name}")
        if positive and number <= 0.0:
            raise decoder.Bi4FormatError(f"required metadata field must be positive: {item.name}.{name}")
        if nonnegative and (number < 0.0 or (number == 0.0 and math.copysign(1.0, number) < 0.0)):
            raise decoder.Bi4FormatError(f"required metadata field must be non-negative positive-zero: {item.name}.{name}")
    elif positive and int(entry.value) <= 0:
        raise decoder.Bi4FormatError(f"required metadata field must be positive: {item.name}.{name}")
    return entry


def canonical_manifest_bytes(value: dict[str, Any]) -> bytes:
    """Serialize the metadata manifest using the frozen detached encoding."""
    try:
        return (
            json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise decoder.Bi4FormatError("metadata manifest is not canonicalizable") from error


def bind_metadata_fd(fd: int, expected_sha256: str) -> dict[str, Any]:
    """Return exact typed metadata for a held, no-follow BI4 file descriptor.

    The caller is responsible for opening ``fd`` beneath the trusted root with
    ``O_NOFOLLOW``. The underlying scanner rechecks the raw input's hash,
    regular-file/link-count properties, and stable descriptor identity.
    """
    scan = decoder.scan_bi4_fd(fd, expected_sha256)
    root = scan.root
    if root.name != "JPartDataBi4" or len(root.children) != 1:
        raise decoder.Bi4FormatError("metadata source is not one bounded R008 BI4 frame")
    part = root.children[0]

    mass = _require_field(root, "MassFluid", 12, positive=True)
    _require_field(root, "CaseNp", 10, positive=True)
    _require_field(root, "CaseNfluid", 10, positive=True)
    _require_field(part, "TimeStep", 12, nonnegative=True)
    _require_field(part, "Npok", 8, positive=True)

    manifest = {
        "schema": SCHEMA,
        "input_sha256": scan.input_sha256,
        "input_bytes": scan.input_bytes,
        "metadata_records": [
            _record(item, value)
            for item in (root, part)
            for value in item.values
        ],
        "required_semantics": {
            "MassFluid": "root/global positive finite binary64 kg per particle",
            "TimeStep": "selected PART non-negative finite binary64 seconds; negative zero rejected",
            "Npok": "selected PART positive uint32 particle count",
        },
    }
    # These values are checked above and deliberately derived from parser-bound
    # records, not from the lossy %.15E XML display representation.
    if mass.type_code != 12:
        raise decoder.Bi4FormatError("MassFluid must be a JBinaryData double")
    payload = canonical_manifest_bytes(manifest)
    return {
        "manifest": manifest,
        "manifest_bytes": payload,
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "scan": scan,
    }


__all__ = ["SCHEMA", "bind_metadata_fd", "canonical_manifest_bytes"]

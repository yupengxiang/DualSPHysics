"""Strict, non-authorizing byte codec for the future F4 V3 bundle.

This module validates serialization and computes content digests only. It does
not read paths/descriptors, establish producer identity, mint a capability,
verify fs-verity, or authorize a batch.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


DOMAIN_SEPARATOR = b"CORE-F4-QUALIFICATION-BUNDLE-V3\n"
ROLE_ORDER = ("binding_admission", "evaluation_admission", "evaluation_source_raw")
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BundleCodecError(ValueError):
    """Raw bundle bytes or serialization fields violate the codec contract."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleCodecError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise BundleCodecError(f"non-finite JSON constant is forbidden: {value}")


def _parse_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise BundleCodecError("JSON number is outside the finite float domain")
    return value


def strict_json_object(raw: bytes, *, label: str = "JSON document") -> dict[str, Any]:
    """Parse exact raw UTF-8 bytes, rejecting duplicate keys and non-finite values."""
    if type(raw) is not bytes:
        raise BundleCodecError(f"{label} must be exact bytes")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise BundleCodecError(f"{label} is not strict UTF-8") from error
    try:
        value = json.loads(
            text,
            strict=True,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
            parse_float=_parse_float,
        )
    except BundleCodecError:
        raise
    except (json.JSONDecodeError, ValueError, OverflowError, RecursionError) as error:
        raise BundleCodecError(f"{label} is not valid strict JSON") from error
    if type(value) is not dict:
        raise BundleCodecError(f"{label} top level must be a JSON object")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Encode V12 canonical JSON bytes (default ASCII escaping, no newline)."""
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise BundleCodecError("value is not canonically JSON-serializable") from error
    return encoded


def document_digests(raw: bytes, *, label: str = "JSON document") -> tuple[str, str]:
    """Return (raw-byte SHA-256, canonical-parsed-object SHA-256)."""
    parsed = strict_json_object(raw, label=label)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    canonical_sha256 = hashlib.sha256(canonical_json_bytes(parsed)).hexdigest()
    return raw_sha256, canonical_sha256


def qualification_bundle_sha256(envelope_raw: bytes, role_documents: dict[str, bytes]) -> str:
    """Compute the V13 domain-separated object-graph digest, without authorizing it."""
    if type(role_documents) is not dict or set(role_documents) != set(ROLE_ORDER):
        raise BundleCodecError("role_documents must contain exactly the three V3 roles")
    if type(envelope_raw) is not bytes:
        raise BundleCodecError("qualification envelope must be exact bytes")
    strict_json_object(envelope_raw, label="qualification envelope")
    if len(envelope_raw) >= 1 << 64:
        raise BundleCodecError("qualification envelope exceeds U64 length")

    encoded = bytearray(DOMAIN_SEPARATOR)
    encoded.extend(len(envelope_raw).to_bytes(8, "big"))
    encoded.extend(envelope_raw)
    for role in ROLE_ORDER:
        role_bytes = role.encode("ascii")
        if len(role_bytes) >= 1 << 16:
            raise BundleCodecError("bundle role exceeds U16 length")
        raw = role_documents[role]
        raw_sha256, canonical_sha256 = document_digests(raw, label=role)
        if not _LOWER_SHA256.fullmatch(raw_sha256) or not _LOWER_SHA256.fullmatch(canonical_sha256):
            raise BundleCodecError("internal digest encoding is invalid")
        encoded.extend(len(role_bytes).to_bytes(2, "big"))
        encoded.extend(role_bytes)
        encoded.extend(bytes.fromhex(raw_sha256))
        encoded.extend(bytes.fromhex(canonical_sha256))
    return hashlib.sha256(encoded).hexdigest()


def positive_builtin_int(value: Any, *, name: str) -> int:
    """Validate an exact positive JSON integer; bool is deliberately rejected."""
    if type(value) is not int or value <= 0:
        raise BundleCodecError(f"{name} must be an exact positive integer")
    return value

"""Non-authorizing verifier for F8 R008 attempt-ledger attestations.

This module verifies the frozen Ed25519 message format and bindings between an
attestation, a structurally valid caller-supplied ledger, and the frozen
qualification matrix. The public key is also caller-supplied: without an
out-of-band active/revocation registry and trusted runtime identity, a valid
signature remains diagnostic evidence and never establishes ledger
completeness or grants qualification authority.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scripts.core_strict_json import strict_json_object
from scripts import f8_r008_attempt_ledger_v1 as ledger_v1


SCHEMA = "core.cfd.f8.r008_untrusted_attempt_ledger_attestation_diagnostic.v1"
ATTESTATION_SCHEMA = "core.cfd.f8.r008_attempt_ledger_attestation.v1"
DOMAIN = b"CORE-F8-R008-ATTEMPT-LEDGER-ATTESTATION-V1\n"
MAX_ATTESTATION_BYTES = 65_536
ATTESTATION_FIELDS = frozenset({
    "schema", "scope_id", "qualification_matrix_raw_sha256",
    "attempt_ledger_raw_sha256", "supervisor_source_id",
    "coverage_start_ns_hex", "coverage_end_ns_hex", "event_count",
    "overflow", "lost_count", "signature_algorithm",
    "verification_key_id", "signature_base64",
})
_HEX16 = re.compile(r"[0-9a-f]{16}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)


class AttemptLedgerAttestationV1Error(ValueError):
    """An attestation is malformed, inconsistent, or has an invalid signature."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AttemptLedgerAttestationV1Error(message)


def _canonical_json_bytes(value: Any) -> bytes:
    """Encode the repository V12 canonical JSON form (ASCII escapes, no LF)."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError,
            RecursionError) as error:
        raise AttemptLedgerAttestationV1Error(
            "attestation is not canonically JSON-serializable") from error


def _parse_attestation(raw: bytes) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_ATTESTATION_BYTES,
             "attestation raw bytes are outside the fixed size bound")
    try:
        value = strict_json_object(raw, label="F8 R008 attempt-ledger attestation",
                                  max_bytes=MAX_ATTESTATION_BYTES)
    except ValueError as error:
        raise AttemptLedgerAttestationV1Error(str(error)) from error
    _require(set(value) == ATTESTATION_FIELDS,
             "attestation fields do not match the exact frozen schema")
    _require(_canonical_json_bytes(value) == raw,
             "attestation raw bytes are not exact V12 canonical JSON")
    _require(value.get("schema") == ATTESTATION_SCHEMA,
             "attestation schema is unsupported")
    _require(value.get("scope_id") == ledger_v1.SCOPE_ID,
             "attestation scope differs from the frozen F8 R008 scope")
    for field in ("qualification_matrix_raw_sha256", "attempt_ledger_raw_sha256"):
        _require(type(value.get(field)) is str
                 and bool(_SHA256.fullmatch(value[field])),
                 f"attestation {field} is not lowercase SHA-256")
    for field in ("coverage_start_ns_hex", "coverage_end_ns_hex"):
        _require(type(value.get(field)) is str
                 and bool(_HEX16.fullmatch(value[field])),
                 f"attestation {field} is not 16 lowercase hexadecimal digits")
    _require(int(value["coverage_start_ns_hex"], 16)
             <= int(value["coverage_end_ns_hex"], 16),
             "attestation coverage start exceeds its end")
    _require(type(value.get("event_count")) is int and value["event_count"] >= 0,
             "attestation event_count must be a nonnegative builtin integer")
    _require(type(value.get("overflow")) is bool,
             "attestation overflow must be a builtin boolean")
    _require(type(value.get("lost_count")) is int and value["lost_count"] >= 0,
             "attestation lost_count must be a nonnegative builtin integer")
    _require(value.get("signature_algorithm") == "ed25519",
             "attestation signature_algorithm must be ed25519")
    _require(type(value.get("supervisor_source_id")) is str
             and bool(_IDENTIFIER.fullmatch(value["supervisor_source_id"])),
             "attestation supervisor_source_id is malformed")
    _require(type(value.get("verification_key_id")) is str
             and bool(_IDENTIFIER.fullmatch(value["verification_key_id"])),
             "attestation verification_key_id is malformed")
    signature_text = value.get("signature_base64")
    _require(type(signature_text) is str,
             "attestation signature_base64 must be a builtin string")
    try:
        signature_ascii = signature_text.encode("ascii")
        signature = base64.b64decode(signature_ascii, validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        raise AttemptLedgerAttestationV1Error(
            "attestation signature is not strict standard base64") from error
    _require(len(signature) == 64 and base64.b64encode(signature) == signature_ascii,
             "attestation signature is not canonical base64 for a 64-byte Ed25519 signature")
    return value


def _signature_message(attestation: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in attestation.items()
                if key != "signature_base64"}
    return DOMAIN + _canonical_json_bytes(unsigned)


def verify_untrusted_attempt_ledger_attestation(
    attestation_raw: bytes,
    ledger_raw: bytes,
    qualification_matrix_raw: bytes,
    *,
    candidate_verification_key_id: str,
    candidate_public_key_bytes: bytes,
) -> dict[str, Any]:
    """Verify signature and content bindings without asserting key trust.

    ``candidate_public_key_bytes`` is intentionally not called trusted: its
    provenance, active status, revocation state, and binding to a supervisor
    process are not established here. All accepted results remain
    non-authorizing diagnostics with ``attempt_ledger_complete=False``.
    """
    attestation = _parse_attestation(attestation_raw)
    _require(type(candidate_verification_key_id) is str
             and candidate_verification_key_id == attestation["verification_key_id"],
             "candidate key ID differs from the attested verification_key_id")
    _require(type(candidate_public_key_bytes) is bytes
             and len(candidate_public_key_bytes) == 32,
             "candidate Ed25519 public key must be exactly 32 raw bytes")

    try:
        ledger_diagnostic = ledger_v1.inspect_untrusted_attempt_ledger(
            ledger_raw, qualification_matrix_raw=qualification_matrix_raw,
        )
    except ValueError as error:
        raise AttemptLedgerAttestationV1Error(
            f"ledger/matrix structural validation failed: {error}") from error

    expected_bindings = {
        "schema": ATTESTATION_SCHEMA,
        "scope_id": ledger_diagnostic["scope_id"],
        "qualification_matrix_raw_sha256": ledger_diagnostic[
            "qualification_matrix_raw_sha256"],
        "attempt_ledger_raw_sha256": ledger_diagnostic["ledger_raw_sha256"],
        "supervisor_source_id": ledger_diagnostic["supervisor_source_id"],
        "coverage_start_ns_hex": ledger_diagnostic["coverage_start_ns_hex"],
        "coverage_end_ns_hex": ledger_diagnostic["coverage_end_ns_hex"],
        "event_count": ledger_diagnostic["event_count"],
        "overflow": ledger_diagnostic["overflow"],
        "lost_count": ledger_diagnostic["lost_count"],
        "signature_algorithm": "ed25519",
        "verification_key_id": candidate_verification_key_id,
    }
    for field, expected in expected_bindings.items():
        _require(attestation[field] == expected,
                 f"attestation {field} differs from the supplied ledger/matrix binding")

    public_key_fingerprint = hashlib.sha256(candidate_public_key_bytes).hexdigest()
    try:
        public_key = Ed25519PublicKey.from_public_bytes(candidate_public_key_bytes)
        public_key.verify(base64.b64decode(attestation["signature_base64"]),
                          _signature_message(attestation))
    except InvalidSignature as error:
        raise AttemptLedgerAttestationV1Error(
            "attestation Ed25519 signature is invalid for the candidate key") from error
    except (TypeError, ValueError) as error:
        raise AttemptLedgerAttestationV1Error(
            "candidate Ed25519 key or attestation signature is invalid") from error

    return {
        "schema": SCHEMA,
        "status": "untrusted_signature_and_binding_verified",
        "attestation_schema": ATTESTATION_SCHEMA,
        "attestation_raw_bytes": len(attestation_raw),
        "attestation_raw_sha256": hashlib.sha256(attestation_raw).hexdigest(),
        "ledger_raw_bytes": len(ledger_raw),
        "ledger_raw_sha256": ledger_diagnostic["ledger_raw_sha256"],
        "qualification_matrix_raw_sha256": ledger_diagnostic[
            "qualification_matrix_raw_sha256"],
        "ledger_structure_valid": True,
        "signature_cryptographically_valid": True,
        "signed_claim_bindings_match_supplied_ledger": True,
        "verification_key_id": candidate_verification_key_id,
        "candidate_public_key_sha256": public_key_fingerprint,
        "candidate_key_is_active": False,
        "active_key_registry_verified": False,
        "supervisor_identity_authenticated": False,
        "descriptor_root_authenticated": False,
        "attempt_ledger_complete": False,
        "capability_minted": False,
        "qualification_adjudicated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


__all__ = [
    "ATTESTATION_FIELDS", "ATTESTATION_SCHEMA", "AttemptLedgerAttestationV1Error",
    "DOMAIN", "MAX_ATTESTATION_BYTES", "SCHEMA",
    "verify_untrusted_attempt_ledger_attestation",
]

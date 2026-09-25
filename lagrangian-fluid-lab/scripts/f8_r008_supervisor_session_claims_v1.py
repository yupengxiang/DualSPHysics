"""Non-authorizing bridge for signed F8 R008 supervisor-session claims.

This module binds two Ed25519 signatures made by one caller-supplied candidate
key to one raw ledger, one ledger-derived C process-terminal reference, and one
nonce-matched V5 journal runtime-identity projection. It establishes only
claim consistency under that candidate key. No trust root, active-key
registry, authentic event source, or runtime measurement is available here.
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
from scripts import f8_r008_attempt_ledger_attestation_v1 as ledger_attestation_v1
from scripts import f8_r008_attempt_ledger_v1 as ledger_v1
from scripts import f8_r008_c_execution_journal_v5 as journal_v5


SCHEMA = "core.cfd.f8.r008_untrusted_supervisor_session_claim_projection.v1"
SESSION_SCHEMA = "core.cfd.f8.r008_supervisor_session_claim.v1"
DOMAIN = b"CORE-F8-R008-SUPERVISOR-SESSION-CLAIM-V1\n"
MAX_SESSION_BYTES = 65_536
MAX_ATTESTATION_BYTES = ledger_attestation_v1.MAX_ATTESTATION_BYTES
SESSION_FIELDS = frozenset({
    "schema", "scope_id", "qualification_matrix_raw_sha256",
    "qualification_row_sha256", "attempt_ledger_raw_sha256",
    "ledger_attestation_raw_sha256", "ledger_coverage_start_ns_hex",
    "ledger_coverage_end_ns_hex", "ledger_event_count", "ledger_overflow",
    "ledger_lost_count", "case_id", "attempt_id", "nonce_hex",
    "process_terminal_seq", "ledger_process_generation_id", "process_journal_ref",
    "process_journal_raw_sha256", "supervisor_source_id", "verification_key_id",
    "candidate_public_key_sha256", "journal_source_id",
    "journal_source_binary_sha256", "root_spawn_seq",
    "root_process_generation_sha256", "root_supervisor_identity_binding_sha256",
    "root_exec_seq", "root_exec_event_sha256", "observed_load_event_count",
    "observed_load_events_sha256", "signature_algorithm", "signature_base64",
})
PROCESS_JOURNAL_REF_FIELDS = frozenset({"stage", "role", "object_id", "bytes", "sha256"})
_HEX16 = re.compile(r"[0-9a-f]{16}\Z", re.ASCII)
_HEX32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)


class SupervisorSessionClaimsError(ValueError):
    """Session, ledger, candidate signature, and journal claims disagree."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SupervisorSessionClaimsError(message)


def _canonical_json_bytes(value: Any, label: str) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise SupervisorSessionClaimsError(f"{label} is not canonical-JSON serializable") from error


def _parse_session(raw: bytes) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_SESSION_BYTES,
             "supervisor session bytes are outside the fixed size bound")
    try:
        value = strict_json_object(raw, label="F8 R008 supervisor session", max_bytes=MAX_SESSION_BYTES)
    except ValueError as error:
        raise SupervisorSessionClaimsError(str(error)) from error
    _require(set(value) == SESSION_FIELDS,
             "supervisor session fields do not match the exact frozen schema")
    _require(_canonical_json_bytes(value, "supervisor session") == raw,
             "supervisor session bytes are not exact canonical JSON")
    _require(value.get("schema") == SESSION_SCHEMA,
             "supervisor session schema is unsupported")
    for field in (
        "case_id", "attempt_id", "ledger_process_generation_id",
        "supervisor_source_id", "verification_key_id", "journal_source_id",
    ):
        _require(type(value.get(field)) is str and bool(_IDENTIFIER.fullmatch(value[field])),
                 f"supervisor session {field} is malformed")
    _require(type(value.get("scope_id")) is str and value["scope_id"] == ledger_v1.SCOPE_ID,
             "supervisor session scope_id is not the fixed F8 R008 scope")
    for field in ("nonce_hex",):
        _require(type(value.get(field)) is str and bool(_HEX32.fullmatch(value[field])),
                 f"supervisor session {field} is malformed")
    for field in ("ledger_coverage_start_ns_hex", "ledger_coverage_end_ns_hex"):
        _require(type(value.get(field)) is str and bool(_HEX16.fullmatch(value[field])),
                 f"supervisor session {field} is malformed")
    _require(value["ledger_coverage_start_ns_hex"] <= value["ledger_coverage_end_ns_hex"],
             "supervisor session ledger coverage start exceeds end")
    for field in (
        "qualification_matrix_raw_sha256", "qualification_row_sha256",
        "attempt_ledger_raw_sha256", "ledger_attestation_raw_sha256",
        "process_journal_raw_sha256", "candidate_public_key_sha256",
        "journal_source_binary_sha256", "root_process_generation_sha256",
        "root_supervisor_identity_binding_sha256", "root_exec_event_sha256",
        "observed_load_events_sha256",
    ):
        _require(type(value.get(field)) is str and bool(_SHA256.fullmatch(value[field])),
                 f"supervisor session {field} is not lowercase SHA-256")
    for field in ("ledger_event_count", "ledger_lost_count", "process_terminal_seq",
                  "root_spawn_seq", "root_exec_seq", "observed_load_event_count"):
        _require(type(value.get(field)) is int and value[field] >= 0,
                 f"supervisor session {field} must be a nonnegative builtin integer")
    _require(type(value.get("ledger_overflow")) is bool,
             "supervisor session ledger_overflow must be an exact boolean")
    ref = value.get("process_journal_ref")
    _require(type(ref) is dict and set(ref) == PROCESS_JOURNAL_REF_FIELDS,
             "supervisor session process_journal_ref fields are not exact")
    _require(ref.get("stage") == "C" and ref.get("role") == "process_journal"
             and type(ref.get("object_id")) is str
             and bool(_IDENTIFIER.fullmatch(ref["object_id"]))
             and type(ref.get("bytes")) is int and ref["bytes"] > 0
             and ref["bytes"] <= journal_v5.MAX_RAW_BYTES
             and type(ref.get("sha256")) is str and bool(_SHA256.fullmatch(ref["sha256"])),
             "supervisor session process_journal_ref is malformed or exceeds the V5 journal cap")
    _require(value.get("signature_algorithm") == "ed25519",
             "supervisor session signature_algorithm must be ed25519")
    signature_text = value.get("signature_base64")
    _require(type(signature_text) is str,
             "supervisor session signature_base64 must be a builtin string")
    try:
        signature = base64.b64decode(signature_text.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        raise SupervisorSessionClaimsError("supervisor session signature is not strict Base64") from error
    _require(len(signature) == 64 and base64.b64encode(signature).decode("ascii") == signature_text,
             "supervisor session signature is not canonical 64-byte Ed25519 Base64")
    return value


def _session_message(session: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in session.items() if key != "signature_base64"}
    return DOMAIN + _canonical_json_bytes(unsigned, "unsigned supervisor session")


def _projection_ref(projection: ledger_v1.UntrustedCProcessTerminalProjectionV1) -> dict[str, Any]:
    return {
        "stage": projection.process_journal_ref_stage,
        "role": projection.process_journal_ref_role,
        "object_id": projection.process_journal_ref_object_id,
        "bytes": projection.process_journal_ref_bytes,
        "sha256": projection.process_journal_ref_sha256,
    }


def bind_untrusted_supervisor_session_claims_v1(
    qualification_matrix_raw: bytes,
    ledger_raw: bytes,
    ledger_attestation_raw: bytes,
    c_journal_raw: bytes,
    supervisor_session_raw: bytes,
    *,
    candidate_key_id: str,
    candidate_public_key_bytes: bytes,
    case_id: str,
    attempt_id: str,
    nonce_hex: str,
) -> dict[str, Any]:
    """Bind candidate-signed session claims to one ledger-derived C journal.

    The attempt selector is resolved against the supplied raw ledger; callers
    cannot supply a terminal event, generation ID, or journal reference. Both
    signatures are checked with the same caller-supplied candidate key and
    distinct domain separators. A valid signature proves neither key trust nor
    supervisor/runtime identity.
    """
    _require(type(qualification_matrix_raw) is bytes
             and 0 < len(qualification_matrix_raw) <= ledger_v1.MAX_LEDGER_BYTES,
             "qualification matrix bytes are outside the fixed size bound")
    _require(type(ledger_raw) is bytes and 0 < len(ledger_raw) <= ledger_v1.MAX_LEDGER_BYTES,
             "attempt ledger bytes are outside the fixed size bound")
    _require(type(ledger_attestation_raw) is bytes
             and 0 < len(ledger_attestation_raw) <= MAX_ATTESTATION_BYTES,
             "ledger attestation bytes are outside the fixed size bound")
    _require(type(c_journal_raw) is bytes and 0 < len(c_journal_raw) <= journal_v5.MAX_RAW_BYTES,
             "C V5 journal bytes are outside the fixed size bound")
    _require(type(candidate_key_id) is str and bool(_IDENTIFIER.fullmatch(candidate_key_id)),
             "candidate key ID is malformed")
    _require(type(candidate_public_key_bytes) is bytes and len(candidate_public_key_bytes) == 32,
             "candidate Ed25519 public key must be exactly 32 raw bytes")
    session = _parse_session(supervisor_session_raw)
    public_key_sha256 = hashlib.sha256(candidate_public_key_bytes).hexdigest()

    try:
        ledger_signature = ledger_attestation_v1.verify_untrusted_attempt_ledger_attestation(
            ledger_attestation_raw,
            ledger_raw,
            qualification_matrix_raw,
            candidate_verification_key_id=candidate_key_id,
            candidate_public_key_bytes=candidate_public_key_bytes,
        )
    except ledger_attestation_v1.AttemptLedgerAttestationV1Error as error:
        raise SupervisorSessionClaimsError(f"ledger candidate signature/binding is invalid: {error}") from error

    try:
        ledger_projection = ledger_v1.inspect_untrusted_c_process_terminal_projection_v1(
            ledger_raw,
            qualification_matrix_raw=qualification_matrix_raw,
            case_id=case_id,
            attempt_id=attempt_id,
            nonce_hex=nonce_hex,
        )
    except ledger_v1.AttemptLedgerV1Error as error:
        raise SupervisorSessionClaimsError(f"C process terminal is not uniquely ledger-derived: {error}") from error

    journal_ref = _projection_ref(ledger_projection)
    _require(ledger_projection.process_journal_ref_stage == "C"
             and ledger_projection.process_journal_ref_role == "process_journal",
             "ledger C process terminal does not reference the registered C V5 journal role")
    _require(len(c_journal_raw) == ledger_projection.process_journal_ref_bytes
             and hashlib.sha256(c_journal_raw).hexdigest() == ledger_projection.process_journal_ref_sha256,
             "C V5 journal raw bytes differ from the ledger-derived descriptor reference")

    try:
        journal_projection = journal_v5.inspect_untrusted_v5_runtime_identity_projection_v1(
            c_journal_raw, expected_attempt_nonce_hex=ledger_projection.nonce_hex,
        )
    except journal_v5.JournalV5Error as error:
        raise SupervisorSessionClaimsError(f"C V5 runtime-identity observations are invalid: {error}") from error

    expected_claims = {
        "schema": SESSION_SCHEMA,
        "scope_id": ledger_projection.scope_id,
        "qualification_matrix_raw_sha256": ledger_projection.qualification_matrix_raw_sha256,
        "qualification_row_sha256": ledger_projection.qualification_row_sha256,
        "attempt_ledger_raw_sha256": ledger_projection.ledger_raw_sha256,
        "ledger_attestation_raw_sha256": hashlib.sha256(ledger_attestation_raw).hexdigest(),
        "ledger_coverage_start_ns_hex": ledger_projection.coverage_start_ns_hex,
        "ledger_coverage_end_ns_hex": ledger_projection.coverage_end_ns_hex,
        "ledger_event_count": ledger_projection.event_count,
        "ledger_overflow": ledger_projection.overflow,
        "ledger_lost_count": ledger_projection.lost_count,
        "case_id": ledger_projection.case_id,
        "attempt_id": ledger_projection.attempt_id,
        "nonce_hex": ledger_projection.nonce_hex,
        "process_terminal_seq": ledger_projection.process_terminal_seq,
        "ledger_process_generation_id": ledger_projection.ledger_process_generation_id,
        "process_journal_ref": journal_ref,
        "process_journal_raw_sha256": journal_projection.journal_raw_sha256,
        "supervisor_source_id": ledger_projection.supervisor_source_id,
        "verification_key_id": candidate_key_id,
        "candidate_public_key_sha256": public_key_sha256,
        "journal_source_id": journal_projection.source_id_observed,
        "journal_source_binary_sha256": journal_projection.source_binary_sha256_observed,
        "root_spawn_seq": journal_projection.root_spawn_seq,
        "root_process_generation_sha256": journal_projection.root_process_generation_sha256,
        "root_supervisor_identity_binding_sha256": (
            journal_projection.root_supervisor_identity_binding_sha256
        ),
        "root_exec_seq": journal_projection.root_exec_seq,
        "root_exec_event_sha256": journal_projection.root_exec_event_sha256,
        "observed_load_event_count": journal_projection.observed_load_event_count,
        "observed_load_events_sha256": journal_projection.observed_load_events_sha256,
        "signature_algorithm": "ed25519",
    }
    for field, expected in expected_claims.items():
        _require(session.get(field) == expected,
                 f"supervisor session {field} differs from the ledger/journal-derived projection")

    try:
        public_key = Ed25519PublicKey.from_public_bytes(candidate_public_key_bytes)
        public_key.verify(base64.b64decode(session["signature_base64"]), _session_message(session))
    except InvalidSignature as error:
        raise SupervisorSessionClaimsError(
            "supervisor session signature is invalid for the candidate key"
        ) from error
    except (TypeError, ValueError) as error:
        raise SupervisorSessionClaimsError("candidate Ed25519 key or session signature is invalid") from error

    return {
        "schema": SCHEMA,
        "status": "untrusted_candidate_signed_supervisor_session_claims_consistent",
        "session_raw_bytes": len(supervisor_session_raw),
        "session_raw_sha256": hashlib.sha256(supervisor_session_raw).hexdigest(),
        "ledger_attestation_raw_sha256": hashlib.sha256(ledger_attestation_raw).hexdigest(),
        "c_journal_raw_sha256": journal_projection.journal_raw_sha256,
        "candidate_key_id": candidate_key_id,
        "candidate_public_key_sha256": public_key_sha256,
        "candidate_key_fingerprint_matches": True,
        "ledger_signature_valid_for_candidate": ledger_signature["signature_cryptographically_valid"],
        "session_signature_valid_for_candidate": True,
        "ledger_session_claims_consistent": True,
        "journal_claims_consistent": True,
        "observed_load_bindings_consistent": True,
        "observed_load_event_count": journal_projection.observed_load_event_count,
        "ledger_derived_c_process_terminal": True,
        "ledger_process_generation_id": ledger_projection.ledger_process_generation_id,
        "journal_root_generation_binding_sha256": journal_projection.root_process_generation_sha256,
        "journal_root_exec_event_sha256": journal_projection.root_exec_event_sha256,
        "journal_observed_load_events_sha256": journal_projection.observed_load_events_sha256,
        "candidate_key_is_active": False,
        "active_key_registry_verified": False,
        "trusted_root_capability_present": False,
        "descriptor_root_authenticated": False,
        "supervisor_identity_authenticated": False,
        "worker_execution_authenticated": False,
        "artifact_producer_authenticated": False,
        "process_generation_identity_linked": False,
        "event_source_completeness_verified": False,
        "runtime_identity_verified": False,
        "loaded_module_code_identity_verified": False,
        "attempt_ledger_complete": False,
        "attempt_outcomes_resolved": False,
        "qualification_adjudicated": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


__all__ = [
    "DOMAIN", "MAX_SESSION_BYTES", "PROCESS_JOURNAL_REF_FIELDS", "SCHEMA",
    "SESSION_FIELDS", "SESSION_SCHEMA", "SupervisorSessionClaimsError",
    "bind_untrusted_supervisor_session_claims_v1",
]

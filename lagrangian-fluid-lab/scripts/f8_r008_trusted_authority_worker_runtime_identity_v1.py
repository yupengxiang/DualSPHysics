#!/usr/bin/env python3
"""Validate a synthetic-only, non-authorizing F8/R008 identity chain.

The existing R008 supervisor-session and attempt-ledger verifiers establish
candidate-key consistency only.  This module adds the missing structural
contract for an explicit trust-root -> active-key -> authority/worker/runtime
chain.  The caller must provide the root public key explicitly; there is no
default trust root, no candidate-key self-certification, and no production
consumer.  Inputs are bounded in-memory synthetic JSON bytes and successful
results remain diagnostic-only.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.core_strict_json import strict_json_object
from scripts import f8_r008_attempt_ledger_v1 as ledger_v1


SCHEMA = "core.cfd.f8.r008_trusted_authority_worker_runtime_identity_contract.v1"
REPORT_SCHEMA = "core.cfd.f8.r008_trusted_identity_contract_report.v1"
RECORD_ID = "f8-r008-trusted-authority-worker-runtime-identity-v1"
REPORT_RECORD_ID = "f8-r008-trusted-identity-contract-report-v1"
STATUS = "synthetic_only_fail_closed_identity_contract"
REPORT_STATUS = "synthetic_only_non_authorizing_contract_design"
SCOPE_ID = ledger_v1.SCOPE_ID
ALGORITHM = "ed25519"
ROOT_DOMAIN = "CORE-F8-R008-TRUST-ROOT-ACTIVE-KEY-V1"
IDENTITY_DOMAIN = "CORE-F8-R008-AUTHORITY-WORKER-RUNTIME-IDENTITY-V1"
ROOT_ASSERTION_SCHEMA = "core.cfd.f8.r008_trust_root_active_key_assertion.v1"
IDENTITY_ASSERTION_SCHEMA = "core.cfd.f8.r008_authority_worker_runtime_identity_assertion.v1"
MAX_BUNDLE_BYTES = 128 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)
IDENTIFIER_DENYLIST = frozenset({"anonymous", "candidate", "default", "self"})

BUNDLE_FIELDS = frozenset({
    "schema", "record_id", "status", "synthetic_only", "input_origin", "scope_id",
    "trust_root", "active_key", "identities", "bindings", "constraints", "signatures",
})
TRUST_ROOT_FIELDS = frozenset({
    "root_id", "role", "algorithm", "domain", "epoch", "revoked",
    "public_key_base64", "public_key_sha256", "source",
})
ACTIVE_KEY_FIELDS = frozenset({
    "key_id", "role", "algorithm", "domain", "epoch", "revoked",
    "public_key_base64", "public_key_sha256", "root_id", "root_public_key_sha256",
    "source",
})
IDENTITY_FIELDS = frozenset({
    "principal_id", "role", "host_id", "host_identity_sha256", "runtime_id",
    "runtime_identity_sha256", "epoch", "revoked", "synthetic_only", "source",
    "parent_binding_sha256", "issuer_key_id", "binding_sha256",
})
BINDING_FIELDS = frozenset({
    "root_active_key_sha256", "authority_worker_sha256", "worker_runtime_sha256",
    "host_runtime_sha256",
})
CONSTRAINT_FIELDS = frozenset({
    "algorithm", "root_domain", "identity_domain", "epoch", "revocation", "trust",
})
REVOCATION_FIELDS = frozenset({"root", "active_key", "authority", "worker", "runtime"})
TRUST_FIELDS = frozenset({"default_trust", "candidate_key_self_attestation", "root_anchor"})
SIGNATURE_FIELDS = frozenset({"root_active_key_base64", "active_identity_base64"})


class TrustedIdentityContractError(ValueError):
    """The synthetic identity bundle is malformed or fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TrustedIdentityContractError(message)


def _canonical_json_bytes(value: Any, label: str = "value") -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise TrustedIdentityContractError(f"{label} is not canonical-JSON serializable") from error


def _sha256_json(value: Any, label: str) -> str:
    return hashlib.sha256(_canonical_json_bytes(value, label)).hexdigest()


def _require_keys(value: Any, expected: frozenset[str], label: str) -> None:
    _require(isinstance(value, dict) and set(value) == expected, f"{label} fields are not exact")


def _validate_identifier(value: Any, label: str) -> None:
    _require(type(value) is str and bool(IDENTIFIER_RE.fullmatch(value)), f"{label} is malformed")
    _require(value not in IDENTIFIER_DENYLIST, f"{label} may not use a default/self identity")


def _validate_sha256(value: Any, label: str) -> None:
    _require(type(value) is str and bool(SHA256_RE.fullmatch(value)), f"{label} is not lowercase SHA-256")


def _decode_public_key(value: Any, label: str) -> bytes:
    _require(type(value) is str, f"{label} must be Base64 text")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        raise TrustedIdentityContractError(f"{label} is not strict Base64") from error
    _require(len(decoded) == 32 and base64.b64encode(decoded).decode("ascii") == value,
             f"{label} is not canonical 32-byte Ed25519 Base64")
    return decoded


def _decode_signature(value: Any, label: str) -> bytes:
    _require(type(value) is str, f"{label} must be Base64 text")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        raise TrustedIdentityContractError(f"{label} is not strict Base64") from error
    _require(len(decoded) == 64 and base64.b64encode(decoded).decode("ascii") == value,
             f"{label} is not canonical 64-byte Ed25519 Base64")
    return decoded


def _parse_bundle(raw: bytes) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_BUNDLE_BYTES,
             "identity bundle bytes are outside the fixed synthetic size bound")
    try:
        value = strict_json_object(raw, label="F8 R008 synthetic identity bundle",
                                   max_bytes=MAX_BUNDLE_BYTES)
    except ValueError as error:
        raise TrustedIdentityContractError(str(error)) from error
    _require(set(value) == BUNDLE_FIELDS, "identity bundle fields do not match the exact schema")
    _require(_canonical_json_bytes(value, "identity bundle") == raw,
             "identity bundle bytes are not exact canonical JSON")
    _require(value.get("schema") == SCHEMA, "identity bundle schema is unsupported")
    _require(value.get("record_id") == RECORD_ID, "identity bundle record_id is unsupported")
    _require(value.get("status") == STATUS, "identity bundle status is not the fixed non-authorizing status")
    _require(value.get("synthetic_only") is True and value.get("input_origin") == "synthetic_fixture",
             "identity bundle must declare synthetic_fixture input origin")
    _require(value.get("scope_id") == SCOPE_ID, "identity bundle scope differs from F8 R008")
    return value


def _validate_constraints(value: Any) -> int:
    _require_keys(value, CONSTRAINT_FIELDS, "identity constraints")
    _require(value["algorithm"] == ALGORITHM, "identity algorithm constraint is not Ed25519")
    _require(value["root_domain"] == ROOT_DOMAIN, "identity root signature domain is unsupported")
    _require(value["identity_domain"] == IDENTITY_DOMAIN, "identity signature domain is unsupported")

    epoch = value["epoch"]
    _require_keys(epoch, frozenset({"current", "minimum", "maximum"}), "epoch constraints")
    for field in ("current", "minimum", "maximum"):
        _require(type(epoch[field]) is int and 0 <= epoch[field] <= 2**31 - 1,
                 f"epoch constraint {field} must be a bounded builtin integer")
    _require(epoch["minimum"] <= epoch["current"] <= epoch["maximum"],
             "epoch constraints are not ordered")

    revocation = value["revocation"]
    _require_keys(revocation, REVOCATION_FIELDS, "revocation constraints")
    for field in REVOCATION_FIELDS:
        _require(type(revocation[field]) is bool, f"revocation constraint {field} must be boolean")
        _require(revocation[field] is False, f"revocation constraint {field} is revoked")

    trust = value["trust"]
    _require_keys(trust, TRUST_FIELDS, "trust constraints")
    _require(trust["default_trust"] == "deny", "default trust must be deny")
    _require(trust["candidate_key_self_attestation"] == "reject",
             "candidate key self-attestation must be rejected")
    _require(trust["root_anchor"] == "explicit_argument_only",
             "trust root must be an explicitly supplied argument")
    return epoch["current"]


def _validate_trust_root(value: Any, *, current_epoch: int,
                         explicit_root_public_key: bytes) -> bytes:
    _require_keys(value, TRUST_ROOT_FIELDS, "trust root")
    _validate_identifier(value["root_id"], "trust root root_id")
    _require(value["role"] == "trust_root", "trust root role is unsupported")
    _require(value["algorithm"] == ALGORITHM, "trust root algorithm is unsupported")
    _require(value["domain"] == ROOT_DOMAIN, "trust root domain is unsupported")
    _require(value["epoch"] == current_epoch, "trust root epoch is outside the active epoch")
    _require(value["revoked"] is False, "trust root is revoked")
    _require(value["source"] == "synthetic_fixture", "trust root source is not synthetic_fixture")
    public_key = _decode_public_key(value["public_key_base64"], "trust root public key")
    _validate_sha256(value["public_key_sha256"], "trust root public key hash")
    _require(value["public_key_sha256"] == hashlib.sha256(public_key).hexdigest(),
             "trust root public key hash does not match its bytes")
    _require(type(explicit_root_public_key) is bytes and len(explicit_root_public_key) == 32,
             "explicit trust root public key must be exactly 32 raw bytes")
    _require(public_key == explicit_root_public_key,
             "bundle trust root does not match the explicitly supplied trust anchor")
    return public_key


def _validate_active_key(value: Any, *, root: dict[str, Any], current_epoch: int,
                         root_public_key: bytes) -> bytes:
    _require_keys(value, ACTIVE_KEY_FIELDS, "active key")
    _validate_identifier(value["key_id"], "active key key_id")
    _require(value["key_id"] != root["root_id"], "active key must be distinct from the trust root")
    _require(value["role"] == "authority_issuer", "active key role is unsupported")
    _require(value["algorithm"] == ALGORITHM, "active key algorithm is unsupported")
    _require(value["domain"] == IDENTITY_DOMAIN, "active key domain is unsupported")
    _require(value["epoch"] == current_epoch, "active key epoch is outside the active epoch")
    _require(value["revoked"] is False, "active key is revoked")
    _require(value["root_id"] == root["root_id"], "active key root_id does not bind to the trust root")
    _validate_sha256(value["root_public_key_sha256"], "active key root public key hash")
    _require(value["root_public_key_sha256"] == hashlib.sha256(root_public_key).hexdigest(),
             "active key root public key hash differs from the explicit anchor")
    _require(value["source"] == "synthetic_fixture", "active key source is not synthetic_fixture")
    public_key = _decode_public_key(value["public_key_base64"], "active key public key")
    _validate_sha256(value["public_key_sha256"], "active key public key hash")
    _require(value["public_key_sha256"] == hashlib.sha256(public_key).hexdigest(),
             "active key public key hash does not match its bytes")
    _require(public_key != root_public_key,
             "active key may not reuse the trust-root key for self-attestation")
    return public_key


def _identity_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(IDENTITY_FIELDS) if key != "binding_sha256"}


def _validate_identity(value: Any, *, expected_role: str, current_epoch: int,
                       active_key_id: str, parent_required: bool) -> dict[str, Any]:
    _require_keys(value, IDENTITY_FIELDS, f"{expected_role} identity")
    for field in ("principal_id", "host_id", "runtime_id", "issuer_key_id"):
        _validate_identifier(value[field], f"{expected_role} identity {field}")
    _require(value["role"] == expected_role, f"{expected_role} identity role is malformed")
    _validate_sha256(value["host_identity_sha256"], f"{expected_role} host identity")
    _validate_sha256(value["runtime_identity_sha256"], f"{expected_role} runtime identity")
    _require(value["epoch"] == current_epoch, f"{expected_role} identity epoch is outside the active epoch")
    _require(value["revoked"] is False, f"{expected_role} identity is revoked")
    _require(value["synthetic_only"] is True and value["source"] == "synthetic_fixture",
             f"{expected_role} identity is not synthetic-only")
    _require(value["issuer_key_id"] == active_key_id,
             f"{expected_role} identity issuer does not bind to the active key")
    if parent_required:
        _validate_sha256(value["parent_binding_sha256"], f"{expected_role} parent binding")
    else:
        _require(value["parent_binding_sha256"] is None,
                 f"{expected_role} identity may not invent a parent binding")
    _validate_sha256(value["binding_sha256"], f"{expected_role} binding")
    _require(value["binding_sha256"] == _sha256_json(_identity_payload(value),
                                                     f"{expected_role} identity payload"),
             f"{expected_role} identity binding hash does not match its fields")
    return value


def _validate_identities(value: Any, *, current_epoch: int, active_key_id: str) -> dict[str, dict[str, Any]]:
    _require_keys(value, frozenset({"authority", "worker", "runtime"}), "identity roles")
    authority = _validate_identity(value["authority"], expected_role="authority_issuer",
                                   current_epoch=current_epoch, active_key_id=active_key_id,
                                   parent_required=False)
    worker = _validate_identity(value["worker"], expected_role="worker",
                                current_epoch=current_epoch, active_key_id=active_key_id,
                                parent_required=True)
    runtime = _validate_identity(value["runtime"], expected_role="runtime",
                                 current_epoch=current_epoch, active_key_id=active_key_id,
                                 parent_required=True)
    _require(authority["principal_id"] != active_key_id,
             "authority principal must be distinct from the active signing key")
    _require(worker["parent_binding_sha256"] == authority["binding_sha256"],
             "worker parent binding does not bind to the authority identity")
    _require(runtime["parent_binding_sha256"] == worker["binding_sha256"],
             "runtime parent binding does not bind to the worker identity")
    _require(worker["runtime_id"] == runtime["principal_id"] == runtime["runtime_id"],
             "worker runtime_id does not bind to the runtime principal")
    _require(worker["host_id"] == runtime["host_id"]
             and worker["host_identity_sha256"] == runtime["host_identity_sha256"],
             "worker and runtime host identities are not bound")
    _require(worker["runtime_identity_sha256"] == runtime["runtime_identity_sha256"],
             "worker and runtime code identities are not bound")
    return {"authority": authority, "worker": worker, "runtime": runtime}


def _expected_bindings(root: dict[str, Any], active_key: dict[str, Any],
                       identities: dict[str, dict[str, Any]], current_epoch: int) -> dict[str, str]:
    authority = identities["authority"]
    worker = identities["worker"]
    runtime = identities["runtime"]
    return {
        "root_active_key_sha256": _sha256_json({
            "root_id": root["root_id"],
            "active_key_id": active_key["key_id"],
            "epoch": current_epoch,
        }, "root-active-key binding"),
        "authority_worker_sha256": _sha256_json({
            "authority_binding_sha256": authority["binding_sha256"],
            "worker_binding_sha256": worker["binding_sha256"],
        }, "authority-worker binding"),
        "worker_runtime_sha256": _sha256_json({
            "worker_binding_sha256": worker["binding_sha256"],
            "runtime_binding_sha256": runtime["binding_sha256"],
        }, "worker-runtime binding"),
        "host_runtime_sha256": _sha256_json({
            "worker_host_id": worker["host_id"],
            "worker_host_identity_sha256": worker["host_identity_sha256"],
            "runtime_host_id": runtime["host_id"],
            "runtime_host_identity_sha256": runtime["host_identity_sha256"],
            "worker_runtime_id": worker["runtime_id"],
            "runtime_runtime_id": runtime["runtime_id"],
        }, "host-runtime binding"),
    }


def _validate_bindings(value: Any, *, root: dict[str, Any], active_key: dict[str, Any],
                       identities: dict[str, dict[str, Any]], current_epoch: int) -> None:
    _require_keys(value, BINDING_FIELDS, "identity bindings")
    for field in BINDING_FIELDS:
        _validate_sha256(value[field], f"identity binding {field}")
    _require(value == _expected_bindings(root, active_key, identities, current_epoch),
             "identity binding digest set differs from its role and key records")


def _root_signing_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": ROOT_ASSERTION_SCHEMA,
        "scope_id": bundle["scope_id"],
        "trust_root": bundle["trust_root"],
        "active_key": bundle["active_key"],
        "constraints": bundle["constraints"],
    }


def root_signing_message(bundle: dict[str, Any]) -> bytes:
    """Return the exact root assertion bytes for synthetic test fixtures."""
    return ROOT_DOMAIN.encode("ascii") + b"\n" + _canonical_json_bytes(
        _root_signing_payload(bundle), "root assertion")


def _identity_signing_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    root = bundle["trust_root"]
    active = bundle["active_key"]
    return {
        "schema": IDENTITY_ASSERTION_SCHEMA,
        "scope_id": bundle["scope_id"],
        "trust_root_ref": {
            "root_id": root["root_id"],
            "public_key_sha256": root["public_key_sha256"],
        },
        "active_key_ref": {
            "key_id": active["key_id"],
            "public_key_sha256": active["public_key_sha256"],
            "epoch": active["epoch"],
            "role": active["role"],
        },
        "identities": bundle["identities"],
        "bindings": bundle["bindings"],
        "constraints": bundle["constraints"],
    }


def identity_signing_message(bundle: dict[str, Any]) -> bytes:
    """Return the exact active-key assertion bytes for synthetic test fixtures."""
    return IDENTITY_DOMAIN.encode("ascii") + b"\n" + _canonical_json_bytes(
        _identity_signing_payload(bundle), "identity assertion")


def _verify_signature(public_key_bytes: bytes, signature: bytes, message: bytes, label: str) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature, message)
    except (InvalidSignature, TypeError, ValueError) as error:
        raise TrustedIdentityContractError(f"{label} signature is invalid") from error


def verify_synthetic_identity_bundle(
    bundle_raw: bytes,
    *,
    trust_root_public_key_bytes: bytes,
) -> dict[str, Any]:
    """Verify one in-memory synthetic chain without minting any capability.

    The explicit root argument is an anchor for this diagnostic verification,
    not a production registry.  A valid result proves only that the supplied
    synthetic bytes form a self-consistent root-authorized identity chain.
    """
    _require(type(trust_root_public_key_bytes) is bytes
             and len(trust_root_public_key_bytes) == 32,
             "trust_root_public_key_bytes must be explicitly supplied as exactly 32 raw bytes")
    bundle = _parse_bundle(bundle_raw)
    current_epoch = _validate_constraints(bundle["constraints"])
    root_public_key = _validate_trust_root(
        bundle["trust_root"],
        current_epoch=current_epoch,
        explicit_root_public_key=trust_root_public_key_bytes,
    )
    active_public_key = _validate_active_key(
        bundle["active_key"],
        root=bundle["trust_root"],
        current_epoch=current_epoch,
        root_public_key=root_public_key,
    )
    identities = _validate_identities(
        bundle["identities"], current_epoch=current_epoch,
        active_key_id=bundle["active_key"]["key_id"],
    )
    _validate_bindings(
        bundle["bindings"], root=bundle["trust_root"],
        active_key=bundle["active_key"], identities=identities,
        current_epoch=current_epoch,
    )
    _require_keys(bundle["signatures"], SIGNATURE_FIELDS, "identity signatures")
    root_signature = _decode_signature(
        bundle["signatures"]["root_active_key_base64"],
        "root active-key signature",
    )
    active_signature = _decode_signature(
        bundle["signatures"]["active_identity_base64"],
        "active identity signature",
    )
    _verify_signature(root_public_key, root_signature, root_signing_message(bundle),
                      "trust-root active-key")
    _verify_signature(active_public_key, active_signature, identity_signing_message(bundle),
                      "active authority/worker/runtime")

    return {
        "schema": SCHEMA,
        "status": "synthetic_identity_chain_consistent_non_authorizing",
        "input_origin": "synthetic_fixture",
        "synthetic_only": True,
        "bundle_raw_bytes": len(bundle_raw),
        "bundle_raw_sha256": hashlib.sha256(bundle_raw).hexdigest(),
        "trust_root_anchor_explicit": True,
        "trust_root_signature_valid_for_explicit_anchor": True,
        "active_key_authorized_by_trust_root": True,
        "active_identity_signature_valid": True,
        "authority_worker_runtime_chain_bound": True,
        "host_identity_binding_verified": True,
        "runtime_identity_binding_verified": True,
        "epoch_constraints_satisfied": True,
        "revocation_constraints_satisfied": True,
        "algorithm_constraints_satisfied": True,
        "domain_constraints_satisfied": True,
        "default_trust_rejected": True,
        "candidate_key_self_attestation_rejected": True,
        "trust_root_id": bundle["trust_root"]["root_id"],
        "active_key_id": bundle["active_key"]["key_id"],
        "epoch": current_epoch,
        "diagnostic_only": True,
        "capability_minted": False,
        "execution_authority": False,
        "formal_admission": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "gate_mutation": 0,
        "privileged_operation_performed": False,
        "workload_started": False,
    }


def build_report() -> dict[str, Any]:
    """Return the checked-in design report without reading or writing inputs."""
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": REPORT_STATUS,
        "contract_schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "input_boundary": {
            "mode": "bounded_in_memory_raw_json",
            "synthetic_only": True,
            "input_origin": "synthetic_fixture",
            "explicit_trust_root_argument_required": True,
            "default_trust_root": False,
            "candidate_key_self_attestation": "reject",
        },
        "verified_chain": [
            "explicit_trust_root_to_active_key",
            "active_key_to_authority_worker_runtime_assertion",
            "authority_to_worker_parent_binding",
            "worker_to_runtime_parent_binding",
            "worker_and_runtime_host_identity_binding",
            "worker_and_runtime_code_identity_binding",
        ],
        "constraints": {
            "algorithm": ALGORITHM,
            "root_domain": ROOT_DOMAIN,
            "identity_domain": IDENTITY_DOMAIN,
            "epoch": "current bounded epoch; every root/key/role record must match it",
            "revocation": "root, active key, authority, worker, and runtime must all be explicitly not revoked",
        },
        "non_authorizing_boundary": {
            "diagnostic_only": True,
            "capability_minted": False,
            "execution_authority": False,
            "formal_admission": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "gate_mutation": 0,
        },
        "prohibited_operations": [
            "root_or_sudo",
            "ptrace_or_seccomp",
            "fanotify_or_kernel_probe",
            "native_or_solver",
            "worker_gpu_or_queue",
        ],
        "integration_boundary": {
            "supervisor_session_claims": "not replaced; candidate-key consistency remains non-trusted",
            "attempt_ledger_and_attestation": "not consumed or mutated",
            "execution_readiness_v8": "not rewritten or promoted",
            "syscall_policy_contract": "not rewritten or executed",
            "registry_ledger_gate": "not read for mutation and never written",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-report", action="store_true",
                        help="print the deterministic synthetic-only design report")
    args = parser.parse_args()
    if args.print_report:
        print(json.dumps(build_report(), indent=2, sort_keys=True, allow_nan=False))
    else:
        print(json.dumps({
            "schema": SCHEMA,
            "status": STATUS,
            "synthetic_only": True,
            "diagnostic_only": True,
            "capability_minted": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALGORITHM", "BINDING_FIELDS", "IDENTITY_DOMAIN", "IDENTITY_FIELDS",
    "IDENTITY_ASSERTION_SCHEMA", "MAX_BUNDLE_BYTES", "REPORT_SCHEMA", "ROOT_DOMAIN",
    "ROOT_ASSERTION_SCHEMA", "SCHEMA", "STATUS", "SCOPE_ID",
    "TrustedIdentityContractError", "build_report", "identity_signing_message",
    "root_signing_message", "verify_synthetic_identity_bundle",
]

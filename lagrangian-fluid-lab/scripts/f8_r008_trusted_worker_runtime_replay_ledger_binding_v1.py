"""Verify a synthetic, non-authorizing single-use replay-ledger transition.

UPDATE-308 already verifies the identity chain and the signed worker/runtime
handoff.  This additive sidecar deliberately delegates those checks to that
contract and adds only the missing replay-consumption boundary: two bounded,
canonical, explicitly anchored ledger witnesses must bind the exact handoff
digest, scope, attempt, case, nonce, issuer, subject and epoch window.  The
transition must be exactly ``consumed=false, generation=n`` to
``consumed=true, generation=n+1``.

The verifier is pure and synthetic-only.  It never reads or mutates a real
ledger, registry or gate, and a successful transition remains diagnostic-only.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f8_r008_trusted_worker_runtime_handoff_v1 as handoff_contract
from scripts.core_strict_json import strict_json_object


SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_replay_ledger_binding_contract.v1"
REPORT_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_replay_ledger_binding_report.v1"
RECORD_ID = "f8-r008-trusted-worker-runtime-replay-ledger-binding-v1"
REPORT_RECORD_ID = "f8-r008-trusted-worker-runtime-replay-ledger-binding-report-v1"
STATUS = "synthetic_only_replay_consumption_transition_verified"
REPORT_STATUS = "synthetic_only_non_authorizing_replay_ledger_contract_design"
SCOPE_ID = handoff_contract.SCOPE_ID
WITNESS_DOMAIN = "CORE-F8-R008-TRUSTED-WORKER-RUNTIME-REPLAY-LEDGER-WITNESS-V1"
CONSUMPTION_DOMAIN = "CORE-F8-R008-TRUSTED-WORKER-RUNTIME-REPLAY-CONSUMPTION-V1"
ALGORITHM = "ed25519"
MAX_WITNESS_BYTES = 128 * 1024
MAX_EPOCH = (1 << 63) - 1
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
NONCE_RE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)
SYNTHETIC_IDENTIFIER_RE = re.compile(r"synthetic-[a-z0-9][a-z0-9._-]{0,62}\Z", re.ASCII)

WITNESS_FIELDS = frozenset({
    "schema", "record_id", "status", "synthetic_only", "input_origin",
    "scope_id", "handoff_binding", "ledger", "issuer", "constraints",
    "signature",
})
HANDOFF_BINDING_FIELDS = frozenset({
    "handoff_sha256", "scope_id", "attempt_id", "case_id", "nonce_hex",
    "issued_epoch", "expires_epoch", "handoff_issuer", "handoff_subject",
})
HANDOFF_ISSUER_FIELDS = frozenset({
    "active_key_id", "authority_binding_sha256",
})
HANDOFF_SUBJECT_FIELDS = frozenset({
    "worker_principal_id", "worker_binding_sha256", "runtime_principal_id",
    "runtime_binding_sha256",
})
LEDGER_FIELDS = frozenset({
    "ledger_id", "entry_id", "generation", "consumed",
    "consumption_id_sha256", "consumed_epoch",
})
ISSUER_FIELDS = frozenset({
    "ledger_principal_id", "key_id", "key_sha256", "role", "source",
})
CONSTRAINT_FIELDS = frozenset({
    "algorithm", "default_trust", "witness_anchor", "transition",
    "production_ledger", "mutation",
})
SIGNATURE_FIELDS = frozenset({"algorithm", "signature_base64"})


class TrustedReplayLedgerBindingError(ValueError):
    """The synthetic replay witness or transition fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TrustedReplayLedgerBindingError(message)


def _canonical(value: Any, label: str = "value") -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise TrustedReplayLedgerBindingError(
            f"{label} is not canonical-JSON serializable"
        ) from error


def _digest(value: Any, label: str) -> None:
    _require(type(value) is str and SHA256_RE.fullmatch(value) is not None,
             f"{label} is not lowercase SHA-256")


def _identifier(value: Any, label: str, *, synthetic: bool = False) -> None:
    pattern = SYNTHETIC_IDENTIFIER_RE if synthetic else IDENTIFIER_RE
    _require(type(value) is str and pattern.fullmatch(value) is not None,
             f"{label} is malformed")


def _decode_base64(value: Any, *, size: int, label: str) -> bytes:
    _require(type(value) is str, f"{label} must be strict Base64 text")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        raise TrustedReplayLedgerBindingError(f"{label} is not strict Base64") from error
    _require(len(decoded) == size and base64.b64encode(decoded).decode("ascii") == value,
             f"{label} is not canonical {size}-byte Base64")
    return decoded


def _require_keys(value: Any, expected: frozenset[str], label: str) -> None:
    _require(type(value) is dict and set(value) == expected,
             f"{label} fields are not exact")


def _parse_canonical(raw: bytes, *, label: str) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_WITNESS_BYTES,
             f"{label} bytes are outside the fixed size bound")
    try:
        value = strict_json_object(raw, label=label, max_bytes=MAX_WITNESS_BYTES)
    except ValueError as error:
        raise TrustedReplayLedgerBindingError(str(error)) from error
    _require(_canonical(value, label) == raw, f"{label} bytes are not exact canonical JSON")
    return value


def _parse_handoff(handoff_raw: bytes) -> dict[str, Any]:
    _require(type(handoff_raw) is bytes and 0 < len(handoff_raw) <= handoff_contract.MAX_HANDOFF_BYTES,
             "handoff bytes are outside the handoff contract size bound")
    try:
        value = strict_json_object(
            handoff_raw, label="F8 R008 synthetic worker/runtime handoff",
            max_bytes=handoff_contract.MAX_HANDOFF_BYTES,
        )
    except ValueError as error:
        raise TrustedReplayLedgerBindingError(str(error)) from error
    _require(_canonical(value, "worker/runtime handoff") == handoff_raw,
             "worker/runtime handoff bytes are not exact canonical JSON")
    return value


def derive_handoff_binding(handoff_raw: bytes) -> dict[str, Any]:
    """Project only the replay identity fields from a verified handoff.

    Callers must run ``verify_synthetic_worker_runtime_handoff`` first.  This
    helper intentionally does not repeat identity, authority, subject or
    handoff validation; it only creates the exact digest/projection that a
    trusted replay witness must sign.
    """
    handoff = _parse_handoff(handoff_raw)
    attempt = handoff["attempt"]
    issuer = handoff["issuer"]
    subject = handoff["subject"]
    return {
        "handoff_sha256": hashlib.sha256(handoff_raw).hexdigest(),
        "scope_id": handoff["scope_id"],
        "attempt_id": attempt["attempt_id"],
        "case_id": attempt["case_id"],
        "nonce_hex": attempt["nonce_hex"],
        "issued_epoch": attempt["issued_epoch"],
        "expires_epoch": attempt["expires_epoch"],
        "handoff_issuer": {
            "active_key_id": issuer["active_key_id"],
            "authority_binding_sha256": issuer["authority_binding_sha256"],
        },
        "handoff_subject": {
            "worker_principal_id": subject["worker_principal_id"],
            "worker_binding_sha256": subject["worker_binding_sha256"],
            "runtime_principal_id": subject["runtime_principal_id"],
            "runtime_binding_sha256": subject["runtime_binding_sha256"],
        },
    }


def consumption_id_sha256(
    handoff_binding: dict[str, Any], *, ledger_id: str, entry_id: str,
    pre_generation: int, post_generation: int, consumed_epoch: int,
) -> str:
    """Derive the exact single-use transition identifier from canonical fields."""
    return hashlib.sha256(_canonical({
        "domain": CONSUMPTION_DOMAIN,
        "handoff_binding": handoff_binding,
        "ledger_id": ledger_id,
        "entry_id": entry_id,
        "pre_generation": pre_generation,
        "post_generation": post_generation,
        "consumed_epoch": consumed_epoch,
    }, "replay consumption binding")).hexdigest()


def witness_signing_message(value: dict[str, Any]) -> bytes:
    """Return the exact trusted-ledger witness signing message."""
    _require_keys(value, WITNESS_FIELDS, "replay ledger witness")
    payload = {key: value[key] for key in sorted(WITNESS_FIELDS) if key != "signature"}
    return WITNESS_DOMAIN.encode("ascii") + b"\n" + _canonical(
        payload, "replay ledger witness signing payload",
    )


def _validate_handoff_binding_shape(binding: Any) -> None:
    _require_keys(binding, HANDOFF_BINDING_FIELDS, "handoff replay binding")
    _digest(binding["handoff_sha256"], "handoff replay binding handoff_sha256")
    _require(binding["scope_id"] == SCOPE_ID,
             "handoff replay binding scope differs from F8 R008")
    for field in ("attempt_id", "case_id"):
        _identifier(binding[field], f"handoff replay binding {field}", synthetic=True)
    _require(type(binding["nonce_hex"]) is str
             and NONCE_RE.fullmatch(binding["nonce_hex"]) is not None,
             "handoff replay binding nonce is not lowercase 128-bit hex")
    for field in ("issued_epoch", "expires_epoch"):
        _require(type(binding[field]) is int and not isinstance(binding[field], bool)
                 and 0 <= binding[field] <= MAX_EPOCH,
                 f"handoff replay binding {field} is outside the bounded epoch domain")
    _require(binding["expires_epoch"] > binding["issued_epoch"],
             "handoff replay binding epoch window is reversed")

    _require_keys(binding["handoff_issuer"], HANDOFF_ISSUER_FIELDS,
                  "handoff replay binding issuer")
    _identifier(binding["handoff_issuer"]["active_key_id"],
                "handoff replay binding issuer active_key_id")
    _digest(binding["handoff_issuer"]["authority_binding_sha256"],
            "handoff replay binding issuer authority_binding_sha256")

    _require_keys(binding["handoff_subject"], HANDOFF_SUBJECT_FIELDS,
                  "handoff replay binding subject")
    _identifier(binding["handoff_subject"]["worker_principal_id"],
                "handoff replay binding worker principal")
    _identifier(binding["handoff_subject"]["runtime_principal_id"],
                "handoff replay binding runtime principal")
    for field in ("worker_binding_sha256", "runtime_binding_sha256"):
        _digest(binding["handoff_subject"][field],
                f"handoff replay binding subject {field}")


def _validate_witness_shape(value: dict[str, Any]) -> None:
    _require_keys(value, WITNESS_FIELDS, "replay ledger witness")
    _require(value["schema"] == SCHEMA, "replay ledger witness schema is unsupported")
    _require(value["record_id"] == RECORD_ID,
             "replay ledger witness record_id is unsupported")
    _require(value["status"] == "synthetic_only_trusted_replay_ledger_witness",
             "replay ledger witness status is unsupported")
    _require(value["synthetic_only"] is True,
             "replay ledger witness must be synthetic-only")
    _require(value["input_origin"] == "synthetic_fixture",
             "replay ledger witness input origin must be synthetic_fixture")
    _require(value["scope_id"] == SCOPE_ID,
             "replay ledger witness scope differs from F8 R008")
    _validate_handoff_binding_shape(value["handoff_binding"])

    _require_keys(value["ledger"], LEDGER_FIELDS, "replay ledger state")
    for field in ("ledger_id", "entry_id"):
        _identifier(value["ledger"][field], f"replay ledger state {field}", synthetic=True)
    generation = value["ledger"]["generation"]
    _require(type(generation) is int and not isinstance(generation, bool)
             and 0 <= generation <= MAX_EPOCH,
             "replay ledger generation is outside the bounded integer domain")
    _require(type(value["ledger"]["consumed"]) is bool,
             "replay ledger consumed state must be boolean")
    if value["ledger"]["consumed"]:
        _digest(value["ledger"]["consumption_id_sha256"],
                "replay ledger consumption_id_sha256")
        consumed_epoch = value["ledger"]["consumed_epoch"]
        _require(type(consumed_epoch) is int and not isinstance(consumed_epoch, bool)
                 and 0 <= consumed_epoch <= MAX_EPOCH,
                 "replay ledger consumed_epoch is outside the bounded integer domain")
    else:
        _require(value["ledger"]["consumption_id_sha256"] is None,
                 "unconsumed replay ledger state may not claim a consumption id")
        _require(value["ledger"]["consumed_epoch"] is None,
                 "unconsumed replay ledger state may not claim a consumed epoch")

    _require_keys(value["issuer"], ISSUER_FIELDS, "replay ledger witness issuer")
    _identifier(value["issuer"]["ledger_principal_id"],
                "replay ledger witness ledger_principal_id")
    _identifier(value["issuer"]["key_id"], "replay ledger witness key_id")
    _digest(value["issuer"]["key_sha256"], "replay ledger witness key_sha256")
    _require(value["issuer"]["role"] == "trusted_replay_ledger",
             "replay ledger witness issuer role is unsupported")
    _require(value["issuer"]["source"] == "synthetic_fixture",
             "replay ledger witness issuer source is not synthetic_fixture")

    _require_keys(value["constraints"], CONSTRAINT_FIELDS,
                  "replay ledger witness constraints")
    _require(value["constraints"] == {
        "algorithm": ALGORITHM,
        "default_trust": "deny",
        "witness_anchor": "explicit_ledger_key_argument_only",
        "transition": "exact_single_use_consumption_generation_plus_one",
        "production_ledger": "not_authenticated",
        "mutation": "none_in_memory_witnesses_only",
    }, "replay ledger witness constraints are not fail-closed")

    _require_keys(value["signature"], SIGNATURE_FIELDS,
                  "replay ledger witness signature")
    _require(value["signature"]["algorithm"] == ALGORITHM,
             "replay ledger witness signature algorithm is unsupported")
    _decode_base64(value["signature"]["signature_base64"], size=64,
                   label="replay ledger witness signature")


def _verify_witness_signature(value: dict[str, Any], trusted_public_key: bytes) -> None:
    _require(type(trusted_public_key) is bytes and len(trusted_public_key) == 32,
             "trusted_ledger_public_key_bytes must be explicitly supplied as 32 raw bytes")
    _require(value["issuer"]["key_sha256"] == hashlib.sha256(trusted_public_key).hexdigest(),
             "replay ledger witness key digest differs from the explicit trust anchor")
    signature = _decode_base64(value["signature"]["signature_base64"], size=64,
                               label="replay ledger witness signature")
    try:
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(
            signature, witness_signing_message(value),
        )
    except (InvalidSignature, TypeError, ValueError) as error:
        raise TrustedReplayLedgerBindingError(
            "replay ledger witness signature is invalid for the explicit trust anchor"
        ) from error


def _parse_active_identity_public_key(identity_bundle_raw: bytes) -> bytes:
    """Read the already-verified active key only to reject self-claimed ledger trust."""
    try:
        bundle = strict_json_object(
            identity_bundle_raw, label="F8 R008 synthetic identity bundle",
            max_bytes=handoff_contract.identity.MAX_BUNDLE_BYTES,
        )
        active = bundle["active_key"]
        return _decode_base64(active["public_key_base64"], size=32,
                              label="identity active public key")
    except (KeyError, TypeError, ValueError) as error:
        raise TrustedReplayLedgerBindingError(
            "identity active key could not be read after handoff verification"
        ) from error


def _validate_witness_binding(value: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    _require(value["scope_id"] == expected["scope_id"],
             f"{label} scope does not bind to the handoff")
    _require(value["handoff_binding"] == expected,
             f"{label} exact handoff binding differs")


def verify_synthetic_replay_consumption(
    handoff_raw: bytes,
    *,
    identity_bundle_raw: bytes,
    trust_root_public_key_bytes: bytes,
    pre_ledger_witness_raw: bytes,
    post_ledger_witness_raw: bytes,
    trusted_ledger_public_key_bytes: bytes,
) -> dict[str, Any]:
    """Verify one exact synthetic ``unconsumed -> consumed`` ledger transition.

    The two witness snapshots are caller-provided bytes, but neither snapshot
    is trusted on its own: both must be signed by the explicitly supplied
    ledger key and bind to the already-verified handoff.  The function never
    mutates either snapshot or any external state.
    """
    _require(type(trusted_ledger_public_key_bytes) is bytes
             and len(trusted_ledger_public_key_bytes) == 32,
             "trusted_ledger_public_key_bytes must be explicitly supplied as 32 raw bytes")
    try:
        handoff_result = handoff_contract.verify_synthetic_worker_runtime_handoff(
            handoff_raw,
            identity_bundle_raw=identity_bundle_raw,
            trust_root_public_key_bytes=trust_root_public_key_bytes,
        )
    except handoff_contract.TrustedWorkerRuntimeHandoffError as error:
        raise TrustedReplayLedgerBindingError(
            f"trusted worker/runtime handoff verification failed: {error}"
        ) from error

    handoff = _parse_handoff(handoff_raw)
    expected_binding = derive_handoff_binding(handoff_raw)
    active_identity_public_key = _parse_active_identity_public_key(identity_bundle_raw)
    _require(trusted_ledger_public_key_bytes != active_identity_public_key,
             "ledger witness trust anchor may not reuse the handoff active identity key")

    pre = _parse_canonical(pre_ledger_witness_raw,
                           label="synthetic pre-consumption replay ledger witness")
    post = _parse_canonical(post_ledger_witness_raw,
                            label="synthetic post-consumption replay ledger witness")
    _validate_witness_shape(pre)
    _validate_witness_shape(post)
    _verify_witness_signature(pre, trusted_ledger_public_key_bytes)
    _verify_witness_signature(post, trusted_ledger_public_key_bytes)

    _validate_witness_binding(pre, expected_binding, "pre-consumption witness")
    _validate_witness_binding(post, expected_binding, "post-consumption witness")
    _require(pre["issuer"] == post["issuer"],
             "replay ledger witness issuer changed across the transition")
    _require(pre["ledger"]["ledger_id"] == post["ledger"]["ledger_id"]
             and pre["ledger"]["entry_id"] == post["ledger"]["entry_id"],
             "replay ledger witness ledger/entry identity changed across the transition")

    handoff_issuer = expected_binding["handoff_issuer"]["active_key_id"]
    subject_ids = {
        expected_binding["handoff_subject"]["worker_principal_id"],
        expected_binding["handoff_subject"]["runtime_principal_id"],
    }
    _require(pre["issuer"]["ledger_principal_id"] not in {handoff_issuer, *subject_ids}
             and pre["issuer"]["key_id"] != handoff_issuer,
             "replay ledger witness issuer may not self-claim the handoff identity")

    pre_state = pre["ledger"]
    post_state = post["ledger"]
    _require(pre_state["consumed"] is False,
             "replay rejected: pre-consumption ledger state is already consumed")
    _require(post_state["consumed"] is True,
             "post-consumption ledger witness must mark the entry consumed")
    _require(post_state["generation"] == pre_state["generation"] + 1,
             "replay ledger generation must advance exactly one without rollback")
    consumed_epoch = post_state["consumed_epoch"]
    _require(expected_binding["issued_epoch"] <= consumed_epoch <= expected_binding["expires_epoch"],
             "replay ledger consumed_epoch is outside the handoff lifetime")
    expected_consumption_id = consumption_id_sha256(
        expected_binding,
        ledger_id=pre_state["ledger_id"],
        entry_id=pre_state["entry_id"],
        pre_generation=pre_state["generation"],
        post_generation=post_state["generation"],
        consumed_epoch=consumed_epoch,
    )
    _require(post_state["consumption_id_sha256"] == expected_consumption_id,
             "replay ledger consumption id is not bound to the exact transition")

    return {
        "schema": SCHEMA,
        "status": STATUS,
        "record_id": RECORD_ID,
        "scope_id": SCOPE_ID,
        "input_origin": "synthetic_fixture",
        "synthetic_only": True,
        "handoff_digest_bound": True,
        "handoff_identity_projection_bound": True,
        "attempt_case_nonce_bound": True,
        "issuer_subject_bound": True,
        "bounded_epoch_window_bound": True,
        "trusted_ledger_witness_verified": True,
        "single_use_consumption_transition_verified": True,
        "pre_generation": pre_state["generation"],
        "post_generation": post_state["generation"],
        "generation_delta": 1,
        "pre_consumed": False,
        "post_consumed": True,
        "replay_rejected_by_consumed_state": True,
        "handoff_dependency_status": handoff_result["status"],
        "production_ledger_authenticated": False,
        "real_ledger_read": False,
        "real_ledger_mutation": 0,
        "diagnostic_only": True,
        "capability_minted": False,
        "execution_authority": False,
        "formal_admission": False,
        "readiness_pass": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "qualification_credit": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "production_bundle_read": False,
        "kernel_or_solver_access": False,
        "worker_gpu_queue_access": False,
    }


def build_report() -> dict[str, Any]:
    """Return the deterministic synthetic-only diagnostic contract report."""
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": REPORT_STATUS,
        "contract_schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "input_boundary": {
            "mode": "bounded_in_memory_canonical_json",
            "synthetic_only": True,
            "input_origin": "synthetic_fixture",
            "handoff_contract_reused": True,
            "production_paths_read": False,
            "real_ledger_read": False,
        },
        "exact_bindings": [
            "canonical_handoff_raw_sha256",
            "scope_attempt_case_nonce_projection",
            "issued_and_expiry_epoch_projection",
            "handoff_issuer_active_key_and_authority_binding",
            "handoff_worker_and_runtime_subject_bindings",
            "trusted_ledger_issuer_and_explicit_public_key",
            "ledger_id_entry_id_generation_and_consumed_state",
            "single_use_consumption_id_over_the_exact_transition",
        ],
        "trusted_witness_contract": {
            "algorithm": ALGORITHM,
            "domain": WITNESS_DOMAIN,
            "anchor": "explicit_ledger_key_argument_only",
            "default_trust": "deny",
            "precondition": "consumed=false",
            "postcondition": "consumed=true",
            "generation_rule": "post_generation=pre_generation+1",
            "caller_self_claim": "reject_handoff_identity_reuse_and_missing_anchor",
        },
        "rejection_rules": [
            "reject a replayed consumed pre-state",
            "reject cross-scope/case/nonce or handoff-digest rebinding",
            "reject issuer/subject rebinding",
            "reject generation rollback, skip, or non-advancing transition",
            "reject consumed epochs outside the bounded issued/expiry window",
            "reject caller self-claimed or missing trusted ledger witness",
        ],
        "non_authorizing_boundary": {
            "diagnostic_only": True,
            "capability_minted": False,
            "execution_authority": False,
            "formal_admission": False,
            "readiness_pass": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "qualification_credit": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "real_ledger_mutation": 0,
        },
        "integration_boundary": {
            "trusted_worker_runtime_handoff": "delegated; identity and handoff fields are not reimplemented",
            "trusted_identity_authority_worker_runtime": "not replaced",
            "production_registry_and_ledger": "not read or modified",
            "15_case_matrix_and_attempt_attestation": "not consumed or credited",
            "production_bundle_kernel_solver_worker_gpu_queue": "never accessed",
        },
        "prohibited_operations": [
            "production_bundle_read",
            "production_ledger_read_or_write",
            "registry_or_gate_mutation",
            "root_or_sudo",
            "kernel_or_solver_access",
            "worker_gpu_or_queue",
        ],
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
            "execution_authority": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALGORITHM", "CONSUMPTION_DOMAIN", "CONSTRAINT_FIELDS", "HANDOFF_BINDING_FIELDS",
    "MAX_WITNESS_BYTES", "REPORT_SCHEMA", "SCHEMA", "SCOPE_ID", "STATUS",
    "TrustedReplayLedgerBindingError", "build_report", "consumption_id_sha256",
    "derive_handoff_binding", "verify_synthetic_replay_consumption",
    "witness_signing_message",
]

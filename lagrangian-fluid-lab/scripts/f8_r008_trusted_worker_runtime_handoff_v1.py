"""Validate a synthetic, attempt-scoped F8/R008 worker/runtime handoff.

The trusted-identity contract proves only a root-authorized authority -> worker
-> runtime identity chain.  This additive contract binds that already-verified
chain to one synthetic attempt: its scope, nonce and bounded lifetime, the
declared worker/runtime code claims, immutable input hashes, and an output
manifest plan.  It deliberately does not authenticate a production process,
observe a launch, consume a replay ledger, or inspect any path-backed artifact.

All inputs are bounded canonical JSON bytes.  A successful result is still a
diagnostic structural check and never mints execution/readiness capability.
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

from scripts import f8_r008_trusted_authority_worker_runtime_identity_v1 as identity
from scripts.core_strict_json import strict_json_object


SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_handoff_contract.v1"
REPORT_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_handoff_report.v1"
RECORD_ID = "f8-r008-trusted-worker-runtime-handoff-v1"
REPORT_RECORD_ID = "f8-r008-trusted-worker-runtime-handoff-report-v1"
STATUS = "synthetic_only_attempt_handoff_structurally_consistent"
REPORT_STATUS = "synthetic_only_non_authorizing_handoff_contract_design"
SCOPE_ID = identity.SCOPE_ID
HANDOFF_DOMAIN = "CORE-F8-R008-TRUSTED-WORKER-RUNTIME-HANDOFF-V1"
ALGORITHM = "ed25519"
MAX_HANDOFF_BYTES = 128 * 1024
MAX_REQUIRED_ARTIFACTS = 16
MAX_EPOCH_DELTA = 255
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
NONCE_RE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)
SYNTHETIC_IDENTIFIER_RE = re.compile(r"synthetic-[a-z0-9][a-z0-9._-]{0,62}\Z", re.ASCII)
ARTIFACT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)

HANDOFF_FIELDS = frozenset({
    "schema", "record_id", "status", "synthetic_only", "input_origin",
    "scope_id", "handoff_id", "issuer", "subject", "attempt", "execution",
    "inputs", "outputs", "constraints", "signature",
})
ISSUER_FIELDS = frozenset({
    "active_key_id", "active_key_sha256", "identity_bundle_sha256",
    "authority_binding_sha256",
})
SUBJECT_FIELDS = frozenset({
    "worker_principal_id", "worker_binding_sha256", "runtime_principal_id",
    "runtime_binding_sha256", "runtime_code_sha256", "host_id",
    "host_identity_sha256",
})
ATTEMPT_FIELDS = frozenset({
    "attempt_id", "case_id", "nonce_hex", "request_sha256", "issued_epoch",
    "expires_epoch", "single_use",
})
EXECUTION_FIELDS = frozenset({
    "worker_code_sha256", "runtime_code_sha256", "source_manifest_sha256",
    "runtime_manifest_sha256", "process_generation_id", "launch_mode",
    "retry_policy",
})
INPUT_FIELDS = frozenset({
    "definition_sha256", "control_sha256", "initial_state_sha256",
    "configuration_sha256",
})
OUTPUT_FIELDS = frozenset({
    "output_manifest_sha256", "output_schema", "required_artifacts",
})
CONSTRAINT_FIELDS = frozenset({
    "algorithm", "domain", "default_trust", "production_identity", "replay",
    "runtime",
})
SIGNATURE_FIELDS = frozenset({"algorithm", "signature_base64"})


class TrustedWorkerRuntimeHandoffError(ValueError):
    """The synthetic handoff is malformed or fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TrustedWorkerRuntimeHandoffError(message)


def _canonical(value: Any, label: str = "value") -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise TrustedWorkerRuntimeHandoffError(
            f"{label} is not canonical-JSON serializable"
        ) from error


def _sha256_json(value: Any, label: str) -> str:
    return hashlib.sha256(_canonical(value, label)).hexdigest()


def _require_keys(value: Any, expected: frozenset[str], label: str) -> None:
    _require(type(value) is dict and set(value) == expected,
             f"{label} fields are not exact")


def _sha256(value: Any, label: str) -> None:
    _require(type(value) is str and SHA256_RE.fullmatch(value) is not None,
             f"{label} is not lowercase SHA-256")


def _identifier(value: Any, label: str, *, synthetic: bool = False) -> None:
    pattern = SYNTHETIC_IDENTIFIER_RE if synthetic else IDENTIFIER_RE
    _require(type(value) is str and pattern.fullmatch(value) is not None,
             f"{label} is malformed")
    _require(value not in {"anonymous", "candidate", "default", "self"},
             f"{label} may not use a default/self identity")


def _decode_base64(value: Any, *, size: int, label: str) -> bytes:
    _require(type(value) is str, f"{label} must be strict Base64 text")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        raise TrustedWorkerRuntimeHandoffError(f"{label} is not strict Base64") from error
    _require(len(decoded) == size and base64.b64encode(decoded).decode("ascii") == value,
             f"{label} is not canonical {size}-byte Base64")
    return decoded


def _parse_identity(identity_raw: bytes) -> dict[str, Any]:
    _require(type(identity_raw) is bytes and 0 < len(identity_raw) <= identity.MAX_BUNDLE_BYTES,
             "identity bundle bytes are outside the fixed size bound")
    try:
        value = strict_json_object(
            identity_raw, label="F8 R008 synthetic identity bundle",
            max_bytes=identity.MAX_BUNDLE_BYTES,
        )
    except ValueError as error:
        raise TrustedWorkerRuntimeHandoffError(str(error)) from error
    _require(_canonical(value, "identity bundle") == identity_raw,
             "identity bundle bytes are not canonical JSON")
    return value


def _signing_payload(value: dict[str, Any]) -> dict[str, Any]:
    _require_keys(value, HANDOFF_FIELDS, "worker/runtime handoff")
    return {key: value[key] for key in sorted(HANDOFF_FIELDS) if key != "signature"}


def handoff_signing_message(value: dict[str, Any]) -> bytes:
    """Return the exact active-key message for a synthetic handoff fixture."""
    return HANDOFF_DOMAIN.encode("ascii") + b"\n" + _canonical(
        _signing_payload(value), "worker/runtime handoff signing payload",
    )


def _validate_handoff_shape(value: dict[str, Any]) -> None:
    _require_keys(value, HANDOFF_FIELDS, "worker/runtime handoff")
    _require(value["schema"] == SCHEMA, "handoff schema is unsupported")
    _require(value["record_id"] == RECORD_ID, "handoff record_id is unsupported")
    _require(value["status"] == STATUS, "handoff status is not the fixed diagnostic status")
    _require(value["synthetic_only"] is True, "handoff must be synthetic-only")
    _require(value["input_origin"] == "synthetic_fixture",
             "handoff input origin must be synthetic_fixture")
    _require(value["scope_id"] == SCOPE_ID, "handoff scope differs from F8 R008")
    _identifier(value["handoff_id"], "handoff_id", synthetic=True)

    _require_keys(value["issuer"], ISSUER_FIELDS, "handoff issuer")
    _identifier(value["issuer"]["active_key_id"], "issuer.active_key_id")
    _sha256(value["issuer"]["active_key_sha256"], "issuer.active_key_sha256")
    _sha256(value["issuer"]["identity_bundle_sha256"], "issuer.identity_bundle_sha256")
    _sha256(value["issuer"]["authority_binding_sha256"], "issuer.authority_binding_sha256")

    _require_keys(value["subject"], SUBJECT_FIELDS, "handoff subject")
    for field in ("worker_principal_id", "runtime_principal_id", "host_id"):
        _identifier(value["subject"][field], f"subject.{field}")
    for field in (
        "worker_binding_sha256", "runtime_binding_sha256", "runtime_code_sha256",
        "host_identity_sha256",
    ):
        _sha256(value["subject"][field], f"subject.{field}")

    _require_keys(value["attempt"], ATTEMPT_FIELDS, "handoff attempt")
    for field in ("attempt_id", "case_id"):
        _identifier(value["attempt"][field], f"attempt.{field}", synthetic=True)
    _require(type(value["attempt"]["nonce_hex"]) is str
             and NONCE_RE.fullmatch(value["attempt"]["nonce_hex"]) is not None,
             "attempt.nonce_hex is not lowercase 128-bit hex")
    _sha256(value["attempt"]["request_sha256"], "attempt.request_sha256")
    for field in ("issued_epoch", "expires_epoch"):
        _require(type(value["attempt"][field]) is int and not isinstance(value["attempt"][field], bool)
                 and 0 <= value["attempt"][field] <= (1 << 63) - 1,
                 f"attempt.{field} is outside the bounded epoch domain")
    _require(value["attempt"]["expires_epoch"] > value["attempt"]["issued_epoch"]
             and value["attempt"]["expires_epoch"] - value["attempt"]["issued_epoch"] <= MAX_EPOCH_DELTA,
             "handoff lifetime is outside the bounded epoch window")
    _require(value["attempt"]["single_use"] is True,
             "handoff must declare single-use semantics")

    _require_keys(value["execution"], EXECUTION_FIELDS, "handoff execution")
    for field in (
        "worker_code_sha256", "runtime_code_sha256", "source_manifest_sha256",
        "runtime_manifest_sha256",
    ):
        _sha256(value["execution"][field], f"execution.{field}")
    _identifier(value["execution"]["process_generation_id"],
                "execution.process_generation_id", synthetic=True)
    _require(value["execution"]["launch_mode"] == "single_attempt_handoff",
             "handoff launch mode is unsupported")
    _require(value["execution"]["retry_policy"] == "reject_replay_and_retry",
             "handoff retry policy is not fail-closed")

    _require_keys(value["inputs"], INPUT_FIELDS, "handoff inputs")
    for field in INPUT_FIELDS:
        _sha256(value["inputs"][field], f"inputs.{field}")

    _require_keys(value["outputs"], OUTPUT_FIELDS, "handoff outputs")
    _sha256(value["outputs"]["output_manifest_sha256"], "outputs.output_manifest_sha256")
    _require(value["outputs"]["output_schema"] == "core.cfd.f8.r008.synthetic_worker_output_manifest.v1",
             "handoff output schema is unsupported")
    artifacts = value["outputs"]["required_artifacts"]
    _require(type(artifacts) is list and 1 <= len(artifacts) <= MAX_REQUIRED_ARTIFACTS,
             "handoff required_artifacts has an invalid bounded length")
    _require(all(type(item) is str and ARTIFACT_RE.fullmatch(item) is not None for item in artifacts),
             "handoff required_artifacts contains an unsafe name")
    _require(artifacts == sorted(set(artifacts)),
             "handoff required_artifacts must be sorted and duplicate-free")

    _require_keys(value["constraints"], CONSTRAINT_FIELDS, "handoff constraints")
    _require(value["constraints"] == {
        "algorithm": ALGORITHM,
        "domain": HANDOFF_DOMAIN,
        "default_trust": "deny",
        "production_identity": "not_authenticated",
        "replay": "single_use_claim_only_no_consumer",
        "runtime": "not_measured",
    }, "handoff constraints are not the fixed non-authorizing contract")

    _require_keys(value["signature"], SIGNATURE_FIELDS, "handoff signature")
    _require(value["signature"]["algorithm"] == ALGORITHM,
             "handoff signature algorithm is unsupported")
    _decode_base64(value["signature"]["signature_base64"], size=64,
                    label="handoff signature")


def _verify_active_signature(value: dict[str, Any], identity_bundle: dict[str, Any]) -> None:
    public_key = _decode_base64(
        identity_bundle["active_key"]["public_key_base64"], size=32,
        label="identity active public key",
    )
    signature = _decode_base64(
        value["signature"]["signature_base64"], size=64,
        label="handoff signature",
    )
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, handoff_signing_message(value),
        )
    except (InvalidSignature, TypeError, ValueError) as error:
        raise TrustedWorkerRuntimeHandoffError(
            "handoff signature is invalid for the identity-contract active key"
        ) from error


def verify_synthetic_worker_runtime_handoff(
    handoff_raw: bytes,
    *,
    identity_bundle_raw: bytes,
    trust_root_public_key_bytes: bytes,
) -> dict[str, Any]:
    """Verify one signed synthetic handoff without minting a capability.

    The identity contract is reused as the authority/worker/runtime chain
    verifier.  This function adds only attempt-scoped handoff binding; it does
    not replace identity, supervisor-session, ledger, reducer, or runtime
    observation logic.
    """
    _require(type(trust_root_public_key_bytes) is bytes
             and len(trust_root_public_key_bytes) == 32,
             "trust_root_public_key_bytes must be explicitly supplied as 32 raw bytes")
    _require(type(handoff_raw) is bytes and 0 < len(handoff_raw) <= MAX_HANDOFF_BYTES,
             "handoff bytes are outside the fixed size bound")
    try:
        handoff = strict_json_object(
            handoff_raw, label="F8 R008 synthetic worker/runtime handoff",
            max_bytes=MAX_HANDOFF_BYTES,
        )
    except ValueError as error:
        raise TrustedWorkerRuntimeHandoffError(str(error)) from error
    _require(_canonical(handoff, "worker/runtime handoff") == handoff_raw,
             "handoff bytes are not exact canonical JSON")
    _validate_handoff_shape(handoff)

    try:
        identity_result = identity.verify_synthetic_identity_bundle(
            identity_bundle_raw,
            trust_root_public_key_bytes=trust_root_public_key_bytes,
        )
    except identity.TrustedIdentityContractError as error:
        raise TrustedWorkerRuntimeHandoffError(
            f"identity-chain verification failed: {error}"
        ) from error
    identity_bundle = _parse_identity(identity_bundle_raw)
    active = identity_bundle["active_key"]
    identities = identity_bundle["identities"]
    worker = identities["worker"]
    runtime = identities["runtime"]
    _require(handoff["issuer"]["active_key_id"] == active["key_id"],
             "handoff issuer active key differs from the identity chain")
    _require(handoff["issuer"]["active_key_sha256"] == active["public_key_sha256"],
             "handoff issuer key digest differs from the identity chain")
    _require(handoff["issuer"]["identity_bundle_sha256"] == hashlib.sha256(identity_bundle_raw).hexdigest(),
             "handoff identity bundle digest differs from the signed identity bytes")
    _require(handoff["issuer"]["authority_binding_sha256"] == identities["authority"]["binding_sha256"],
             "handoff authority binding differs from the identity chain")

    subject = handoff["subject"]
    _require(subject["worker_principal_id"] == worker["principal_id"]
             and subject["worker_binding_sha256"] == worker["binding_sha256"],
             "handoff worker subject differs from the identity chain")
    _require(subject["runtime_principal_id"] == runtime["principal_id"]
             and subject["runtime_binding_sha256"] == runtime["binding_sha256"],
             "handoff runtime subject differs from the identity chain")
    _require(subject["runtime_code_sha256"] == runtime["runtime_identity_sha256"]
             and subject["host_id"] == worker["host_id"] == runtime["host_id"]
             and subject["host_identity_sha256"] == worker["host_identity_sha256"]
             == runtime["host_identity_sha256"],
             "handoff host/runtime subject differs from the identity chain")

    execution = handoff["execution"]
    _require(execution["worker_code_sha256"] == worker["runtime_identity_sha256"],
             "handoff worker code claim differs from the identity chain")
    _require(execution["runtime_code_sha256"] == runtime["runtime_identity_sha256"],
             "handoff runtime code claim differs from the identity chain")
    _verify_active_signature(handoff, identity_bundle)

    return {
        "schema": SCHEMA,
        "status": "synthetic_worker_runtime_handoff_consistent_non_authorizing",
        "record_id": RECORD_ID,
        "scope_id": SCOPE_ID,
        "input_origin": "synthetic_fixture",
        "synthetic_only": True,
        "handoff_raw_bytes": len(handoff_raw),
        "handoff_raw_sha256": hashlib.sha256(handoff_raw).hexdigest(),
        "identity_bundle_raw_sha256": hashlib.sha256(identity_bundle_raw).hexdigest(),
        "identity_chain_consistent": identity_result["status"]
        == "synthetic_identity_chain_consistent_non_authorizing",
        "active_key_handoff_signature_valid": True,
        "attempt_scope_bound": True,
        "bounded_lifetime_declared": True,
        "single_use_declared": True,
        "worker_source_claim_bound": True,
        "runtime_source_claim_bound": True,
        "input_contract_bound": True,
        "output_contract_bound": True,
        "replay_enforcement_verified": False,
        "production_identity_authenticated": False,
        "runtime_measured": False,
        "worker_launched": False,
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
        "privileged_operation_performed": False,
        "workload_started": False,
    }


def build_report() -> dict[str, Any]:
    """Return the checked-in deterministic non-authorizing design report."""
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
            "identity_contract_reused": True,
            "production_paths_read": False,
        },
        "handoff_bindings": [
            "explicit_identity_bundle_sha256_and_active_key_id",
            "authority_binding_to_worker_and_runtime_subject",
            "synthetic_scope_attempt_case_nonce_and_bounded_epoch_window",
            "worker_and_runtime_code_identity_claims",
            "source_and_runtime_manifest_hash_claims",
            "definition_control_initial_state_and_configuration_hashes",
            "declared_output_manifest_schema_and_artifact_names",
            "active_key_signature_over_the_exact_handoff_payload",
        ],
        "fail_closed_constraints": {
            "algorithm": ALGORITHM,
            "domain": HANDOFF_DOMAIN,
            "default_trust": "deny",
            "production_identity": "not_authenticated",
            "replay": "single_use_claim_only_no_consumer",
            "runtime": "not_measured",
        },
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
        },
        "integration_boundary": {
            "trusted_identity_contract": "reused as an input verifier; not replaced",
            "supervisor_session_claims": "not consumed or upgraded from candidate-key consistency",
            "attempt_ledger_and_attestation": "not consumed or mutated",
            "15_case_matrix": "not evaluated or credited",
            "final_fput_and_reducers": "not read, joined, or modified",
            "execution_readiness_v8": "not rewritten or promoted",
            "registry_ledger_gate": "never written",
        },
        "prohibited_operations": [
            "production_identity_authentication",
            "replay_ledger_consumption",
            "root_or_sudo",
            "ptrace_or_seccomp",
            "fanotify_or_kernel_probe",
            "native_or_solver",
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
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALGORITHM", "HANDOFF_DOMAIN", "HANDOFF_FIELDS", "MAX_HANDOFF_BYTES",
    "REPORT_SCHEMA", "SCHEMA", "STATUS", "SCOPE_ID",
    "TrustedWorkerRuntimeHandoffError", "build_report", "handoff_signing_message",
    "verify_synthetic_worker_runtime_handoff",
]

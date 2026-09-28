from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import f8_r008_trusted_worker_runtime_handoff_v1 as contract
from tests import test_f8_r008_trusted_authority_worker_runtime_identity_v1 as identity_fixtures


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _handoff() -> tuple[dict[str, Any], bytes, bytes, Any, bytes]:
    identity_bundle, identity_raw, root_public, active_key = identity_fixtures._fixture()
    identities = identity_bundle["identities"]
    worker = identities["worker"]
    runtime = identities["runtime"]
    handoff: dict[str, Any] = {
        "schema": contract.SCHEMA,
        "record_id": contract.RECORD_ID,
        "status": contract.STATUS,
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "scope_id": contract.SCOPE_ID,
        "handoff_id": "synthetic-handoff-001",
        "issuer": {
            "active_key_id": identity_bundle["active_key"]["key_id"],
            "active_key_sha256": identity_bundle["active_key"]["public_key_sha256"],
            "identity_bundle_sha256": hashlib.sha256(identity_raw).hexdigest(),
            "authority_binding_sha256": identities["authority"]["binding_sha256"],
        },
        "subject": {
            "worker_principal_id": worker["principal_id"],
            "worker_binding_sha256": worker["binding_sha256"],
            "runtime_principal_id": runtime["principal_id"],
            "runtime_binding_sha256": runtime["binding_sha256"],
            "runtime_code_sha256": runtime["runtime_identity_sha256"],
            "host_id": worker["host_id"],
            "host_identity_sha256": worker["host_identity_sha256"],
        },
        "attempt": {
            "attempt_id": "synthetic-attempt-001",
            "case_id": "synthetic-case-001",
            "nonce_hex": "0123456789abcdef0123456789abcdef",
            "request_sha256": _sha("synthetic-request-001"),
            "issued_epoch": 100,
            "expires_epoch": 120,
            "single_use": True,
        },
        "execution": {
            "worker_code_sha256": worker["runtime_identity_sha256"],
            "runtime_code_sha256": runtime["runtime_identity_sha256"],
            "source_manifest_sha256": _sha("synthetic-worker-source-manifest-001"),
            "runtime_manifest_sha256": _sha("synthetic-runtime-manifest-001"),
            "process_generation_id": "synthetic-process-generation-001",
            "launch_mode": "single_attempt_handoff",
            "retry_policy": "reject_replay_and_retry",
        },
        "inputs": {
            "definition_sha256": _sha("synthetic-definition-001"),
            "control_sha256": _sha("synthetic-control-001"),
            "initial_state_sha256": _sha("synthetic-initial-state-001"),
            "configuration_sha256": _sha("synthetic-configuration-001"),
        },
        "outputs": {
            "output_manifest_sha256": _sha("synthetic-output-manifest-001"),
            "output_schema": "core.cfd.f8.r008.synthetic_worker_output_manifest.v1",
            "required_artifacts": ["runtime-observation.json", "worker-status.json"],
        },
        "constraints": {
            "algorithm": contract.ALGORITHM,
            "domain": contract.HANDOFF_DOMAIN,
            "default_trust": "deny",
            "production_identity": "not_authenticated",
            "replay": "single_use_claim_only_no_consumer",
            "runtime": "not_measured",
        },
        "signature": {
            "algorithm": contract.ALGORITHM,
            "signature_base64": "",
        },
    }
    handoff["signature"]["signature_base64"] = base64.b64encode(
        active_key.sign(contract.handoff_signing_message(handoff))
    ).decode("ascii")
    return handoff, _canonical(handoff), root_public, active_key, identity_raw


def _verify(fixture: tuple[dict[str, Any], bytes, bytes, Any, bytes]) -> dict[str, Any]:
    _handoff_value, handoff_raw, root_public, _active_key, identity_raw = fixture
    return contract.verify_synthetic_worker_runtime_handoff(
        handoff_raw,
        identity_bundle_raw=identity_raw,
        trust_root_public_key_bytes=root_public,
    )


def _resign(value: dict[str, Any], active_key: Any) -> bytes:
    value["signature"]["signature_base64"] = base64.b64encode(
        active_key.sign(contract.handoff_signing_message(value))
    ).decode("ascii")
    return _canonical(value)


def test_valid_handoff_reuses_identity_chain_and_is_non_authorizing() -> None:
    fixture = _handoff()
    before = copy.deepcopy(fixture[0])
    result = _verify(fixture)

    assert fixture[0] == before
    assert result["status"] == "synthetic_worker_runtime_handoff_consistent_non_authorizing"
    assert result["identity_chain_consistent"] is True
    assert result["active_key_handoff_signature_valid"] is True
    assert result["attempt_scope_bound"] is True
    assert result["bounded_lifetime_declared"] is True
    assert result["single_use_declared"] is True
    assert result["worker_source_claim_bound"] is True
    assert result["runtime_source_claim_bound"] is True
    assert result["input_contract_bound"] is True
    assert result["output_contract_bound"] is True
    assert result["replay_enforcement_verified"] is False
    assert result["production_identity_authenticated"] is False
    assert result["runtime_measured"] is False
    assert result["worker_launched"] is False
    assert result["diagnostic_only"] is True
    assert result["capability_minted"] is False
    assert result["readiness_pass"] is False
    assert result["formal_eligible"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0
    assert result["registry_mutation"] == 0
    assert result["ledger_mutation"] == 0
    assert result["denominator_mutation"] == 0
    assert result["gate_mutation"] == 0


def test_explicit_trust_root_is_required_and_must_match() -> None:
    _value, handoff_raw, root_public, _active_key, identity_raw = _handoff()
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="does not match"):
        contract.verify_synthetic_worker_runtime_handoff(
            handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=bytes(32),
        )
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="32 raw bytes"):
        contract.verify_synthetic_worker_runtime_handoff(
            handoff_raw,
            identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=b"",
        )
    result = contract.verify_synthetic_worker_runtime_handoff(
        handoff_raw,
        identity_bundle_raw=identity_raw,
        trust_root_public_key_bytes=root_public,
    )
    assert result["identity_chain_consistent"] is True


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("scope_id",), "other-scope", "scope"),
        (("attempt", "single_use"), False, "single-use"),
        (("attempt", "expires_epoch"), 1000, "lifetime"),
        (("execution", "launch_mode"), "retryable", "launch mode"),
        (("constraints", "production_identity"), "authenticated", "constraints"),
        (("outputs", "output_schema"), "production-output", "output schema"),
    ],
)
def test_handoff_contract_constraints_fail_closed(
    path: tuple[str, ...], value: object, message: str,
) -> None:
    handoff, _raw, root_public, active_key, identity_raw = _handoff()
    target: Any = handoff
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    raw = _resign(handoff, active_key)
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match=message):
        contract.verify_synthetic_worker_runtime_handoff(
            raw, identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
        )


def test_handoff_cannot_rebind_identity_bundle_or_subject() -> None:
    handoff, _raw, root_public, active_key, identity_raw = _handoff()
    handoff["issuer"]["identity_bundle_sha256"] = "f" * 64
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="identity bundle digest"):
        contract.verify_synthetic_worker_runtime_handoff(
            _resign(handoff, active_key), identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
        )

    handoff, _raw, root_public, active_key, identity_raw = _handoff()
    handoff["subject"]["worker_binding_sha256"] = "e" * 64
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="worker subject"):
        contract.verify_synthetic_worker_runtime_handoff(
            _resign(handoff, active_key), identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
        )


def test_worker_and_runtime_code_claims_cannot_be_rebound() -> None:
    handoff, _raw, root_public, active_key, identity_raw = _handoff()
    handoff["execution"]["runtime_code_sha256"] = "d" * 64
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="runtime code claim"):
        contract.verify_synthetic_worker_runtime_handoff(
            _resign(handoff, active_key), identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
        )


def test_handoff_signature_must_verify_for_active_identity_key() -> None:
    handoff, _raw, root_public, active_key, identity_raw = _handoff()
    handoff["signature"]["signature_base64"] = base64.b64encode(b"x" * 64).decode("ascii")
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="signature is invalid"):
        contract.verify_synthetic_worker_runtime_handoff(
            _canonical(handoff), identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
        )

    handoff, _raw, root_public, _active_key, identity_raw = _handoff()
    other_key = identity_fixtures.Ed25519PrivateKey.generate()
    handoff["signature"]["signature_base64"] = base64.b64encode(
        other_key.sign(contract.handoff_signing_message(handoff))
    ).decode("ascii")
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="signature is invalid"):
        contract.verify_synthetic_worker_runtime_handoff(
            _canonical(handoff), identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
        )


def test_canonical_duplicate_free_json_and_synthetic_origin_are_required() -> None:
    handoff, raw, root_public, active_key, identity_raw = _handoff()
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="canonical JSON"):
        contract.verify_synthetic_worker_runtime_handoff(
            raw + b"\n", identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
        )
    handoff["input_origin"] = "production_receipt"
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="synthetic_fixture"):
        contract.verify_synthetic_worker_runtime_handoff(
            _resign(handoff, active_key), identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
        )
    duplicate = b'{"schema":"one","schema":"two"}'
    with pytest.raises(contract.TrustedWorkerRuntimeHandoffError, match="duplicate JSON object key"):
        contract.verify_synthetic_worker_runtime_handoff(
            duplicate, identity_bundle_raw=identity_raw,
            trust_root_public_key_bytes=root_public,
        )


def test_report_matches_checked_in_non_authorizing_boundary() -> None:
    report = contract.build_report()
    assert report["schema"] == contract.REPORT_SCHEMA
    assert report["input_boundary"]["synthetic_only"] is True
    assert report["input_boundary"]["identity_contract_reused"] is True
    boundary = report["non_authorizing_boundary"]
    assert boundary["diagnostic_only"] is True
    assert boundary["capability_minted"] is False
    assert boundary["readiness_pass"] is False
    assert boundary["T1_numerical"] is False
    assert boundary["qualification_credit"] == 0
    assert boundary["registry_mutation"] == 0
    assert boundary["ledger_mutation"] == 0
    assert boundary["gate_mutation"] == 0

    report_path = Path(__file__).resolve().parents[1] / (
        "reports/F8-R008-TRUSTED-WORKER-RUNTIME-HANDOFF-CONTRACT-V1.json"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == report

from __future__ import annotations

import base64
import copy
import hashlib
import json
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import f8_r008_trusted_authority_worker_runtime_identity_v1 as contract


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _public_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )


def _identity(*, principal_id: str, role: str, runtime_id: str,
              runtime_identity_sha256: str, parent_binding_sha256: str | None,
              issuer_key_id: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "principal_id": principal_id,
        "role": role,
        "host_id": "synthetic-host-001",
        "host_identity_sha256": _sha("synthetic-host-identity"),
        "runtime_id": runtime_id,
        "runtime_identity_sha256": runtime_identity_sha256,
        "epoch": 7,
        "revoked": False,
        "synthetic_only": True,
        "source": "synthetic_fixture",
        "parent_binding_sha256": parent_binding_sha256,
        "issuer_key_id": issuer_key_id,
        "binding_sha256": "",
    }
    payload = {key: value[key] for key in sorted(contract.IDENTITY_FIELDS) if key != "binding_sha256"}
    value["binding_sha256"] = _sha(payload)
    return value


def _fixture() -> tuple[dict[str, Any], bytes, bytes, Ed25519PrivateKey]:
    root_key = Ed25519PrivateKey.generate()
    active_key = Ed25519PrivateKey.generate()
    root_public = _public_bytes(root_key)
    active_public = _public_bytes(active_key)
    root_id = "synthetic-root-001"
    active_id = "synthetic-active-authority-001"
    runtime_identity = _sha("synthetic-runtime-code-001")

    authority = _identity(
        principal_id="synthetic-authority-001",
        role="authority_issuer",
        runtime_id="synthetic-authority-runtime-001",
        runtime_identity_sha256=_sha("synthetic-authority-runtime-code-001"),
        parent_binding_sha256=None,
        issuer_key_id=active_id,
    )
    worker = _identity(
        principal_id="synthetic-worker-001",
        role="worker",
        runtime_id="synthetic-runtime-001",
        runtime_identity_sha256=runtime_identity,
        parent_binding_sha256=authority["binding_sha256"],
        issuer_key_id=active_id,
    )
    runtime = _identity(
        principal_id="synthetic-runtime-001",
        role="runtime",
        runtime_id="synthetic-runtime-001",
        runtime_identity_sha256=runtime_identity,
        parent_binding_sha256=worker["binding_sha256"],
        issuer_key_id=active_id,
    )
    trust_root = {
        "root_id": root_id,
        "role": "trust_root",
        "algorithm": contract.ALGORITHM,
        "domain": contract.ROOT_DOMAIN,
        "epoch": 7,
        "revoked": False,
        "public_key_base64": base64.b64encode(root_public).decode("ascii"),
        "public_key_sha256": hashlib.sha256(root_public).hexdigest(),
        "source": "synthetic_fixture",
    }
    active = {
        "key_id": active_id,
        "role": "authority_issuer",
        "algorithm": contract.ALGORITHM,
        "domain": contract.IDENTITY_DOMAIN,
        "epoch": 7,
        "revoked": False,
        "public_key_base64": base64.b64encode(active_public).decode("ascii"),
        "public_key_sha256": hashlib.sha256(active_public).hexdigest(),
        "root_id": root_id,
        "root_public_key_sha256": hashlib.sha256(root_public).hexdigest(),
        "source": "synthetic_fixture",
    }
    identities = {"authority": authority, "worker": worker, "runtime": runtime}
    bindings = {
        "root_active_key_sha256": _sha({
            "root_id": root_id, "active_key_id": active_id, "epoch": 7,
        }),
        "authority_worker_sha256": _sha({
            "authority_binding_sha256": authority["binding_sha256"],
            "worker_binding_sha256": worker["binding_sha256"],
        }),
        "worker_runtime_sha256": _sha({
            "worker_binding_sha256": worker["binding_sha256"],
            "runtime_binding_sha256": runtime["binding_sha256"],
        }),
        "host_runtime_sha256": _sha({
            "worker_host_id": worker["host_id"],
            "worker_host_identity_sha256": worker["host_identity_sha256"],
            "runtime_host_id": runtime["host_id"],
            "runtime_host_identity_sha256": runtime["host_identity_sha256"],
            "worker_runtime_id": worker["runtime_id"],
            "runtime_runtime_id": runtime["runtime_id"],
        }),
    }
    bundle: dict[str, Any] = {
        "schema": contract.SCHEMA,
        "record_id": contract.RECORD_ID,
        "status": contract.STATUS,
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "scope_id": contract.SCOPE_ID,
        "trust_root": trust_root,
        "active_key": active,
        "identities": identities,
        "bindings": bindings,
        "constraints": {
            "algorithm": contract.ALGORITHM,
            "root_domain": contract.ROOT_DOMAIN,
            "identity_domain": contract.IDENTITY_DOMAIN,
            "epoch": {"current": 7, "minimum": 7, "maximum": 7},
            "revocation": {
                "root": False, "active_key": False, "authority": False,
                "worker": False, "runtime": False,
            },
            "trust": {
                "default_trust": "deny",
                "candidate_key_self_attestation": "reject",
                "root_anchor": "explicit_argument_only",
            },
        },
        "signatures": {
            "root_active_key_base64": "",
            "active_identity_base64": "",
        },
    }
    bundle["signatures"] = {
        "root_active_key_base64": base64.b64encode(
            root_key.sign(contract.root_signing_message(bundle))
        ).decode("ascii"),
        "active_identity_base64": base64.b64encode(
            active_key.sign(contract.identity_signing_message(bundle))
        ).decode("ascii"),
    }
    return bundle, _canonical(bundle), root_public, active_key


def test_valid_synthetic_chain_is_explicitly_non_authorizing() -> None:
    bundle, raw, root_public, _ = _fixture()
    before = copy.deepcopy(bundle)

    result = contract.verify_synthetic_identity_bundle(
        raw, trust_root_public_key_bytes=root_public,
    )

    assert bundle == before
    assert result["status"] == "synthetic_identity_chain_consistent_non_authorizing"
    assert result["synthetic_only"] is True
    assert result["trust_root_anchor_explicit"] is True
    assert result["trust_root_signature_valid_for_explicit_anchor"] is True
    assert result["active_key_authorized_by_trust_root"] is True
    assert result["authority_worker_runtime_chain_bound"] is True
    assert result["host_identity_binding_verified"] is True
    assert result["runtime_identity_binding_verified"] is True
    assert result["default_trust_rejected"] is True
    assert result["candidate_key_self_attestation_rejected"] is True
    assert result["diagnostic_only"] is True
    assert result["capability_minted"] is False
    assert result["readiness_pass"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0
    assert result["registry_mutation"] == 0
    assert result["ledger_mutation"] == 0
    assert result["gate_mutation"] == 0


def test_explicit_root_anchor_is_required_and_must_match() -> None:
    _, raw, root_public, _ = _fixture()
    with pytest.raises(contract.TrustedIdentityContractError, match="does not match"):
        contract.verify_synthetic_identity_bundle(
            raw, trust_root_public_key_bytes=_public_bytes(Ed25519PrivateKey.generate()),
        )
    with pytest.raises(contract.TrustedIdentityContractError, match="exactly 32 raw bytes"):
        contract.verify_synthetic_identity_bundle(raw, trust_root_public_key_bytes=b"")

    result = contract.verify_synthetic_identity_bundle(
        raw, trust_root_public_key_bytes=root_public,
    )
    assert result["trust_root_anchor_explicit"] is True


def test_root_signature_is_required_for_active_key_authorization() -> None:
    bundle, raw, root_public, active_key = _fixture()
    bundle["signatures"]["root_active_key_base64"] = base64.b64encode(
        active_key.sign(contract.root_signing_message(bundle))
    ).decode("ascii")
    with pytest.raises(contract.TrustedIdentityContractError, match="trust-root active-key signature"):
        contract.verify_synthetic_identity_bundle(
            _canonical(bundle), trust_root_public_key_bytes=root_public,
        )


def test_active_key_cannot_reuse_the_trust_root_for_self_attestation() -> None:
    bundle, _, root_public, _ = _fixture()
    bundle["active_key"]["public_key_base64"] = bundle["trust_root"]["public_key_base64"]
    bundle["active_key"]["public_key_sha256"] = bundle["trust_root"]["public_key_sha256"]
    with pytest.raises(contract.TrustedIdentityContractError, match="reuse the trust-root"):
        contract.verify_synthetic_identity_bundle(
            _canonical(bundle), trust_root_public_key_bytes=root_public,
        )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("constraints", "algorithm"), "rsa", "algorithm constraint"),
        (("constraints", "root_domain"), "wrong-root-domain", "root signature domain"),
        (("constraints", "identity_domain"), "wrong-identity-domain", "identity signature domain"),
        (("constraints", "epoch", "current"), 8, "epoch constraint"),
        (("constraints", "revocation", "worker"), True, "revocation constraint"),
        (("constraints", "trust", "default_trust"), "allow", "default trust"),
        (("constraints", "trust", "candidate_key_self_attestation"), "allow", "self-attestation"),
    ],
)
def test_epoch_revocation_algorithm_domain_and_trust_constraints_fail_closed(
    path: tuple[str, ...], value: object, message: str,
) -> None:
    bundle, _, root_public, _ = _fixture()
    target: Any = bundle
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    with pytest.raises(contract.TrustedIdentityContractError, match=message):
        contract.verify_synthetic_identity_bundle(
            _canonical(bundle), trust_root_public_key_bytes=root_public,
        )


def test_worker_runtime_parent_and_host_bindings_cannot_be_rebound() -> None:
    bundle, _, root_public, _ = _fixture()
    bundle["identities"]["runtime"]["parent_binding_sha256"] = "0" * 64
    with pytest.raises(contract.TrustedIdentityContractError, match="runtime identity binding hash"):
        contract.verify_synthetic_identity_bundle(
            _canonical(bundle), trust_root_public_key_bytes=root_public,
        )

    bundle, _, root_public, _ = _fixture()
    bundle["identities"]["runtime"]["host_id"] = "synthetic-other-host-001"
    runtime = bundle["identities"]["runtime"]
    runtime["binding_sha256"] = _sha(
        {key: runtime[key] for key in sorted(contract.IDENTITY_FIELDS) if key != "binding_sha256"}
    )
    with pytest.raises(contract.TrustedIdentityContractError, match="host identities"):
        contract.verify_synthetic_identity_bundle(
            _canonical(bundle), trust_root_public_key_bytes=root_public,
        )


def test_non_synthetic_input_origin_is_rejected_even_with_valid_signatures() -> None:
    bundle, _, root_public, _ = _fixture()
    bundle["input_origin"] = "production_receipt"
    with pytest.raises(contract.TrustedIdentityContractError, match="synthetic_fixture"):
        contract.verify_synthetic_identity_bundle(
            _canonical(bundle), trust_root_public_key_bytes=root_public,
        )


def test_bundle_requires_canonical_duplicate_free_json() -> None:
    _, raw, root_public, _ = _fixture()
    with pytest.raises(contract.TrustedIdentityContractError, match="canonical JSON"):
        contract.verify_synthetic_identity_bundle(raw + b"\n", trust_root_public_key_bytes=root_public)
    duplicate = b'{"schema":"one","schema":"two"}'
    with pytest.raises(contract.TrustedIdentityContractError, match="duplicate JSON object key"):
        contract.verify_synthetic_identity_bundle(duplicate, trust_root_public_key_bytes=root_public)


def test_checked_in_report_describes_the_same_non_authorizing_boundary() -> None:
    report = contract.build_report()
    assert report["schema"] == contract.REPORT_SCHEMA
    assert report["input_boundary"]["synthetic_only"] is True
    assert report["input_boundary"]["default_trust_root"] is False
    assert report["input_boundary"]["candidate_key_self_attestation"] == "reject"
    authorization = report["non_authorizing_boundary"]
    assert authorization["diagnostic_only"] is True
    assert authorization["capability_minted"] is False
    assert authorization["readiness_pass"] is False
    assert authorization["T1_numerical"] is False
    assert authorization["qualification_credit"] == 0
    assert authorization["registry_mutation"] == 0
    assert authorization["ledger_mutation"] == 0
    assert authorization["gate_mutation"] == 0

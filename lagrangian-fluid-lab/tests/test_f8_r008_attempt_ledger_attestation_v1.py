from __future__ import annotations

import base64
import copy
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import f8_r008_attempt_ledger_attestation_v1 as attestation_v1
from scripts import f8_r008_attempt_ledger_v1 as ledger_v1
from tests import test_f8_r008_attempt_ledger_v1 as ledger_fixtures


KEY_ID = "test-supervisor-key-001"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _signed_fixture(*, ledger_raw: bytes | None = None,
                    matrix_raw: bytes | None = None,
                    private_key: Ed25519PrivateKey | None = None
                    ) -> tuple[bytes, bytes, bytes, bytes, Ed25519PrivateKey]:
    ledger_raw = ledger_fixtures._raw() if ledger_raw is None else ledger_raw
    matrix_raw = ledger_fixtures.MATRIX_RAW if matrix_raw is None else matrix_raw
    private_key = Ed25519PrivateKey.generate() if private_key is None else private_key
    ledger = ledger_v1.inspect_untrusted_attempt_ledger(
        ledger_raw, qualification_matrix_raw=matrix_raw,
    )
    unsigned = {
        "schema": attestation_v1.ATTESTATION_SCHEMA,
        "scope_id": ledger["scope_id"],
        "qualification_matrix_raw_sha256": ledger["qualification_matrix_raw_sha256"],
        "attempt_ledger_raw_sha256": ledger["ledger_raw_sha256"],
        "supervisor_source_id": ledger["supervisor_source_id"],
        "coverage_start_ns_hex": ledger["coverage_start_ns_hex"],
        "coverage_end_ns_hex": ledger["coverage_end_ns_hex"],
        "event_count": ledger["event_count"],
        "overflow": ledger["overflow"],
        "lost_count": ledger["lost_count"],
        "signature_algorithm": "ed25519",
        "verification_key_id": KEY_ID,
    }
    signature = private_key.sign(
        attestation_v1.DOMAIN + _canonical(unsigned),
    )
    attestation = {**unsigned, "signature_base64": base64.b64encode(signature).decode("ascii")}
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    return _canonical(attestation), ledger_raw, matrix_raw, public_key, private_key


def _verify(attestation_raw: bytes, ledger_raw: bytes, matrix_raw: bytes,
            public_key: bytes, *, key_id: str = KEY_ID) -> dict:
    return attestation_v1.verify_untrusted_attempt_ledger_attestation(
        attestation_raw, ledger_raw, matrix_raw,
        candidate_verification_key_id=key_id,
        candidate_public_key_bytes=public_key,
    )


def test_valid_ephemeral_signature_and_bindings_remain_untrusted() -> None:
    raw, ledger_raw, matrix_raw, public_key, _key = _signed_fixture()

    result = _verify(raw, ledger_raw, matrix_raw, public_key)

    assert result["signature_cryptographically_valid"] is True
    assert result["signed_claim_bindings_match_supplied_ledger"] is True
    assert result["candidate_key_is_active"] is False
    assert result["active_key_registry_verified"] is False
    assert result["supervisor_identity_authenticated"] is False
    assert result["descriptor_root_authenticated"] is False
    assert result["attempt_ledger_complete"] is False
    assert result["capability_minted"] is False
    assert result["qualification_adjudicated"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_self_signed_attestation_does_not_establish_an_active_supervisor_key() -> None:
    raw, ledger_raw, matrix_raw, public_key, _key = _signed_fixture()

    result = _verify(raw, ledger_raw, matrix_raw, public_key)

    assert result["status"] == "untrusted_signature_and_binding_verified"
    assert result["candidate_public_key_sha256"] == hashlib.sha256(public_key).hexdigest()
    assert result["attempt_ledger_complete"] is False


@pytest.mark.parametrize("binding", [
    "qualification_matrix_raw_sha256", "attempt_ledger_raw_sha256",
    "supervisor_source_id", "coverage_start_ns_hex", "coverage_end_ns_hex",
    "event_count", "overflow", "lost_count",
])
def test_signed_claim_must_match_supplied_matrix_and_structural_ledger(binding: str) -> None:
    raw, ledger_raw, matrix_raw, public_key, private_key = _signed_fixture()
    document = json.loads(raw)
    document[binding] = ("0000000000000001" if binding == "coverage_start_ns_hex"
                         else "000000000000000c" if binding == "coverage_end_ns_hex"
                         else not document[binding] if type(document[binding]) is bool
                         else document[binding] + 1 if type(document[binding]) is int
                         else ("1" * len(document[binding])
                               if document[binding] != "1" * len(document[binding])
                               else "0" * len(document[binding])))
    # Keep the signature valid for the changed claim so this exercises binding
    # validation rather than merely the signature check.
    unsigned = {key: value for key, value in document.items()
                if key != "signature_base64"}
    document["signature_base64"] = base64.b64encode(
        private_key.sign(attestation_v1.DOMAIN + _canonical(unsigned)),
    ).decode("ascii")
    with pytest.raises(attestation_v1.AttemptLedgerAttestationV1Error,
                       match=f"{binding} differs"):
        _verify(_canonical(document), ledger_raw, matrix_raw, public_key)


def test_invalid_signature_rejects() -> None:
    raw, ledger_raw, matrix_raw, public_key, _key = _signed_fixture()
    document = json.loads(raw)
    signature = bytearray(base64.b64decode(document["signature_base64"]))
    signature[0] ^= 1
    document["signature_base64"] = base64.b64encode(signature).decode("ascii")

    with pytest.raises(attestation_v1.AttemptLedgerAttestationV1Error,
                       match="signature is invalid"):
        _verify(_canonical(document), ledger_raw, matrix_raw, public_key)


def test_noncanonical_json_and_duplicate_keys_reject() -> None:
    raw, ledger_raw, matrix_raw, public_key, _key = _signed_fixture()

    with pytest.raises(attestation_v1.AttemptLedgerAttestationV1Error,
                       match="not exact V12 canonical JSON"):
        _verify(json.dumps(json.loads(raw), indent=2).encode(),
                ledger_raw, matrix_raw, public_key)

    duplicate = raw.replace(b'"schema":"core.cfd.f8.r008_attempt_ledger_attestation.v1",',
                            b'"schema":"core.cfd.f8.r008_attempt_ledger_attestation.v1",'
                            b'"schema":"core.cfd.f8.r008_attempt_ledger_attestation.v1",', 1)
    with pytest.raises(attestation_v1.AttemptLedgerAttestationV1Error,
                       match="duplicate JSON object key"):
        _verify(duplicate, ledger_raw, matrix_raw, public_key)


@pytest.mark.parametrize("mutation, message", [
    (lambda value: value.__setitem__("unexpected", 0), "exact frozen schema"),
    (lambda value: value.__setitem__("signature_algorithm", "Ed25519"),
     "signature_algorithm must be ed25519"),
    (lambda value: value.__setitem__("event_count", True),
     "event_count must be a nonnegative builtin integer"),
    (lambda value: value.__setitem__("lost_count", False),
     "lost_count must be a nonnegative builtin integer"),
    (lambda value: value.__setitem__("signature_base64", "!"),
     "not strict standard base64"),
])
def test_exact_schema_and_builtin_json_types_are_enforced(mutation, message: str) -> None:
    raw, ledger_raw, matrix_raw, public_key, _key = _signed_fixture()
    document = copy.deepcopy(json.loads(raw))
    mutation(document)
    with pytest.raises(attestation_v1.AttemptLedgerAttestationV1Error, match=message):
        _verify(_canonical(document), ledger_raw, matrix_raw, public_key)


def test_candidate_key_id_must_match_signed_key_id() -> None:
    raw, ledger_raw, matrix_raw, public_key, _key = _signed_fixture()

    with pytest.raises(attestation_v1.AttemptLedgerAttestationV1Error,
                       match="candidate key ID differs"):
        _verify(raw, ledger_raw, matrix_raw, public_key, key_id="other-key")


def test_structurally_invalid_ledger_cannot_receive_a_valid_diagnostic() -> None:
    raw, ledger_raw, matrix_raw, public_key, _key = _signed_fixture()
    broken_ledger = ledger_fixtures._raw({**ledger_fixtures._ledger_document(), "lost_count": 1})

    with pytest.raises(attestation_v1.AttemptLedgerAttestationV1Error,
                       match="ledger/matrix structural validation failed"):
        _verify(raw, broken_ledger, matrix_raw, public_key)

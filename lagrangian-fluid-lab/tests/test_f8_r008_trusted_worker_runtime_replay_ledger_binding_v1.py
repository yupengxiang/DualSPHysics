from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import f8_r008_trusted_worker_runtime_replay_ledger_binding_v1 as contract
from tests import test_f8_r008_trusted_worker_runtime_handoff_v1 as handoff_fixtures


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _public_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )


def _witness(
    binding: dict[str, Any], ledger_key: Ed25519PrivateKey, *, generation: int,
    consumed: bool, ledger_id: str = "synthetic-replay-ledger-001",
    entry_id: str = "synthetic-replay-entry-001", consumed_epoch: int | None = None,
    issuer_principal: str = "synthetic-replay-ledger-issuer-001",
    issuer_key_id: str = "synthetic-replay-ledger-key-001",
    consumption_id: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": contract.SCHEMA,
        "record_id": contract.RECORD_ID,
        "status": "synthetic_only_trusted_replay_ledger_witness",
        "synthetic_only": True,
        "input_origin": "synthetic_fixture",
        "scope_id": contract.SCOPE_ID,
        "handoff_binding": copy.deepcopy(binding),
        "ledger": {
            "ledger_id": ledger_id,
            "entry_id": entry_id,
            "generation": generation,
            "consumed": consumed,
            "consumption_id_sha256": consumption_id,
            "consumed_epoch": consumed_epoch,
        },
        "issuer": {
            "ledger_principal_id": issuer_principal,
            "key_id": issuer_key_id,
            "key_sha256": hashlib.sha256(_public_bytes(ledger_key)).hexdigest(),
            "role": "trusted_replay_ledger",
            "source": "synthetic_fixture",
        },
        "constraints": {
            "algorithm": contract.ALGORITHM,
            "default_trust": "deny",
            "witness_anchor": "explicit_ledger_key_argument_only",
            "transition": "exact_single_use_consumption_generation_plus_one",
            "production_ledger": "not_authenticated",
            "mutation": "none_in_memory_witnesses_only",
        },
        "signature": {
            "algorithm": contract.ALGORITHM,
            "signature_base64": "",
        },
    }
    value["signature"]["signature_base64"] = base64.b64encode(
        ledger_key.sign(contract.witness_signing_message(value))
    ).decode("ascii")
    return value


def _fixture(ledger_key: Ed25519PrivateKey | None = None) -> dict[str, Any]:
    handoff, handoff_raw, root_public, active_key, identity_raw = handoff_fixtures._handoff()
    ledger_key = ledger_key or Ed25519PrivateKey.generate()
    binding = contract.derive_handoff_binding(handoff_raw)
    pre = _witness(binding, ledger_key, generation=40, consumed=False)
    post_id = contract.consumption_id_sha256(
        binding,
        ledger_id=pre["ledger"]["ledger_id"],
        entry_id=pre["ledger"]["entry_id"],
        pre_generation=40,
        post_generation=41,
        consumed_epoch=110,
    )
    post = _witness(
        binding, ledger_key, generation=41, consumed=True, consumed_epoch=110,
        consumption_id=post_id,
    )
    return {
        "handoff": handoff,
        "handoff_raw": handoff_raw,
        "root_public": root_public,
        "active_key": active_key,
        "identity_raw": identity_raw,
        "ledger_key": ledger_key,
        "ledger_public": _public_bytes(ledger_key),
        "binding": binding,
        "pre": pre,
        "post": post,
    }


def _raw(value: dict[str, Any]) -> bytes:
    return _canonical(value)


def _resign(value: dict[str, Any], key: Ed25519PrivateKey) -> bytes:
    value["signature"]["signature_base64"] = base64.b64encode(
        key.sign(contract.witness_signing_message(value))
    ).decode("ascii")
    return _raw(value)


def _verify(fixture: dict[str, Any], *, pre: dict[str, Any] | None = None,
            post: dict[str, Any] | None = None) -> dict[str, Any]:
    pre_value = copy.deepcopy(pre) if pre is not None else fixture["pre"]
    post_value = copy.deepcopy(post) if post is not None else fixture["post"]
    pre_raw = _resign(pre_value, fixture["ledger_key"]) if pre is not None else _raw(pre_value)
    post_raw = _resign(post_value, fixture["ledger_key"]) if post is not None else _raw(post_value)
    return contract.verify_synthetic_replay_consumption(
        fixture["handoff_raw"],
        identity_bundle_raw=fixture["identity_raw"],
        trust_root_public_key_bytes=fixture["root_public"],
        pre_ledger_witness_raw=pre_raw,
        post_ledger_witness_raw=post_raw,
        trusted_ledger_public_key_bytes=fixture["ledger_public"],
    )


def test_valid_transition_is_exactly_bound_and_non_authorizing() -> None:
    fixture = _fixture()
    before_pre = copy.deepcopy(fixture["pre"])
    before_post = copy.deepcopy(fixture["post"])
    result = _verify(fixture)

    assert fixture["pre"] == before_pre
    assert fixture["post"] == before_post
    assert result["status"] == contract.STATUS
    assert result["handoff_digest_bound"] is True
    assert result["handoff_identity_projection_bound"] is True
    assert result["attempt_case_nonce_bound"] is True
    assert result["issuer_subject_bound"] is True
    assert result["bounded_epoch_window_bound"] is True
    assert result["trusted_ledger_witness_verified"] is True
    assert result["single_use_consumption_transition_verified"] is True
    assert result["pre_generation"] == 40
    assert result["post_generation"] == 41
    assert result["generation_delta"] == 1
    assert result["pre_consumed"] is False
    assert result["post_consumed"] is True
    assert result["replay_rejected_by_consumed_state"] is True
    assert result["production_ledger_authenticated"] is False
    assert result["real_ledger_read"] is False
    assert result["real_ledger_mutation"] == 0
    assert result["diagnostic_only"] is True
    assert result["capability_minted"] is False
    assert result["execution_authority"] is False
    assert result["readiness_pass"] is False
    assert result["formal_eligible"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0
    assert result["registry_mutation"] == 0
    assert result["ledger_mutation"] == 0
    assert result["denominator_mutation"] == 0
    assert result["gate_mutation"] == 0


def test_missing_or_wrong_trusted_ledger_anchor_fails_closed() -> None:
    fixture = _fixture()
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="explicitly supplied"):
        contract.verify_synthetic_replay_consumption(
            fixture["handoff_raw"], identity_bundle_raw=fixture["identity_raw"],
            trust_root_public_key_bytes=fixture["root_public"],
            pre_ledger_witness_raw=_raw(fixture["pre"]),
            post_ledger_witness_raw=_raw(fixture["post"]),
            trusted_ledger_public_key_bytes=b"",
        )

    wrong_key = Ed25519PrivateKey.generate()
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="key digest"):
        _verify({**fixture, "ledger_public": _public_bytes(wrong_key)})


def test_replay_of_consumed_state_is_rejected() -> None:
    fixture = _fixture()
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="already consumed"):
        _verify(fixture, pre=fixture["post"])


@pytest.mark.parametrize("field", ["scope_id", "case_id", "nonce_hex", "handoff_sha256"])
def test_cross_scope_case_nonce_or_handoff_digest_rebinding_is_rejected(field: str) -> None:
    fixture = _fixture()
    pre = copy.deepcopy(fixture["pre"])
    post = copy.deepcopy(fixture["post"])
    if field == "scope_id":
        pre["scope_id"] = post["scope_id"] = "other-scope"
    elif field == "case_id":
        pre["handoff_binding"][field] = post["handoff_binding"][field] = "synthetic-other-case-001"
    elif field == "nonce_hex":
        pre["handoff_binding"][field] = post["handoff_binding"][field] = "f" * 32
    else:
        pre["handoff_binding"][field] = post["handoff_binding"][field] = "f" * 64
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="exact handoff binding|scope"):
        _verify(fixture, pre=pre, post=post)


def test_handoff_issuer_and_subject_projection_cannot_be_rebound() -> None:
    fixture = _fixture()
    pre = copy.deepcopy(fixture["pre"])
    post = copy.deepcopy(fixture["post"])
    pre["handoff_binding"]["handoff_issuer"]["active_key_id"] = "synthetic-other-issuer-001"
    post["handoff_binding"]["handoff_issuer"]["active_key_id"] = "synthetic-other-issuer-001"
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="exact handoff binding"):
        _verify(fixture, pre=pre, post=post)

    pre = copy.deepcopy(fixture["pre"])
    post = copy.deepcopy(fixture["post"])
    pre["handoff_binding"]["handoff_subject"]["worker_binding_sha256"] = "e" * 64
    post["handoff_binding"]["handoff_subject"]["worker_binding_sha256"] = "e" * 64
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="exact handoff binding"):
        _verify(fixture, pre=pre, post=post)


@pytest.mark.parametrize("post_generation", [39, 40, 42])
def test_generation_rollback_skip_or_nonadvance_is_rejected(post_generation: int) -> None:
    fixture = _fixture()
    post = copy.deepcopy(fixture["post"])
    post["ledger"]["generation"] = post_generation
    post["ledger"]["consumption_id_sha256"] = contract.consumption_id_sha256(
        fixture["binding"], ledger_id=post["ledger"]["ledger_id"],
        entry_id=post["ledger"]["entry_id"], pre_generation=40,
        post_generation=post_generation, consumed_epoch=110,
    )
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="advance exactly one"):
        _verify(fixture, post=post)


def test_consumed_epoch_must_stay_inside_handoff_window() -> None:
    fixture = _fixture()
    post = copy.deepcopy(fixture["post"])
    post["ledger"]["consumed_epoch"] = 99
    post["ledger"]["consumption_id_sha256"] = contract.consumption_id_sha256(
        fixture["binding"], ledger_id=post["ledger"]["ledger_id"],
        entry_id=post["ledger"]["entry_id"], pre_generation=40,
        post_generation=41, consumed_epoch=99,
    )
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="outside the handoff lifetime"):
        _verify(fixture, post=post)


def test_consumption_id_binds_the_exact_transition() -> None:
    fixture = _fixture()
    post = copy.deepcopy(fixture["post"])
    post["ledger"]["consumption_id_sha256"] = "0" * 64
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="consumption id"):
        _verify(fixture, post=post)


def test_ledger_issuer_cannot_self_claim_handoff_identity() -> None:
    fixture = _fixture()
    pre = copy.deepcopy(fixture["pre"])
    post = copy.deepcopy(fixture["post"])
    active_id = fixture["handoff"]["issuer"]["active_key_id"]
    pre["issuer"]["ledger_principal_id"] = active_id
    post["issuer"]["ledger_principal_id"] = active_id
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="self-claim"):
        _verify(fixture, pre=pre, post=post)


def test_ledger_witness_may_not_reuse_handoff_active_identity_key() -> None:
    fixture = _fixture()
    active_key = fixture["active_key"]
    pre = _witness(
        fixture["binding"], active_key, generation=40, consumed=False,
        issuer_key_id="synthetic-reused-active-key-001",
    )
    post_id = contract.consumption_id_sha256(
        fixture["binding"], ledger_id=pre["ledger"]["ledger_id"],
        entry_id=pre["ledger"]["entry_id"], pre_generation=40,
        post_generation=41, consumed_epoch=110,
    )
    post = _witness(
        fixture["binding"], active_key, generation=41, consumed=True,
        consumed_epoch=110, consumption_id=post_id,
        issuer_key_id="synthetic-reused-active-key-001",
    )
    active_public = _public_bytes(active_key)
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="reuse the handoff active identity"):
        contract.verify_synthetic_replay_consumption(
            fixture["handoff_raw"], identity_bundle_raw=fixture["identity_raw"],
            trust_root_public_key_bytes=fixture["root_public"],
            pre_ledger_witness_raw=_raw(pre), post_ledger_witness_raw=_raw(post),
            trusted_ledger_public_key_bytes=active_public,
        )


def test_canonical_duplicate_free_witness_bytes_are_required() -> None:
    fixture = _fixture()
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="canonical JSON"):
        contract.verify_synthetic_replay_consumption(
            fixture["handoff_raw"], identity_bundle_raw=fixture["identity_raw"],
            trust_root_public_key_bytes=fixture["root_public"],
            pre_ledger_witness_raw=_raw(fixture["pre"]) + b"\n",
            post_ledger_witness_raw=_raw(fixture["post"]),
            trusted_ledger_public_key_bytes=fixture["ledger_public"],
        )
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="duplicate JSON object key"):
        contract.verify_synthetic_replay_consumption(
            fixture["handoff_raw"], identity_bundle_raw=fixture["identity_raw"],
            trust_root_public_key_bytes=fixture["root_public"],
            pre_ledger_witness_raw=b'{"ledger_id":"one","ledger_id":"two"}',
            post_ledger_witness_raw=_raw(fixture["post"]),
            trusted_ledger_public_key_bytes=fixture["ledger_public"],
        )


def test_witness_issuer_and_ledger_identity_must_remain_stable() -> None:
    fixture = _fixture()
    post = copy.deepcopy(fixture["post"])
    post["ledger"]["entry_id"] = "synthetic-other-entry-001"
    post["ledger"]["consumption_id_sha256"] = contract.consumption_id_sha256(
        fixture["binding"], ledger_id=post["ledger"]["ledger_id"],
        entry_id=post["ledger"]["entry_id"], pre_generation=40,
        post_generation=41, consumed_epoch=110,
    )
    with pytest.raises(contract.TrustedReplayLedgerBindingError, match="identity changed"):
        _verify(fixture, post=post)


def test_report_matches_checked_in_non_authorizing_boundary() -> None:
    report = contract.build_report()
    assert report["schema"] == contract.REPORT_SCHEMA
    assert report["input_boundary"]["synthetic_only"] is True
    assert report["input_boundary"]["handoff_contract_reused"] is True
    boundary = report["non_authorizing_boundary"]
    assert boundary["diagnostic_only"] is True
    assert boundary["capability_minted"] is False
    assert boundary["execution_authority"] is False
    assert boundary["readiness_pass"] is False
    assert boundary["T1_numerical"] is False
    assert boundary["qualification_credit"] == 0
    assert boundary["registry_mutation"] == 0
    assert boundary["ledger_mutation"] == 0
    assert boundary["gate_mutation"] == 0
    assert boundary["real_ledger_mutation"] == 0

    report_path = Path(__file__).resolve().parents[1] / (
        "reports/F8-R008-TRUSTED-WORKER-RUNTIME-REPLAY-LEDGER-BINDING-V1.json"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == report

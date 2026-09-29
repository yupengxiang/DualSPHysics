from __future__ import annotations

import base64
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import f8_r008_trusted_target_pin_intake_v1 as contract


LAB = Path(__file__).parents[1]
REPORT_PATH = LAB / "reports/F8-R008-TRUSTED-TARGET-PIN-INTAKE-V1.json"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _anchor(key: Ed25519PrivateKey, *, synthetic: bool = False) -> dict[str, Any]:
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return {
        "schema": contract.ANCHOR_SCHEMA,
        "record_id": contract.ANCHOR_RECORD_ID,
        "evidence_origin": contract.ANCHOR_ORIGIN,
        "synthetic": synthetic,
        "root_id": "prod-f8-r008-root-001",
        "key_id": "prod-f8-r008-pin-key-001",
        "algorithm": contract.ALGORITHM,
        "public_key_base64": base64.b64encode(public).decode("ascii"),
        "public_key_sha256": hashlib.sha256(public).hexdigest(),
        "registry_sha256": _sha_text("external-trust-registry-entry-001"),
        "epoch": 17,
        "revoked": False,
        "source": contract.ANCHOR_SOURCE,
    }


def _public_key_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def _fixture(
    tmp_path: Path,
    *,
    synthetic: bool = False,
    anchor_synthetic: bool = False,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any], Ed25519PrivateKey]:
    key = Ed25519PrivateKey.generate()
    anchor = _anchor(key, synthetic=anchor_synthetic)
    target = {
        "kernel_release": "6.8.0-r008-target.20260929",
        "arch": "x86_64",
        "source_commit": _sha1_text("external-r008-source-commit"),
        "source_tree_sha256": _sha_text("external-r008-source-tree"),
        "uapi_sha256": _sha_text("external-r008-uapi"),
        "config_sha256": _sha_text("external-r008-config"),
        "build_id": _sha_text("external-r008-build-id"),
        "kernel_image_sha256": _sha_text("external-r008-kernel-image"),
        "config_options_sha256": _sha_text("external-r008-config-options"),
        "syscall_policy_sha256": _sha_text("external-r008-syscall-policy"),
    }
    source = {
        "source_commit": target["source_commit"],
        "source_tree_sha256": target["source_tree_sha256"],
        "uapi_sha256": target["uapi_sha256"],
        "source_manifest_sha256": _sha_text("external-r008-source-manifest"),
        "callgraph_sha256": _sha_text("external-r008-callgraph"),
        "patchset_sha256": _sha_text("external-r008-patchset"),
    }
    build = {
        "arch": target["arch"],
        "build_id": target["build_id"],
        "build_closure_sha256": _sha_text("external-r008-build-closure"),
        "compiler_identity_sha256": _sha_text("external-r008-compiler"),
        "linker_identity_sha256": _sha_text("external-r008-linker"),
        "binary_sha256": target["kernel_image_sha256"],
        "config_sha256": target["config_sha256"],
        "build_manifest_sha256": _sha_text("external-r008-build-manifest"),
    }
    host = {
        "host_id": "external-host-r008-001",
        "machine_id_sha256": _sha_text("external-machine-id"),
        "boot_id_sha256": _sha_text("external-boot-id"),
        "host_attestation_sha256": _sha_text("external-host-attestation"),
        "host_profile_sha256": _sha_text("external-host-profile"),
    }
    runtime = {
        "abi_schema": contract.ABI_SCHEMA,
        "kernel_release": target["kernel_release"],
        "arch": target["arch"],
        "build_id": target["build_id"],
        "config_sha256": target["config_sha256"],
        "host_identity_sha256": _sha(host),
        "runtime_image_sha256": target["kernel_image_sha256"],
        "loaded_modules_sha256": _sha_text("external-loaded-modules"),
        "syscall_policy_sha256": target["syscall_policy_sha256"],
        "fanotify_abi_sha256": _sha_text("external-fanotify-abi"),
        "fid_abi_sha256": _sha_text("external-fid-abi"),
        "pidfd_abi_sha256": _sha_text("external-pidfd-abi"),
        "seccomp_abi_sha256": _sha_text("external-seccomp-abi"),
        "selector_min": 0,
        "selector_max": 461,
        "abi_payload_sha256": "",
    }
    runtime["abi_payload_sha256"] = _sha(
        {key: runtime[key] for key in sorted(contract.RUNTIME_ABI_FIELDS)
         if key != "abi_payload_sha256"}
    )
    root_ref = {
        key: anchor[key]
        for key in contract.TRUST_ROOT_REF_FIELDS
    }
    receipt = {
        "schema": contract.RECEIPT_SCHEMA,
        "record_id": contract.RECEIPT_RECORD_ID,
        "receipt_id": "4f3c2c1a-8b7e-4d91-a2f0-6e5b4c3d2a10",
        "scope_id": contract.SCOPE_ID,
        "pin_set_sha256": "",
        "host_identity_sha256": _sha(host),
        "root_id": anchor["root_id"],
        "key_id": anchor["key_id"],
        "nonce_hex": "0123456789abcdef0123456789abcdef",
        "generation": 1,
        "state": "consumed",
        "single_use": True,
        "replay_policy": "reject_replay",
        "issued_epoch": 100,
        "consumed_epoch": 101,
        "expires_epoch": 200,
        "consumption_binding_sha256": "",
    }
    attestation: dict[str, Any] = {
        "schema": contract.SCHEMA,
        "record_id": contract.RECORD_ID,
        "scope_id": contract.SCOPE_ID,
        "evidence_origin": contract.ATTESTATION_ORIGIN,
        "synthetic": synthetic,
        "target_kernel": target,
        "source": source,
        "build": build,
        "runtime_abi": runtime,
        "host_identity": host,
        "trust_root_ref": root_ref,
        "one_shot_receipt": receipt,
        "signature": {
            "algorithm": contract.ALGORITHM,
            "key_id": anchor["key_id"],
            "signed_payload_sha256": "",
            "signature_base64": "",
        },
    }
    receipt["pin_set_sha256"] = contract._pin_set_digest(attestation)
    receipt["consumption_binding_sha256"] = hashlib.sha256(_canonical(
        contract._receipt_consumption_payload(receipt)
    )).hexdigest()
    signed_payload_hash = hashlib.sha256(_canonical(
        contract._attestation_signing_payload(attestation)
    )).hexdigest()
    attestation["signature"]["signed_payload_sha256"] = signed_payload_hash
    attestation["signature"]["signature_base64"] = base64.b64encode(
        key.sign(contract.signing_message(attestation))
    ).decode("ascii")

    attestation_path = tmp_path / "attestation.json"
    anchor_path = tmp_path / "anchor.json"
    attestation_path.write_bytes(_canonical(attestation))
    anchor_path.write_bytes(_canonical(anchor))
    return attestation_path, anchor_path, attestation, anchor, key


def _resign(attestation: dict[str, Any], key: Ed25519PrivateKey) -> bytes:
    attestation["signature"]["signed_payload_sha256"] = hashlib.sha256(_canonical(
        contract._attestation_signing_payload(attestation)
    )).hexdigest()
    attestation["signature"]["signature_base64"] = base64.b64encode(
        key.sign(contract.signing_message(attestation))
    ).decode("ascii")
    return _canonical(attestation)


def _checked_in_report() -> dict[str, Any]:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_missing_default_attestation_is_blocked_and_zero_credit() -> None:
    report = contract.build_report(
        Path("external/definitely-missing-r008-trusted-pin.json"),
        Path("external/definitely-missing-r008-trust-anchor.json"),
    )

    assert report["status"] == contract.STATUS_BLOCKED_MISSING
    assert report["validation"]["blockers"]
    assert report["pins"] == {name: False for name in contract.PIN_NAMES}
    assert report["trust"]["anchor_bound"] is False
    assert report["authorization"]["readiness_pass"] is False
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["qualification_credit"] == 0
    assert all(value is False or value == 0 for value in report["side_effects"].values())


def test_external_candidate_binds_all_domains_but_never_authorizes(tmp_path: Path) -> None:
    attestation_path, anchor_path, _attestation, _anchor, key = _fixture(tmp_path)
    public_key = _public_key_bytes(key)
    result = contract.intake_paths(
        attestation_path,
        anchor_path,
        trust_anchor_public_key=public_key,
    )["result"]
    report = contract.build_report(
        attestation_path,
        anchor_path,
        trust_anchor_public_key=public_key,
    )

    assert result["status"] == contract.STATUS_VALID_NON_AUTHORIZING
    assert result["target_kernel_pin_complete"] is True
    assert result["source_pin_complete"] is True
    assert result["build_pin_complete"] is True
    assert result["runtime_abi_pin_complete"] is True
    assert result["host_identity_bound"] is True
    assert result["trust_root_key_bound"] is True
    assert result["signature_valid"] is True
    assert result["one_shot_receipt_bound"] is True
    assert report["status"] == contract.STATUS_VALID_NON_AUTHORIZING
    assert all(report["pins"].values())
    assert report["trust"]["production_trust_authenticated"] is False
    assert report["trust"]["target_runtime_measured"] is False
    assert report["trust"]["replay_ledger_observed"] is False
    assert report["authorization"] == contract._authorization()
    assert report["side_effects"] == {
        **contract._side_effects(),
        "attestation_read": True,
        "trust_anchor_read": True,
    }


def test_anchor_requires_independent_public_key_binding(tmp_path: Path) -> None:
    attestation_path, anchor_path, _attestation, _anchor, key = _fixture(tmp_path)
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="explicit out-of-band"):
        contract.intake_paths(attestation_path, anchor_path)

    other_key = Ed25519PrivateKey.generate()
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="does not match the explicit"):
        contract.intake_paths(
            attestation_path,
            anchor_path,
            trust_anchor_public_key=_public_key_bytes(other_key),
        )


def test_checked_in_report_matches_deterministic_default_and_verifies() -> None:
    expected = contract.build_report()
    checked_in = _checked_in_report()

    assert checked_in == expected
    assert contract.verify_report(REPORT_PATH) == expected


def test_synthetic_attestation_and_anchor_cannot_be_promoted(tmp_path: Path) -> None:
    attestation_path, anchor_path, attestation, _anchor, key = _fixture(
        tmp_path, synthetic=True
    )
    attestation_path.write_bytes(_resign(attestation, key))
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="synthetic"):
        contract.intake_paths(
            attestation_path,
            anchor_path,
            trust_anchor_public_key=_public_key_bytes(key),
        )

    attestation_path, anchor_path, _attestation, _anchor, key = _fixture(
        tmp_path, anchor_synthetic=True
    )
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="synthetic"):
        contract.intake_paths(
            attestation_path,
            anchor_path,
            trust_anchor_public_key=_public_key_bytes(key),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["target_kernel"].__setitem__("build_id", "f" * 64), "synthetic/placeholder"),
        (lambda value: value["runtime_abi"].__setitem__("selector_max", 460), "selector range"),
        (lambda value: value["host_identity"].__setitem__("host_id", "current-host"), "default/local"),
        (lambda value: value["one_shot_receipt"].__setitem__("generation", 2), "first consumed generation"),
        (lambda value: value["one_shot_receipt"].__setitem__("receipt_id", "r008-pin-receipt-001"), "UUIDv4"),
        (lambda value: value["trust_root_ref"].__setitem__("key_id", "other-key"), "trust_root_ref"),
    ],
)
def test_pin_domain_and_one_shot_drift_fail_closed(
    tmp_path: Path, mutation, message: str
) -> None:
    attestation_path, anchor_path, attestation, _anchor, key = _fixture(tmp_path)
    mutation(attestation)
    attestation_path.write_bytes(_resign(attestation, key))

    with pytest.raises(contract.TrustedTargetPinIntakeError, match=message):
        contract.intake_paths(
            attestation_path,
            anchor_path,
            trust_anchor_public_key=_public_key_bytes(key),
        )


def test_target_build_runtime_arch_config_and_image_bindings_fail_closed(tmp_path: Path) -> None:
    cases = (
        ("build arch", lambda value: value["build"].__setitem__("arch", "aarch64"), "architecture"),
        ("runtime config", lambda value: value["runtime_abi"].__setitem__("config_sha256", _sha_text("wrong-config")), "config SHA"),
        ("build image", lambda value: value["build"].__setitem__("binary_sha256", _sha_text("wrong-image")), "kernel image SHA"),
    )
    for _label, mutate, message in cases:
        attestation_path, anchor_path, attestation, _anchor, key = _fixture(tmp_path)
        mutate(attestation)
        if _label == "runtime config":
            attestation["runtime_abi"]["abi_payload_sha256"] = _sha(
                {field: attestation["runtime_abi"][field]
                 for field in sorted(contract.RUNTIME_ABI_FIELDS)
                 if field != "abi_payload_sha256"}
            )
        attestation_path.write_bytes(_resign(attestation, key))
        with pytest.raises(contract.TrustedTargetPinIntakeError, match=message):
            contract.intake_paths(
                attestation_path,
                anchor_path,
                trust_anchor_public_key=_public_key_bytes(key),
            )


def test_cross_domain_hash_drift_fails_even_with_a_valid_signature(tmp_path: Path) -> None:
    attestation_path, anchor_path, attestation, _anchor, key = _fixture(tmp_path)
    attestation["runtime_abi"]["host_identity_sha256"] = _sha_text("wrong-host")
    attestation["runtime_abi"]["abi_payload_sha256"] = _sha(
        {key: attestation["runtime_abi"][key]
         for key in sorted(contract.RUNTIME_ABI_FIELDS)
         if key != "abi_payload_sha256"}
    )
    attestation_path.write_bytes(_resign(attestation, key))

    with pytest.raises(contract.TrustedTargetPinIntakeError, match="runtime host identity"):
        contract.intake_paths(
            attestation_path,
            anchor_path,
            trust_anchor_public_key=_public_key_bytes(key),
        )


def test_signature_and_trust_anchor_key_binding_fail_closed(tmp_path: Path) -> None:
    attestation_path, anchor_path, attestation, anchor, key = _fixture(tmp_path)
    signature = bytearray(base64.b64decode(attestation["signature"]["signature_base64"]))
    signature[-1] ^= 1
    attestation["signature"]["signature_base64"] = base64.b64encode(signature).decode("ascii")
    attestation_path.write_bytes(_canonical(attestation))
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="signature is invalid"):
        contract.intake_paths(
            attestation_path,
            anchor_path,
            trust_anchor_public_key=_public_key_bytes(key),
        )

    attestation_path, anchor_path, _attestation, anchor, key = _fixture(tmp_path)
    other_key = Ed25519PrivateKey.generate()
    other_public = other_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    anchor["public_key_base64"] = base64.b64encode(other_public).decode("ascii")
    anchor["public_key_sha256"] = hashlib.sha256(other_public).hexdigest()
    anchor_path.write_bytes(_canonical(anchor))
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="does not exactly bind"):
        contract.intake_paths(
            attestation_path,
            anchor_path,
            trust_anchor_public_key=_public_key_bytes(other_key),
        )


def test_canonical_json_duplicate_and_path_boundaries_fail_closed(tmp_path: Path) -> None:
    attestation_path, anchor_path, _attestation, _anchor, _key = _fixture(tmp_path)
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="canonical JSON"):
        contract.verify_attestation(attestation_path.read_bytes() + b"\n", anchor_path.read_bytes())

    duplicate = b'{"schema":"one","schema":"two"}'
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="duplicate JSON"):
        contract.verify_attestation(duplicate, anchor_path.read_bytes())

    link = tmp_path / "anchor-link.json"
    os.symlink(anchor_path, link)
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="symlink"):
        contract.intake_paths(attestation_path, link)

    hardlink = tmp_path / "anchor-hardlink.json"
    os.link(anchor_path, hardlink)
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="exactly one hard link"):
        contract.intake_paths(attestation_path, hardlink)


def test_report_validator_rejects_promotion_aliases() -> None:
    report = contract.build_report(
        Path("external/definitely-missing-r008-trusted-pin.json"),
        Path("external/definitely-missing-r008-trust-anchor.json"),
    )
    promoted = copy.deepcopy(report)
    promoted["authorization"]["T1_numerical"] = True
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="authorization"):
        contract._validate_report(promoted)

    promoted = copy.deepcopy(report)
    promoted["pins"]["source"] = True
    with pytest.raises(contract.TrustedTargetPinIntakeError, match="promoted pins"):
        contract._validate_report(promoted)


def test_module_has_no_runtime_or_execution_surface() -> None:
    source = inspect.getsource(contract)
    for forbidden in (
        "subprocess",
        "Popen",
        "nvidia-smi",
        "CUDA_VISIBLE_DEVICES",
        "import torch",
        "h5py",
        "fanotify_init",
        "uname(",
        "os.system",
    ):
        assert forbidden not in source

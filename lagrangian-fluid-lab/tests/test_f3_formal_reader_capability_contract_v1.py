"""Synthetic negative tests for the isolated F3 V13 reader contract."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from scripts.f3_formal_reader_capability_contract_v1 import (
    CONTRACT_SCHEMA,
    inspect_manifest,
    validate_capability_contract,
)


ROOT = Path(__file__).resolve().parents[1]
F3_MANIFEST = ROOT / "campaigns/core-v1/f3-dataset-v2.json"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _nonce(label: str) -> str:
    return _sha("nonce:" + label)


def _contract(*, formal_release: bool = True) -> dict:
    geometry = {"path": "inputs/geometry.npz", "sha256": _sha("geometry"), "version": "v13"}
    control = {"path": "inputs/control.npz", "sha256": _sha("control"), "version": "v13"}
    source_rows = []
    bindings = []
    for index in range(2):
        case_id = f"F3_SYNTH_{index:02d}"
        source_sha = _sha(f"source:{index}")
        source_rows.append({
            "case_id": case_id,
            "source_sha256": source_sha,
            "bytes": 100 + index,
            "fd_identity": {"st_dev": 1, "st_ino": 10 + index, "st_size": 100 + index},
            "measurement": {"algorithm": "fs-verity", "digest": _sha(f"verity:{index}")},
        })
        bindings.append({
            "case_id": case_id,
            "source_sha256": source_sha,
            "snapshot_nonce": _nonce("snapshot"),
            "geometry_sha256": geometry["sha256"],
            "control_sha256": control["sha256"],
        })
    return {
        "schema": CONTRACT_SCHEMA,
        "formal_release": formal_release,
        "manifest_identity": {"path": "manifest.json", "sha256": _sha("manifest")},
        "source_trust": {
            "mode": "held_fd_fsverity",
            "attested": True,
            "same_fd_snapshot": True,
            "snapshot_nonce": _nonce("snapshot"),
            "case_snapshots": source_rows,
        },
        "descriptors": {"geometry": geometry, "control": control},
        "identities": {
            "session_nonce": _nonce("session"),
            "producer": {"identity": "producer:synth", "nonce": _nonce("producer")},
            "broker": {"identity": "broker:synth", "nonce": _nonce("broker")},
            "worker": {"identity": "worker:synth", "nonce": _nonce("worker")},
        },
        "case_bindings": bindings,
    }


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["blockers"]}


def test_complete_synthetic_envelope_is_structural_only_and_non_authorizing() -> None:
    result = validate_capability_contract(_contract())

    assert result["capability_contract_valid"] is True
    assert result["authorizes_formal"] is False
    assert result["formal_eligible"] is False
    assert result["qualification_credit"] == 0
    assert result["blockers"] == []


def test_formal_release_false_fails_closed_even_when_envelope_is_complete() -> None:
    result = validate_capability_contract(_contract(formal_release=False))

    assert result["checks"]["source_trust"] is True
    assert result["checks"]["descriptor_binding"] is True
    assert result["checks"]["identity_nonce"] is True
    assert result["checks"]["case_binding"] is True
    assert result["checks"]["formal_release"] is False
    assert result["capability_contract_valid"] is False
    assert "FORMAL_RELEASE_REQUIRED" in _codes(result)
    assert result["formal_eligible"] is False
    assert result["qualification_credit"] == 0


def test_missing_source_trust_fails_closed() -> None:
    contract = _contract()
    del contract["source_trust"]
    result = validate_capability_contract(contract)

    assert result["checks"]["source_trust"] is False
    assert "SOURCE_TRUST_REQUIRED" in _codes(result)
    assert result["formal_eligible"] is False


def test_missing_manifest_binding_fails_closed() -> None:
    contract = _contract()
    del contract["manifest_identity"]
    result = validate_capability_contract(contract)

    assert result["checks"]["manifest_binding"] is False
    assert "MANIFEST_BINDING_REQUIRED" in _codes(result)
    assert result["qualification_credit"] == 0


def test_source_snapshot_rebind_fails_closed() -> None:
    contract = _contract()
    contract["case_bindings"][1]["source_sha256"] = _sha("replacement-source")
    result = validate_capability_contract(contract)

    assert result["checks"]["case_binding"] is False
    assert "DESCRIPTOR_REBIND" in _codes(result)
    assert result["qualification_credit"] == 0


def test_geometry_descriptor_rebind_fails_closed() -> None:
    contract = _contract()
    contract["case_bindings"][0]["geometry_sha256"] = _sha("replacement-geometry")
    result = validate_capability_contract(contract)

    assert result["checks"]["case_binding"] is False
    assert "DESCRIPTOR_REBIND" in _codes(result)
    assert result["formal_eligible"] is False


def test_missing_or_duplicate_identity_nonce_fails_closed() -> None:
    contract = _contract()
    contract["identities"]["worker"].pop("nonce")
    result = validate_capability_contract(contract)
    assert result["checks"]["identity_nonce"] is False
    assert "IDENTITY_NONCE_REQUIRED" in _codes(result)

    duplicate = _contract()
    duplicate["identities"]["worker"]["nonce"] = duplicate["identities"]["broker"]["nonce"]
    duplicate_result = validate_capability_contract(duplicate)
    assert duplicate_result["checks"]["identity_nonce"] is False
    assert "IDENTITY_NONCE_REQUIRED" in _codes(duplicate_result)


def test_manifest_inventory_never_promotes_metadata_to_capability() -> None:
    manifest = json.loads(F3_MANIFEST.read_text(encoding="utf-8"))
    report = inspect_manifest(manifest)

    assert report["manifest"]["declared_formal_release"] is False
    assert report["observed_capabilities"]["source_hash_and_byte_metadata"] is True
    assert report["observed_capabilities"]["content_addressed_geometry_control_metadata"] is True
    assert report["observed_capabilities"]["held_fd_snapshot_capability"] is False
    assert report["observed_capabilities"]["producer_broker_worker_identity_chain"] is False
    assert report["formal_eligible"] is False
    assert report["qualification_credit"] == 0
    assert "CAPABILITY_CONTRACT_REQUIRED" in _codes(report)
    assert "FORMAL_RELEASE_REQUIRED" in _codes(report)


def test_validation_does_not_mutate_contract() -> None:
    contract = _contract()
    before = deepcopy(contract)

    validate_capability_contract(contract)

    assert contract == before


def test_malformed_case_identity_fails_closed_without_type_error() -> None:
    contract = _contract()
    contract["source_trust"]["case_snapshots"][0]["case_id"] = {"not": "hashable"}
    result = validate_capability_contract(contract)

    assert result["checks"]["source_trust"] is False
    assert result["formal_eligible"] is False

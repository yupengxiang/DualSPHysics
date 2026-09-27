"""Synthetic negative tests for the isolated strict F3 reader capability sidecar."""

from __future__ import annotations

from copy import deepcopy
import hashlib

from scripts.f3_formal_reader_capability_contract_v1 import CONTRACT_SCHEMA
from scripts.f3_formal_reader_strict_capability_contract_v1 import (
    REPORT_SCHEMA,
    STRICT_CONTRACT_SCHEMA,
    canonical_sha256,
    validate_strict_capability_contract,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _nonce(label: str) -> str:
    return _sha("nonce:" + label)


def _base_contract(*, formal_release: bool = True) -> dict:
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


def _fd_identity(index: int, size: int) -> dict[str, int]:
    return {"st_dev": 2, "st_ino": 100 + index, "st_size": size}


def _strict_contract(*, formal_release: bool = True) -> dict:
    base = _base_contract(formal_release=formal_release)
    snapshots = base["source_trust"]["case_snapshots"]
    source_inventory_sha256 = canonical_sha256([
        {
            "case_id": row["case_id"],
            "source_sha256": row["source_sha256"],
            "bytes": row["bytes"],
            "fd_identity": row["fd_identity"],
            "measurement": row["measurement"],
        }
        for row in sorted(snapshots, key=lambda item: item["case_id"])
    ])
    session = {
        "session_id": "session-f3-synthetic",
        "session_nonce": _nonce("strict-session"),
        "source_snapshot_nonce": base["source_trust"]["snapshot_nonce"],
        "source_inventory_sha256": source_inventory_sha256,
    }
    attempt = {
        "attempt_id": "attempt-f3-synthetic-001",
        "attempt_nonce": _nonce("strict-attempt-001"),
        "session_id": session["session_id"],
        "session_nonce": session["session_nonce"],
        "source_snapshot_nonce": session["source_snapshot_nonce"],
        "descriptor_bundle_id": "bundle-f3-synthetic-001",
    }
    cases = []
    tokens = []
    for index, snapshot in enumerate(snapshots):
        source_token = f"fd:source-{index}"
        geometry_token = f"fd:geometry-{index}"
        control_token = f"fd:control-{index}"
        tokens.extend((source_token, geometry_token, control_token))
        common = {
            "bundle_id": attempt["descriptor_bundle_id"],
            "session_id": session["session_id"],
            "session_nonce": session["session_nonce"],
            "source_snapshot_nonce": session["source_snapshot_nonce"],
            "attempt_id": attempt["attempt_id"],
            "attempt_nonce": attempt["attempt_nonce"],
            "access_mode": "held_fd_only",
            "path_reopen": False,
            "path_rebind": False,
        }
        source = {
            "case_id": snapshot["case_id"],
            "source_sha256": snapshot["source_sha256"],
            "bytes": snapshot["bytes"],
            "fd_identity": dict(snapshot["fd_identity"]),
            "fd_token": source_token,
            **common,
        }
        descriptors = {}
        for role, token, fd_index in (
            ("geometry", geometry_token, 10 + index * 2),
            ("control", control_token, 11 + index * 2),
        ):
            registered = base["descriptors"][role]
            descriptors[role] = {
                "role": role,
                "case_id": snapshot["case_id"],
                "sha256": registered["sha256"],
                "version": registered["version"],
                "fd_identity": _fd_identity(fd_index, 200 + fd_index),
                "fd_token": token,
                "source_fd_token": source_token,
                "source_sha256": snapshot["source_sha256"],
                **common,
            }
        cases.append({
            "case_id": snapshot["case_id"],
            "source": source,
            "descriptors": descriptors,
        })
    tokens = sorted(tokens)
    history = {
        "attempt_id": attempt["attempt_id"],
        "attempt_nonce": attempt["attempt_nonce"],
        "session_id": session["session_id"],
        "session_nonce": session["session_nonce"],
        "source_snapshot_nonce": session["source_snapshot_nonce"],
        "descriptor_bundle_id": attempt["descriptor_bundle_id"],
        "fd_tokens": tokens,
        "fd_token_digest": canonical_sha256(tokens),
        "status": "current",
    }
    return {
        "schema": STRICT_CONTRACT_SCHEMA,
        "formal_release": formal_release,
        "base_contract": base,
        "session": session,
        "attempt": attempt,
        "descriptor_bundle": {
            "bundle_id": attempt["descriptor_bundle_id"],
            "session_id": session["session_id"],
            "session_nonce": session["session_nonce"],
            "source_snapshot_nonce": session["source_snapshot_nonce"],
            "attempt_id": attempt["attempt_id"],
            "attempt_nonce": attempt["attempt_nonce"],
            "access_mode": "held_fd_only",
            "path_reopen": False,
            "path_rebind": False,
            "cases": cases,
        },
        "attempt_history": [history],
    }


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["blockers"]}


def test_complete_strict_envelope_checks_bindings_but_never_authorizes() -> None:
    result = validate_strict_capability_contract(_strict_contract())

    assert result["schema"] == REPORT_SCHEMA
    assert result["strict_capability_contract_valid"] is True
    assert all(result["checks"].values())
    assert result["authorizes_formal"] is False
    assert result["formal_eligible"] is False
    assert result["qualification_credit"] == 0
    assert result["execution_constraints"]["opens_source_fd"] is False
    assert result["execution_constraints"]["starts_worker"] is False


def test_same_bundle_binds_source_fd_identity_nonce_and_session() -> None:
    contract = _strict_contract()
    contract["descriptor_bundle"]["cases"][1]["source"]["fd_identity"]["st_ino"] += 1

    result = validate_strict_capability_contract(contract)

    assert result["checks"]["descriptor_bundle"] is False
    assert "SOURCE_IDENTITY_BINDING_REQUIRED" in _codes(result)
    assert result["formal_eligible"] is False


def test_descriptor_source_nonce_or_session_rebind_fails_closed() -> None:
    contract = _strict_contract()
    descriptor = contract["descriptor_bundle"]["cases"][0]["descriptors"]["geometry"]
    descriptor["session_nonce"] = _nonce("different-session")

    result = validate_strict_capability_contract(contract)

    assert result["checks"]["descriptor_bundle"] is False
    assert "DESCRIPTOR_SOURCE_BINDING_REQUIRED" in _codes(result)
    assert result["qualification_credit"] == 0


def test_descriptor_source_fd_token_must_match_exact_case_source_fd() -> None:
    contract = _strict_contract()
    descriptor = contract["descriptor_bundle"]["cases"][0]["descriptors"]["geometry"]
    descriptor["source_fd_token"] = "fd:source-1"

    result = validate_strict_capability_contract(contract)

    assert result["checks"]["descriptor_bundle"] is False
    assert "DESCRIPTOR_SOURCE_BINDING_REQUIRED" in _codes(result)
    assert result["formal_eligible"] is False


def test_path_reopen_and_path_rebind_are_forbidden_even_with_matching_hashes() -> None:
    contract = _strict_contract()
    contract["descriptor_bundle"]["cases"][0]["descriptors"]["control"]["path"] = \
        "inputs/control.npz"

    result = validate_strict_capability_contract(contract)

    assert "PATH_REOPEN_FORBIDDEN" in _codes(result)
    assert result["checks"]["descriptor_bundle"] is False
    assert result["execution_constraints"]["reopens_by_path"] is False


def test_positive_path_rebind_flag_is_forbidden() -> None:
    contract = _strict_contract()
    contract["descriptor_bundle"]["path_rebind"] = True

    result = validate_strict_capability_contract(contract)

    assert "PATH_REOPEN_FORBIDDEN" in _codes(result)
    assert result["checks"]["descriptor_bundle"] is False


def test_exact_fields_reject_missing_descriptor_and_extra_history_members() -> None:
    missing = _strict_contract()
    del missing["descriptor_bundle"]["cases"][0]["descriptors"]["geometry"]["source_fd_token"]
    missing_result = validate_strict_capability_contract(missing)
    assert missing_result["checks"]["descriptor_bundle"] is False
    assert "DESCRIPTOR_BUNDLE_REQUIRED" in _codes(missing_result)

    extra = _strict_contract()
    extra["attempt_history"][0]["unexpected"] = "reject"
    extra_result = validate_strict_capability_contract(extra)
    assert extra_result["checks"]["replay_guard"] is False
    assert "ATTEMPT_REPLAY" in _codes(extra_result)


def test_top_level_exact_fields_reject_unregistered_claims() -> None:
    contract = _strict_contract()
    contract["unregistered_claim"] = True

    result = validate_strict_capability_contract(contract)

    assert "STRICT_CONTRACT_FIELDS" in _codes(result)
    assert result["strict_capability_contract_valid"] is False


def test_duplicate_attempt_history_fails_closed() -> None:
    contract = _strict_contract()
    contract["attempt_history"].append(deepcopy(contract["attempt_history"][0]))

    result = validate_strict_capability_contract(contract)

    assert result["checks"]["replay_guard"] is False
    assert "ATTEMPT_REPLAY" in _codes(result)
    assert result["formal_eligible"] is False


def test_cross_attempt_fd_bundle_replay_fails_closed() -> None:
    contract = _strict_contract()
    prior = deepcopy(contract["attempt_history"][0])
    prior["attempt_id"] = "attempt-f3-synthetic-000"
    prior["attempt_nonce"] = _nonce("strict-attempt-000")
    prior["descriptor_bundle_id"] = "bundle-f3-synthetic-000"
    prior["status"] = "consumed"
    contract["attempt_history"].insert(0, prior)

    result = validate_strict_capability_contract(contract)

    assert result["checks"]["replay_guard"] is False
    assert "ATTEMPT_REPLAY" in _codes(result)


def test_cross_attempt_nonce_reuse_fails_closed_even_with_new_fd_tokens() -> None:
    contract = _strict_contract()
    prior = deepcopy(contract["attempt_history"][0])
    prior["attempt_id"] = "attempt-f3-synthetic-000"
    prior["descriptor_bundle_id"] = "bundle-f3-synthetic-000"
    prior["status"] = "consumed"
    prior["fd_tokens"] = [f"fd:prior-{index}" for index in range(len(prior["fd_tokens"]))]
    prior["fd_token_digest"] = canonical_sha256(prior["fd_tokens"])
    # Reuse the active attempt nonce across two attempts.
    contract["attempt_history"].insert(0, prior)

    result = validate_strict_capability_contract(contract)

    assert result["checks"]["replay_guard"] is False
    assert "ATTEMPT_REPLAY" in _codes(result)


def test_formal_release_false_fails_closed_after_all_strict_bindings_pass() -> None:
    result = validate_strict_capability_contract(_strict_contract(formal_release=False))

    assert result["checks"]["base_contract"] is False
    assert result["checks"]["formal_release"] is False
    assert result["checks"]["descriptor_bundle"] is True
    assert result["checks"]["replay_guard"] is True
    assert "FORMAL_RELEASE_REQUIRED" in _codes(result)
    assert result["strict_capability_contract_valid"] is False
    assert result["formal_eligible"] is False
    assert result["qualification_credit"] == 0


def test_descriptor_token_alias_or_rebind_fails_closed() -> None:
    contract = _strict_contract()
    source = contract["descriptor_bundle"]["cases"][0]["source"]
    control = contract["descriptor_bundle"]["cases"][0]["descriptors"]["control"]
    control["fd_token"] = source["fd_token"]
    control["source_fd_token"] = source["fd_token"]

    result = validate_strict_capability_contract(contract)

    assert result["checks"]["descriptor_bundle"] is False
    assert "DESCRIPTOR_REBIND_FORBIDDEN" in _codes(result)


def test_validation_does_not_mutate_strict_contract() -> None:
    contract = _strict_contract()
    before = deepcopy(contract)

    validate_strict_capability_contract(contract)

    assert contract == before

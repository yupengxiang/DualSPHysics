"""Tests for the bounded, non-authorizing F4 receipt-pair contract."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f4_tallwall120_material_fresh_root_scheduler_receipt_contract_v1 as contract


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / contract.DEFAULT_REPORT


def _receipt_identity(path: Path) -> dict[str, object]:
    identity, error = contract._lstat_identity(path, label="test receipt", require_kind={"file"})
    assert error is None
    assert identity is not None
    return identity


def _root_path_identity() -> dict[str, object]:
    return {
        "path": str((ROOT / contract.DEFAULT_OUTPUT_NAMESPACE).resolve()),
        "device": 0,
        "inode": 0,
        "owner_uid": 0,
        "owner_name": "root",
        "nlink": 0,
        "mode": 0,
        "kind": "directory",
    }


def _side_effects() -> dict[str, object]:
    return {
        "worker_started": False,
        "solver_started": False,
        "native_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
        "plan_mutations": 0,
    }


def _candidate_pair(tmp_path: Path) -> tuple[Path, Path]:
    base = contract.build_report(ROOT)
    anchor = deepcopy(base["binding_contract"])
    nonce = "ab" * 32
    binding = contract._binding_for_nonce(anchor, nonce)
    binding_sha256 = contract.canonical_digest(binding)
    root_path = tmp_path / "fresh-root-receipt.json"
    scheduler_path = tmp_path / "scheduler-host-io-reservation.json"
    reservation_path = tmp_path / "scheduler-owned-host-io.lock"
    reservation_path.write_text("test-only synthetic reservation\n", encoding="utf-8")

    root_capability = dict(contract.CAPABILITY)
    root_capability.update(
        {
            "role": "fresh_root",
            "fresh_namespace_observed": True,
            "root_owned_verified": True,
        }
    )
    scheduler_capability = dict(contract.CAPABILITY)
    scheduler_capability.update(
        {
            "role": "scheduler",
            "scheduler_owned_host_io_verified": True,
        }
    )
    scheduler_path_identity = _receipt_identity(reservation_path)
    root_receipt = {
        "schema": contract.ROOT_RECEIPT_SCHEMA,
        "receipt_id": "f4-tallwall120-material-fresh-root-receipt-contract-v1",
        "kind": "fresh_root",
        "status": "fresh_root_observed",
        "synthetic": True,
        "pair_id": "f4-tallwall120-contract-test-pair",
        "nonce": nonce,
        "binding_sha256": binding_sha256,
        "pair_commitment_sha256": "0" * 64,
        "binding": binding,
        "receipt_identity": {},
        "fresh_root": {
            "namespace": contract.DEFAULT_OUTPUT_NAMESPACE,
            "namespace_path": str((ROOT / contract.DEFAULT_OUTPUT_NAMESPACE).resolve()),
            "path_identity": _root_path_identity(),
            "fresh": True,
            "reused": False,
            "overwrite_allowed": False,
            "resume_allowed": False,
            "single_use": True,
            "consumed": False,
        },
        "capability": root_capability,
        "counterparty": {},
        "side_effects": _side_effects(),
    }
    scheduler_receipt = {
        "schema": contract.SCHEDULER_RECEIPT_SCHEMA,
        "receipt_id": "f4-tallwall120-material-scheduler-receipt-contract-v1",
        "kind": "scheduler_host_io_reservation",
        "status": "scheduler_host_io_reservation_observed",
        "synthetic": True,
        "pair_id": root_receipt["pair_id"],
        "nonce": nonce,
        "binding_sha256": binding_sha256,
        "pair_commitment_sha256": "0" * 64,
        "binding": binding,
        "receipt_identity": {},
        "host_io_reservation": {
            "reservation_id": "f4-tallwall120-contract-test-reservation",
            "reservation_path": str(reservation_path.resolve()),
            "path_identity": scheduler_path_identity,
            "owner_role": "scheduler",
            "reservation_active": True,
            "scheduler_owned_host_io_verified": True,
            "resource_request": deepcopy(base["binding_contract"]["resource_request"]),
            "io_weight": 2,
            "owned_io_weight": 2,
            "io_capacity": 4,
            "filesystem": "test-only",
            "snapshot_id": "f4-tallwall120-contract-test-snapshot",
            "single_use": True,
            "consumed": False,
        },
        "capability": scheduler_capability,
        "counterparty": {},
        "side_effects": _side_effects(),
    }
    root_path.write_text(json.dumps(root_receipt, sort_keys=True) + "\n", encoding="utf-8")
    scheduler_path.write_text(json.dumps(scheduler_receipt, sort_keys=True) + "\n", encoding="utf-8")
    root_identity = _receipt_identity(root_path)
    scheduler_identity = _receipt_identity(scheduler_path)
    root_receipt["receipt_identity"] = root_identity
    scheduler_receipt["receipt_identity"] = scheduler_identity
    root_receipt["counterparty"] = {
        "path": str(scheduler_path.resolve()),
        "pair_id": root_receipt["pair_id"],
        "nonce": nonce,
        "binding_sha256": binding_sha256,
        "receipt_identity": scheduler_identity,
        "pair_commitment_sha256": "0" * 64,
    }
    scheduler_receipt["counterparty"] = {
        "path": str(root_path.resolve()),
        "pair_id": root_receipt["pair_id"],
        "nonce": nonce,
        "binding_sha256": binding_sha256,
        "receipt_identity": root_identity,
        "pair_commitment_sha256": "0" * 64,
    }
    root_path.write_text(json.dumps(root_receipt, sort_keys=True) + "\n", encoding="utf-8")
    scheduler_path.write_text(json.dumps(scheduler_receipt, sort_keys=True) + "\n", encoding="utf-8")
    return root_path, scheduler_path


def test_default_receipts_are_missing_and_fail_closed() -> None:
    report = contract.build_report(ROOT)

    assert report["status"] == contract.STATUS_MISSING
    assert contract.validate_report(report) == []
    checks = report["validation"]["checks"]
    assert checks["anchor_contract_valid"] is True
    assert checks["root_receipt_present"] is False
    assert checks["scheduler_receipt_present"] is False
    assert checks["root_owner_inode_path_bound"] is False
    assert checks["scheduler_owner_inode_path_bound"] is False
    assert checks["contract_valid"] is False
    assert report["authorization"] == contract._authorization()
    assert report["execution_controls"] == contract._execution_controls()


def test_candidate_pair_is_explicitly_synthetic_and_never_authorizing(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _candidate_pair(tmp_path)
    report = contract.build_report(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert report["status"] == contract.STATUS_INVALID
    assert report["validation"]["checks"]["pair_id_equal"] is True
    assert report["validation"]["checks"]["nonce_equal"] is True
    assert report["validation"]["checks"]["argv_hash_bound"] is True
    assert "root.synthetic" in report["validation"]["blockers"]
    assert "scheduler.synthetic" in report["validation"]["blockers"]
    assert report["authorization"] == contract._authorization()
    assert report["credit"] == 0


def test_nonce_drift_breaks_pair_binding(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _candidate_pair(tmp_path)
    payload = json.loads(scheduler_receipt.read_text(encoding="utf-8"))
    payload["nonce"] = "cd" * 32
    scheduler_receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    report = contract.build_report(ROOT, root_receipt_path=root_receipt, scheduler_receipt_path=scheduler_receipt)

    assert report["validation"]["checks"]["nonce_equal"] is False
    assert "pair.nonce_equal" in report["validation"]["blockers"]
    assert report["authorization"]["launch_allowed"] is False


def test_argv_hash_drift_is_visible(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _candidate_pair(tmp_path)
    payload = json.loads(root_receipt.read_text(encoding="utf-8"))
    payload["binding"]["normalized_launch_sha256"] = "0" * 64
    root_receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    report = contract.build_report(ROOT, root_receipt_path=root_receipt, scheduler_receipt_path=scheduler_receipt)

    assert report["validation"]["checks"]["argv_hash_bound"] is False
    assert "root.binding.value" in report["validation"]["blockers"]
    assert report["authorization"]["worker_launch_authorized"] is False


def test_capability_promotion_is_rejected(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _candidate_pair(tmp_path)
    payload = json.loads(root_receipt.read_text(encoding="utf-8"))
    payload["capability"]["launch_authorized"] = True
    root_receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    report = contract.build_report(ROOT, root_receipt_path=root_receipt, scheduler_receipt_path=scheduler_receipt)

    assert "capability.launch_authorized" in report["validation"]["blockers"]
    assert report["authorization"]["launch_allowed"] is False
    assert report["qualification_credit"] == 0


def test_receipt_inode_and_owner_path_identity_drift_is_rejected(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _candidate_pair(tmp_path)
    payload = json.loads(root_receipt.read_text(encoding="utf-8"))
    payload["receipt_identity"]["inode"] += 1
    payload["receipt_identity"]["owner_uid"] = 0
    root_receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    report = contract.build_report(ROOT, root_receipt_path=root_receipt, scheduler_receipt_path=scheduler_receipt)

    assert "root.receipt_identity.actual_mismatch" in report["validation"]["blockers"]
    assert report["validation"]["checks"]["root_receipt_contract_valid"] is False
    assert report["authorization"]["launch_allowed"] is False


def test_duplicate_json_and_symlink_receipts_fail_closed(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _candidate_pair(tmp_path)
    duplicate = root_receipt.read_text(encoding="utf-8")
    duplicate = duplicate.replace('"status": "fresh_root_observed",', '"status": "fresh_root_observed",\n  "status": "fresh_root_observed",', 1)
    root_receipt.write_text(duplicate, encoding="utf-8")
    report = contract.build_report(ROOT, root_receipt_path=root_receipt, scheduler_receipt_path=scheduler_receipt)
    assert report["receipts"]["fresh_root"]["error"] == "ValueError"
    assert report["authorization"]["formal"] is False

    symlink = tmp_path / "receipt-link.json"
    symlink.symlink_to(scheduler_receipt)
    linked = contract.build_report(ROOT, root_receipt_path=symlink, scheduler_receipt_path=scheduler_receipt)
    assert linked["receipts"]["fresh_root"]["exists"] is False
    assert linked["authorization"]["launch_allowed"] is False


def test_nonempty_fresh_namespace_is_rejected(tmp_path: Path) -> None:
    namespace = tmp_path / "fresh-namespace"
    namespace.mkdir()
    (namespace / "unexpected-entry").write_text("occupied\n", encoding="utf-8")
    identity, error = contract._lstat_identity(namespace, label="test fresh namespace", require_kind={"directory"})
    assert error is None and identity is not None

    empty, inspection_error = contract._directory_is_empty(
        namespace,
        identity,
        label="test fresh namespace",
    )

    assert empty is False
    assert inspection_error is None


def test_report_contract_derivation_cannot_be_promoted() -> None:
    report = contract.build_report(ROOT)
    report["status"] = contract.STATUS_BOUND
    report["validation"]["blockers"] = []
    report["validation"]["checks"]["contract_valid"] = True

    assert "report.validation.checks.contract_derivation" in contract.validate_report(report)


def test_report_writer_is_non_overwriting_and_checked_in_report_matches() -> None:
    report = contract.build_report(ROOT)
    assert contract.validate_report(report) == []
    if REPORT.is_file():
        checked_in = json.loads(REPORT.read_text(encoding="utf-8"))
        assert checked_in == report
        assert contract.validate_report(checked_in) == []

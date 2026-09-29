"""Focused tests for the F4 external fresh-root/scheduler intake boundary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import f4_tallwall120_material_external_receipt_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_default_external_receipts_are_missing_and_fail_closed() -> None:
    report = intake.build_report(ROOT)

    assert intake.validate_report(report) == []
    assert report["status"] == intake.STATUS_MISSING
    checks = report["validation"]["checks"]
    assert checks["anchor_contract_valid"] is True
    assert checks["source_claim_bound"] is True
    assert checks["current_code_hashes_valid"] is True
    assert checks["manifest_sha_valid"] is True
    assert checks["root_receipt_present"] is False
    assert checks["scheduler_receipt_present"] is False
    assert checks["external_intake_valid"] is False
    assert report["authorization"]["launch_allowed"] is False
    assert report["authorization"]["solver_authorized"] is False
    assert report["authorization"]["gpu_authorized"] is False
    assert report["credit"] == 0
    assert report["execution_controls"]["replay_guard_consumed"] is False


def test_current_source_is_metadata_only_and_code_manifest_are_rehashed() -> None:
    report = intake.build_report(ROOT)

    source = report["current_input_observation"]["source"]
    assert source["exists"] is True
    assert source["read"] is False
    assert source["hash_recomputed"] is False
    assert source["actual_bytes"] == intake.prior_contract.SOURCE_BYTES
    assert report["current_input_observation"]["manifest"]["actual_sha256"] == report["binding_contract"]["manifest"]["sha256"]
    assert report["validation"]["checks"]["current_code_hashes_valid"] is True
    assert report["validation"]["checks"]["manifest_sha_valid"] is True


def test_self_declared_old_receipt_shape_cannot_be_promoted(tmp_path: Path) -> None:
    root_receipt = _write_json(
        tmp_path / "root-receipt.json",
        {
            "schema": intake.prior_contract.ROOT_RECEIPT_SCHEMA,
            "synthetic": False,
            "root_authorization": {"root_authorized": True},
        },
    )
    scheduler_receipt = _write_json(
        tmp_path / "scheduler-receipt.json",
        {
            "schema": intake.prior_contract.SCHEDULER_RECEIPT_SCHEMA,
            "synthetic": False,
            "scheduler_reservation": {"scheduler_owned_host_io_verified": True},
        },
    )

    report = intake.build_report(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert report["status"] == intake.STATUS_INVALID
    assert report["validation"]["checks"]["root_producer_authenticated"] is False
    assert report["validation"]["checks"]["scheduler_producer_authenticated"] is False
    assert "root.fields" in report["validation"]["blockers"]
    assert "scheduler.fields" in report["validation"]["blockers"]
    assert report["authorization"]["external_receipts_verified"] is False
    assert report["authorization"]["launch_allowed"] is False


def test_receipt_inside_repository_is_not_external(tmp_path: Path) -> None:
    report = intake.build_report(
        ROOT,
        root_receipt_path=ROOT / intake.ANCHOR_REPORT,
        scheduler_receipt_path=ROOT / intake.ANCHOR_REPORT,
    )

    assert report["validation"]["checks"]["root_receipt_external_path"] is False
    assert report["validation"]["checks"]["scheduler_receipt_external_path"] is False
    assert report["authorization"]["launch_allowed"] is False
    assert report["credit"] == 0


def test_symlinked_external_receipt_is_rejected(tmp_path: Path) -> None:
    target = _write_json(tmp_path / "target.json", {})
    link = tmp_path / "receipt-link.json"
    link.symlink_to(target)
    report = intake.build_report(
        ROOT,
        root_receipt_path=link,
        scheduler_receipt_path=target,
    )

    assert report["status"] in {intake.STATUS_MISSING, intake.STATUS_INVALID}
    assert report["receipts"]["fresh_root"]["exists"] is False
    assert report["receipts"]["fresh_root"]["error"] == "symlink_path"
    assert report["authorization"]["solver_authorized"] is False


def test_consumed_replay_guard_is_rejected(tmp_path: Path) -> None:
    nonce = "ab" * 32
    pair_id = "f4-test-pair"
    guard_path = _write_json(
        tmp_path / "replay-guard.json",
        {
            "schema": intake.REPLAY_GUARD_SCHEMA,
            "record_id": intake.REPLAY_GUARD_ID,
            "role": "scheduler",
            "pair_id": pair_id,
            "attempt_id": intake.ATTEMPT_ID,
            "nonce": nonce,
            "lease_id": "lease-test",
            "state": "consumed",
            "single_use": True,
            "consumed": True,
            "producer_uid": os.getuid(),
        },
    )
    identity, error = intake._lstat_identity(guard_path, label="test replay guard", kinds={"file"})
    assert error is None and identity is not None
    ref = {
        "schema": intake.REPLAY_GUARD_SCHEMA,
        "record_id": intake.REPLAY_GUARD_ID,
        "path": str(guard_path.resolve()),
        "sha256": hashlib.sha256(guard_path.read_bytes()).hexdigest(),
        "identity": identity,
        "role": "scheduler",
        "pair_id": pair_id,
        "attempt_id": intake.ATTEMPT_ID,
        "nonce": nonce,
        "lease_id": "lease-test",
        "state": "consumed",
        "single_use": True,
        "consumed": True,
        "producer_uid": os.getuid(),
    }
    errors: list[str] = []
    valid, _ = intake._validate_replay_guard(
        ref,
        role="scheduler",
        pair_id=pair_id,
        attempt_id=intake.ATTEMPT_ID,
        nonce=nonce,
        producer_uid=os.getuid(),
        errors=errors,
    )

    assert valid is False
    assert "scheduler.replay_guard.reuse_or_consumed" in errors
    assert "scheduler.replay_guard.document.binding" in errors


def test_synthetic_host_snapshot_is_rejected(tmp_path: Path) -> None:
    nonce = "cd" * 32
    snapshot_path = _write_json(
        tmp_path / "host-snapshot.json",
        {
            "schema": intake.HOST_SNAPSHOT_SCHEMA,
            "record_id": intake.HOST_SNAPSHOT_ID,
            "synthetic": True,
            "snapshot_id": "snapshot-test",
            "pair_id": "f4-test-pair",
            "attempt_id": intake.ATTEMPT_ID,
            "nonce": nonce,
            "host": {
                "hostname": "test-host",
                "boot_id": "boot-test",
                "captured_at_utc": "2026-09-29T00:00:00Z",
            },
            "resources": {
                "cpu_count": 8,
                "ram_total_mib": 65536,
                "ram_available_mib": 32768,
                "disk_free_bytes": intake.MIN_FREE_DISK_BYTES,
                "io_capacity": 4,
                "filesystem": "testfs",
                "gpus": [],
                "gpu_processes": [],
            },
        },
    )
    identity, error = intake._lstat_identity(snapshot_path, label="test host snapshot", kinds={"file"})
    assert error is None and identity is not None
    ref = {
        "schema": intake.HOST_SNAPSHOT_SCHEMA,
        "record_id": intake.HOST_SNAPSHOT_ID,
        "path": str(snapshot_path.resolve()),
        "sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        "identity": identity,
        "snapshot_id": "snapshot-test",
        "pair_id": "f4-test-pair",
        "attempt_id": intake.ATTEMPT_ID,
        "nonce": nonce,
    }
    reservation = {
        "snapshot_id": "snapshot-test",
        "filesystem": "testfs",
        "selected_gpu_uuid": None,
    }
    errors: list[str] = []
    valid, _, _ = intake._validate_snapshot(
        ref,
        pair_id="f4-test-pair",
        attempt_id=intake.ATTEMPT_ID,
        nonce=nonce,
        reservation=reservation,
        expected_resources={"cpu_cores": 2, "ram_mib": 1024, "gpu_peak_mib": 0, "io_weight": 2},
        errors=errors,
    )

    assert valid is False
    assert "scheduler.host_resource_snapshot.document.synthetic" in errors


def test_report_writer_and_authorization_are_closed(tmp_path: Path) -> None:
    report = intake.build_report(ROOT)
    destination = tmp_path / "external-intake.json"
    assert intake.write_report(report, destination) == destination
    assert intake.validate_report(json.loads(destination.read_text(encoding="utf-8"))) == []
    with pytest.raises(FileExistsError):
        intake.write_report(report, destination)

    promoted = json.loads(destination.read_text(encoding="utf-8"))
    promoted["authorization"]["launch_allowed"] = True
    assert "report.authorization.execution_closed" in intake.validate_report(promoted)

    falsely_verified = json.loads(destination.read_text(encoding="utf-8"))
    falsely_verified["authorization"]["external_receipts_verified"] = True
    assert "report.authorization.external_receipts_verified" in intake.validate_report(falsely_verified)

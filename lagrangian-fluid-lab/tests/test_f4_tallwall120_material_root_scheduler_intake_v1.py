"""Focused tests for the F4 material root/scheduler admission intake."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f4_tallwall120_material_root_scheduler_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / intake.DEFAULT_REPORT
ZH_REPORT = ROOT / intake.DEFAULT_ZH_REPORT


def _side_effects() -> dict[str, object]:
    return {
        "worker_started": False,
        "solver_started": False,
        "native_started": False,
        "gpu_started": False,
        "queue_mutations": 0,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "plan_mutations": 0,
        "production_hdf5_mutations": 0,
    }


def _valid_receipts(tmp_path: Path) -> tuple[Path, Path]:
    base = intake.build_report(ROOT)
    input_names = (
        "proposal", "host_io_projection", "case_sidecar_intake", "collection", "reader",
        "archive_v1", "archive", "archive_reader_reconciliation", "consistency", "job_spec", "runtime_status", "material",
        "material_diagnosis", "collector", "runtime", "cfd_runner",
    )
    binding = {
        "input_refs": {
            name: {
                "path": base["input_bindings"][name]["path"],
                "sha256": base["input_bindings"][name]["sha256"],
            }
            for name in input_names
        },
        "hashes": deepcopy(base["binding_projection"]["hashes"]),
        "source_identity": deepcopy(base["binding_projection"]["source_identity"]),
        "normalized_launch": deepcopy(base["binding_projection"]["normalized_launch"]),
        "normalized_launch_sha256": base["binding_projection"]["normalized_launch_sha256"],
        "fresh_output_namespace": {
            "namespace": intake.DEFAULT_OUTPUT_NAMESPACE,
            "namespace_path": intake.DEFAULT_OUTPUT_NAMESPACE,
            "namespace_nonce": "ab" * 32,
            "fresh": True,
            "reused": False,
            "same_attempt_resume_only": True,
            "historical_trace_reuse_forbidden": True,
        },
    }
    binding["fresh_output_namespace_sha256"] = intake._canonical_digest(
        binding["fresh_output_namespace"]
    )
    root_path = tmp_path / "fresh-root-receipt.json"
    scheduler_path = tmp_path / "scheduler-host-io-reservation.json"
    root_binding = deepcopy(binding)
    scheduler_binding = deepcopy(binding)
    pair_id = "f4-material-pair-20260928-01"
    root_receipt = {
        "schema": intake.ROOT_RECEIPT_SCHEMA,
        "record_id": intake.ROOT_RECEIPT_ID,
        "status": "root_authorization_issued",
        "pair_id": pair_id,
        "synthetic": False,
        "binding": root_binding,
        "counterparty": {
            "path": str(scheduler_path.resolve()),
            "binding_sha256": intake._canonical_digest(scheduler_binding),
            "pair_id": pair_id,
        },
        "fresh_root": {
            "namespace": intake.DEFAULT_OUTPUT_NAMESPACE,
            "created": True,
            "reused": False,
            "root_owned": True,
        },
        "root_authorization": {
            "authorization_id": "f4-root-auth-20260928-01",
            "root_authorized": True,
            "single_use": True,
            "consumed": False,
        },
        "side_effects": _side_effects(),
    }
    scheduler_receipt = {
        "schema": intake.SCHEDULER_RECEIPT_SCHEMA,
        "record_id": intake.SCHEDULER_RECEIPT_ID,
        "status": "scheduler_host_io_reserved",
        "pair_id": pair_id,
        "synthetic": False,
        "binding": scheduler_binding,
        "counterparty": {
            "path": str(root_path.resolve()),
            "binding_sha256": intake._canonical_digest(root_binding),
            "pair_id": pair_id,
        },
        "scheduler_reservation": {
            "reservation_id": "f4-scheduler-reservation-20260928-01",
            "reservation_active": True,
            "scheduler_owned_host_io_verified": True,
            "resource_request": deepcopy(base["binding_projection"]["resource_request"]),
            "host_io_reservation": {
                "io_weight": 2,
                "owned_io_weight": 2,
                "io_capacity": 4,
                "filesystem": "ext4:/dev/nvme0n1p2",
                "snapshot_id": "f4-scheduler-snapshot-20260928-01",
            },
            "single_use": True,
            "consumed": False,
        },
        "side_effects": _side_effects(),
    }
    root_path.write_text(json.dumps(root_receipt, sort_keys=True) + "\n", encoding="utf-8")
    scheduler_path.write_text(json.dumps(scheduler_receipt, sort_keys=True) + "\n", encoding="utf-8")
    return root_path, scheduler_path


def test_default_external_receipts_are_missing_and_fail_closed() -> None:
    value = intake.build_report(ROOT)

    assert intake.validate_report(value) == []
    assert value["status"] == intake.STATUS_MISSING
    checks = value["validation"]["checks"]
    assert checks["proposal_contract_valid"] is True
    assert checks["host_io_projection_contract_valid"] is True
    assert checks["case_sidecar_intake_contract_valid"] is True
    assert checks["current_code_hashes_valid"] is True
    assert checks["future_root_receipt_present"] is False
    assert checks["future_scheduler_receipt_present"] is False
    assert checks["intake_contract_valid"] is False
    assert value["diagnostic_only"] is True
    assert value["formal"] is False
    assert value["T1"] is False
    assert value["T2"] is False
    assert value["credit"] == 0
    assert value["authorization"] == intake._authorization()


def test_source_hdf5_is_metadata_only_and_current_identity_drift_is_visible() -> None:
    value = intake.build_report(ROOT)
    source = value["input_bindings"]["source_hdf5"]
    source_identity = value["binding_projection"]["source_identity"]

    assert source["exists"] is True
    assert source["bytes"] == intake.SOURCE_BYTES
    assert source["read"] is False
    assert source["opened_as_hdf5"] is False
    assert source["hash_recomputed"] is False
    assert value["validation"]["checks"]["source_hdf5_metadata_only_valid"] is True
    assert source_identity["collection"]["path_exact"] is False
    assert source_identity["reader"]["manifest_sha_exact"] is False
    assert value["validation"]["checks"]["source_identity_contract_valid"] is False
    assert value["validation"]["checks"]["archive_reader_reconciliation_bound"] is True


def test_source_hdf5_never_reaches_bounded_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = intake.os.open
    source_path = str((ROOT / intake.SOURCE_HDF5).absolute())

    def guarded_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if str(path) == source_path:
            raise AssertionError("trajectory HDF5 must not be opened")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(intake.os, "open", guarded_open)
    value = intake.build_report(ROOT)
    assert value["input_bindings"]["source_hdf5"]["read"] is False


def test_structurally_complete_pair_is_cross_bound_but_not_authorizing(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    value = intake.build_report(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert intake.validate_report(value) == []
    assert value["status"] == intake.STATUS_INVALID
    checks = value["validation"]["checks"]
    assert checks["future_root_receipt_valid"] is True
    assert checks["future_scheduler_receipt_valid"] is True
    assert checks["receipt_pair_cross_binding_valid"] is True
    assert checks["scheduler_owned_host_io_reservation_valid"] is True
    assert checks["intake_contract_valid"] is False
    assert value["authorization"]["launch_admitted"] is False
    assert value["authorization"]["formal"] is False
    assert value["authorization"]["credit"] == 0


def test_root_binding_hash_drift_is_rejected(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    payload = json.loads(root_receipt.read_text(encoding="utf-8"))
    payload["binding"]["hashes"]["runtime_sha256"] = "0" * 64
    root_receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    value = intake.build_report(ROOT, root_receipt_path=root_receipt, scheduler_receipt_path=scheduler_receipt)

    assert value["status"] == intake.STATUS_INVALID
    assert value["validation"]["checks"]["future_root_receipt_valid"] is False
    assert value["authorization"]["worker_launch_authorized"] is False


def test_scheduler_resource_drift_is_rejected(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    payload = json.loads(scheduler_receipt.read_text(encoding="utf-8"))
    payload["scheduler_reservation"]["resource_request"]["gpu_peak_mib"] = 1
    scheduler_receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    value = intake.build_report(ROOT, root_receipt_path=root_receipt, scheduler_receipt_path=scheduler_receipt)

    assert value["status"] == intake.STATUS_INVALID
    assert value["validation"]["checks"]["future_scheduler_receipt_valid"] is False
    assert value["validation"]["checks"]["scheduler_owned_host_io_reservation_valid"] is False
    assert value["authorization"]["credit"] == 0


def test_duplicate_json_receipt_is_rejected(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    raw = root_receipt.read_text(encoding="utf-8")
    raw = raw.replace('"status": "root_authorization_issued",', '"status": "root_authorization_issued",\n  "status": "root_authorization_issued",', 1)
    root_receipt.write_text(raw, encoding="utf-8")
    value = intake.build_report(ROOT, root_receipt_path=root_receipt, scheduler_receipt_path=scheduler_receipt)

    assert value["status"] == intake.STATUS_INVALID
    assert value["input_bindings"]["fresh_root_receipt"]["error"] == "duplicate_json_key"
    assert value["authorization"]["formal"] is False


def test_nonfinite_json_number_is_rejected(tmp_path: Path) -> None:
    document = tmp_path / "nonfinite.json"
    document.write_text('{"value": 1e999}\n', encoding="utf-8")

    value, reference, error = intake._read_json_document(
        tmp_path,
        document,
        role="test nonfinite JSON",
    )

    assert value is None
    assert error is not None
    assert reference["error"] == "non_strict_json"


def test_source_parent_symlink_is_rejected_without_reading_hdf5(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    source = real_parent / "trajectory.h5"
    source.write_bytes(b"metadata-only fixture")
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(real_parent, target_is_directory=True)

    result, error = intake._source_metadata(
        tmp_path,
        alias_parent / source.name,
        declared_sha256=intake.SOURCE_SHA256,
        declared_bytes=len(source.read_bytes()),
    )

    assert result["read"] is False
    assert result["opened_as_hdf5"] is False
    assert result["error"] == "symlink_path"
    assert error is not None


def test_report_contract_derivation_cannot_be_promoted() -> None:
    report = intake.build_report(ROOT)
    report["status"] = intake.STATUS_BOUND
    report["validation"]["blockers"] = []
    report["validation"]["checks"]["intake_contract_valid"] = True

    assert "validation.checks.contract_derivation" in intake.validate_report(report)


def test_report_writers_do_not_overwrite(tmp_path: Path) -> None:
    value = intake.build_report(ROOT)
    destination = tmp_path / "intake.json"
    zh_destination = tmp_path / "intake.zh-CN.md"
    assert intake.write_report(value, destination) == destination
    assert intake.write_zh_cn(value, zh_destination) == zh_destination
    assert json.loads(destination.read_text(encoding="utf-8")) == value
    assert zh_destination.read_text(encoding="utf-8").startswith("# F4 Tallwall120")
    with pytest.raises(FileExistsError):
        intake.write_report(value, destination)
    with pytest.raises(FileExistsError):
        intake.write_zh_cn(value, zh_destination)


def test_committed_reports_bind_build_report() -> None:
    if not REPORT.is_file():
        pytest.skip("committed report is generated after the implementation test run")
    value = json.loads(REPORT.read_text(encoding="utf-8"))
    assert value == intake.build_report(ROOT)
    assert intake.validate_report(value) == []
    assert value["status"] == intake.STATUS_MISSING
    assert ZH_REPORT.read_text(encoding="utf-8").startswith("# F4 Tallwall120")

"""Focused tests for the bounded F3 root/scheduler receipt intake."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import f3_material_coarse_root_scheduler_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / intake.DEFAULT_REPORT
ZH_REPORT = ROOT / intake.DEFAULT_ZH_CN


def _side_effects() -> dict[str, object]:
    return {
        "worker_started": False,
        "solver_started": False,
        "gpu_started": False,
        "queue_mutations": 0,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "plan_mutations": 0,
    }


def _valid_receipts(tmp_path: Path) -> tuple[Path, Path]:
    base = intake.build_report(ROOT)
    binding = {
        "proposal": {
            "path": base["input_bindings"]["proposal"]["path"],
            "sha256": base["input_bindings"]["proposal"]["sha256"],
        },
        "host_io_admission": {
            "path": base["input_bindings"]["host_io_admission"]["path"],
            "sha256": base["input_bindings"]["host_io_admission"]["sha256"],
        },
        "hashes": deepcopy(base["binding_projection"]["hashes"]),
        "normalized_launch": deepcopy(base["binding_projection"]["normalized_launch"]),
        "normalized_launch_sha256": base["binding_projection"]["normalized_launch_sha256"],
        "fresh_attempt_namespace": {
            "attempt_root": base["binding_projection"]["proposal_namespace_contract"]["attempt_root"],
            "attempt_id": "fresh-test-20260928-01",
            "attempt_path": base["binding_projection"]["proposal_namespace_contract"]["attempt_root"]
            + "/fresh-test-20260928-01",
            "namespace_template": base["binding_projection"]["proposal_namespace_contract"]["namespace_template"],
            "namespace_nonce": "ab" * 32,
            "fresh": True,
            "reused": False,
            "same_attempt_resume_only": True,
            "historical_attempt_reuse_forbidden": True,
        },
    }
    binding["fresh_attempt_namespace_sha256"] = intake._canonical_digest(
        binding["fresh_attempt_namespace"]
    )
    pair_id = "f3-coarse-pair-20260928-01"
    root_path = tmp_path / "fresh-root-receipt.json"
    scheduler_path = tmp_path / "scheduler-host-io-reservation.json"
    root_binding = deepcopy(binding)
    scheduler_binding = deepcopy(binding)
    root_receipt = {
        "schema": intake.ROOT_RECEIPT_SCHEMA,
        "record_id": intake.ROOT_RECEIPT_ID,
        "status": "root_authorization_issued",
        "pair_id": pair_id,
        "synthetic": False,
        "binding": root_binding,
        "counterparty": {
            "path": str(scheduler_path),
            "binding_sha256": intake._canonical_digest(scheduler_binding),
            "pair_id": pair_id,
        },
        "fresh_root": {
            "attempt_id": binding["fresh_attempt_namespace"]["attempt_id"],
            "attempt_path": binding["fresh_attempt_namespace"]["attempt_path"],
            "created": True,
            "reused": False,
            "root_owned": True,
        },
        "root_authorization": {
            "authorization_id": "root-auth-20260928-01",
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
            "path": str(root_path),
            "binding_sha256": intake._canonical_digest(root_binding),
            "pair_id": pair_id,
        },
        "scheduler_reservation": {
            "reservation_id": "scheduler-reservation-20260928-01",
            "reservation_active": True,
            "scheduler_owned_host_io_verified": True,
            "resource_request": {
                "cpu_cores": 2,
                "ram_mib": 4096,
                "gpu_peak_mib": 0,
                "io_weight": 0.1,
            },
            "host_io_reservation": {
                "io_weight": 0.1,
                "owned_io_weight": 0.1,
                "io_capacity": 1.0,
                "filesystem": "ext4:/dev/nvme0n1p2",
                "snapshot_id": "scheduler-snapshot-20260928-01",
            },
            "single_use": True,
            "consumed": False,
        },
        "side_effects": _side_effects(),
    }
    root_path.write_text(json.dumps(root_receipt, sort_keys=True) + "\n", encoding="utf-8")
    scheduler_path.write_text(json.dumps(scheduler_receipt, sort_keys=True) + "\n", encoding="utf-8")
    return root_path, scheduler_path


def test_default_future_receipts_are_missing_and_fail_closed() -> None:
    value = intake.build_report(ROOT)

    assert intake.validate_report(value) == []
    assert value["status"] == intake.STATUS_MISSING
    checks = value["validation"]["checks"]
    assert checks["proposal_contract_valid"] is True
    assert checks["host_io_admission_contract_valid"] is True
    assert checks["current_hashes_valid"] is True
    assert checks["source_hash_only_boundary_valid"] is True
    assert checks["future_root_receipt_present"] is False
    assert checks["future_scheduler_receipt_present"] is False
    assert checks["intake_contract_valid"] is False
    assert value["diagnostic_only"] is True
    assert value["formal"] is False
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["qualification"] is False
    assert value["credit"] == 0
    assert value["authorization"] == intake._authorization()
    assert value["input_bindings"]["source_h5"]["opened_as_hdf5"] is False
    assert value["input_bindings"]["source_h5"]["hash_recomputed"] is False
    assert value["execution_controls"]["source_hdf5_read"] is False
    assert value["execution_controls"]["source_hdf5_hash_recomputed"] is False


def test_structurally_complete_pair_is_bound_but_never_authorizing(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    value = intake.build_report(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert intake.validate_report(value) == []
    assert value["status"] == intake.STATUS_BOUND
    checks = value["validation"]["checks"]
    assert checks["future_root_receipt_valid"] is True
    assert checks["future_scheduler_receipt_valid"] is True
    assert checks["receipt_pair_cross_binding_valid"] is True
    assert checks["fresh_attempt_namespace_valid"] is True
    assert checks["scheduler_owned_host_io_reservation_valid"] is True
    assert checks["intake_contract_valid"] is True
    assert value["binding_projection"]["scheduler_owned_host_io_verified"] is True
    assert value["authorization"]["diagnostic_only"] is True
    assert value["authorization"]["formal"] is False
    assert value["authorization"]["T2_macro"] is False
    assert value["authorization"]["T2_path"] is False
    assert value["authorization"]["qualification"] is False
    assert value["authorization"]["credit"] == 0
    assert value["diagnostic_only"] is True
    assert value["formal"] is False
    assert value["T2_credit"] == 0
    assert value["execution_controls"]["worker_started"] is False
    assert value["execution_controls"]["queue_started"] is False


def test_root_binding_drift_is_rejected_without_launch(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    value = json.loads(root_receipt.read_text(encoding="utf-8"))
    value["binding"]["hashes"]["core_runtime_sha256"] = "0" * 64
    root_receipt.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    report = intake.build_report(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert report["status"] == intake.STATUS_INVALID
    assert report["validation"]["checks"]["future_root_receipt_valid"] is False
    assert report["validation"]["checks"]["intake_contract_valid"] is False
    assert report["authorization"]["launch_admitted"] is False
    assert report["authorization"]["credit"] == 0


def test_scheduler_resource_drift_is_rejected(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    value = json.loads(scheduler_receipt.read_text(encoding="utf-8"))
    value["scheduler_reservation"]["resource_request"]["gpu_peak_mib"] = 1
    scheduler_receipt.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    report = intake.build_report(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert report["status"] == intake.STATUS_INVALID
    assert report["validation"]["checks"]["future_scheduler_receipt_valid"] is False
    assert report["validation"]["checks"]["scheduler_owned_host_io_reservation_valid"] is False
    assert report["authorization"]["worker_launch_authorized"] is False


def test_scheduler_owned_io_must_cover_requested_weight(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    value = json.loads(scheduler_receipt.read_text(encoding="utf-8"))
    value["scheduler_reservation"]["host_io_reservation"]["owned_io_weight"] = 0.0
    scheduler_receipt.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    report = intake.build_report(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert report["status"] == intake.STATUS_INVALID
    assert report["validation"]["checks"]["future_scheduler_receipt_valid"] is False
    assert report["validation"]["checks"]["scheduler_owned_host_io_reservation_valid"] is False
    assert "scheduler_receipt.host_io_reservation.owned_io_weight" in report[
        "validation"
    ]["scheduler_receipt_errors"]
    assert report["authorization"]["launch_admitted"] is False
    assert report["credit"] == 0


def test_existing_host_admission_normalized_launch_drift_is_rejected(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    host = json.loads((ROOT / intake.HOST_IO_ADMISSION).read_text(encoding="utf-8"))
    host["proposal_observation"]["normalized_launch"]["cwd"] = "/tmp/not-the-lab"
    host_path = tmp_path / "host-admission-drift.json"
    host_path.write_text(json.dumps(host, sort_keys=True) + "\n", encoding="utf-8")
    report = intake.build_report(
        ROOT,
        host_io_admission_path=host_path,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert report["status"] == intake.STATUS_INVALID
    assert report["validation"]["checks"]["host_io_admission_contract_valid"] is False
    assert report["validation"]["checks"]["intake_contract_valid"] is False
    assert report["authorization"]["formal"] is False


def test_duplicate_json_receipt_is_rejected(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    raw = root_receipt.read_text(encoding="utf-8")
    root_receipt.write_text(raw.replace('"status": "root_authorization_issued",', '"status": "root_authorization_issued",\n  "status": "root_authorization_issued",', 1), encoding="utf-8")
    report = intake.build_report(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert report["status"] == intake.STATUS_INVALID
    assert report["input_bindings"]["fresh_root_receipt"]["error"] == "duplicate_json_key"
    assert report["authorization"]["formal"] is False


def test_source_path_is_metadata_only_and_report_binding_is_exact() -> None:
    value = intake.build_report(ROOT)
    committed = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.is_file() else value

    assert committed == value
    assert committed["input_bindings"]["source_h5"]["path"] == str(intake.SOURCE_H5)
    assert committed["input_bindings"]["source_h5"]["sha256"] == value["binding_projection"]["hashes"]["source_sha256"]
    assert committed["input_bindings"]["source_h5"]["read"] is False
    assert committed["input_bindings"]["source_h5"]["hash_recomputed"] is False
    assert committed["input_bindings"]["source_h5"]["opened_as_hdf5"] is False


def test_source_hdf5_never_reaches_bounded_read(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = intake.os.open
    source_path = str((ROOT / intake.SOURCE_H5).absolute())

    def guarded_open(path: object, flags: int, *args: object) -> int:
        if str(path) == source_path:
            raise AssertionError("source HDF5 must not be opened by the intake")
        return real_open(path, flags, *args)

    monkeypatch.setattr(intake.os, "open", guarded_open)
    value = intake.build_report(ROOT)
    assert value["input_bindings"]["source_h5"]["read"] is False
    assert value["input_bindings"]["source_h5"]["hash_recomputed"] is False


def test_report_writers_do_not_overwrite(tmp_path: Path) -> None:
    value = intake.build_report(ROOT)
    destination = tmp_path / "report.json"
    zh_destination = tmp_path / "report.zh-CN.md"
    assert intake.write_report(value, destination) == destination
    assert intake.write_zh_cn(value, zh_destination) == zh_destination
    assert json.loads(destination.read_text(encoding="utf-8")) == value
    assert zh_destination.read_text(encoding="utf-8").startswith("# F3 coarse material")
    with pytest.raises(FileExistsError):
        intake.write_report(value, destination)
    with pytest.raises(FileExistsError):
        intake.write_zh_cn(value, zh_destination)


def test_committed_machine_and_chinese_reports_are_fail_closed() -> None:
    value = json.loads(REPORT.read_text(encoding="utf-8"))
    assert intake.validate_report(value) == []
    assert value["status"] == intake.STATUS_MISSING
    assert value["authorization"]["formal"] is False
    assert value["formal"] is False
    assert value["authorization"]["T2_credit"] == 0
    assert value["authorization"]["qualification_credit"] == 0
    assert ZH_REPORT.read_text(encoding="utf-8").startswith("# F3 coarse material")


def test_direct_cli_loads_host_validator_without_false_module_failure(tmp_path: Path) -> None:
    output = tmp_path / "intake.json"
    zh_output = tmp_path / "intake.zh-CN.md"
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/f3_material_coarse_root_scheduler_intake_v1.py"),
            "--root",
            str(ROOT),
            "--output",
            str(output),
            "--zh-cn-output",
            str(zh_output),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "ModuleNotFoundError" not in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr
    assert json.loads(completed.stdout)["status"] == intake.STATUS_MISSING
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["validation"]["checks"]["host_io_admission_contract_valid"] is True
    assert value["execution_controls"]["source_hdf5_read"] is False
    assert value["execution_controls"]["worker_started"] is False
    assert value["execution_controls"]["solver_started"] is False
    assert value["execution_controls"]["gpu_started"] is False

"""Tests for the non-executing F3 coarse canonical launch-spec sidecar."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from scripts import f3_material_coarse_launch_spec_v1 as sidecar
from scripts import f3_material_coarse_root_scheduler_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]


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
            "attempt_id": "fresh-sidecar-20260929-01",
            "attempt_path": base["binding_projection"]["proposal_namespace_contract"]["attempt_root"]
            + "/fresh-sidecar-20260929-01",
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
    pair_id = "f3-coarse-sidecar-pair-20260929-01"
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
            "authorization_id": "root-auth-sidecar-20260929-01",
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
            "reservation_id": "scheduler-reservation-sidecar-20260929-01",
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
                "snapshot_id": "scheduler-snapshot-sidecar-20260929-01",
            },
            "single_use": True,
            "consumed": False,
        },
        "side_effects": _side_effects(),
    }
    root_path.write_text(json.dumps(root_receipt, sort_keys=True) + "\n", encoding="utf-8")
    scheduler_path.write_text(json.dumps(scheduler_receipt, sort_keys=True) + "\n", encoding="utf-8")
    return root_path, scheduler_path


def test_missing_fresh_receipts_are_blocked_without_a_launch_spec() -> None:
    result = sidecar.build_launch_spec(ROOT)

    assert sidecar.validate_launch_spec(result) == []
    assert result["status"] == sidecar.STATUS_BLOCKED
    assert result["canonical_dry_run_launch"] is None
    assert result["canonical_dry_run_launch_sha256"] is None
    assert result["verified_receipts"]["root_authorization"] is False
    assert result["verified_receipts"]["scheduler_owned_host_io_reservation"] is False
    assert result["authorization"]["launch_admitted"] is False
    assert result["authorization"]["credit"] == 0
    assert result["execution_controls"]["worker_started"] is False
    assert "fresh_root_authorization_receipt_not_verified" in result["blocking_reasons"]
    assert "scheduler_owned_host_io_reservation_not_verified" in result["blocking_reasons"]


def test_valid_pair_builds_a_canonical_non_executing_projection(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    result = sidecar.build_launch_spec(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert sidecar.validate_launch_spec(result) == []
    assert result["status"] == sidecar.STATUS_READY
    assert result["blocking_reasons"] == []
    assert result["verified_receipts"] == {
        "root_authorization": True,
        "scheduler_owned_host_io_reservation": True,
        "pair_cross_binding": True,
    }
    assert result["authorization"]["root_authorization_receipt_verified"] is True
    assert result["authorization"]["scheduler_host_io_reservation_verified"] is True
    assert result["authorization"]["launch_admitted"] is False
    assert result["authorization"]["worker_launch_authorized"] is False
    assert result["authorization"]["credit"] == 0

    launch = result["canonical_dry_run_launch"]
    assert launch["mode"] == "dry_run"
    assert launch["dry_run"] is True
    assert launch["would_execute"] is False
    assert launch["execution_allowed"] is False
    assert launch["cwd"] == str(ROOT)
    assert all("{attempt_dir}" not in token for token in launch["argv"])
    assert all("{attempt_dir}" not in token for token in launch["resume_argv_same_attempt"])
    assert "{attempt_dir}" not in launch["output"]
    assert launch["namespace"]["attempt_id"] == "fresh-sidecar-20260929-01"
    assert launch["namespace"]["attempt_path_absolute"] == str(
        ROOT / launch["namespace"]["attempt_path"]
    )
    assert launch["identity"]["pair_id"] == "f3-coarse-sidecar-pair-20260929-01"
    assert launch["identity"]["root_authorization_id"] == "root-auth-sidecar-20260929-01"
    assert launch["identity"]["scheduler_reservation_id"] == "scheduler-reservation-sidecar-20260929-01"
    assert launch["source"]["opened_as_hdf5"] is False
    assert launch["source"]["content_read"] is False
    assert launch["execution"]["would_execute"] is False
    assert launch["execution"]["worker_started"] is False


def test_one_missing_receipt_keeps_the_sidecar_fail_closed(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    scheduler_receipt.unlink()
    result = sidecar.build_launch_spec(ROOT, root_receipt_path=root_receipt, scheduler_receipt_path=scheduler_receipt)

    assert sidecar.validate_launch_spec(result) == []
    assert result["status"] == sidecar.STATUS_BLOCKED
    assert result["canonical_dry_run_launch"] is None
    # The root receipt's counterparty binding cannot be verified without the
    # paired scheduler receipt, so the complete root authorization observation
    # is also fail-closed.
    assert result["verified_receipts"]["root_authorization"] is False
    assert result["verified_receipts"]["scheduler_owned_host_io_reservation"] is False
    assert result["authorization"]["launch_admitted"] is False


def test_duplicate_receipt_key_is_strictly_rejected(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    raw = root_receipt.read_text(encoding="utf-8")
    root_receipt.write_text(
        raw.replace(
            '"status": "root_authorization_issued",',
            '"status": "root_authorization_issued",\n  "status": "root_authorization_issued",',
            1,
        ),
        encoding="utf-8",
    )
    result = sidecar.build_launch_spec(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )

    assert sidecar.validate_launch_spec(result) == []
    assert result["status"] == sidecar.STATUS_BLOCKED
    assert result["canonical_dry_run_launch"] is None
    assert any("duplicate JSON object key: status" in item for item in result["blocking_reasons"])


def test_production_hdf5_is_never_opened_by_the_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = intake.os.open
    source_path = str((ROOT / intake.SOURCE_H5).absolute())

    def guarded_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if str(path) == source_path:
            raise AssertionError("production HDF5 must not be opened")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(intake.os, "open", guarded_open)
    result = sidecar.build_launch_spec(ROOT)
    assert result["status"] == sidecar.STATUS_BLOCKED
    assert result["execution_controls"]["source_hdf5_opened"] is False
    assert result["execution_controls"]["source_hdf5_read"] is False
    assert result["execution_controls"]["source_hdf5_hash_recomputed"] is False


def test_serialized_ready_spec_rejects_execution_or_digest_drift(tmp_path: Path) -> None:
    root_receipt, scheduler_receipt = _valid_receipts(tmp_path)
    result = sidecar.build_launch_spec(
        ROOT,
        root_receipt_path=root_receipt,
        scheduler_receipt_path=scheduler_receipt,
    )
    forged = deepcopy(result)
    forged["canonical_dry_run_launch"]["execution"]["worker_started"] = True
    assert "launch.execution" in sidecar.validate_launch_spec(forged)

    forged = deepcopy(result)
    forged["canonical_dry_run_launch"]["argv"][0] = "/tmp/forged-worker"
    assert "canonical_dry_run_launch_sha256" in sidecar.validate_launch_spec(forged)


def test_cli_is_stdout_only_and_returns_blocked_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = sidecar.main(["--root", str(ROOT)])
    output = json.loads(capsys.readouterr().out)

    assert result == 2
    assert output["status"] == sidecar.STATUS_BLOCKED
    assert output["canonical_dry_run_launch"] is None
    assert not list(tmp_path.iterdir())

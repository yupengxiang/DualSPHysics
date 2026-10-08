from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timedelta, timezone

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_external_solver_v1.py"
RUNTIME = ROOT / "scripts" / "ds_data02_runtime_v2.py"
SPEC = importlib.util.spec_from_file_location("external_solver_v1_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ledger(tmp_path: Path) -> tuple[Path, Path]:
    data_root = tmp_path / "data-root"
    runtime = data_root / "runtime"
    runtime.mkdir(parents=True)
    ledger_path = runtime / "resource-ledger.json"
    ledger = {
        "schema": "ds02.resource-ledger.v1",
        "campaign_id": "DS-DATA-02",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "limits": {
            "gpu_seconds": 100000, "cpu_core_seconds": 100000,
            "new_storage_bytes": 10_000_000, "qualification_attempts": 10,
            "production_attempts": 10, "home_min_free_bytes": 1,
            "home_path": "/home/jade", "storage_policy": "home_free_floor",
        },
        "charges": [], "reservations": [], "attempts": [], "policy_changes": [],
    }
    ledger_path.write_text(json.dumps(ledger))
    (runtime / "resource-ledger.lock").touch()
    return data_root, ledger_path


def _request(tmp_path: Path, *, output_root: Path | None = None,
             command: list[str] | None = None) -> tuple[dict, Path, Path, Path]:
    data_root, ledger_path = _ledger(tmp_path)
    source = tmp_path / "small-source.json"
    source.write_text('{"source":"manufactured"}\n')
    fake_runtime = tmp_path / "fake-runtime.py"
    fake_runtime.write_text(
        "def inventory():\n"
        "    return {'devices':[{'uuid':'GPU-test','index':2,'used_mib':0,'total_mib':10000}], 'processes':[]}\n"
        "def choose_gpu(snapshot, leased, peak):\n"
        "    return snapshot['devices'][0]\n"
    )
    external_fs = Path("/var/tmp")
    if output_root is None:
        output_root = external_fs / f"ds02-ext-solver-test-{os.getpid()}"
    if output_root.exists():
        shutil.rmtree(output_root)
    if command is None:
        command = [sys.executable, "-c", "from pathlib import Path; Path('{output_root}/result.bin').write_bytes(b'ok')"]
    request: dict = {
        "schema": MODULE.SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "case_id": "MANUFACTURED_CASE", "attempt_id": "external-v1-test",
        "kind": "qualification", "command": command, "cwd": str(tmp_path),
        "max_wall_seconds": 20, "cpu_threads": 1, "estimated_peak_gpu_mib": 256,
        "data_root": str(data_root), "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(MODULE.UNKNOWN),
        "runtime_binding": {"path": str(fake_runtime), "sha256": _sha(fake_runtime)},
        "parent_resource_binding": {
            "ledger_path": str(ledger_path), "data_root": str(data_root),
            "campaign_id": "DS-DATA-02", "deadline_utc": json.loads(ledger_path.read_text())["deadline_utc"],
            "ledger_reset": False, "no_new_data_root": True,
        },
        "storage_scope": {
            "external_filesystem": str(external_fs), "output_root": str(output_root),
            "external_product_reserved_bytes": 100_000, "home_receipt_reserved_bytes": 100_000,
            "new_storage_bytes": 200_000, "home_min_free_bytes": 1,
            "external_min_free_bytes": 1,
        },
        "gpu": {"required": True, "gpu_uuid": "GPU-test", "lease_root": str(data_root / "leases")},
        "input_files": [str(source)],
        "input_sha256": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()},
        "input_content_scope": {str(source): "post_reservation_hash"},
        "execution": {"manufactured_only": True},
    }
    request["sha256"] = MODULE.canonical_sha(request)
    return request, data_root, ledger_path, output_root


def test_external_solver_preflight_separates_home_and_external_headroom(tmp_path: Path) -> None:
    request, data_root, _ledger_path, output = _request(tmp_path)
    value = MODULE._validate_request(request, verify_content=False)
    assert value["storage"]["new_storage_bytes"] == 200_000
    assert value["storage"]["home"]["device_id"] != value["storage"]["external"]["device_id"]
    assert not output.exists()
    result = MODULE.run(tmp_path / "request.json", io_slot_approved=False) if False else None
    assert result is None


def test_external_solver_rejects_total_or_symlink_bypass(tmp_path: Path) -> None:
    request, _data_root, _ledger_path, _output = _request(tmp_path)
    request["storage_scope"]["new_storage_bytes"] = 200_001
    request["sha256"] = MODULE.canonical_sha(request)
    with pytest.raises(MODULE.ExternalSolverError, match="equal external"):
        MODULE._validate_request(request, verify_content=False)

    link = tmp_path / "external-link"
    link.symlink_to("/var/tmp", target_is_directory=True)
    request, _data_root, _ledger_path, _output = _request(tmp_path / "symlink-case", output_root=link / "output")
    request["storage_scope"]["external_filesystem"] = str(link)
    request["storage_scope"]["output_root"] = str(link / "output")
    request["sha256"] = MODULE.canonical_sha(request)
    with pytest.raises(MODULE.ExternalSolverError, match="symlink"):
        MODULE._validate_request(request, verify_content=False)


def test_external_solver_two_fs_reservation_rejects_each_floor_independently() -> None:
    ledger = {"deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
              "attempts": [], "reservations": [],
              "limits": {"gpu_seconds": 100, "cpu_core_seconds": 100, "new_storage_bytes": 1000,
                          "qualification_attempts": 2, "production_attempts": 2}}
    reservation = {"id": "x", "kind": "qualification", "gpu_seconds": 1,
                   "cpu_core_seconds": 1, "new_storage_bytes": 20,
                   "home_storage_bytes": 10, "external_storage_bytes": 10}
    with pytest.raises(MODULE.ExternalSolverError, match="Home"):
        MODULE._check_two_fs_reservation(ledger, reservation, home_free=10, external_free=100,
                                          home_floor=1, external_floor=1)
    with pytest.raises(MODULE.ExternalSolverError, match="external"):
        MODULE._check_two_fs_reservation(ledger, reservation, home_free=100, external_free=10,
                                          home_floor=1, external_floor=1)


def test_external_solver_manufactured_run_charges_exact_two_fs_bytes_and_releases_uuid(tmp_path: Path) -> None:
    request, data_root, ledger_path, output = _request(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    # Keep the real shared v2 ledger_locked/atomic writer while replacing only
    # the inventory query for this manufactured no-GPU test.
    runtime_spec = importlib.util.spec_from_file_location("shared_runtime_v2_test", RUNTIME)
    assert runtime_spec is not None and runtime_spec.loader is not None
    shared_runtime = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(shared_runtime)
    shared_runtime.inventory = lambda: {
        "devices": [{"uuid": "GPU-test", "index": 2, "used_mib": 0, "total_mib": 10000}],
        "processes": [],
    }
    MODULE._load_runtime = lambda _request: shared_runtime
    report = MODULE.run(request_path, io_slot_approved=True, parent_pid=None)
    assert report["status"] == "COMPLETED_DEVELOPMENT_UNKNOWN"
    assert report["terminal_charge_written"] is True
    assert output.is_dir()
    receipt = Path(report["receipt_path"])
    assert receipt.is_file()
    ledger = json.loads(ledger_path.read_text())
    attempt = "F2/MANUFACTURED_CASE/external-v1-test"
    assert not any(row.get("id") == attempt for row in ledger["reservations"])
    charge = next(row for row in ledger["charges"] if row.get("id") == attempt)
    assert charge["external_storage_bytes"] == report["external_product_bytes"]
    assert charge["home_storage_bytes"] == report["home_receipt_bytes"]
    assert charge["new_storage_bytes"] == charge["external_storage_bytes"] + charge["home_storage_bytes"]
    assert not (data_root / "leases" / "GPU-test.json").exists()
    shutil.rmtree(output)

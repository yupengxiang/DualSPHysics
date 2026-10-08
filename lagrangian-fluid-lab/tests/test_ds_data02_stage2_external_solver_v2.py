from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_external_solver_v2.py"
V1_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_external_solver_v1.py"
RUNTIME = ROOT / "scripts" / "ds_data02_runtime_v2.py"
SPEC = importlib.util.spec_from_file_location("external_solver_v2_test_module", SCRIPT)
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


def _request(tmp_path: Path, *, attempt: str = "external-v2-test",
             command: list[str] | None = None, max_wall: float = 20.0) -> tuple[dict, Path, Path, Path]:
    data_root, ledger_path = _ledger(tmp_path)
    source = tmp_path / "small-source.json"
    source.write_text('{"source":"manufactured-v2"}\n')
    fake_runtime = tmp_path / "fake-runtime.py"
    fake_runtime.write_text(
        "def inventory():\n"
        "    return {'devices':[{'uuid':'GPU-test','index':2,'used_mib':0,'total_mib':10000}], 'processes':[]}\n"
        "def choose_gpu(snapshot, leased, peak):\n"
        "    return snapshot['devices'][0]\n"
    )
    external_fs = Path("/var/tmp")
    output = external_fs / f"ds02-ext-solver-v2-{os.getpid()}-{attempt}"
    if output.exists():
        shutil.rmtree(output)
    if command is None:
        command = [sys.executable, "-c", "from pathlib import Path; Path('{output_root}/result.bin').write_bytes(b'ok-v2')"]
    request: dict = {
        "schema": MODULE.SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "case_id": "MANUFACTURED_CASE", "attempt_id": attempt,
        "kind": "qualification", "command": command, "cwd": str(tmp_path),
        "max_wall_seconds": max_wall, "cpu_threads": 1, "estimated_peak_gpu_mib": 256,
        "data_root": str(data_root), "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(MODULE.UNKNOWN),
        "runtime_binding": {"path": str(fake_runtime), "sha256": _sha(fake_runtime)},
        "v1_runner_binding": {"path": str(V1_SCRIPT), "sha256": _sha(V1_SCRIPT)},
        "parent_resource_binding": {
            "ledger_path": str(ledger_path), "data_root": str(data_root),
            "campaign_id": "DS-DATA-02", "deadline_utc": json.loads(ledger_path.read_text())["deadline_utc"],
            "ledger_reset": False, "no_new_data_root": True,
        },
        "storage_scope": {
            "external_filesystem": str(external_fs), "output_root": str(output),
            "external_product_reserved_bytes": 100_000, "home_receipt_reserved_bytes": 100_000,
            "new_storage_bytes": 200_000, "home_min_free_bytes": 1,
            "external_min_free_bytes": 1,
        },
        "gpu": {"required": True, "gpu_uuid": "GPU-test", "lease_root": str(data_root / "leases")},
        "input_files": [str(source)],
        "input_sha256": {str(source): _sha(source)},
        "input_content_scope": {str(source): "post_reservation_hash"},
        "execution": {"manufactured_only": True},
        "timing_contract": {
            "entry_to_terminal_deadline": True,
            "posthash_and_receipt_cpu_included": True,
            "cancel_cleanup_bounded": True,
        },
    }
    request["sha256"] = MODULE.canonical_sha(request)
    return request, data_root, ledger_path, output


def _shared_runtime():
    runtime_spec = importlib.util.spec_from_file_location("shared_runtime_v2_for_external_v2_test", RUNTIME)
    assert runtime_spec is not None and runtime_spec.loader is not None
    shared_runtime = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(shared_runtime)
    shared_runtime.inventory = lambda: {
        "devices": [{"uuid": "GPU-test", "index": 2, "used_mib": 0, "total_mib": 10000}],
        "processes": [],
    }
    return shared_runtime


def test_external_solver_v2_preflight_does_not_mutate_parent(tmp_path: Path) -> None:
    request, data_root, ledger_path, output = _request(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    before = ledger_path.read_bytes()
    result = MODULE.run(request_path, io_slot_approved=False)
    assert result["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert result["ledger_mutated"] is False
    assert ledger_path.read_bytes() == before
    assert not output.exists()
    assert not (data_root / "leases").exists()


def test_external_solver_v2_success_reuses_cpu_cutoff_and_two_fs_charge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request, data_root, ledger_path, output = _request(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    monkeypatch.setattr(MODULE, "_load_runtime", lambda _request: _shared_runtime())
    report = MODULE.run(request_path, io_slot_approved=True)
    assert report["status"] == "COMPLETED_DEVELOPMENT_UNKNOWN"
    assert report["terminal_charge_written"] is True
    assert output.is_dir()
    receipt_path = Path(report["receipt_path"])
    receipt = json.loads(receipt_path.read_text())
    ledger = json.loads(ledger_path.read_text())
    attempt = "F2/MANUFACTURED_CASE/external-v2-test"
    charge = next(row for row in ledger["charges"] if row.get("id") == attempt)
    assert charge["external_storage_bytes"] == report["external_product_bytes"]
    assert charge["home_storage_bytes"] == report["home_receipt_bytes"]
    assert charge["new_storage_bytes"] == charge["external_storage_bytes"] + charge["home_storage_bytes"]
    assert charge["cpu_core_seconds"] == receipt["execution"]["cpu_core_seconds"]
    assert receipt["execution"]["cpu_core_seconds"] == report["cpu_core_seconds"]
    assert not ledger["reservations"]
    assert not (data_root / "leases" / "GPU-test.json").exists()
    assert receipt["source_validation"]["content_verified"] is True
    assert receipt["original_path_fallback"] == "FORBIDDEN"
    shutil.rmtree(output)


def test_external_solver_v2_deadline_after_reservation_charges_failure_and_releases_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request, data_root, ledger_path, output = _request(
        tmp_path,
        attempt="external-v2-timeout",
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        max_wall=1.0,
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    monkeypatch.setattr(MODULE, "_load_runtime", lambda _request: _shared_runtime())
    report = MODULE.run(request_path, io_slot_approved=True)
    assert report["status"] == "FAILED_EXTERNAL_SOLVER"
    assert report["terminal_charge_written"] is True
    assert report["cpu_core_seconds"] >= 0
    ledger = json.loads(ledger_path.read_text())
    attempt = "F2/MANUFACTURED_CASE/external-v2-timeout"
    assert not ledger["reservations"]
    charge = next(row for row in ledger["charges"] if row.get("id") == attempt)
    assert charge["status"] == "FAILED_EXTERNAL_SOLVER"
    assert charge["cpu_core_seconds"] == report["cpu_core_seconds"]
    assert not (data_root / "leases" / "GPU-test.json").exists()
    assert "deadline" in (report.get("termination") or "").lower() or "deadline" in json.loads(Path(report["receipt_path"]).read_text())["execution"]["termination"].lower()
    shutil.rmtree(output)


def test_external_solver_v2_rejects_changed_v1_dependency(tmp_path: Path) -> None:
    request, _data_root, _ledger_path, _output = _request(tmp_path)
    request["v1_runner_binding"]["sha256"] = "0" * 64
    request["sha256"] = MODULE.canonical_sha(request)
    with pytest.raises(MODULE.ExternalSolverV2Error, match="v1 forward runner SHA"):
        MODULE._validate_request(request, verify_content=False)

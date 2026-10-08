from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_external_supervisor_v17.py"
RUNTIME = ROOT / "scripts" / "ds_data02_runtime_v2.py"
SPEC = importlib.util.spec_from_file_location("external_supervisor_v17_test_module", SCRIPT)
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
        "schema": "ds02.resource-ledger.v1", "campaign_id": "DS-DATA-02",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "limits": {"gpu_seconds": 100000, "cpu_core_seconds": 100000,
                   "new_storage_bytes": 1_000_000, "qualification_attempts": 10,
                   "production_attempts": 10, "home_min_free_bytes": 1,
                   "home_path": "/home/jade", "storage_policy": "home_free_floor"},
        "charges": [], "reservations": [], "attempts": [], "policy_changes": [],
    }
    ledger_path.write_text(json.dumps(ledger))
    (runtime / "resource-ledger.lock").touch()
    return data_root, ledger_path


def _fixtures(tmp_path: Path) -> tuple[dict, Path, Path, Path, Path]:
    data_root, ledger_path = _ledger(tmp_path)
    external = Path("/var/tmp") / f"ds02-supervisor-v17-{os.getpid()}"
    if external.exists():
        shutil.rmtree(external)
    external.mkdir(parents=True)
    fake_v12 = tmp_path / "fake-v12.py"
    fake_v12.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "args=sys.argv; req=Path(args[args.index('--request')+1]); r=json.loads(req.read_text())\n"
        "led=Path(r['accounting']['ledger_path']); d=json.loads(led.read_text())\n"
        "d['charges'].append({'id':r['accounting']['attempt_id'],'status':'completed','cpu_core_seconds':2.0,'new_storage_bytes':0})\n"
        "led.write_text(json.dumps(d))\n"
        "print(json.dumps({'schema':'fake-v12','status':'COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN','error':None}))\n"
    )
    fake_v13 = tmp_path / "fake-v13.py"
    fake_v13.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "if sys.argv[1]=='build-request': Path(sys.argv[sys.argv.index('--output')+1]).write_text(json.dumps({'status':'READY'})); print(json.dumps({'status':'READY'}))\n"
        "else: print(json.dumps({'status':'SUPPLEMENTAL_CHARGE_APPLIED','cpu_core_seconds':0.0}))\n"
    )
    bridge = tmp_path / "bridge.json"
    bridge.write_text(json.dumps({"guard_bindings": [{"role": "shared_runtime_v6", "path": str(RUNTIME), "sha256": _sha(RUNTIME)}]}))
    v11 = tmp_path / "v11.json"
    v11.write_text(json.dumps({"bridge_request": {"path": str(bridge)}}))
    trace = external / "trace.log"
    sidecar = external / "trace-sidecar.json"
    v12 = {
        "schema": "ds02.stage2.f2-parent-supervised-launch.v12", "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT", "v11_launch": {"path": str(v11)},
        "trace": {"path": str(trace)},
        "execution": {"python": sys.executable, "bridge": "/usr/bin/true", "strace": "/usr/bin/true",
                       "trace_finalization_sidecar": str(sidecar)},
        "storage_scope": {"external_filesystem": str(external), "home_min_free_bytes": 1},
        "accounting": {"attempt_id": "F2/test-case/v12-attempt", "ledger_path": str(ledger_path)},
    }
    v12["sha256"] = MODULE.canonical_sha(v12)
    v12_path = tmp_path / "v12.json"
    v12_path.write_text(json.dumps(v12))
    return v12, v12_path, data_root, ledger_path, external


def test_v17_build_and_preflight_are_bound_and_metadata_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v12, v12_path, data_root, ledger_path, external = _fixtures(tmp_path)
    monkeypatch.setattr(MODULE, "V12_PATH", tmp_path / "fake-v12.py")
    monkeypatch.setattr(MODULE, "V15_PATH", tmp_path / "fake-v13.py")
    request_path = tmp_path / "supervisor.json"
    output_root = external / "run-v17"
    request = MODULE.build_request(v12_path, request_path, output_root=output_root,
                                   max_wall_seconds=30, supervisor_python=Path(sys.executable))
    assert request["status"] == "READY_FOR_PARENT_GUARD"
    before = ledger_path.read_bytes()
    result = MODULE.run(request_path, io_slot_approved=False)
    assert result["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert ledger_path.read_bytes() == before
    assert not output_root.exists()
    assert request["storage_scope"]["external_filesystem"] == str(external)
    assert request["runtime_binding"]["sha256"] == _sha(RUNTIME)


def test_v17_runs_v12_cli_v13_and_charges_only_supervisor_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v12, v12_path, data_root, ledger_path, external = _fixtures(tmp_path)
    monkeypatch.setattr(MODULE, "V12_PATH", tmp_path / "fake-v12.py")
    monkeypatch.setattr(MODULE, "V15_PATH", tmp_path / "fake-v13.py")
    request_path = tmp_path / "supervisor.json"
    output_root = external / "run-v17"
    request = MODULE.build_request(v12_path, request_path, output_root=output_root,
                                   max_wall_seconds=30, supervisor_python=Path(sys.executable))
    result = MODULE.run(request_path, io_slot_approved=True)
    assert result["status"] == "COMPLETED_EXTERNAL_SUPERVISOR_DEVELOPMENT_UNKNOWN"
    assert result["ledger_mutated"] is True
    assert result["v12_returncode"] == 0
    assert result["v15_status"] == "SUPPLEMENTAL_CHARGE_APPLIED"
    assert Path(result["report_path"]).is_file()
    assert (output_root / "supervisor.stdout.log").is_file()
    assert (output_root / "supervisor.stderr.log").is_file()
    ledger = json.loads(ledger_path.read_text())
    attempt = "F2/test-case/v12-attempt"
    charge = next(row for row in ledger["charges"] if row.get("id") == attempt + "::supervisor-v17")
    assert charge["external_storage_bytes"] == result["new_logs_and_reports_bytes"]
    assert charge["home_storage_bytes"] == 0
    assert charge["accounting_scope"].startswith("same_parent_supervisor")
    assert not ledger["reservations"]
    shutil.rmtree(external)


def test_v17_rejects_existing_output_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v12, v12_path, _data_root, _ledger_path, external = _fixtures(tmp_path)
    monkeypatch.setattr(MODULE, "V12_PATH", tmp_path / "fake-v12.py")
    monkeypatch.setattr(MODULE, "V15_PATH", tmp_path / "fake-v13.py")
    output_root = external / "already-there"
    output_root.mkdir()
    with pytest.raises(MODULE.SupervisorError, match="already exists"):
        MODULE.build_request(v12_path, tmp_path / "supervisor.json", output_root=output_root)
    shutil.rmtree(external)


def test_v17_home_floor_ignores_historical_cumulative_byte_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v12, v12_path, _data_root, ledger_path, external = _fixtures(tmp_path)
    monkeypatch.setattr(MODULE, "V12_PATH", tmp_path / "fake-v12.py")
    monkeypatch.setattr(MODULE, "V15_PATH", tmp_path / "fake-v13.py")
    ledger = json.loads(ledger_path.read_text())
    ledger["limits"]["new_storage_bytes"] = 1
    ledger_path.write_text(json.dumps(ledger))
    request_path = tmp_path / "supervisor.json"
    request = MODULE.build_request(v12_path, request_path, output_root=external / "run-cap-bypass",
                                   max_wall_seconds=30, supervisor_python=Path(sys.executable))
    result = MODULE.run(request_path, io_slot_approved=True)
    assert result["status"] == "COMPLETED_EXTERNAL_SUPERVISOR_DEVELOPMENT_UNKNOWN"
    ledger = json.loads(ledger_path.read_text())
    charge = next(row for row in ledger["charges"] if row.get("id") == request["accounting"]["supplemental_charge_id"])
    assert charge["new_storage_bytes"] > 1
    assert not ledger["reservations"]
    shutil.rmtree(external)


def test_v17_static_content_failure_gets_supervisor_only_failed_charge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v12, v12_path, _data_root, ledger_path, external = _fixtures(tmp_path)
    monkeypatch.setattr(MODULE, "V12_PATH", tmp_path / "fake-v12.py")
    monkeypatch.setattr(MODULE, "V15_PATH", tmp_path / "fake-v13.py")
    request_path = tmp_path / "supervisor.json"
    request = MODULE.build_request(v12_path, request_path, output_root=external / "run-static-failure",
                                   max_wall_seconds=30, supervisor_python=Path(sys.executable))
    request["static_bindings"][0]["sha256"] = "0" * 64
    request["sha256"] = MODULE.canonical_sha(request)
    request_path.write_text(json.dumps(request))
    result = MODULE.run(request_path, io_slot_approved=True)
    assert result["status"] == "FAILED_EXTERNAL_SUPERVISOR_PREFLIGHT"
    ledger = json.loads(ledger_path.read_text())
    charge = next(row for row in ledger["charges"] if row.get("id") == request["accounting"]["supplemental_charge_id"])
    assert charge["status"] == "failed"
    assert charge["parent_terminal_charge_present"] is False
    assert not ledger["reservations"]
    shutil.rmtree(external)


def test_v17_missing_v10_terminal_still_charges_failed_supervisor_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v12, v12_path, _data_root, ledger_path, external = _fixtures(tmp_path)
    silent_v12 = tmp_path / "silent-v12.py"
    silent_v12.write_text("import time\ntime.sleep(0.01)\n")
    monkeypatch.setattr(MODULE, "V12_PATH", silent_v12)
    monkeypatch.setattr(MODULE, "V15_PATH", tmp_path / "fake-v13.py")
    request_path = tmp_path / "supervisor.json"
    request = MODULE.build_request(v12_path, request_path, output_root=external / "run-missing-v10",
                                   max_wall_seconds=30, supervisor_python=Path(sys.executable))
    result = MODULE.run(request_path, io_slot_approved=True)
    assert result["status"] == "FAILED_EXTERNAL_SUPERVISOR"
    ledger = json.loads(ledger_path.read_text())
    charge = next(row for row in ledger["charges"] if row.get("id") == request["accounting"]["supplemental_charge_id"])
    assert charge["status"] == "failed"
    assert charge["parent_terminal_charge_present"] is False
    assert not ledger["reservations"]
    shutil.rmtree(external)


def test_v17_reservation_has_one_thread_cpu_window_and_parent_fs_reservations_are_subtracted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _v12, _v12_path, data_root, ledger_path, external = _fixtures(tmp_path)
    ledger = json.loads(ledger_path.read_text())
    ledger["limits"]["cpu_core_seconds"] = 1000.0
    ledger["reservations"].append({
        "id": "parent-active", "cpu_core_seconds": 7.0,
        "new_storage_bytes": 500, "external_storage_bytes": 500,
        "home_storage_bytes": 300, "storage_filesystems": [str(external)],
    })
    ledger_path.write_text(json.dumps(ledger))

    def fake_statvfs(path: Path):
        # The test makes the subtraction observable without depending on the
        # machine's changing free-space counters.
        if Path(path).resolve() == external.resolve():
            return SimpleNamespace(f_bavail=2000, f_frsize=1)
        return SimpleNamespace(f_bavail=1000, f_frsize=1)

    monkeypatch.setattr(MODULE.os, "statvfs", fake_statvfs)
    result = MODULE._reserve_wrapper(
        RUNTIME, _sha(RUNTIME), ledger_path, "supervisor-reservation", "parent-attempt",
        external=external, bytes_count=1000, home_path=Path("/home/jade"),
        home_floor=700, external_floor=500, cpu_reserve_seconds=30.0,
        max_wall_seconds=30.0, deadline_utc=ledger["deadline_utc"],
        max_storage=1, max_cpu=1000.0,
    )
    assert result["status"] == "SUPERVISOR_RESERVATION_APPLIED"
    reserved = result["reservation"]
    assert reserved["cpu_core_seconds"] == 30.0
    assert reserved["cpu_threads"] == 1
    assert reserved["reservation_cpu_basis"] == "one CPU thread multiplied by max_wall_seconds"
    assert reserved["external_storage_bytes"] == 1000
    assert reserved["home_storage_bytes"] == 0
    current = json.loads(ledger_path.read_text())
    row = next(item for item in current["reservations"] if item["id"] == "supervisor-reservation")
    assert row["cpu_core_seconds"] == 30.0
    assert MODULE._release_reservation(RUNTIME, _sha(RUNTIME), ledger_path, "supervisor-reservation") is True
    assert MODULE._release_reservation(RUNTIME, _sha(RUNTIME), ledger_path, "supervisor-reservation") is False
    assert not json.loads(ledger_path.read_text())["reservations"] or all(
        item["id"] != "supervisor-reservation" for item in json.loads(ledger_path.read_text())["reservations"]
    )
    shutil.rmtree(external)


def test_v17_reservation_rejects_floor_cpu_and_parent_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v12, _v12_path, _data_root, ledger_path, external = _fixtures(tmp_path)
    ledger = json.loads(ledger_path.read_text())
    ledger["limits"]["cpu_core_seconds"] = 20.0
    ledger["reservations"].append({
        "id": "parent-active", "cpu_core_seconds": 1.0,
        "new_storage_bytes": 500, "external_storage_bytes": 500,
        "home_storage_bytes": 300, "storage_filesystems": [str(external)],
    })
    ledger_path.write_text(json.dumps(ledger))

    def fake_statvfs(path: Path):
        if Path(path).resolve() == external.resolve():
            return SimpleNamespace(f_bavail=1200, f_frsize=1)
        return SimpleNamespace(f_bavail=1000, f_frsize=1)

    monkeypatch.setattr(MODULE.os, "statvfs", fake_statvfs)
    with pytest.raises(MODULE.SupervisorError, match="CPU budget"):
        MODULE._reserve_wrapper(
            RUNTIME, _sha(RUNTIME), ledger_path, "cpu-reservation", "parent-attempt",
            external=external, bytes_count=100, home_path=Path("/home/jade"),
            home_floor=1, external_floor=1, cpu_reserve_seconds=30.0,
            max_wall_seconds=30.0, deadline_utc=ledger["deadline_utc"],
            max_storage=1_000_000, max_cpu=20.0,
        )

    ledger["limits"]["cpu_core_seconds"] = 1000.0
    def tight_statvfs(path: Path):
        if Path(path).resolve() == external.resolve():
            return SimpleNamespace(f_bavail=1100, f_frsize=1)
        return SimpleNamespace(f_bavail=1000, f_frsize=1)
    monkeypatch.setattr(MODULE.os, "statvfs", tight_statvfs)
    ledger_path.write_text(json.dumps(ledger))
    with pytest.raises(MODULE.SupervisorError, match="headroom after parent reservations"):
        MODULE._reserve_wrapper(
            RUNTIME, _sha(RUNTIME), ledger_path, "floor-reservation", "parent-attempt",
            external=external, bytes_count=100, home_path=Path("/home/jade"),
            home_floor=1, external_floor=501, cpu_reserve_seconds=30.0,
            max_wall_seconds=30.0, deadline_utc=ledger["deadline_utc"],
            max_storage=1_000_000, max_cpu=1000.0,
        )

    ledger["deadline_utc"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    ledger_path.write_text(json.dumps(ledger))
    with pytest.raises(MODULE.SupervisorError, match="deadline"):
        MODULE._reserve_wrapper(
            RUNTIME, _sha(RUNTIME), ledger_path, "deadline-reservation", "parent-attempt",
            external=external, bytes_count=100, home_path=Path("/home/jade"),
            home_floor=1, external_floor=1, cpu_reserve_seconds=30.0,
            max_wall_seconds=30.0, deadline_utc=ledger["deadline_utc"],
            max_storage=1_000_000, max_cpu=1000.0,
        )
    shutil.rmtree(external)


def test_v17_failure_after_reservation_cleans_parent_reservation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _v12, v12_path, _data_root, ledger_path, external = _fixtures(tmp_path)
    monkeypatch.setattr(MODULE, "V12_PATH", tmp_path / "fake-v12.py")
    monkeypatch.setattr(MODULE, "V15_PATH", tmp_path / "fake-v13.py")
    request_path = tmp_path / "supervisor.json"
    request = MODULE.build_request(v12_path, request_path, output_root=external / "run-after-reserve",
                                   max_wall_seconds=30, supervisor_python=Path(sys.executable))

    def fail_disk_probe(_path: Path):
        raise MODULE.SupervisorError("manufactured disk probe failure")

    monkeypatch.setattr(MODULE, "_disk_probe", fail_disk_probe)
    result = MODULE.run(request_path, io_slot_approved=True)
    assert result["status"] == "FAILED_EXTERNAL_SUPERVISOR_PREFLIGHT"
    ledger = json.loads(ledger_path.read_text())
    assert not any(row.get("id") == request["accounting"]["reservation_id"]
                   for row in ledger["reservations"])
    assert any(row.get("id") == request["accounting"]["supplemental_charge_id"]
               and row.get("status") == "failed" for row in ledger["charges"])
    shutil.rmtree(external)

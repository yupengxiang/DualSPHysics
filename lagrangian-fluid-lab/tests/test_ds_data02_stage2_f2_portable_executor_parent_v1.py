from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_parent_v1.py"
V34_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v34.py"
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parent = _load(SCRIPT, "parent_executor_v1_test")
v34 = _load(V34_SCRIPT, "portable_executor_v34_test")


def _bound(tmp_path: Path) -> dict:
    external = tmp_path / "nvme"
    home = tmp_path / "home"
    external.mkdir()
    home.mkdir()
    data_root = tmp_path / "data"
    (data_root / "runtime").mkdir(parents=True)
    ledger = data_root / "runtime" / "resource-ledger.json"
    ledger.write_text(json.dumps({
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {"storage_policy": "home_free_floor", "home_path": str(home),
                   "home_min_free_bytes": 0, "cpu_core_seconds": 1000},
        "charges": [], "reservations": [], "attempts": [],
    }) + "\n")
    source_sha = parent.sha256_file(parent.RUNTIME_V6_DEFAULT)
    request = {"storage_scope": {"external_min_free_bytes": 0},
               "executor": {"source_entries": [{"bytes": 8}]}}
    return {
        "runtime_path": parent.RUNTIME_V6_DEFAULT,
        "runtime_sha": source_sha,
        "ledger": ledger,
        "external": external,
        "output_root": external / "attempt",
        "receipt": home / "receipt.json",
        "request": request,
        "limits": json.loads(ledger.read_text())["limits"],
        "parent_attempt_id": "synthetic-parent-absent",
        "reservation_id": "synthetic-parent-absent::reservation",
        "charge_id": "synthetic-parent-absent::charge",
        "external_estimate": 100,
        "home_estimate": 20,
        "max_wall": 10.0,
        "allow_missing_parent": True,
    }


def test_dual_filesystem_reservation_charge_and_release(tmp_path: Path) -> None:
    bound = _bound(tmp_path)
    reserved = parent._reserve(bound)
    assert reserved["status"] == "PARENT_RESERVATION_APPLIED"
    ledger = json.loads(bound["ledger"].read_text())
    row = ledger["reservations"][-1]
    assert row["external_storage_bytes"] == 100
    assert row["home_storage_bytes"] == 20
    (bound["external"] / "copied.bin").write_bytes(b"x" * 13)
    (tmp_path / "home" / "receipt.json").write_bytes(b"home")
    charged = parent._charge(bound, status="failed", cpu_seconds=0.2,
                             external_bytes=13, home_bytes=4, trace_bytes=0,
                             copy_hash_bytes=8, allow_missing_parent=True)
    assert charged["status"] == "PARENT_CHARGE_APPLIED"
    ledger = json.loads(bound["ledger"].read_text())
    assert not ledger["reservations"]
    charge = ledger["charges"][-1]
    assert charge["external_storage_bytes"] == 13
    assert charge["home_storage_bytes"] == 4
    assert charge["new_storage_bytes"] == 17


def test_cancel_cleanup_releases_registered_reservation(tmp_path: Path) -> None:
    bound = _bound(tmp_path)
    parent._reserve(bound)
    assert parent._release(bound) is True
    ledger = json.loads(bound["ledger"].read_text())
    assert ledger["reservations"] == []


def test_private_worker_timeout_terminates_direct_child_without_group_hang(tmp_path: Path) -> None:
    worker = tmp_path / "sleep_worker.py"
    worker.write_text("import time\ntime.sleep(5)\n")
    output = tmp_path / "out"
    code, _stdout, stderr = v34._run_private_worker(
        VENV, worker, tmp_path / "request.json", output,
        deadline=time.monotonic() + 0.1)
    assert code == 124
    assert "deadline exceeded" in stderr

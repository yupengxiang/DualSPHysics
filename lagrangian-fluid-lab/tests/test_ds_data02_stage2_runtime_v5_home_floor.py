from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_runtime_v5.py"
SPEC = importlib.util.spec_from_file_location("runtime_v5_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sys.path.insert(0, str(SCRIPT.parent))
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _ledger(policy: str = "home_free_floor") -> dict:
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    return {
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": deadline,
        "limits": {
            "gpu_seconds": 10_000.0,
            "cpu_core_seconds": 10_000.0,
            "new_storage_bytes": 10_000,
            "qualification_attempts": 10,
            "production_attempts": 10,
            "storage_policy": policy,
            "home_min_free_bytes": 100,
        },
        "charges": [],
        "reservations": [],
        "attempts": [],
    }


def _reservation(identifier: str = "manufactured-v5-001", bytes_: int = 400) -> dict:
    return {
        "id": identifier,
        "kind": "cpu",
        "cpu_task_kind": "tests",
        "cpu_threads": 1,
        "cpu_core_seconds": 20,
        "gpu_seconds": 0,
        "new_storage_bytes": bytes_,
    }


def test_home_floor_skips_only_parent_tree_scan_and_keeps_attempt_scan(tmp_path: Path) -> None:
    data_root = tmp_path / "data-root"
    (data_root / "runtime").mkdir(parents=True)
    (data_root / "runtime" / "resource-ledger.json").write_text(json.dumps(_ledger()))
    module._ACTIVE_DATA_ROOT = data_root.resolve()
    original = module._BASE_TREE_BYTES
    try:
        module._BASE_TREE_BYTES = lambda _root: (_ for _ in ()).throw(AssertionError("parent tree scan"))
        assert module.tree_bytes(data_root) == 0
    finally:
        module._BASE_TREE_BYTES = original
        module._ACTIVE_DATA_ROOT = None


def test_non_home_policy_preserves_existing_tree_limit_check() -> None:
    ledger = _ledger("fixed_total")
    reservation = _reservation(bytes_=400)
    try:
        module.check_reservation(ledger, reservation, existing_bytes=9_700,
                                 available_bytes=10_000_000)
    except RuntimeError as error:
        assert "storage budget exhausted" in str(error)
    else:
        raise AssertionError("non-Home policy must retain existing-tree budget enforcement")


def test_manufactured_home_ledger_reservation_charge_roundtrip(tmp_path: Path) -> None:
    data_root = tmp_path / "data-root"
    runtime_dir = data_root / "runtime"
    runtime_dir.mkdir(parents=True)
    ledger_path = runtime_dir / "resource-ledger.json"
    ledger_path.write_text(json.dumps(_ledger()))
    reservation = _reservation(bytes_=400)
    with module.ledger_locked(data_root) as ledger:
        module.check_reservation(ledger, reservation, existing_bytes=10**12,
                                 available_bytes=10_000_000)
        ledger["reservations"].append(dict(reservation))
        ledger["attempts"].append({"id": reservation["id"], "kind": "cpu", "status": "reserved"})
    with module.ledger_locked(data_root) as ledger:
        ledger["reservations"] = [row for row in ledger["reservations"] if row["id"] != reservation["id"]]
        ledger["charges"].append({"id": reservation["id"], "gpu_seconds": 0.0,
                                   "cpu_core_seconds": 3.5, "new_storage_bytes": 257,
                                   "status": "completed"})
        ledger["attempts"][0].update(status="completed")
    final = json.loads(ledger_path.read_text())
    assert final["reservations"] == []
    assert final["charges"][0]["new_storage_bytes"] == 257
    assert final["attempts"][0]["status"] == "completed"

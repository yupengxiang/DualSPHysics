from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_runtime_v6.py"
SPEC = importlib.util.spec_from_file_location("runtime_v6_entry_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sys.path.insert(0, str(SCRIPT.parent))
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _ledger() -> dict:
    return {
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "limits": {
            "gpu_seconds": 10_000.0,
            "cpu_core_seconds": 10_000.0,
            "new_storage_bytes": 10_000,
            "qualification_attempts": 10,
            "production_attempts": 10,
            "storage_policy": "home_free_floor",
            "home_min_free_bytes": 100,
        },
        "charges": [],
        "reservations": [],
        "attempts": [],
    }


def test_v6_entry_clock_includes_manufactured_prevalidation_cpu(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data-root"
    (data_root / "runtime").mkdir(parents=True)
    (data_root / "runtime" / "resource-ledger.json").write_text(json.dumps(_ledger()))
    source = tmp_path / "small-input.txt"
    source.write_text("source-bound")
    request_path = tmp_path / "request.json"
    request = {
        "family_id": "infra",
        "case_id": "manufactured-v6-entry",
        "attempt_id": "entry-001",
        "kind": "cpu",
        "cpu_task_kind": "tests",
        "command": [sys.executable, "-c", "pass"],
        "cwd": str(ROOT),
        "max_wall_seconds": 30,
        "cpu_threads": 1,
        "estimated_storage_bytes": 16_000,
        "input_files": [str(source)],
        "worktree_root": str(ROOT),
    }
    request_path.write_text(json.dumps(request))

    def slow_validation(value, *, approval_context=None):
        # Burn measurable user CPU before the child is launched.  This models
        # a large source preflight without reading any scientific file.
        total = 0
        for number in range(350_000):
            total += number * 3
        assert total > 0
        return {str(source.resolve()): module.base.sha256(source)}

    monkeypatch.setattr(module, "validate_request", slow_validation)
    result = module.run_request(request_path, data_root=data_root)

    assert result["status"] == "completed"
    assert result["cpu_core_seconds"] > 0
    assert result["wall_seconds_from_entry"] >= result["elapsed_seconds"]
    assert result["timing_scope"]["clock_start"].startswith("function_entry")
    assert result["timing_scope"]["cpu_includes_input_hashing_and_validation"] is True
    receipt = data_root / "families" / "infra" / "manufactured-v6-entry" / "entry-001" / "execution-receipt.json"
    saved = json.loads(receipt.read_text())
    assert saved["cpu_core_seconds"] == result["cpu_core_seconds"]
    ledger = json.loads((data_root / "runtime" / "resource-ledger.json").read_text())
    assert ledger["reservations"] == []
    assert ledger["charges"][0]["cpu_core_seconds"] == result["cpu_core_seconds"]


def test_v6_home_roundtrip_skips_only_parent_tree_scan(tmp_path: Path) -> None:
    data_root = tmp_path / "data-root"
    runtime_dir = data_root / "runtime"
    runtime_dir.mkdir(parents=True)
    ledger_path = runtime_dir / "resource-ledger.json"
    ledger_path.write_text(json.dumps(_ledger()))
    reservation = {
        "id": "manufactured-v6-roundtrip",
        "kind": "cpu",
        "cpu_task_kind": "tests",
        "cpu_threads": 1,
        "cpu_core_seconds": 20,
        "gpu_seconds": 0,
        "new_storage_bytes": 400,
    }
    original = module._BASE_TREE_BYTES
    module._ACTIVE_DATA_ROOT = data_root.resolve()
    try:
        module._BASE_TREE_BYTES = lambda _root: (_ for _ in ()).throw(AssertionError("Home parent scan"))
        assert module.tree_bytes(data_root) == 0
    finally:
        module._BASE_TREE_BYTES = original
        module._ACTIVE_DATA_ROOT = None
    with module.ledger_locked(data_root) as ledger:
        module.check_reservation(ledger, reservation, existing_bytes=10**12, available_bytes=10_000_000)
        ledger["reservations"].append(dict(reservation))
        ledger["attempts"].append({"id": reservation["id"], "kind": "cpu", "status": "reserved"})
    with module.ledger_locked(data_root) as ledger:
        ledger["reservations"] = []
        ledger["charges"].append({"id": reservation["id"], "gpu_seconds": 0,
                                   "cpu_core_seconds": 1.25, "new_storage_bytes": 211,
                                   "status": "completed"})
        ledger["attempts"][0]["status"] = "completed"
    final = json.loads(ledger_path.read_text())
    assert final["reservations"] == []
    assert final["charges"][0]["new_storage_bytes"] == 211

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_ledger_bridge_v9_forward_v6.py"
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v9-forward-v6/"
    "f2-s1-portable-ledger-bridge-request-v9-002.json"
)
SPEC = importlib.util.spec_from_file_location("portable_bridge_v9_forward_v6_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_forward_request_binds_v6_closure_and_preserves_v9_001() -> None:
    value = json.loads(REQUEST.read_text())
    assert value["schema"] == module.SCHEMA
    assert value["sha256"] == module.canonical_sha(value)
    assert value["forward_of"] == {
        "prior_attempt_id": "f2-s1-portable-ledger-bridge-v9-001",
        "prior_request_is_immutable": True,
        "revision": "v9-forward-v6",
    }
    assert {item["role"] for item in value["guard_bindings"]} == set(module.V6_GUARD_ROLES)
    assert all("_v6.py" in item["path"] or item["role"] == "shared_runtime_v2"
               for item in value["guard_bindings"])
    assert value["execution"]["prevalidation_cost"]["included_in_same_parent_charge"] is True
    assert value["model_invoked"] is False and value["cfd_invoked"] is False


def test_forward_metadata_preflight_is_read_only() -> None:
    value = module.run(REQUEST, io_slot_approved=False)
    assert value["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert value["execution_boundary"]["ledger_mutated"] is False
    assert value["execution_boundary"]["hdf5_opened"] is False
    assert value["prevalidation"]["process_and_children_cpu_seconds"] >= 0


def test_forward_bridge_charges_manufactured_parent_ledger(tmp_path: Path) -> None:
    data_root = tmp_path / "data-root"
    runtime_dir = data_root / "runtime"
    runtime_dir.mkdir(parents=True)
    ledger = {
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "limits": {"gpu_seconds": 1000.0, "cpu_core_seconds": 1000.0,
                   "new_storage_bytes": 10000, "qualification_attempts": 10,
                   "production_attempts": 10, "storage_policy": "home_free_floor",
                   "home_min_free_bytes": 100},
        "charges": [],
        "reservations": [{"id": "v9-v6-manufactured", "new_storage_bytes": 500}],
        "attempts": [{"id": "v9-v6-manufactured", "kind": "cpu", "status": "reserved"}],
    }
    ledger_path = runtime_dir / "resource-ledger.json"
    ledger_path.write_text(json.dumps(ledger))
    request = {
        "data_root": str(data_root),
        "attempt_id": "v9-v6-manufactured",
        "external_storage_scope": {"filesystem": str(tmp_path)},
    }
    reservation = {"id": "v9-v6-manufactured", "new_storage_bytes": 500}
    module._charge_parent(object(), module._load_shared_v6(
        ROOT / "scripts" / "ds_data02_stage2_dispatch_v6.py")[1], request,
        reservation=reservation, actual_bytes=321, cpu_seconds=2.5,
        status="failed", finished_at="2026-10-08T00:00:00Z")
    final = json.loads(ledger_path.read_text())
    assert final["reservations"] == []
    assert final["charges"] == [{
        "id": "v9-v6-manufactured", "gpu_seconds": 0.0,
        "cpu_core_seconds": 2.5, "new_storage_bytes": 321,
        "status": "failed", "finished_at_utc": "2026-10-08T00:00:00Z",
        "storage_filesystem": str(tmp_path),
        "storage_filesystems": [str(tmp_path), str(data_root)],
        "accounting_scope": "external_target_selected_roots_sidecars_plus_home_bridge_receipt",
    }]
    assert final["attempts"][0]["status"] == "failed"


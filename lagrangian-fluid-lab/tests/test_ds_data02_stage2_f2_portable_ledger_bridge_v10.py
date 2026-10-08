from __future__ import annotations

import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_ledger_bridge_v10.py"
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v10-hardwall-v6/"
    "f2-s1-portable-ledger-bridge-request-v10-006.json"
)
CONTRACT_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_v6_execution_contract.py"
CONTRACT = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v10-hardwall-v6/"
    "f2-s1-portable-ledger-execution-contract-v6-006.json"
)

spec = importlib.util.spec_from_file_location("portable_bridge_v10_test_module", SCRIPT)
assert spec is not None and spec.loader is not None
sys.path.insert(0, str(SCRIPT.parent))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_v10_metadata_preflight_is_read_only_and_source_bound() -> None:
    request = json.loads(REQUEST.read_text())
    assert request["schema"] == module.SCHEMA
    assert request["sha256"] == module.canonical_sha(request)
    assert request["attempt_id"].endswith("v10-006")
    assert request["qualification"] == module.UNKNOWN
    assert request["model_invoked"] is False
    assert request["cfd_invoked"] is False
    assert {item["role"] for item in request["guard_bindings"]} == set(module.V6_GUARD_ROLES)

    result = module.run(REQUEST, io_slot_approved=False)

    assert result["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert result["execution_boundary"] == {
        "ledger_mutated": False,
        "raw_opened": False,
        "hdf5_opened": False,
        "model_invoked": False,
        "cfd_invoked": False,
    }
    assert result["source_count"] == len(request["source_bindings"])


def test_v10_nested_loader_timeout_terminates_only_child_group() -> None:
    previous = module._ACTIVE_DEADLINE
    module._ACTIVE_DEADLINE = module._Deadline(0.2)
    started = time.monotonic()
    try:
        with pytest.raises(module.BridgeDeadlineExceeded, match="nested loader"):
            module._bounded_subprocess_run(
                [sys.executable, "-c", "import time; time.sleep(3)"],
                capture_output=True,
                text=True,
            )
    finally:
        module._ACTIVE_DEADLINE = previous
    assert time.monotonic() - started < 1.5


def test_v6_execution_contract_records_inner_and_parent_wall_guards() -> None:
    contract = json.loads(CONTRACT.read_text())
    contract_module_spec = importlib.util.spec_from_file_location(
        "execution_contract_test_module", CONTRACT_SCRIPT
    )
    assert contract_module_spec is not None and contract_module_spec.loader is not None
    contract_module = importlib.util.module_from_spec(contract_module_spec)
    contract_module_spec.loader.exec_module(contract_module)

    assert contract["sha256"] == contract_module.canonical_sha(contract)
    boundary = contract["parent_boundary"]
    assert "bridge entry-to-finalization timer" in boundary["hard_wall_owner"]
    assert boundary["cancellation"]["bridge_inner_timeout"] is True
    assert boundary["cancellation"]["nested_loader"].startswith("inherits")
    assert contract["dependencies"]["source_binding_count"] == 456
    assert contract["model_invoked"] is False
    assert contract["qualification"] == module.UNKNOWN


def test_v10_manufactured_timeout_charges_registered_parent_attempt(tmp_path: Path, monkeypatch) -> None:
    """Exercise the approved bridge path without H5/BI4 payloads."""
    data_root = tmp_path / "data-root"
    (data_root / "runtime").mkdir(parents=True)
    ledger_path = data_root / "runtime/resource-ledger.json"
    ledger_path.write_text(json.dumps({
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {"gpu_seconds": 10.0, "cpu_core_seconds": 100.0,
                   "new_storage_bytes": 100_000, "qualification_attempts": 1,
                   "production_attempts": 1},
        "charges": [], "reservations": [], "attempts": [],
    }))
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text("{}")
    dispatch_path = tmp_path / "dispatch-v6.py"
    dispatch_path.write_text("# manufactured dispatch binding\n")
    v7_request_path = tmp_path / "v7-request.json"
    v7_request_path.write_text("{}")
    child_pid_path = tmp_path / "child.pid"
    child_script = tmp_path / "sleep-child.py"
    child_script.write_text(
        f"import os, pathlib, time\npathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid()))\ntime.sleep(3)\n"
    )
    engine = tmp_path / "fake-v7-engine.py"
    engine.write_text(
        "import pathlib, subprocess, sys\n"
        "def _validate_request(*args, **kwargs): return None\n"
        "def run(*args, **kwargs):\n"
        f"    subprocess.run([sys.executable, {str(child_script)!r}], capture_output=True, text=True)\n"
        "    return {'status': 'COMPLETE_DEVELOPMENT_UNKNOWN'}\n"
    )

    class FakeRuntime:
        @staticmethod
        def tree_bytes(root):
            return 0

        @contextmanager
        def ledger_locked(self, root):
            value = json.loads(ledger_path.read_text())
            yield value
            ledger_path.write_text(json.dumps(value))

    class FakeDispatch:
        @staticmethod
        def check_reservation(*args, **kwargs):
            return None

    def fake_load_shared(_path):
        return FakeDispatch(), FakeRuntime()

    monkeypatch.setattr(module, "_validate", lambda request, verify_content: [])
    monkeypatch.setattr(module, "_load_shared_v6", fake_load_shared)
    monkeypatch.setattr(module, "_load_v7", lambda path: {
        "execution": {"command": [sys.executable, "-B", str(engine)]},
    })

    request = {
        "data_root": str(data_root),
        "attempt_id": "manufactured-timeout",
        "reservation": {
            "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 1,
            "max_wall_seconds": 0.25, "cpu_core_seconds": 1.0, "gpu_seconds": 0,
            "new_storage_bytes": 100_000, "external_product_reserved_bytes": 50_000,
            "home_receipt_reserved_bytes": 50_000,
        },
        "parent_resource_binding": {
            "path": str(ledger_path), "checkpoint_path": str(checkpoint),
            "no_reset": True, "no_new_data_root_ledger": True,
        },
        "guard_bindings": [{"role": "shared_dispatch_v6", "path": str(dispatch_path)}],
        "source_bindings": [{"role": "v7:portable_orchestrator_v7", "path": str(engine)}],
        "v7_request": {"path": str(v7_request_path)},
        "external_storage_scope": {
            "filesystem": str(tmp_path),
            "roots": [str(tmp_path / "target"), str(tmp_path / "products")],
            "expected_artifacts": [{"role": "manufactured", "path": str(tmp_path / "missing.json")}],
        },
    }
    request_path = tmp_path / "bridge-request.json"
    request_path.write_text(json.dumps(request))

    started = time.monotonic()
    result = module.run(request_path, io_slot_approved=True)
    elapsed = time.monotonic() - started

    assert result["status"] == "FAILED_PARENT_BRIDGED_REPLAY"
    assert result["deadline"]["status"] == "EXCEEDED"
    assert result["parent_ledger"]["reservation_registered"] is True
    assert elapsed < 2.0
    final = json.loads(ledger_path.read_text())
    assert final["reservations"] == []
    assert final["charges"][-1]["status"] == "failed"
    assert child_pid_path.is_file()
    child_pid = int(child_pid_path.read_text())
    with pytest.raises(FileNotFoundError):
        # The nested loader was started in the bridge-owned process group and
        # must not survive the deadline.  /proc lookup avoids signal delivery.
        Path(f"/proc/{child_pid}").stat()

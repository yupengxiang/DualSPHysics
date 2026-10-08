from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_runtime_v8.py"
DISPATCH = ROOT / "scripts" / "ds_data02_stage2_dispatch_v8.py"
SPEC = importlib.util.spec_from_file_location("runtime_v8_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sys.path.insert(0, str(SCRIPT.parent))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _ledger() -> dict:
    return {
        "schema": "ds02.resource-ledger.v1",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "limits": {
            "gpu_seconds": 0.0,
            "cpu_core_seconds": 1000.0,
            "new_storage_bytes": 100_000,
            "qualification_attempts": 1,
            "production_attempts": 1,
            "storage_policy": "home_free_floor",
            "home_min_free_bytes": 100,
        },
        "charges": [],
        "reservations": [],
        "attempts": [],
    }


def _request(tmp_path: Path, *, max_wall: float = 20.0) -> tuple[dict, Path, Path]:
    data_root = tmp_path / "data-root"
    (data_root / "runtime").mkdir(parents=True)
    (data_root / "runtime" / "resource-ledger.json").write_text(json.dumps(_ledger()))
    source = tmp_path / "source.csv"
    source.write_text("source-bound-small\n")
    request = {
        "family_id": "F7",
        "case_id": "manufactured-v8-prehash",
        "attempt_id": "v8-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "command": [sys.executable, "-c", "pass"],
        "cwd": str(ROOT),
        "max_wall_seconds": max_wall,
        "cpu_threads": 1,
        "estimated_storage_bytes": 100_000,
        "input_files": [str(source)],
        "worktree_root": str(ROOT),
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    return request, request_path, data_root


def test_v8_hashes_content_only_after_atomic_reservation(tmp_path: Path, monkeypatch) -> None:
    request, request_path, data_root = _request(tmp_path)
    source = Path(request["input_files"][0])
    observed: list[bool] = []

    def fake_full_validate(value, *, approval_context=None):
        ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
        attempt = f"{value['family_id']}/{value['case_id']}/{value['attempt_id']}"
        observed.append(any(row.get("id") == attempt for row in ledger["reservations"]))
        # Manufacture measurable source-validation CPU after the reservation.
        total = 0
        for number in range(300_000):
            total += number * 7
        assert total > 0
        return {str(source.resolve()): hashlib.sha256(source.read_bytes()).hexdigest()}

    monkeypatch.setattr(MODULE, "validate_request", fake_full_validate)
    original_sha256 = MODULE.base.sha256

    def burning_sha256(path):
        total = 0
        for number in range(120_000):
            total += number * 11
        assert total > 0
        return original_sha256(path)

    # This burn occurs in the post-run source hash and receipt/output hashes;
    # v8's cutoff must include it while the terminal writer itself remains
    # outside the cutoff.
    monkeypatch.setattr(MODULE.base, "sha256", burning_sha256)
    result = MODULE.run_request(request_path, data_root=data_root)
    assert result["status"] == "completed"
    assert observed == [True]
    receipt_path = data_root / "families/F7/manufactured-v8-prehash/v8-001/execution-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["source_preflight"]["reservation_registered_before_content_hash"] is True
    assert receipt["source_preflight"]["status"] == "PASS_AFTER_RESERVATION"
    assert receipt["timing_scope"]["reservation_before_input_content_hash"] is True
    ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
    assert ledger["reservations"] == []
    assert ledger["charges"][-1]["status"] == "completed"
    assert ledger["charges"][-1]["cpu_core_seconds"] > 0
    assert receipt["cpu_core_seconds"] == ledger["charges"][-1]["cpu_core_seconds"]
    assert receipt["timing_scope"]["cpu_cutoff_value_reused_for_ledger_charge"] is True
    assert receipt["runner_git_at_launch"] is not None
    assert receipt["git_at_launch"] is not None
    assert receipt["started_at_utc"] == receipt["reservation_started_at_utc"] or receipt["started_at_utc"]


def test_v8_pre_hash_timeout_gets_terminal_failure_charge(tmp_path: Path, monkeypatch) -> None:
    request, request_path, data_root = _request(tmp_path, max_wall=0.2)

    def hanging_validate(value, *, approval_context=None):
        while True:
            time.sleep(0.05)

    monkeypatch.setattr(MODULE, "validate_request", hanging_validate)
    started = time.monotonic()
    result = MODULE.run_request(request_path, data_root=data_root)
    elapsed = time.monotonic() - started
    assert elapsed < 1.5
    assert result["status"] == "failed"
    assert result["deadline_status"] == "EXCEEDED"
    receipt_path = data_root / "families/F7/manufactured-v8-prehash/v8-001/execution-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "failed"
    assert receipt["source_preflight"]["status"] == "SKIPPED_AFTER_DEADLINE_OR_CANCEL"
    ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
    assert ledger["reservations"] == []
    assert ledger["charges"][-1]["status"] == "failed"
    assert receipt["cpu_core_seconds"] == ledger["charges"][-1]["cpu_core_seconds"]


def test_v8_cancel_after_real_reservation_gets_terminal_failure_charge(tmp_path: Path, monkeypatch) -> None:
    request, request_path, data_root = _request(tmp_path, max_wall=2.0)

    def cancel_validate(value, *, approval_context=None):
        os.kill(os.getpid(), signal.SIGTERM)
        raise AssertionError("SIGTERM should have raised the v8 cancellation handler")

    monkeypatch.setattr(MODULE, "validate_request", cancel_validate)
    result = MODULE.run_request(request_path, data_root=data_root)
    assert result["status"] == "failed"
    assert result["deadline_status"] == "CANCELLED"
    receipt_path = data_root / "families/F7/manufactured-v8-prehash/v8-001/execution-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["deadline"]["status"] == "CANCELLED"
    assert ledger["reservations"] == []
    assert ledger["charges"][-1]["status"] == "failed"
    assert receipt["cpu_core_seconds"] == ledger["charges"][-1]["cpu_core_seconds"]


def test_v8_dispatch_binds_all_forward_runtime_sources() -> None:
    spec = importlib.util.spec_from_file_location("dispatch_v8_test_module", DISPATCH)
    assert spec is not None and spec.loader is not None
    dispatch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dispatch)
    assert all(Path(path).is_file() for path in dispatch.BOUND_RUNNER_FILES)
    assert dispatch.runtime.RUNTIME_PATH.endswith("ds_data02_runtime_v8.py")
    assert dispatch.runtime.V6_RUNTIME_PATH.endswith("ds_data02_runtime_v6.py")

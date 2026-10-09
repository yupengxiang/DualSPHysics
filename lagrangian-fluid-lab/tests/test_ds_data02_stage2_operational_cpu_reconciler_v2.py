from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_operational_cpu_reconciler_v2.py"
RUNTIME = ROOT / "scripts" / "ds_data02_runtime_v2.py"
spec = importlib.util.spec_from_file_location("ds02_operational_cpu_reconciler_v2", SCRIPT)
assert spec is not None and spec.loader is not None
reconciler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconciler)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict]:
    rows = []
    for pid, start, ticks in (
        (101, 1001, 10_000),
        (102, 1002, 20_000),
        (103, 1003, 30_000),
        (104, 1004, 61_336),
    ):
        rows.append({
            "pid": pid,
            "ppid": pid - 1,
            "cwd": "/small/worktree",
            "argv": ["rg", "-n", "small-pattern", "/small/file-list"],
            "io": "rchar: 100\nread_bytes: 0\n",
            "clock_ticks_per_second": 100,
            "sampled_utime_ticks": ticks,
            "sampled_stime_ticks": 0,
            "sampled_process_cpu_seconds": ticks / 100,
            "process_starttime_ticks": start,
            "parent_argv": ["/usr/bin/zsh", "-lc", "rg -n small-pattern"],
        })
    snapshot = {
        "schema": reconciler.SNAPSHOT_SCHEMA,
        "status": "OWNERSHIP_VERIFIED_SNAPSHOT_BEFORE_SIGNAL",
        "utc": "2026-10-09T00:00:00+00:00",
        "budget_scope": "unreserved operational search, no scientific credit",
        "array_content_read_by_root": False,
        "io_not_equal_decoded_scientific_arrays": True,
        "rows": rows,
    }
    snapshot_path = tmp_path / "snapshot.json"
    _write(snapshot_path, snapshot)
    signal = {
        "schema": reconciler.SIGNAL_SCHEMA,
        "snapshot": str(snapshot_path),
        "foreign_processes_signalled": False,
        "whole_process_terminal_confirmation": "pending additive observation",
        "results": [
            {"pid": row["pid"], "signal": "SIGTERM",
             "only_exact_verified_rg_process_signalled": True}
            for row in rows
        ],
    }
    signal_path = tmp_path / "signal.json"
    _write(signal_path, signal)
    snapshot_sha = reconciler.sha256_file(snapshot_path)
    signal_sha = reconciler.sha256_file(signal_path)
    operational_rows = [
        {
            "observation_id": f"{snapshot_sha}:{row['pid']}:{row['process_starttime_ticks']}",
            "snapshot_sha256": snapshot_sha,
            "signal_sidecar_sha256": signal_sha,
            "pid": row["pid"],
            "process_starttime_ticks": row["process_starttime_ticks"],
            "cwd": row["cwd"],
            "argv": row["argv"],
            "sampled_utime_ticks": row["sampled_utime_ticks"],
            "sampled_stime_ticks": row["sampled_stime_ticks"],
            "clock_ticks_per_second": row["clock_ticks_per_second"],
            "sampled_process_cpu_seconds": row["sampled_process_cpu_seconds"],
            "io_snapshot": row["io"],
            "accounting_status": "SAMPLED_PRE_SIGNAL_ONLY",
            "post_signal_cpu": "UNKNOWN",
            "teardown_cpu": "UNKNOWN",
            "scientific_credit": "NONE",
            "qualification": dict(reconciler.UNKNOWN),
        }
        for row in rows
    ]
    operational = {
        "schema": reconciler.OPERATIONAL_SCHEMA,
        "status": "APPEND_ONLY_OPERATIONAL_NONSCIENTIFIC",
        "accounting_scope": "unreserved operational process sample; no scientific attempt charge",
        "resource_ledger_mutated": False,
        "reservation_created": False,
        "qualification_credit": "NONE",
        "qualification": dict(reconciler.UNKNOWN),
        "rows": operational_rows,
        "append_history": [{
            "snapshot_sha256": snapshot_sha,
            "signal_sidecar_sha256": signal_sha,
            "snapshot_path": str(snapshot_path),
            "signal_path": str(signal_path),
            "base_ledger_sha256": None,
            "row_count": 4,
            "content_read": False,
            "resource_ledger_mutated": False,
        }],
        "last_append": {
            "snapshot_sha256": snapshot_sha,
            "signal_sidecar_sha256": signal_sha,
            "sampled_cpu_seconds_total": 1213.36,
            "rows": 4,
            "status": "OPERATIONAL_SAMPLE_ONLY",
        },
    }
    operational_path = tmp_path / "operational-ledger.json"
    _write(operational_path, operational)

    data_root = tmp_path / "data-root"
    resource_path = data_root / "runtime" / "resource-ledger.json"
    ordinary_id = "F1/case/attempt"
    resource = {
        "schema": "ds02.resource-ledger.test.v1",
        "charges": [{
            "id": ordinary_id,
            "status": "completed",
            "cpu_core_seconds": 2.5,
            "gpu_seconds": 7.0,
            "new_storage_bytes": 123,
        }],
        "reservations": [{
            "id": "active-reservation",
            "cpu_core_seconds": 1.5,
            "gpu_seconds": 0.0,
            "new_storage_bytes": 456,
        }],
        "attempts": [{"id": "attempt-kept", "kind": "qualification", "status": "completed"}],
        "limits": {
            "gpu_seconds": 10_000.0,
            "cpu_core_seconds": 10_000.0,
            "new_storage_bytes": 10_000_000,
            "qualification_attempts": 100,
            "production_attempts": 100,
        },
    }
    _write(resource_path, resource)
    return snapshot_path, signal_path, operational_path, resource_path, resource


def test_reconcile_appends_sampled_cpu_only_and_is_idempotent(tmp_path: Path) -> None:
    snapshot, signal, operational, resource, original = _inputs(tmp_path)
    output = tmp_path / "reconciliation.json"
    inspected = reconciler.inspect(
        snapshot_path=snapshot, signal_path=signal,
        operational_ledger_path=operational, resource_ledger_path=resource,
        runtime_path=RUNTIME,
    )
    assert inspected["sampled_cpu_seconds"] == pytest.approx(1213.36)
    result = reconciler.reconcile(
        snapshot_path=snapshot, signal_path=signal,
        operational_ledger_path=operational, resource_ledger_path=resource,
        runtime_path=RUNTIME, output=output,
    )
    assert result["status"] == "APPENDED_OPERATIONAL_CPU_SAMPLE"
    saved = json.loads(resource.read_text(encoding="utf-8"))
    assert saved["attempts"] == original["attempts"]
    assert saved["reservations"] == original["reservations"]
    assert saved["charges"][0] == original["charges"][0]
    rows = [row for row in saved["charges"] if row.get("kind") == "operational_cpu_sample"]
    assert len(rows) == 1
    assert rows[0]["cpu_core_seconds"] == pytest.approx(1213.36)
    assert rows[0]["gpu_seconds"] == 0.0
    assert rows[0]["new_storage_bytes"] == 0
    assert rows[0]["reservation_created"] is False
    assert rows[0]["ancestor_cpu_seconds"] == "UNKNOWN"
    assert rows[0]["teardown_cpu_seconds"] == "UNKNOWN"
    repeated = reconciler.reconcile(
        snapshot_path=snapshot, signal_path=signal,
        operational_ledger_path=operational, resource_ledger_path=resource,
        runtime_path=RUNTIME, output=output,
    )
    assert repeated["status"] == "ALREADY_APPLIED_OPERATIONAL_CPU_SAMPLE"
    saved_again = json.loads(resource.read_text(encoding="utf-8"))
    assert len([row for row in saved_again["charges"] if row.get("kind") == "operational_cpu_sample"]) == 1


def test_reconcile_rejects_duplicate_identity_and_bad_signal_sha(tmp_path: Path) -> None:
    snapshot, signal, operational, resource, _original = _inputs(tmp_path)
    value = json.loads(operational.read_text(encoding="utf-8"))
    value["rows"][1]["pid"] = value["rows"][0]["pid"]
    value["rows"][1]["process_starttime_ticks"] = value["rows"][0]["process_starttime_ticks"]
    _write(operational, value)
    with pytest.raises(reconciler.OperationalReconciliationError, match="duplicate operational"):
        reconciler.inspect(
            snapshot_path=snapshot, signal_path=signal,
            operational_ledger_path=operational, resource_ledger_path=resource,
            runtime_path=RUNTIME,
        )

    snapshot, signal, operational, resource, _original = _inputs(tmp_path / "bad-signal")
    signal_value = json.loads(signal.read_text(encoding="utf-8"))
    signal_value["results"][0]["pid"] = 999999
    _write(signal, signal_value)
    with pytest.raises(reconciler.OperationalReconciliationError, match="signal PID"):
        reconciler.inspect(
            snapshot_path=snapshot, signal_path=signal,
            operational_ledger_path=operational, resource_ledger_path=resource,
            runtime_path=RUNTIME,
        )


def test_reconcile_rejects_conflicting_existing_operational_charge(tmp_path: Path) -> None:
    snapshot, signal, operational, resource, _original = _inputs(tmp_path)
    observation = reconciler._load_observation(
        snapshot_path=snapshot, signal_path=signal, operational_ledger_path=operational
    )
    charge_id = "operational::stale-search::" + observation["snapshot"]["sha256"]
    value = json.loads(resource.read_text(encoding="utf-8"))
    value["charges"].append({
        "id": charge_id,
        "kind": "operational_cpu_sample",
        "status": "sampled_operational_only",
        "cpu_core_seconds": 1.0,
        "gpu_seconds": 0.0,
        "new_storage_bytes": 0,
        "reservation_created": False,
        "snapshot_sha256": observation["snapshot"]["sha256"],
        "signal_sidecar_sha256": observation["signal"]["sha256"],
        "operational_ledger_sha256": observation["operational_ledger"]["sha256"],
    })
    _write(resource, value)
    with pytest.raises(reconciler.OperationalReconciliationError, match="different accounting"):
        reconciler.reconcile(
            snapshot_path=snapshot, signal_path=signal,
            operational_ledger_path=operational, resource_ledger_path=resource,
            runtime_path=RUNTIME, output=tmp_path / "reconciliation.json",
        )

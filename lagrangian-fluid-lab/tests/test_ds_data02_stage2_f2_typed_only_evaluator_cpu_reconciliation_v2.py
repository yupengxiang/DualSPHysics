from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_cpu_reconciliation_v2.py"
RUNTIME_V6 = ROOT / "scripts/ds_data02_runtime_v6.py"


def _load():
    spec = importlib.util.spec_from_file_location("typed_cpu_reconciliation_v2_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = _load()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    data_root = tmp_path / "data-root"
    runtime_dir = data_root / "runtime"
    runtime_dir.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    ledger = runtime_dir / "resource-ledger.json"
    ledger.write_text(json.dumps({
        "deadline_utc": "2099-01-01T00:00:00+00:00",
        "limits": {"home_path": str(home), "storage_policy": "home_free_floor",
                   "home_min_free_bytes": 0, "cpu_core_seconds": 1000,
                   "gpu_seconds": 1000, "new_storage_bytes": 10**9},
        "attempts": [], "charges": [], "reservations": []}) + "\n", encoding="utf-8")
    original = tmp_path / "original-request.json"
    original_value = {
        "schema": "fixture.terminal-request.v1", "status": "COMPLETED",
        "parent_resource_binding": {"ledger_path": str(ledger), "attempt_id": "root093",
                                     "charge_id": "root093::charge"},
        "accounting": {"charge_id": "root093::charge"},
        "static_bindings": [{"role": "shared_runtime_v6", "path": str(RUNTIME_V6),
                             "sha256": R.sha256_file(RUNTIME_V6)}],
    }
    original_value["sha256"] = R.canonical_sha(original_value)
    original.write_text(json.dumps(original_value) + "\n", encoding="utf-8")
    ledger_value = json.loads(ledger.read_text(encoding="utf-8"))
    ledger_value["charges"].append({"id": "root093::charge", "status": "completed",
                                     "cpu_core_seconds": 2.153004,
                                     "external_storage_bytes": 0, "home_storage_bytes": 0})
    ledger.write_text(json.dumps(ledger_value) + "\n", encoding="utf-8")
    return original, ledger


def test_completed_terminal_delta_binds_unit_receipt_and_is_idempotent(tmp_path: Path) -> None:
    original, ledger = _fixture(tmp_path)
    unit = "ds02-root093"
    evidence = tmp_path / "systemd-cpu-evidence.json"
    value = {"schema": "ds02.stage2.f2-typed-only-evaluator-cpu-evidence.v2",
             "status": "OBSERVED_SERVICE_CPU", "CPUUsageNSec": 2_376_480_000,
             "source_scope": {"unit": unit}}
    value["sha256"] = R.canonical_sha(value)
    evidence.write_text(json.dumps(value) + "\n", encoding="utf-8")
    receipt = tmp_path / "terminal-receipt.json"
    receipt_value = {"schema": "fixture.terminal-receipt.v1", "status": "COMPLETED",
                     "unit_name": unit, "request": {"attempt_id": "root093"}}
    receipt_value["sha256"] = R.canonical_sha(receipt_value)
    receipt.write_text(json.dumps(receipt_value) + "\n", encoding="utf-8")
    request = tmp_path / "reconcile-request.json"
    result = R.build_request(
        original_request=original, evidence=evidence, output=request,
        report_path=tmp_path / "reconcile-report.json", terminal_receipt=receipt,
        unit_name=unit)
    assert result["original_cpu_seconds"] == pytest.approx(2.153004)
    assert result["observed_cpu_seconds"] == pytest.approx(2.376480)
    assert result["delta_cpu_seconds"] == pytest.approx(0.223476)
    bound = json.loads(request.read_text(encoding="utf-8"))
    assert bound["accounting"]["original_charge_immutable"] is True
    assert bound["terminal_receipt"]["sha256"] == R.sha256_file(receipt)
    first = R.apply(request)
    assert first["status"] == "CPU_DELTA_RECONCILED"
    second = R.apply(request)
    assert second["status"] == "IDEMPOTENT_ALREADY_RECONCILED"
    updated = json.loads(ledger.read_text(encoding="utf-8"))
    assert len(updated["charges"]) == 2
    assert updated["charges"][0]["cpu_core_seconds"] == pytest.approx(2.153004)
    assert updated["charges"][1]["cpu_core_seconds"] == pytest.approx(0.223476)


def test_lower_service_cpu_is_rejected_without_a_zero_or_negative_delta(tmp_path: Path) -> None:
    original, _ = _fixture(tmp_path)
    evidence = tmp_path / "systemd-cpu-evidence.json"
    value = {"schema": R.EVIDENCE_SCHEMA, "status": "OBSERVED_SERVICE_CPU",
             "cpu_usage_nanoseconds": 2_000_000_000,
             "source_scope": {"unit": "ds02-root093"}}
    value["sha256"] = R.canonical_sha(value)
    evidence.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(R.CpuReconciliationError, match="does not exceed"):
        R.build_request(original_request=original, evidence=evidence,
                        output=tmp_path / "request.json",
                        report_path=tmp_path / "report.json")

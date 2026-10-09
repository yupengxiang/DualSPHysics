from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_v63_terminal_cpu_delta_adapter_v1.py"
spec = importlib.util.spec_from_file_location("v63_terminal_delta", SCRIPT)
assert spec is not None and spec.loader is not None
V63 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V63)


def _dump(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    data = tmp_path / "data"
    ledger = data / "runtime/resource-ledger.json"
    ledger.parent.mkdir(parents=True)
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "from contextlib import contextmanager\n"
        "import json\n"
        "from pathlib import Path\n"
        "@contextmanager\n"
        "def ledger_locked(data_root):\n"
        "    path = Path(data_root) / 'runtime/resource-ledger.json'\n"
        "    value = json.loads(path.read_text())\n"
        "    yield value\n"
        "    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\\n')\n",
        encoding="utf-8",
    )
    charge_id = "v63-parent-opaque-001::charge"
    attempt = "v63-parent-opaque-001"
    request = tmp_path / "request.json"
    receipt = home / "home-receipt.json"
    report = home / "returned-report.json"
    evidence = home / "systemd-evidence.json"
    req = {
        "schema": "ds02.stage2.f2-root145-copied-recovery-parent-request.v63",
        "status": "READY_FOR_PARENT_GUARD",
        "attempt_id": attempt,
        "family_id": "F2",
        "case_id": "CASE-78",
        "parent_resource_binding": {
            "ledger_path": str(ledger), "home_path": str(home),
            "attempt_id": attempt, "charge_id": charge_id,
            "same_parent_ledger": True, "allow_missing_parent": True,
        },
        "runtime_binding": {"path": str(runtime), "sha256": V63.sha256_file(runtime)},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    req["sha256"] = V63._canonical(req)
    _dump(request, req)
    request_sha = V63.sha256_file(request)
    receipt_value = {
        "schema": "test.home-receipt.v1",
        "request": {"path": str(request), "sha256": request_sha},
        "accounting": {"charge_id": charge_id},
        "filesystem": {"home_receipt_bytes": 0},
    }
    _dump(receipt, receipt_value)
    receipt_value["filesystem"]["home_receipt_bytes"] = receipt.stat().st_size
    _dump(receipt, receipt_value)
    # One final stat stabilization is enough for this fixed-size JSON fixture.
    if receipt_value["filesystem"]["home_receipt_bytes"] != receipt.stat().st_size:
        receipt_value["filesystem"]["home_receipt_bytes"] = receipt.stat().st_size
        _dump(receipt, receipt_value)
    home_bytes = receipt.stat().st_size
    original = {
        "id": charge_id, "status": "failed", "cpu_core_seconds": 2.5,
        "external_storage_bytes": 10, "home_storage_bytes": home_bytes,
        "trace_bytes": 0, "copy_hash_bytes": 3,
        "new_storage_bytes": 10 + home_bytes,
    }
    _dump(ledger, {"charges": [original], "reservations": [], "limits": {}})
    report_value = {
        "schema": "ds02.stage2.f2-root145-copied-recovery-report.v63",
        "status": "FAILED_PARENT_EXECUTOR",
        "request_sha256": request_sha,
        "report_path": str(report),
        "ledger_mutated": True,
        "external_bytes": 10, "home_bytes": home_bytes,
        "charge": {"status": "PARENT_CHARGE_APPLIED", "charge": dict(original)},
    }
    _dump(report, report_value)
    evidence_value = {
        "schema": "ds02.stage2.systemd-cpu-evidence.v1", "terminal": True,
        "unit": "ds02-v63-test.service", "request": str(request),
        "request_sha256": request_sha, "receipt": str(receipt),
        "receipt_sha256": V63.sha256_file(receipt),
        "actual_returned_report": str(report),
        "actual_returned_report_sha256": V63.sha256_file(report),
        "charge_id": charge_id, "CPUUsageNSec": "2750000000",
        "cpu_usage_nsec": 2750000000,
        "systemd_properties": {
            "Id": "ds02-v63-test.service", "InvocationID": "inv-v63-test",
            "SubState": "failed", "CPUUsageNSec": 2750000000,
            "ExecStart": f"/bin/runner --request {request}",
        },
    }
    _dump(evidence, evidence_value)
    return request, report, receipt, evidence, ledger


def test_inspect_binds_opaque_charge_and_separate_metadata(tmp_path: Path) -> None:
    request, report, receipt, evidence, ledger = _fixture(tmp_path)
    value = V63.inspect_binding(request_path=request, report_path=report,
                                receipt_path=receipt, evidence_path=evidence,
                                ledger_path=ledger)
    assert value["status"] == "READY_FOR_SAME_PARENT_TERMINAL_DELTA"
    assert value["delta_cpu_core_seconds"] == pytest.approx(0.25)
    assert value["additional_returned_report_bytes"] == report.stat().st_size
    assert value["additional_terminal_evidence_bytes"] == evidence.stat().st_size
    assert value["additional_metadata_bytes"] == report.stat().st_size + evidence.stat().st_size
    assert value["reservation_created"] is False


def test_inspect_rejects_wrong_exec_request_and_cpu_copy(tmp_path: Path) -> None:
    request, report, receipt, evidence, ledger = _fixture(tmp_path)
    bad = json.loads(evidence.read_text(encoding="utf-8"))
    bad["systemd_properties"]["ExecStart"] = "/bin/runner --request /wrong/request.json"
    bad_path = tmp_path / "bad-evidence.json"
    _dump(bad_path, bad)
    with pytest.raises(V63.ReconciliationError, match="ExecStart"):
        V63.inspect_binding(request_path=request, report_path=report,
                            receipt_path=receipt, evidence_path=bad_path,
                            ledger_path=ledger)
    bad["systemd_properties"]["ExecStart"] = f"/bin/runner --request {request}"
    bad["systemd_properties"]["CPUUsageNSec"] = 2750000010
    _dump(bad_path, bad)
    with pytest.raises(V63.ReconciliationError, match="CPUUsageNSec copies differ"):
        V63.inspect_binding(request_path=request, report_path=report,
                            receipt_path=receipt, evidence_path=bad_path,
                            ledger_path=ledger)


def test_apply_requires_explicit_authorization_and_is_idempotent(tmp_path: Path) -> None:
    request, report, receipt, evidence, ledger = _fixture(tmp_path)
    output = tmp_path / "reconciliation.json"
    with pytest.raises(V63.ReconciliationError, match="explicit allow"):
        V63.apply_binding(request_path=request, report_path=report,
                          receipt_path=receipt, evidence_path=evidence,
                          ledger_path=ledger, output=output)
    before = json.loads(ledger.read_text(encoding="utf-8"))
    first = V63.apply_binding(request_path=request, report_path=report,
                              receipt_path=receipt, evidence_path=evidence,
                              ledger_path=ledger, output=output,
                              allow_ledger_mutation=True)
    assert first["status"] == "APPENDED_SAME_PARENT_TERMINAL_DELTA"
    value = json.loads(ledger.read_text(encoding="utf-8"))
    rows = [row for row in value["charges"] if row["id"] == first["supplemental_charge_id"]]
    assert len(rows) == 1
    assert rows[0]["cpu_core_seconds"] == pytest.approx(0.25)
    assert rows[0]["returned_report_bytes"] == report.stat().st_size
    assert rows[0]["terminal_evidence_bytes"] == evidence.stat().st_size
    second = V63.apply_binding(request_path=request, report_path=report,
                               receipt_path=receipt, evidence_path=evidence,
                               ledger_path=ledger, output=output,
                               allow_ledger_mutation=True)
    assert second["status"] == "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA"
    value_again = json.loads(ledger.read_text(encoding="utf-8"))
    assert len([row for row in value_again["charges"] if row["id"] == first["supplemental_charge_id"]]) == 1
    assert len(value_again["charges"]) == len(before["charges"]) + 1

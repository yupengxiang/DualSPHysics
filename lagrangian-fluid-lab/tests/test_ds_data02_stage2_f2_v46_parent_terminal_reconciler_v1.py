from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_v46_parent_terminal_reconciler_v1.py"
spec = importlib.util.spec_from_file_location("v46_terminal_reconciler_under_test", SCRIPT)
assert spec is not None and spec.loader is not None
V1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V1)

ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ROOT_STAGE2 = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REQUEST = ROOT_STAGE2 / (
    "native-reconstruction/raw-to-label-v46-parent-closure-root-082/"
    "f2-s1-portable-parent-request-v46-root-082.json"
)
RETURNED_REPORT = ROOT_STAGE2 / (
    "native-reconstruction/raw-to-label-v46-parent-closure-root-082/"
    "actual-returned-parent-report.json"
)
EVIDENCE = ROOT_STAGE2 / (
    "native-reconstruction/raw-to-label-v46-parent-closure-root-082/"
    "actual-terminal-systemd-cpu-evidence.json"
)
RECEIPT = ROOT_STAGE2 / (
    "native-reconstruction/raw-to-label-v45-full-chain-root-082/"
    "f2-s1-portable-parent-v45-root-082-receipt.json"
)
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")


def _dump(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Make a small JSON-only copy with an isolated resource ledger."""
    data_root = tmp_path / "data-root"
    ledger = data_root / "runtime/resource-ledger.json"
    ledger.parent.mkdir(parents=True)
    shutil.copyfile(LEDGER, ledger)
    request = tmp_path / "request.json"
    receipt = tmp_path / "home-receipt.json"
    report = tmp_path / "returned-report.json"
    evidence = tmp_path / "systemd-evidence.json"
    req = json.loads(REQUEST.read_text(encoding="utf-8"))
    rec = json.loads(RECEIPT.read_text(encoding="utf-8"))
    rep = json.loads(RETURNED_REPORT.read_text(encoding="utf-8"))
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    req["parent_resource_binding"]["ledger_path"] = str(ledger)
    req["parent_resource_binding"]["home_path"] = str(tmp_path)
    req["storage_scope"]["home_receipt_path"] = str(receipt)
    # The request and receipt bind one another.  Iterate only the small JSON
    # files until the receipt byte stat is stable; no scientific source is
    # touched.
    home_bytes = int(rec["filesystem"]["home_receipt_bytes"])
    for _ in range(8):
        req["storage_scope"]["home_receipt_bytes"] = home_bytes
        req["sha256"] = V1._canonical_sha(req)
        _dump(request, req)
        request_sha = V1.sha256_file(request)
        rec["request"]["path"] = str(request)
        rec["request"]["sha256"] = request_sha
        rec["filesystem"]["home_receipt_path"] = str(receipt)
        rec["filesystem"]["home_receipt_bytes"] = home_bytes
        _dump(receipt, rec)
        observed = receipt.stat().st_size
        if observed == home_bytes:
            break
        home_bytes = observed
    req["storage_scope"]["home_receipt_bytes"] = home_bytes
    req["sha256"] = V1._canonical_sha(req)
    _dump(request, req)
    request_sha = V1.sha256_file(request)
    rec["request"]["sha256"] = request_sha
    rec["filesystem"]["home_receipt_bytes"] = home_bytes
    _dump(receipt, rec)
    home_bytes = receipt.stat().st_size
    if home_bytes != int(rec["filesystem"]["home_receipt_bytes"]):
        rec["filesystem"]["home_receipt_bytes"] = home_bytes
        _dump(receipt, rec)
    request_sha = V1.sha256_file(request)

    rep["request_sha256"] = request_sha
    rep["report_path"] = str(receipt)
    row = rep["charge"]["charge"]
    row["home_storage_bytes"] = home_bytes
    row["new_storage_bytes"] = int(row["external_storage_bytes"]) + home_bytes
    rep["home_bytes"] = home_bytes
    rep["external_bytes"] = int(row["external_storage_bytes"])
    _dump(report, rep)

    receipt_sha = V1.sha256_file(receipt)
    report_sha = V1.sha256_file(report)
    ev["request"] = str(request)
    ev["request_sha256"] = request_sha
    ev["receipt"] = str(receipt)
    ev["receipt_sha256"] = receipt_sha
    ev["actual_returned_report"] = str(report)
    ev["actual_returned_report_sha256"] = report_sha
    props = ev["systemd_properties"]
    old_request = str(REQUEST)
    props["ExecStart"] = str(props["ExecStart"]).replace(old_request, str(request))
    ev["raw_systemctl_show"] = str(ev["raw_systemctl_show"]).replace(old_request, str(request))
    _dump(evidence, ev)

    ledger_value = json.loads(ledger.read_text(encoding="utf-8"))
    charge_id = req["accounting"]["charge_id"]
    matches = [item for item in ledger_value["charges"] if item.get("id") == charge_id]
    assert len(matches) == 1
    matches[0]["home_storage_bytes"] = home_bytes
    matches[0]["new_storage_bytes"] = int(matches[0]["external_storage_bytes"]) + home_bytes
    ledger.write_text(json.dumps(ledger_value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return request, report, receipt, evidence, ledger


@pytest.mark.skipif(not REQUEST.is_file(), reason="ROOT082 V46 request is not present")
def test_real_root082_inspection_uses_returned_charge_and_explicit_opaque_id() -> None:
    value = V1.inspect_binding(request_path=REQUEST, report_path=RETURNED_REPORT,
                               receipt_path=RECEIPT, evidence_path=EVIDENCE,
                               ledger_path=LEDGER)
    assert value["status"] == "READY_FOR_SAME_PARENT_TERMINAL_DELTA"
    assert value["request"]["charge_id"] == (
        "f2-s1-portable-executor-v46-parent-root-082-001::f2-v46-parent-charge"
    )
    assert value["delta_cpu_core_seconds"] == pytest.approx(0.239881)
    assert value["returned_parent_report"]["cpu_core_seconds"] == pytest.approx(0.734478)
    assert value["original_home_receipt"]["entry_cpu_core_seconds_ignored"] == pytest.approx(0.732301)
    assert value["additional_home_metadata_bytes"] == 2196 + 4412
    assert value["reservation_created"] is False


@pytest.mark.skipif(not REQUEST.is_file(), reason="ROOT082 V46 request is not present")
def test_reconciler_rejects_wrong_charge_or_duplicate_cpu_evidence(tmp_path: Path) -> None:
    bad_report = json.loads(RETURNED_REPORT.read_text(encoding="utf-8"))
    bad_report["charge"]["charge"]["id"] = "F2/STAGE2/attempt-derived-id"
    bad_report_path = tmp_path / "bad-report.json"
    _dump(bad_report_path, bad_report)
    with pytest.raises(V1.ReconciliationError, match="charge ID differs"):
        V1.inspect_binding(request_path=REQUEST, report_path=bad_report_path,
                           receipt_path=RECEIPT, evidence_path=EVIDENCE,
                           ledger_path=LEDGER)

    bad_evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    bad_evidence["systemd_properties"]["CPUUsageNSec"] = "974359001"
    bad_evidence_path = tmp_path / "bad-evidence.json"
    _dump(bad_evidence_path, bad_evidence)
    with pytest.raises(V1.ReconciliationError, match="nanosecond copies differ"):
        V1.inspect_binding(request_path=REQUEST, report_path=RETURNED_REPORT,
                           receipt_path=RECEIPT, evidence_path=bad_evidence_path,
                           ledger_path=LEDGER)


@pytest.mark.skipif(not REQUEST.is_file(), reason="ROOT082 V46 request is not present")
def test_reconcile_appends_once_to_an_isolated_same_ledger_copy(tmp_path: Path) -> None:
    request, report, receipt, evidence, ledger = _fixture(tmp_path)
    output = tmp_path / "reconciliation.json"
    first = V1.reconcile(request_path=request, report_path=report, receipt_path=receipt,
                         evidence_path=evidence, ledger_path=ledger, output=output)
    assert first["status"] == "APPENDED_SAME_PARENT_TERMINAL_DELTA"
    assert first["delta_cpu_core_seconds"] == pytest.approx(0.239881)
    assert first["additional_home_metadata_bytes"] == report.stat().st_size + evidence.stat().st_size
    value = json.loads(ledger.read_text(encoding="utf-8"))
    rows = [row for row in value["charges"] if row.get("id") == first["supplemental_charge_id"]]
    assert len(rows) == 1
    assert rows[0]["cpu_core_seconds"] == pytest.approx(0.239881)
    assert rows[0]["home_storage_bytes"] == first["additional_home_metadata_bytes"]
    second = V1.reconcile(request_path=request, report_path=report, receipt_path=receipt,
                          evidence_path=evidence, ledger_path=ledger, output=output)
    assert second["status"] == "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA"
    value_again = json.loads(ledger.read_text(encoding="utf-8"))
    rows_again = [row for row in value_again["charges"] if row.get("id") == first["supplemental_charge_id"]]
    assert len(rows_again) == 1

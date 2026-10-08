from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_parent_launcher_v12.py"
V11_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v11-parent-supervised/"
    "f2-s1-parent-supervised-launch-request-v11-001.json"
)
SPEC = importlib.util.spec_from_file_location("parent_launcher_v12_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v12_builds_and_validates_additive_terminal_cleanup_contract(tmp_path: Path) -> None:
    output = tmp_path / "parent-launch-v12.json"
    request = MODULE.build_request(V11_REQUEST, output, cleanup_grace_seconds=2.5)
    assert request["schema"] == MODULE.SCHEMA
    assert request["forward_of"]["schema"] == MODULE.V11_SCHEMA
    assert request["execution"]["cleanup_sequence"][-1] == "verify_terminal_accounting"
    assert request["storage_scope"]["supplemental_delta_is_parent_charge"] is True
    assert request["qualification"] == MODULE.UNKNOWN
    assert request["source_bindings"]
    validated, _v11 = MODULE._validate_launch(request, verify_content=True)
    assert validated["schema"] == MODULE.V11_SCHEMA
    saved = json.loads(output.read_text())
    assert saved["sha256"] == MODULE.canonical_sha(saved)
    assert any(item.get("source_kind") == "parent" for item in request["source_bindings"])


def _ledger_fixture(tmp_path: Path, *, terminal: bool, lease: bool = False) -> tuple[Path, Path]:
    data_root = tmp_path / "data"
    ledger_path = data_root / "runtime" / "resource-ledger.json"
    leases = data_root / "runtime" / "leases"
    leases.mkdir(parents=True)
    attempt = "F2/F2_CASE/attempt-v12-test"
    ledger = {
        "schema": "ds02.resource-ledger.v1",
        "campaign_id": "DS-DATA-02",
        "reservations": [] if terminal else [{"id": attempt, "kind": "cpu"}],
        "charges": [{"id": attempt, "status": "failed", "new_storage_bytes": 11}] if terminal else [],
        "attempts": [{"id": attempt, "kind": "cpu", "status": "failed" if terminal else "reserved"}],
    }
    if lease:
        (leases / "GPU-test.json").write_text(json.dumps({"attempt_id": attempt, "uuid": "GPU-test"}))
    ledger_path.write_text(json.dumps(ledger))
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"status": "FAILED_PARENT_BRIDGED_REPLAY" if terminal else "running"}))
    return ledger_path, receipt


def _accounting_request(ledger: Path, receipt: Path) -> dict:
    return {"accounting": {"ledger_path": str(ledger), "attempt_id": "F2/F2_CASE/attempt-v12-test",
                            "home_receipt_path": str(receipt)}}


def test_v12_terminal_accounting_requires_charge_and_no_reservation_or_lease(tmp_path: Path) -> None:
    ledger, receipt = _ledger_fixture(tmp_path, terminal=False, lease=True)
    result = MODULE._terminal_accounting_status(_accounting_request(ledger, receipt))
    assert result["status"] == "UNCONFIRMED"
    assert result["reason"]
    ledger, receipt = _ledger_fixture(tmp_path / "pass", terminal=True, lease=False)
    result = MODULE._terminal_accounting_status(_accounting_request(ledger, receipt))
    assert result["status"] == "PASS_TERMINAL_CHARGE_AND_LEASE_CLEANUP"
    assert result["reservation_rows"] == 0
    assert result["charge_rows"] == 1


def _fake_v12_request(tmp_path: Path, *, ignore_term: bool = False) -> tuple[dict, Path, Path]:
    data_root = tmp_path / "data"
    ledger_path = data_root / "runtime" / "resource-ledger.json"
    (data_root / "runtime" / "leases").mkdir(parents=True)
    attempt = "F2/F2_CASE/attempt-v12-run"
    receipt_path = data_root / "families" / "F2" / "case" / "execution-receipt.json"
    ledger_path.write_text(json.dumps({
        "schema": "ds02.resource-ledger.v1", "campaign_id": "DS-DATA-02",
        "reservations": [{"id": attempt, "kind": "cpu"}], "charges": [],
        "attempts": [{"id": attempt, "kind": "cpu", "status": "reserved"}],
    }))
    bridge_config = tmp_path / "bridge-config.json"
    bridge_config.write_text(json.dumps({"ledger": str(ledger_path), "attempt": attempt,
                                         "receipt": str(receipt_path),
                                         "ignore_term": ignore_term}))
    fake_bridge = tmp_path / "fake-bridge.py"
    handler = "signal.signal(signal.SIGTERM, lambda *_: finish())" if not ignore_term else "signal.signal(signal.SIGTERM, signal.SIG_IGN)"
    script = f'''import json, signal, sys, time
cfg=json.load(open(sys.argv[sys.argv.index("--request")+1]))
def finish(*_):
    l=json.load(open(cfg["ledger"]))
    l["reservations"]=[x for x in l["reservations"] if x.get("id") != cfg["attempt"]]
    l["charges"].append({{"id":cfg["attempt"],"status":"failed","new_storage_bytes":3}})
    for x in l["attempts"]:
        if x.get("id")==cfg["attempt"]: x["status"]="failed"
    open(cfg["ledger"],"w").write(json.dumps(l))
    p=cfg["receipt"]
    import os
    os.makedirs(os.path.dirname(p),exist_ok=True)
    open(p,"w").write(json.dumps({{"status":"FAILED_PARENT_BRIDGED_REPLAY"}}))
    print(json.dumps({{"status":"BRIDGE_CANCELLED"}}),flush=True)
    raise SystemExit(0)
{handler}
time.sleep(10)
'''
    fake_bridge.write_text(script)
    trace = tmp_path / "trace.log"
    sidecar = tmp_path / "trace-finalization-v12.json"
    request = {
        "schema": MODULE.SCHEMA, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "sha256": "0" * 64, "qualification": dict(MODULE.UNKNOWN),
        "model_invoked": False, "cfd_invoked": False,
        "parent_resource_binding": {"limits": {"home_path": str(tmp_path), "home_min_free_bytes": 1}},
        "storage_scope": {"finalization_sidecar": str(sidecar)},
        "trace": {"role": "parent_os_open_trace", "path": str(trace), "required_for_completion": True},
        "execution": {"python": sys.executable, "strace": "/usr/bin/strace", "bridge": str(fake_bridge),
                       "cleanup_grace_seconds": 2.0},
        "parent_boundary": {"max_wall_seconds": 1},
        "bridge_request": {"path": str(bridge_config)},
        "v11_launch": {"bridge_request": {"path": str(bridge_config)}},
        "accounting": {"ledger_path": str(ledger_path), "attempt_id": attempt,
                        "home_receipt_path": str(receipt_path), "terminal_charge_required": True},
    }
    return request, trace, sidecar


@pytest.mark.skipif(not Path("/usr/bin/strace").is_file(), reason="strace is required for OS open audit")
def test_v12_timeout_allows_registered_bridge_terminal_cleanup(tmp_path: Path, monkeypatch) -> None:
    request, trace, sidecar = _fake_v12_request(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    monkeypatch.setattr(MODULE, "_validate_launch", lambda value, verify_content: (dict(value), None))
    monkeypatch.setattr(MODULE, "_storage_preflight", lambda value: {"status": "PASS"})
    request_path.write_text(json.dumps(request))
    report = MODULE.run(request_path, parent_pid=os.getppid())
    assert report["deadline"]["timed_out"] is True
    assert report["cleanup"]["sigterm_sent"] is True
    assert report["terminal_accounting"]["status"] == "PASS_TERMINAL_CHARGE_AND_LEASE_CLEANUP"
    assert report["status"] == "FAILED_PARENT_SUPERVISED_DEADLINE"
    assert sidecar.is_file()
    assert trace.is_file()


@pytest.mark.skipif(not Path("/usr/bin/strace").is_file(), reason="strace is required for OS open audit")
def test_v12_timeout_reports_unconfirmed_if_child_ignores_term(tmp_path: Path, monkeypatch) -> None:
    request, trace, sidecar = _fake_v12_request(tmp_path, ignore_term=True)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    request_path.write_text(json.dumps(request))
    monkeypatch.setattr(MODULE, "_validate_launch", lambda value, verify_content: (dict(value), None))
    monkeypatch.setattr(MODULE, "_storage_preflight", lambda value: {"status": "PASS"})
    report = MODULE.run(request_path, parent_pid=os.getppid())
    assert report["cleanup"]["forced_sigkill"] is True
    assert report["terminal_accounting"]["status"] == "UNCONFIRMED"
    assert report["status"] == "FAILED_PARENT_ACCOUNTING_UNCONFIRMED"
    assert sidecar.is_file()

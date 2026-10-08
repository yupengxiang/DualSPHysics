from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_parent_terminal_reconciliation_v1.py"
SPEC = importlib.util.spec_from_file_location("typed_parent_reconciliation_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[dict, dict, Path, Path, Path, Path]:
    external = tmp_path / "external"
    output_root = external / "attempt"
    output_root.mkdir(parents=True)
    (output_root / "worker.log").write_bytes(b"worker")
    trace = output_root / "trace"
    trace.write_bytes(b"trace-bytes")
    receipt = tmp_path / "home-receipt.json"
    receipt.write_bytes(b"receipt")
    request_path = tmp_path / "request.json"
    request_path.write_text("{}\n", encoding="utf-8")
    report_path = tmp_path / "returned-finalization.json"
    report = {
        "schema": "typed-evaluator-parent-report",
        "status": "FAILED_TYPED_ONLY_EVALUATOR_FINALIZATION",
        "request": {"path": str(request_path), "sha256": _sha(request_path)},
        "model_invoked": False, "cfd_invoked": False,
    }
    _json(report_path, report)
    evidence_path = tmp_path / "systemd-evidence.json"
    _json(evidence_path, {"request_sha256": _sha(request_path), "terminal_report_sha256": _sha(report_path)})
    ledger = tmp_path / "ledger.json"
    _json(ledger, {"limits": {"home_path": str(tmp_path), "storage_policy": "home_free_floor",
                              "home_min_free_bytes": 1},
                   "deadline_utc": "2099-01-01T00:00:00+00:00", "charges": [], "reservations": []})
    request = {"parent_resource_binding": {"allow_missing_parent": False}}
    request["typed_request"] = {"path": str(request_path)}
    runtime = tmp_path / "runtime_v6.py"
    runtime.write_text("# bound manufactured runtime\n", encoding="utf-8")
    bound = {
        "path": request_path, "request": request, "ledger": ledger,
        "limits": {"home_path": str(tmp_path)}, "external": external,
        "output_root": output_root, "receipt": receipt, "trace_path": trace,
        "parent_attempt_id": "typed-v6-root-078",
        "reservation_id": "typed-v6-root-078::reservation",
        "charge_id": "typed-v6-root-078::charge",
        "runtime_path": runtime, "runtime_sha": _sha(runtime), "max_wall": 900.0,
        "cleanup_grace": 25.0, "external_estimate": 1000, "home_estimate": 100,
        "allow_missing_parent": False,
    }
    evidence = {"request_sha256": _sha(request_path), "report_sha256": _sha(report_path),
                "evidence_sha256": _sha(evidence_path), "cpu_seconds": 3.365520,
                "external_bytes": sum(p.stat().st_size for p in output_root.iterdir()),
                "home_bytes": receipt.stat().st_size, "trace_bytes": trace.stat().st_size}
    return bound, request, report_path, evidence_path, output_root, receipt


def test_terminal_inputs_are_live_stat_bound_and_no_payload(tmp_path: Path) -> None:
    bound, request, report, evidence, _output_root, _receipt = _fixture(tmp_path)
    _report, measured = M._validate_terminal_inputs(
        request, bound, report, evidence, 3.365520,
        sum(p.stat().st_size for p in bound["output_root"].iterdir()),
        bound["receipt"].stat().st_size, bound["trace_path"].stat().st_size)
    assert measured["cpu_seconds"] == 3.365520
    assert measured["report_sha256"] == _sha(report)
    assert measured["evidence_sha256"] == _sha(evidence)


def test_repair_uses_one_scoped_missing_parent_charge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bound, request, report, evidence, _output_root, _receipt = _fixture(tmp_path)
    calls: list[dict] = []
    monkeypatch.setattr(M, "_load_bound_request", lambda _path: (request, bound, {}))
    monkeypatch.setattr(M, "_validate_terminal_inputs", lambda *args: (
        json.loads(report.read_text(encoding="utf-8")), {
            "request_sha256": _sha(bound["path"]), "report_sha256": _sha(report),
            "evidence_sha256": _sha(evidence), "cpu_seconds": 3.365520,
            "external_bytes": sum(p.stat().st_size for p in bound["output_root"].iterdir()),
            "home_bytes": bound["receipt"].stat().st_size,
            "trace_bytes": bound["trace_path"].stat().st_size,
        }))
    monkeypatch.setattr(M, "_live_rows", lambda _ledger: ([], []))

    class _Parent:
        def _charge(self, _bound, **kwargs):
            calls.append(kwargs)
            return {"status": "PARENT_CHARGE_APPLIED", "charge": {"id": bound["charge_id"], **kwargs},
                    "ledger_mutated": True}

    monkeypatch.setattr(M, "PARENT", _Parent())
    output = tmp_path / "repair-proof.json"
    result = M.reconcile_terminal(
        request_path=bound["path"], report_path=report, evidence_path=evidence,
        output=output, cpu_seconds=3.365520,
        external_bytes=sum(p.stat().st_size for p in bound["output_root"].iterdir()),
        home_bytes=bound["receipt"].stat().st_size, trace_bytes=bound["trace_path"].stat().st_size,
        allow_missing_parent_repair=True)
    assert result["status"] == "RECONCILED_TERMINAL_CHARGE_APPLIED"
    assert calls and calls[0]["allow_missing_parent"] is True
    assert calls[0]["cpu_seconds"] == 3.365520
    proof = json.loads(output.read_text(encoding="utf-8"))
    assert proof["hdf5_or_bi4_content_read"] is False
    assert proof["credit_boundary"].startswith("Accounting reconciliation only")


def test_repair_requires_explicit_scope(tmp_path: Path) -> None:
    bound, _request, report, evidence, _output_root, _receipt = _fixture(tmp_path)
    with pytest.raises(M.TypedParentReconciliationError, match="explicit"):
        M.reconcile_terminal(
            request_path=bound["path"], report_path=report, evidence_path=evidence,
            output=tmp_path / "proof.json", cpu_seconds=3.365520,
            external_bytes=13, home_bytes=7, trace_bytes=11)

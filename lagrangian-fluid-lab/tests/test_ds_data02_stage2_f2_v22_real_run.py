from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import os
import signal
import subprocess
import textwrap
import time


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V10_FIXTURE = ROOT / "tests/test_ds_data02_stage2_f2_v10_real_cancel_v22.py"
V15 = ROOT / "scripts/ds_data02_stage2_f2_parent_launcher_v15.py"
V22 = ROOT / "scripts/ds_data02_stage2_f2_external_supervisor_v23.py"
V10 = ROOT / "scripts/ds_data02_stage2_f2_portable_ledger_bridge_v10.py"
V14 = ROOT / "scripts/ds_data02_stage2_f2_parent_launcher_v14.py"
RUNTIME_V6 = ROOT / "scripts/ds_data02_runtime_v6.py"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _binding(role: str, path: Path) -> dict[str, object]:
    stat = path.stat()
    return {"role": role, "path": str(path.resolve()), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": _sha(path),
            "source_kind": "static"}


def _make_v14_request(tmp_path: Path):
    base = _load("v22_real_run_fixture_base", V10_FIXTURE)
    request_path, attempt, marker = base._make_request(tmp_path)
    v10_request = json.loads(request_path.read_text(encoding="utf-8"))
    external = Path(v10_request["external_storage_scope"]["filesystem"]).resolve()
    ledger = Path(v10_request["parent_resource_binding"]["path"]).resolve()
    receipt = (Path(v10_request["data_root"]) / "families/F2/F2_S1_PORTABLE_RAW_TO_LABEL_V10"
               / attempt / "execution-receipt.json")

    # V21/V22 need a concrete immutable v11→v10 edge.  The v14 harness below
    # only substitutes the expensive scientific closure; V10 reservation,
    # signal handler, receipt and ledger charge remain the production code.
    v11_path = tmp_path / "tiny-v11-request.json"
    v11 = {
        "schema": "ds02.stage2.f2-parent-supervised-launch.v11",
        "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "qualification": dict(UNKNOWN),
        "bridge_request": {"path": str(request_path.resolve()),
                           "sha256": str(v10_request["sha256"])},
    }
    v11_path.write_text(json.dumps(v11, sort_keys=True) + "\n", encoding="utf-8")

    harness = tmp_path / "v22-v15-harness.py"
    harness.write_text(textwrap.dedent(f"""
        import importlib.util, json, pathlib, sys
        sys.path.insert(0, {str(V22.parent)!r})
        spec = importlib.util.spec_from_file_location('bound_v15_v22_tiny', {str(V15)!r})
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        # Only the scientific closure is fixture-bound.  The V15/V14 process,
        # strace group, V10 bridge, reservation and terminal charge are real.
        module.V14._validate_launch = lambda request, verify_content: (
            {{'bridge_request': {{'path': {str(request_path.resolve())!r}}}}}, None)
        module.V14.V13.V12._storage_preflight = lambda _v11: {{'fixture': True}}
        request_arg = sys.argv[sys.argv.index('--request') + 1]
        parent_arg = int(sys.argv[sys.argv.index('--parent-pid') + 1])
        result = module.run(request_arg, parent_pid=parent_arg)
        pathlib.Path({str(tmp_path / 'v15-result.json')!r}).write_text(
            json.dumps(result, sort_keys=True, default=str))
    """).lstrip(), encoding="utf-8")

    # V15 checks its own wrapper binding before entering V14.  The harness is
    # the V22 launcher path, while the immutable V15 source remains a bound
    # dependency in the v14 closure.
    v14 = {
        "schema": "ds02.stage2.f2-parent-supervised-launch.v14",
        "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "qualification": dict(UNKNOWN), "model_invoked": False, "cfd_invoked": False,
        "attempt_id": attempt,
        "parent_boundary": {"max_wall_seconds": 45, "parent_pid_required": True},
        "execution": {"python": str(PYTHON), "strace": "/usr/bin/strace",
                       "bridge": str(V10), "cleanup_grace_seconds": 25.0,
                       "v15_accounting_adapter": str(harness.resolve()),
                       "trace_finalization_sidecar": str(external / "v14-real-finalization.json")},
        "trace": {"path": str(external / "os-open-trace-v22-real.log")},
        "storage_scope": {"external_filesystem": str(external),
                           "finalization_sidecar": str(external / "v14-real-finalization.json")},
        "accounting": {"ledger_path": str(ledger), "attempt_id": attempt,
                        "home_receipt_path": str(receipt)},
        "v11_launch": {"path": str(v11_path.resolve())},
        "source_bindings": [_binding("parent_launcher_v15_accounting_adapter", V15)],
    }
    # V21 only uses the canonical request hash and the v14 transitive runtime
    # binding.  V14's scientific validator is intentionally replaced in the
    # isolated harness; no accounting predicate or terminal row is fabricated.
    v14["sha256"] = base._canonical(v14)
    v14_path = tmp_path / "v14-request.json"
    v14_path.write_text(json.dumps(v14, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request_path, v14_path, attempt, marker, ledger, external


def test_v22_run_real_cancel_reserves_charges_and_releases_empty_ledger(tmp_path: Path) -> None:
    v22 = _load("supervisor_v22_real_run", V22)
    _request_path, v14_path, attempt, marker, ledger_path, external = _make_v14_request(tmp_path)
    request_path = tmp_path / "v22-request.json"
    output_root = external / "v22-real-run-output"
    value = v22.build_request(v14_path, request_path, output_root=output_root,
                              max_wall_seconds=45.0)
    assert value["forward_runtime"]["helper_cleanup_grace_seconds"] >= 25.0

    result_path = tmp_path / "v22-result.json"
    runner = tmp_path / "run-v22.py"
    runner.write_text(textwrap.dedent(f"""
        import importlib.util, json, pathlib, sys
        sys.path.insert(0, {str(V22.parent)!r})
        spec = importlib.util.spec_from_file_location('bound_v22_runner', {str(V22)!r})
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        result = module.run({str(request_path.resolve())!r}, io_slot_approved=True,
                            parent_pid=int(sys.argv[1]))
        pathlib.Path({str(result_path)!r}).write_text(json.dumps(result, sort_keys=True, default=str))
    """).lstrip(), encoding="utf-8")
    process = subprocess.Popen([str(PYTHON), "-B", str(runner), str(os.getpid())],
                               start_new_session=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and not marker.is_file():
            time.sleep(0.02)
        assert marker.is_file(), "real V10 tiny engine never reached its cancellation point"
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=40.0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
    assert process.returncode == 0, (stdout, stderr)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "FAILED_EXTERNAL_SUPERVISOR_CANCELLED"
    assert result["ledger_mutated"] is True
    assert result["model_invoked"] is False and result["cfd_invoked"] is False
    assert output_root.is_dir()
    report_path = output_root / "supervisor-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["execution"]["child_cleanup_grace_seconds"] >= 25.0
    assert report["execution"]["cleanup"].get("sigterm_sent") is True
    # The immutable report is written before the supplemental charge; the
    # returned result and ledger are the post-charge evidence.  The report
    # still records that the v10 terminal parent row was observed.
    assert report["accounting"]["parent_terminal_charge_present"] is True
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    parent_charges = [row for row in ledger["charges"] if row.get("id") == attempt]
    supervisor_charges = [row for row in ledger["charges"]
                          if row.get("id") == attempt + "::supervisor-v21"]
    assert len(parent_charges) == 1 and parent_charges[0]["status"] == "failed"
    assert parent_charges[0]["cpu_core_seconds"] > 0.0
    assert len(supervisor_charges) == 1 and supervisor_charges[0]["status"] == "failed"
    assert supervisor_charges[0]["new_storage_bytes"] > 0
    assert not any(row.get("id") in {attempt, attempt + "::supervisor-v21-reservation"}
                   for row in ledger.get("reservations", []))
    assert (external / "os-open-trace-v22-real.log").is_file()
    assert (external / "v14-real-finalization.json").is_file()

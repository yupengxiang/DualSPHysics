from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import textwrap
import time


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V10_PATH = ROOT / "scripts" / "ds_data02_stage2_f2_portable_ledger_bridge_v10.py"
V21_PATH = ROOT / "scripts" / "ds_data02_stage2_f2_external_supervisor_v21.py"
DISPATCH = ROOT / "scripts" / "ds_data02_stage2_dispatch_v6.py"
STRICT = ROOT / "scripts" / "ds_data02_strict_dispatch_v6.py"
RUNTIME = ROOT / "scripts" / "ds_data02_runtime_v6.py"
RUNTIME_V2 = ROOT / "scripts" / "ds_data02_runtime_v2.py"
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


def _binding(role: str, path: Path, *, source_kind: str = "static") -> dict:
    stat = path.stat()
    return {"role": role, "path": str(path.resolve()), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "sha256": _sha(path),
            "source_kind": source_kind, "content_scope": "content_sha256"}


def _ledger_fixture(root: Path) -> tuple[Path, Path, Path]:
    data_root = root / "data-root"
    runtime = data_root / "runtime"
    runtime.mkdir(parents=True)
    ledger = runtime / "resource-ledger.json"
    checkpoint = data_root / "CHECKPOINT.json"
    future = "2099-01-01T00:00:00+00:00"
    ledger.write_text(json.dumps({
        "limits": {"gpu_seconds": 100.0, "cpu_core_seconds": 100.0,
                   "new_storage_bytes": 50 * 1024 * 1024,
                   "qualification_attempts": 10, "production_attempts": 10,
                   "storage_policy": "home_free_floor",
                   "home_min_free_bytes": 1},
        "deadline_utc": future, "charges": [], "reservations": [], "attempts": []
    }))
    checkpoint.write_text(json.dumps({"schema": "manufactured-parent-checkpoint.v1"}))
    return data_root, ledger, checkpoint


def _make_request(tmp_path: Path) -> tuple[Path, str, Path]:
    """Build a tiny valid v10 contract using the actual v10 runtime/guards."""
    data_root, ledger, checkpoint = _ledger_fixture(tmp_path)
    external = Path(tempfile.mkdtemp(prefix="ds02-v10-real-cancel-", dir="/var/tmp"))
    target = external / "bundle-target"
    selected = external / "reference-products"
    attempt = "manufactured-v10-real-cancel-v22"
    v7_engine = tmp_path / "tiny_v7_engine.py"
    marker = tmp_path / "v7-entered.marker"
    # This is a deliberately tiny *engine fixture*, while accounting remains
    # entirely in the real v10 bridge.  It creates the same artifact classes
    # expected by v10, then waits until the parent sends SIGTERM.  v10's own
    # signal handler performs the terminal receipt/ledger charge.
    v7_engine.write_text(textwrap.dedent(f"""
        import pathlib, time
        marker = pathlib.Path({str(marker)!r})
        def _validate_request(request, verify_metadata_content=False):
            return {{"status": "PASS_TINY_ENGINE_VALIDATION"}}
        def run(request_path, *, io_slot_approved=False, verify_metadata_content=False):
            assert io_slot_approved and verify_metadata_content
            target = pathlib.Path({str(target)!r})
            selected = pathlib.Path({str(selected)!r})
            target.mkdir(parents=True, exist_ok=False)
            selected.mkdir(parents=True, exist_ok=False)
            (target / "sealed-overlay-v7.json").write_text("sealed\\n")
            (selected.parent / "orchestration-v7-report.json").write_text("report\\n")
            (selected / "private-loader-subprocess-v1.json").write_text("loader\\n")
            (selected / "portable-raw-to-label-run-report-v5.json").write_text("run\\n")
            (selected / "portable-python-access-audit-v5.json").write_text("audit\\n")
            (selected / "native-v5").mkdir()
            (selected / "native-v5" / "label.json").write_text("unknown\\n")
            (selected.parent / "os-open-trace-v10.log").write_text("openat tiny\\n")
            marker.write_text("READY")
            while True:
                time.sleep(0.05)
    """).lstrip())
    v7 = {
        "schema": "ds02.stage2.f2-portable-orchestration-request.v7",
        "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "qualification": UNKNOWN, "model_invoked": False, "cfd_invoked": False,
        "execution": {"command": [str(PYTHON), "-B", str(v7_engine), "run", "--request", "<request>"]},
        "source_bindings": [_binding("portable_orchestrator_v7", v7_engine)],
    }
    v7["sha256"] = _canonical(v7)
    v7_path = tmp_path / "tiny-v7-request.json"
    v7_path.write_text(json.dumps(v7, indent=2, sort_keys=True) + "\n")
    # V10 insists the guard roles are exact; the source list binds the same
    # files and is rehashed by the real bridge before reservation.
    guard_paths = [("shared_dispatch_v6", DISPATCH), ("shared_strict_dispatch_v6", STRICT),
                   ("shared_runtime_v6", RUNTIME), ("shared_runtime_v2", RUNTIME_V2)]
    guard_bindings = [_binding(role, path) for role, path in guard_paths]
    sources = [_binding("v7_request", v7_path), _binding("v7:portable_orchestrator_v7", v7_engine),
               _binding("portable_ledger_bridge_v10", V10_PATH), *guard_bindings]
    trace = external / "os-open-trace-v10.log"
    expected = [
        {"role": "v7_orchestration_report", "path": str(external / "orchestration-v7-report.json")},
        {"role": "private_loader_receipt", "path": str(selected / "private-loader-subprocess-v1.json")},
        {"role": "v5_loader_report", "path": str(selected / "portable-raw-to-label-run-report-v5.json")},
        {"role": "python_access_audit", "path": str(selected / "portable-python-access-audit-v5.json")},
        {"role": "sealed_overlay", "path": str(target / "sealed-overlay-v7.json")},
        {"role": "native_output_root", "path": str(selected / "native-v5")},
        {"role": "parent_os_open_trace", "path": str(trace), "required_for_completion": True},
    ]
    request = {
        "schema": "ds02.stage2.f2-portable-ledger-bridge-request.v10",
        "request_id": attempt, "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F2", "case_id": "MANUFACTURED_V10_REAL_CANCEL", "attempt_id": attempt,
        "data_root": str(data_root), "shared_v6_root": str(ROOT),
        "v7_request": {"path": str(v7_path), "sha256": v7["sha256"], "schema": v7["schema"]},
        "parent_resource_binding": {"path": str(ledger), "checkpoint_path": str(checkpoint),
                                     "no_reset": True, "no_new_data_root_ledger": True},
        "guard_bindings": guard_bindings, "source_bindings": sources,
        "external_storage_scope": {
            "filesystem": str(external), "roots": [str(target), str(selected)],
            "expected_artifacts": expected, "home_receipt": {
                "path": str(data_root / "families/F2/MANUFACTURED_V10_REAL_CANCEL" / attempt / "execution-receipt.json"),
                "reserved_bytes": 256 * 1024},
        },
        "reservation": {"kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 1,
                        "max_wall_seconds": 30, "cpu_core_seconds": 30,
                        "gpu_seconds": 0, "new_storage_bytes": 512 * 1024,
                        "storage_filesystem": str(external), "same_parent_lease": True,
                        "home_receipt_reserved_bytes": 256 * 1024,
                        "external_product_reserved_bytes": 256 * 1024},
        "execution": {"v7_engine": str(v7_engine), "entrypoint": str(V10_PATH)},
        "qualification": UNKNOWN, "model_invoked": False, "cfd_invoked": False,
    }
    request["sha256"] = _canonical(request)
    request_path = tmp_path / "tiny-v10-request.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
    return request_path, attempt, marker


def _canonical(value: dict) -> str:
    import hashlib
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def test_real_v10_cancel_registers_then_closes_terminal_charge_and_lease(tmp_path: Path):
    """Use the actual v10 bridge and v21 25-second group cleanup.

    No terminal row/receipt is prewritten and no accounting predicate is
    monkeypatched.  The tiny v7 fixture only supplies bounded output and a
    cancellation point; v10 creates the reservation, catches SIGTERM, writes
    the terminal receipt, and mutates the real temporary parent ledger.
    """
    v10 = _load("v10_real_cancel_v22", V10_PATH)
    v21 = _load("v21_real_cancel_v22", V21_PATH)
    request_path, attempt, marker = _make_request(tmp_path)
    wrapper = tmp_path / "v10-delayed-supervisor.py"
    wrapper.write_text(textwrap.dedent(f"""
        import signal, subprocess, sys, time
        from pathlib import Path
        child = subprocess.Popen([{str(PYTHON)!r}, '-B', {str(V10_PATH)!r}, 'run', '--request', {str(request_path)!r}, '--io-slot-approved'])
        def stop(_signum, _frame):
            # The child bridge receives SIGTERM too and performs its real
            # terminal charge.  Keep this group leader alive for >2 seconds
            # so v21's old two-second path would have killed it prematurely.
            time.sleep(3.0)
        signal.signal(signal.SIGTERM, stop)
        while not Path({str(marker)!r}).exists():
            time.sleep(0.02)
        child.wait()
    """).lstrip())
    process = subprocess.Popen([str(PYTHON), "-B", str(wrapper)], start_new_session=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.02)
    assert marker.is_file()
    started = time.monotonic()
    cleanup = v21._stop_group(process, grace=v21.V21_CHILD_CLEANUP_GRACE_SECONDS)
    elapsed = time.monotonic() - started
    assert cleanup["sigterm_sent"] is True
    assert cleanup["sigkill_sent"] is False
    assert cleanup["reaped"] is True
    assert elapsed >= 2.5
    assert cleanup["grace_seconds"] >= 25.0
    data_root = tmp_path / "data-root"
    ledger = json.loads((data_root / "runtime/resource-ledger.json").read_text())
    charges = [row for row in ledger["charges"] if row.get("id") == attempt]
    assert len(charges) == 1
    assert charges[0]["status"] == "failed"
    assert charges[0]["cpu_core_seconds"] > 0.0
    assert charges[0]["new_storage_bytes"] > 0
    assert not any(row.get("id") == attempt for row in ledger["reservations"])
    attempts = [row for row in ledger["attempts"] if row.get("id") == attempt]
    assert attempts and attempts[-1]["status"] == "failed"
    receipt = data_root / "families/F2/F2_S1_PORTABLE_RAW_TO_LABEL_V10" / attempt / "execution-receipt.json"
    assert receipt.is_file()
    value = json.loads(receipt.read_text())
    assert value["status"] == "FAILED_PARENT_BRIDGED_REPLAY"
    assert value["parent_ledger"]["reservation_registered"] is True
    assert value["deadline"]["status"] == "CANCELLED"
    assert value["filesystem"]["measured_total_bytes"] >= value["filesystem"]["external_product_bytes"]

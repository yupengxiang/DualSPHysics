from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import textwrap
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
V25_PATH = ROOT / "scripts/ds_data02_stage2_f2_external_supervisor_v25.py"
V22_FIXTURE = ROOT / "tests/test_ds_data02_stage2_f2_v22_real_run.py"
V26 = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v26-supervised-chain/"
    "f2-s1-parent-supervised-launch-request-v14-013.json"
)
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _load():
    spec = importlib.util.spec_from_file_location("ds02_supervisor_v25_test", V25_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_fixture():
    spec = importlib.util.spec_from_file_location("ds02_v25_pre_reserve_fixture", V22_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v25_build_binds_true_outer_baseline_and_v24_helper(tmp_path: Path) -> None:
    v25 = _load()
    external = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5")
    tag = "v25-test-" + uuid.uuid4().hex
    request_path = tmp_path / "v25.json"
    value = v25.build_request(V26, request_path,
                              output_root=external / tag / "supervisor",
                              max_wall_seconds=6000.0)
    assert value["forward_runtime"]["path"] == str(V25_PATH.resolve())
    assert value["forward_runtime"]["entry_clock_at_function_entry"] is True
    assert value["forward_runtime"]["outer_cpu_baseline_includes_pre_reservation"] is True
    assert value["forward_runtime"]["pre_reservation_failure_uses_v21_terminal_failure_path"] is True
    assert any(item.get("role") == "external_supervisor_v25"
               for item in value["static_bindings"])
    checked = v25.validate_request(request_path, verify_content=False)
    assert checked["max_wall_seconds"] == 6000.0
    assert v25.V24._run_process_group_v24 is not None
    ready = v25.run(request_path, io_slot_approved=False)
    assert ready["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert ready["ledger_mutated"] is False
    loaded = json.loads(request_path.read_text())
    assert loaded["sha256"] == v25.canonical_sha(loaded)
    assert PYTHON.is_file()


def test_v25_real_signal_during_pre_reservation_charges_and_releases(tmp_path: Path) -> None:
    """Exercise the real same-parent reservation failure path before V21 starts.

    The tiny fixture uses the production V21 ledger and report accounting.  A
    wrapper delays *after* V24's real reservation call; SIGTERM then reaches
    the V25 outer handler while the pre-reservation phase is active.  No
    terminal row, reservation, or receipt is prewritten by the test.
    """
    v25 = _load()
    fixture = _load_fixture()
    _unused_v10, v14_path, attempt, _marker, ledger_path, external = fixture._make_v14_request(tmp_path)
    request_path = tmp_path / "v25-pre-reserve-cancel.json"
    output_root = external / "v25-pre-reserve-cancel-output"
    v25.build_request(v14_path, request_path, output_root=output_root, max_wall_seconds=45.0)
    marker = tmp_path / "pre-reserve-entered.marker"
    result_path = tmp_path / "v25-pre-reserve-result.json"
    runner = tmp_path / "run-v25-pre-reserve.py"
    runner.write_text(textwrap.dedent(f"""
        import importlib.util, json, pathlib, sys, time
        sys.path.insert(0, {str(V25_PATH.parent)!r})
        path = pathlib.Path({str(V25_PATH)!r})
        spec = importlib.util.spec_from_file_location('bound_v25_pre_reserve', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        original = module.V24._pre_reserve
        def delayed(request, checked):
            value = original(request, checked)
            pathlib.Path({str(marker)!r}).write_text('RESERVED')
            time.sleep(30.0)
            return value
        module.V24._pre_reserve = delayed
        result = module.run({str(request_path.resolve())!r}, io_slot_approved=True,
                            parent_pid=int(sys.argv[1]))
        pathlib.Path({str(result_path)!r}).write_text(json.dumps(result, sort_keys=True, default=str))
    """).lstrip())
    process = subprocess.Popen([str(PYTHON), "-B", str(runner), str(os.getpid())],
                               start_new_session=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    stdout = stderr = ""
    try:
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline and not marker.is_file():
            time.sleep(0.02)
        assert marker.is_file(), "real pre-reservation did not return after the ledger append"
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=35.0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
    assert process.returncode == 0, (stdout, stderr)
    result = json.loads(result_path.read_text())
    assert result["status"] == "FAILED_EXTERNAL_SUPERVISOR_PREFLIGHT"
    assert result["v25_pre_reservation_attempted"] is True
    # SIGTERM interrupts the wrapper after the real ledger API returns but
    # before its Python return reaches V25; the attempted/returned distinction
    # is therefore expected and prevents a false "reservation observed"
    # claim while the ledger check below proves cleanup.
    assert result["v25_pre_reservation_returned"] is False
    ledger = json.loads(ledger_path.read_text())
    parent = [row for row in ledger["charges"] if row.get("id") == attempt]
    # V21 has not launched the native parent yet, so this phase cannot invent
    # a parent terminal row.  Its real prelaunch failure path records only the
    # supervisor-owned failure charge, linked to the same parent attempt id.
    assert not parent
    supervisor = [row for row in ledger["charges"]
                  if row.get("id") == attempt + "::supervisor-v21"]
    assert supervisor and supervisor[-1]["status"] == "failed"
    assert not any(row.get("id") == attempt + "::supervisor-v21-reservation"
                   for row in ledger.get("reservations", []))
    assert output_root.is_dir()

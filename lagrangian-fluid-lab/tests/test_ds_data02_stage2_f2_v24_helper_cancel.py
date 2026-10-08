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
V24_PATH = ROOT / "scripts/ds_data02_stage2_f2_external_supervisor_v24.py"
V10_FIXTURE = ROOT / "tests/test_ds_data02_stage2_f2_v10_real_cancel_v22.py"
V22_TEST = ROOT / "tests/test_ds_data02_stage2_f2_v22_real_run.py"
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


def _canonical(value: dict) -> str:
    import hashlib
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _refresh_binding(item: dict, path: Path) -> None:
    stat = path.stat()
    item.update({"path": str(path.resolve()), "bytes": int(stat.st_size),
                 "mtime_ns": int(stat.st_mtime_ns), "sha256": _sha(path)})


def _completed_v14_request(tmp_path: Path):
    """Turn the existing real V10 fixture into a finite successful bridge.

    The V10 bridge, V14/V15 launcher, parent ledger, and terminal charge stay
    production code.  Only the tiny V7 engine exits with a COMPLETE result so
    v21 can reach its real V20 helper process.
    """
    fixture = _load("v24_fixture_base", V22_TEST)
    request_path, v14_path, attempt, marker, ledger, external = fixture._make_v14_request(tmp_path)
    v11_path = Path(json.loads(v14_path.read_text())["v11_launch"]["path"])
    v11 = json.loads(v11_path.read_text())
    bridge_path = Path(v11["bridge_request"]["path"])
    bridge = json.loads(bridge_path.read_text())
    v7_path = Path(bridge["v7_request"]["path"])
    v7 = json.loads(v7_path.read_text())
    engine_path = Path(v7["execution"]["command"][2])
    source = engine_path.read_text()
    old = "    while True:\n        time.sleep(0.05)\n"
    assert old in source
    engine_path.write_text(source.replace(old, "    return {\"status\": \"COMPLETE_TINY\"}\n"))

    v7["source_bindings"] = [
        ({**item} if item.get("role") != "portable_orchestrator_v7" else {
            **item, "bytes": engine_path.stat().st_size,
            "mtime_ns": engine_path.stat().st_mtime_ns, "sha256": _sha(engine_path)
        }) for item in v7["source_bindings"]
    ]
    v7["sha256"] = _canonical(v7)
    v7_path.write_text(json.dumps(v7, indent=2, sort_keys=True) + "\n")

    bridge["v7_request"]["sha256"] = v7["sha256"]
    for item in bridge["source_bindings"]:
        if item.get("role") == "v7_request":
            _refresh_binding(item, v7_path)
        elif item.get("role") == "v7:portable_orchestrator_v7":
            _refresh_binding(item, engine_path)
    bridge["input_hashes"] = {item["path"]: item["sha256"] for item in bridge["source_bindings"]}
    bridge["sha256"] = _canonical(bridge)
    bridge_path.write_text(json.dumps(bridge, indent=2, sort_keys=True) + "\n")
    v11["bridge_request"]["sha256"] = bridge["sha256"]
    v11_path.write_text(json.dumps(v11, indent=2, sort_keys=True) + "\n")

    # The cancellation fixture normally terminates the launcher before it can
    # print a result.  This helper-active test must let the real v14/v15 child
    # finish first, so make its existing harness emit the JSON that v21 parses
    # before it reaches the v20 build helper.  The harness path is unchanged;
    # no production request/source byte is edited.
    harness_path = Path(json.loads(v14_path.read_text())["execution"]["v15_accounting_adapter"])
    harness_source = harness_path.read_text()
    if "print(json.dumps(result" not in harness_source:
        harness_path.write_text(harness_source +
                                "\nprint(json.dumps(result, sort_keys=True, default=str), flush=True)\n")
    return request_path, v14_path, attempt, marker, ledger, external


def test_v24_helper_active_sigterm_reaps_group_and_charges(tmp_path: Path) -> None:
    v24 = _load("supervisor_v24_helper_cancel", V24_PATH)
    _request_path, v14_path, attempt, _marker, ledger_path, external = _completed_v14_request(tmp_path)
    helper_marker = tmp_path / "v20-helper-entered.marker"
    helper = tmp_path / "tiny-v20-helper.py"
    helper.write_text(textwrap.dedent(f"""
        import pathlib, sys, time
        marker = pathlib.Path({str(helper_marker)!r})
        if sys.argv[1] == 'build-request':
            marker.write_text('ACTIVE')
            while True:
                time.sleep(0.05)
        if sys.argv[1] == 'apply':
            marker.write_text('APPLY')
            print('{{"status":"SUPPLEMENTAL_CHARGE_APPLIED","cpu_core_seconds":0.0}}')
    """).lstrip())
    request_path = tmp_path / "v24-helper-cancel-request.json"
    output_root = external / "v24-helper-cancel-output"
    value = v24.build_request(v14_path, request_path, output_root=output_root, max_wall_seconds=60.0)
    request = json.loads(request_path.read_text())
    for item in request["static_bindings"]:
        if item.get("role") == "v20_helper_v20":
            _refresh_binding(item, helper)
    request["sha256"] = v24.canonical_sha(request)
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")

    result_path = tmp_path / "v24-helper-cancel-result.json"
    runner = tmp_path / "run-v24-helper-cancel.py"
    runner.write_text(textwrap.dedent(f"""
        import importlib.util, json, pathlib, sys
        sys.path.insert(0, {str(V24_PATH.parent)!r})
        path = pathlib.Path({str(V24_PATH)!r})
        spec = importlib.util.spec_from_file_location('bound_v24_runner', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.V21.V20_PATH = pathlib.Path({str(helper)!r})
        result = module.run({str(request_path.resolve())!r}, io_slot_approved=True,
                            parent_pid=int(sys.argv[1]))
        pathlib.Path({str(result_path)!r}).write_text(json.dumps(result, sort_keys=True, default=str))
    """).lstrip())
    process = subprocess.Popen([str(PYTHON), "-B", str(runner), str(os.getpid())],
                               start_new_session=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    stdout = stderr = ""
    try:
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline and not helper_marker.is_file():
            time.sleep(0.02)
        assert helper_marker.is_file(), "real v20 helper did not enter communicate()"
        os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=40.0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
    assert process.returncode == 0, (stdout, stderr)
    result = json.loads(result_path.read_text())
    assert result["status"] == "FAILED_EXTERNAL_SUPERVISOR_CANCELLED"
    assert result["v24_helper_cleanup_grace_seconds"] >= 25.0
    ledger = json.loads(ledger_path.read_text())
    parent = [row for row in ledger["charges"] if row.get("id") == attempt]
    supervisor = [row for row in ledger["charges"] if row.get("id") == attempt + "::supervisor-v21"]
    assert parent and parent[-1]["status"] in {"completed", "failed"}
    assert parent[-1]["cpu_core_seconds"] > 0.0
    assert supervisor and supervisor[-1]["status"] == "failed"
    assert supervisor[-1]["cpu_core_seconds"] >= 0.0
    assert not any(row.get("id") in {attempt + "::supervisor-v21-reservation", attempt}
                   for row in ledger.get("reservations", []))
    assert output_root.is_dir()

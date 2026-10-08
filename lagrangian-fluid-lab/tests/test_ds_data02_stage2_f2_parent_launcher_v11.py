from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import os
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_parent_launcher_v11.py"
V10_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v10-hardwall-v6/"
    "f2-s1-portable-ledger-bridge-request-v10-006.json"
)
SPEC = importlib.util.spec_from_file_location("parent_launcher_v11_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v11_builds_exact_parent_contract_from_v10_without_payload_read(tmp_path: Path) -> None:
    output = tmp_path / "parent-launch-v11.json"
    request = MODULE.build_request(V10_REQUEST, output)
    assert request["schema"] == MODULE.SCHEMA
    assert request["bridge_request"]["sha256"] == json.loads(V10_REQUEST.read_text())["sha256"]
    assert request["execution"]["bridge_owns_ledger"] is True
    assert request["execution"]["nested_runtime_wrapper"] is False
    assert request["parent_boundary"]["parent_pid_required"] is True
    assert request["parent_boundary"]["native_open_trace"].startswith("single -f")
    assert request["trace"]["path"].endswith("os-open-trace-v10.log")
    validated, _module = MODULE._validate_launch(request, verify_content=True)
    assert validated["schema"] == MODULE.V10_SCHEMA
    saved = json.loads(output.read_text())
    assert saved["sha256"] == MODULE.canonical_sha(saved)


def test_v11_two_filesystem_headroom_is_independent_of_home_floor(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    bridge = {
        "external_storage_scope": {"filesystem": str(external)},
        "parent_resource_binding": {"limits": {"home_path": str(tmp_path),
                                                   "home_min_free_bytes": 1}},
        "reservation": {"home_receipt_reserved_bytes": 1,
                         "external_product_reserved_bytes": 1},
    }
    result = MODULE._storage_preflight(bridge)
    assert result["status"] == "PASS_TWO_FILESYSTEM_HEADROOM_STATVFS"
    assert result["home"]["floor_bytes"] == 1
    assert result["external"]["product_reserve_bytes"] == 1


def _fake_request(tmp_path: Path, command: str, max_wall: int = 2) -> tuple[dict, Path]:
    bridge_script = tmp_path / "fake-v10-bridge.py"
    bridge_script.write_text(command)
    bridge_request = tmp_path / "fake-v10-request.json"
    bridge_request.write_text("{}")
    trace = tmp_path / "os-open-trace-v10.log"
    request = {
        "schema": MODULE.SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "sha256": "0" * 64,
        "bridge_request": {"path": str(bridge_request), "sha256": "1" * 64},
        "execution": {
            "python": sys.executable,
            "strace": "/usr/bin/strace",
            "bridge": str(bridge_script),
        },
        "trace": {"role": "parent_os_open_trace", "path": str(trace),
                  "required_for_completion": True},
        "parent_boundary": {"max_wall_seconds": max_wall},
        "source_bindings": [],
        "qualification": dict(MODULE.UNKNOWN),
        "model_invoked": False,
        "cfd_invoked": False,
    }
    return request, trace


@pytest.mark.skipif(not Path("/usr/bin/strace").is_file(), reason="strace is required for OS open audit")
def test_v11_real_parent_launch_has_one_trace_and_no_ledger_wrapper(tmp_path: Path, monkeypatch) -> None:
    request, trace = _fake_request(
        tmp_path,
        "import json\nprint(json.dumps({'status': 'COMPLETE_DEVELOPMENT_UNKNOWN'}), flush=True)\n",
    )
    bridge = {"execution": {}, "schema": MODULE.V10_SCHEMA}
    monkeypatch.setattr(MODULE, "_validate_launch", lambda value, verify_content: (bridge, None))
    monkeypatch.setattr(MODULE, "_storage_preflight", lambda value: {"status": "PASS"})
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    report = MODULE.run(request_path, parent_pid=os.getppid())
    assert report["status"] == "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN"
    assert report["parent"]["ledger_mutated_by_launcher"] is False
    assert report["trace"]["exists"] is True
    assert report["trace"]["bytes"] > 0
    assert trace.is_file()


@pytest.mark.skipif(not Path("/usr/bin/strace").is_file(), reason="strace is required for OS open audit")
def test_v11_parent_launch_timeout_kills_only_child_group(tmp_path: Path, monkeypatch) -> None:
    request, trace = _fake_request(tmp_path, "import time\ntime.sleep(5)\n", max_wall=1)
    bridge = {"execution": {}, "schema": MODULE.V10_SCHEMA}
    monkeypatch.setattr(MODULE, "_validate_launch", lambda value, verify_content: (bridge, None))
    monkeypatch.setattr(MODULE, "_storage_preflight", lambda value: {"status": "PASS"})
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    started = time.monotonic()
    report = MODULE.run(request_path, parent_pid=os.getppid())
    assert time.monotonic() - started < 2.0
    assert report["status"] == "FAILED_PARENT_SUPERVISED_DEADLINE"
    assert report["deadline"]["timed_out"] is True
    assert report["trace"]["exists"] is True
    assert trace.is_file()

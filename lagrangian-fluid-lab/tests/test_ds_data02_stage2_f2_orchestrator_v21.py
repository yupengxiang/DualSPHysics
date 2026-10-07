from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_portable_orchestrator_v21 as worker  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(tmp_path: Path) -> dict:
    source = tmp_path / "v15.json"
    source.write_text(json.dumps({"schema": "ds02.stage2.f2-s1-replay-request.v15"}) + "\n")
    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text(json.dumps({"schema": "sidecar"}) + "\n")
    return {
        "schema": worker.REQUEST_SCHEMA,
        "orchestration_schema": worker.ORCHESTRATION_SCHEMA,
        "source_bindings": {
            "v15_replay_request": {"path": str(source), "sha256": _sha(source)},
            "v16_flux_forward_sidecar": {"path": str(sidecar), "sha256": _sha(sidecar)},
        },
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def test_request_rejects_v19_schema(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["orchestration_schema"] = "ds02.stage2.f2-s1-portable-orchestration.v19"
    with pytest.raises(worker.OrchestrationV21Error, match="v21"):
        worker._require_request(request)


def test_execution_closure_binds_v21_runner_and_four_guard_contract() -> None:
    closure = worker._execution_closure()
    modules = {item["module"] for item in closure["local_modules"]}
    assert "ds_data02_stage2_f2_portable_v21.py" in modules
    assert "ds_data02_stage2_f2_replay_runner_v21.py" in modules
    assert set(closure["shared_four_guard_sources"]) == {
        "runtime_v2", "runtime_v1", "stage2_dispatch_v4", "strict_dispatch_v4",
    }
    for binding in closure["shared_four_guard_sources"].values():
        assert binding["path"].endswith(("ds_data02_runtime_v2.py", "ds_data02_runtime.py",
                                         "ds_data02_stage2_dispatch.py",
                                         "ds_data02_strict_dispatch_v1.py"))
        assert len(binding["sha256"]) == 64


def test_os_strace_requires_new_log_and_real_executable(tmp_path: Path) -> None:
    runner = tmp_path / "runner.py"
    runner.write_text(
        "import json, pathlib, sys\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "out.write_text(json.dumps({}))\n"
    )
    profile = tmp_path / "profile.json"
    request = tmp_path / "request.json"
    path_map = tmp_path / "map.json"
    for path in (profile, request, path_map):
        path.write_text("{}\n")
    output = tmp_path / "result.json"
    log = tmp_path / "nested" / "openat.log"
    result = worker._run_runner(runner, profile, request, path_map, output,
                                io_slot_approved=False, strace_log=log)
    assert result == {}
    assert log.is_file()
    with pytest.raises(worker.OrchestrationV21Error, match="overwrite"):
        worker._run_runner(runner, profile, request, path_map, tmp_path / "second.json",
                           io_slot_approved=False, strace_log=log)

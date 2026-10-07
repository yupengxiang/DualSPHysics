from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/replay/v24/"
    "f2-s1-portable-metadata-probe-request-v24-001.json"
)


def _canonical_sha(value: dict) -> str:
    payload = dict(value)
    payload.pop("sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def test_v24_request_binds_complete_relocated_runtime_closure() -> None:
    request = json.loads(REQUEST.read_text())
    assert request["schema"] == "ds02.request.v1"
    assert request["orchestration_schema"].endswith(".v24")
    assert request["sha256"] == _canonical_sha(request)
    assert request["launch_commit"] == "bfdac41a2"
    assert request["source_hashes_preverified_by_parent"] is True
    roles = set(request["source_bindings"])
    required = {
        "v24_metadata_probe", "v24_portable_worker", "v24_replay_runner",
        "portable_v16_dependency", "replay_runner_v15", "replay_module_v15",
        "replay_module_v14", "dependency_license_index", "v15_replay_request",
        "motion_engine_jmotion_data", "motion_engine_jmotion_mov", "motion_engine_jmotion_obj",
        "runtime_v2", "runtime_v4", "stage2_dispatch_v4", "strict_dispatch_v4",
    }
    assert required <= roles
    assert not {"v23_metadata_probe", "v23_portable_worker", "v23_replay_runner"} & roles
    assert request["probe_contract"]["closure_subprocess_test"].startswith("real subprocess")
    assert request["resource_request"]["cpu_cores"] == 1
    assert request["resource_request"]["hdf5_read"].startswith("metadata stat only")


def test_v24_request_input_hashes_are_real_small_sources() -> None:
    request = json.loads(REQUEST.read_text())
    assert set(request["input_files"]) == set(request["input_hashes"])
    for path_text in request["input_files"]:
        path = Path(path_text)
        assert path.is_file(), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == request["input_hashes"][path_text]

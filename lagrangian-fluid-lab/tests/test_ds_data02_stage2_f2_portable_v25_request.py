from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/replay/v25/"
    "f2-s1-portable-metadata-probe-request-v25-001-root-canonical.json"
)


def _canonical_sha(value: dict) -> str:
    payload = dict(value)
    payload.pop("sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def test_v25_request_is_guard_ready_and_preserves_c49_failure_boundary() -> None:
    request = json.loads(REQUEST.read_text())
    assert request["schema"] == "ds02.request.v1"
    assert request["orchestration_schema"].endswith(".v25")
    assert request["status"] == "READY_FOR_PARENT_GUARD"
    assert request["sha256"] == _canonical_sha(request)
    assert request["launch_commit"] == "9f287aa16"
    assert request["source_hashes_preverified_by_parent"] is True
    assert request["resource_request"]["hdf5_read"].startswith("metadata stat only")
    assert request["probe_contract"]["closure_subprocess_test"].startswith("real subprocess test")
    assert "TRANSITIVE_V25_CLOSURE_OK" in request["probe_contract"]["closure_subprocess_test"]
    assert request["probe_contract"]["c49_correction"]["original_path_fallback"] == "FORBIDDEN"
    assert request["probe_contract"]["c49_correction"]["exact_role_sha_required"] is True
    assert {
        "v25_closure_subprocess_test",
        "v25_metadata_probe",
        "v25_portable_worker",
        "v25_replay_runner",
    } <= set(request["source_bindings"])


def test_v25_request_inputs_exist_and_match_hashes() -> None:
    request = json.loads(REQUEST.read_text())
    assert set(request["input_files"]) == set(request["input_hashes"])
    for path_text in request["input_files"]:
        path = Path(path_text)
        assert path.is_file(), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == request["input_hashes"][path_text]

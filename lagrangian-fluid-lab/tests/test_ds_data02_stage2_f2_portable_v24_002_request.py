from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/replay/v24/"
    "f2-s1-portable-metadata-probe-request-v24-002-root-canonical.json"
)


def _canonical_sha(value: dict) -> str:
    payload = dict(value)
    payload.pop("sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def test_v24_002_is_metadata_only_guard_ready_with_real_closure_evidence() -> None:
    request = json.loads(REQUEST.read_text())
    assert request["schema"] == "ds02.request.v1"
    assert request["orchestration_schema"].endswith(".v24")
    assert request["status"] == "READY_FOR_PARENT_GUARD"
    assert request["sha256"] == _canonical_sha(request)
    assert request["launch_commit"] == "3b357570f"
    assert request["source_hashes_preverified_by_parent"] is True
    assert request["resource_request"]["hdf5_read"].startswith("metadata stat only")
    assert request["probe_contract"]["closure_subprocess_test"].startswith("real subprocess test")
    assert request["probe_contract"]["loader_next_stage"]["status"] == (
        "BOUND_ADDITIVE_NOT_INVOKED_BY_METADATA_PROBE"
    )
    assert {
        "v24_closure_subprocess_test",
        "native_raw_to_label_loader_v1",
        "native_raw_to_label_bundle_v2",
        "native_raw_to_label_loader_test",
    } <= set(request["source_bindings"])


def test_v24_002_all_input_hashes_are_bound_existing_files() -> None:
    request = json.loads(REQUEST.read_text())
    assert set(request["input_files"]) == set(request["input_hashes"])
    for path_text in request["input_files"]:
        path = Path(path_text)
        assert path.is_file(), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == request["input_hashes"][path_text]

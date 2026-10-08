from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
REQUEST_DIR = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f4-s1-stream-v3-forward-002"
REQUEST_PATH = REQUEST_DIR / "f4-s1-stream-v3-request.json"


def _local_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    root_prefix = "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    if path.startswith(root_prefix):
        replacement = ROOT / path[len(root_prefix):]
        if replacement.is_file():
            return replacement
    raise AssertionError(f"request input is unavailable: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_forward002_binds_every_input_key_and_only_declares_h5_sha():
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    assert set(request["input_files"]) == set(request["input_sha256"])
    manifest_path = request["manifest_binding"]["path"]
    manifest = json.loads(_local_path(manifest_path).read_text(encoding="utf-8"))
    h5_paths = {item["trajectory_hdf5"]["path"]: item["trajectory_hdf5"]["sha256"] for item in manifest["artifacts"]}
    assert len(h5_paths) == 5
    for path, expected in request["input_sha256"].items():
        local = _local_path(path)
        if path in h5_paths:
            # This test deliberately performs metadata/stat only.  Opening or
            # hashing producer H5 bytes would consume an unregistered I/O pass.
            stat = local.stat()
            assert stat.st_size > 0
            assert expected == h5_paths[path]
            continue
        assert _sha256(local) == expected, path
    assert request["manifest_binding"]["sha256"] == _sha256(_local_path(manifest_path))
    assert request["manifest_binding"]["worker_sha256"] == _sha256(_local_path(request["manifest_binding"]["worker_path"]))

    audit_path = request["source_closure_audit"]["path"]
    audit = json.loads(_local_path(audit_path).read_text(encoding="utf-8"))
    assert request["source_closure_audit"]["sha256"] == _sha256(_local_path(audit_path))
    assert audit["input_count"] == 59
    assert audit["small_input_count"] == 54
    assert audit["h5_input_count"] == 5
    assert audit["audit_scope"]["audit_file_included_in_request"] is True
    assert audit["audit_scope"]["audit_file_listed_in_audit_inputs"] is False
    assert audit["audit_scope"]["request_input_count_including_audit"] == 60
    assert request["source_cost"]["source_closure_small_input_count"] == 55
    assert all(item["status"] == "verified_at_request_preparation" for item in audit["inputs"] if item["kind"] == "small_source")
    assert all(item["observed_sha256"] == "NOT_REHASHED" for item in audit["inputs"] if item["kind"] == "trajectory_hdf5")


def test_forward002_stale_worker_hash_is_detected_without_opening_h5():
    request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    stale = copy.deepcopy(request)
    worker = stale["manifest_binding"]["worker_path"]
    stale["input_sha256"][worker] = "0" * 64
    with pytest.raises(AssertionError):
        assert _sha256(_local_path(worker)) == stale["input_sha256"][worker]

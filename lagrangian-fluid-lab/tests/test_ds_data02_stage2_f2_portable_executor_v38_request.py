from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v38_request.py"
SPEC = importlib.util.spec_from_file_location("f2_portable_executor_v38_request", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _aux_fixture(tmp_path: Path) -> Path:
    entries = []
    for name, content in (("PartInfo.ibi4", b"info"), ("PartMotionRef.ibi4", b"motion"),
                          ("PartOut_000.obi4", b"out"), ("Part_Head.ibi4", b"head")):
        path = tmp_path / name
        path.write_bytes(content)
        entries.append({"filename": name, "path": str(path), "bytes": len(content),
                        "sha256": _sha(path), "content_hash_status": "PARENT_GUARDED_CONTENT_SHA256"})
    frozen = [{"relative_path": f"Part_{i:04d}.bi4", "bytes": 1, "sha256": "0" * 64} for i in range(401)]
    value = {
        "schema": builder.AUX_SCHEMA, "status": "COMPLETE_PARENT_GUARDED",
        "expected_raw_tree": {"file_count": 405, "tree_sha256": builder.FROZEN_RAW_TREE_SHA256},
        "request_expected_raw_tree": {"frame_count": 401}, "entries": entries,
        "frozen_frame_manifest": frozen,
    }
    value["sha256"] = builder.canonical_sha(value)
    path = tmp_path / "aux.json"
    path.write_text(json.dumps(value) + "\n")
    return path


def test_auxiliary_loader_requires_parent_content_hash_and_full_frame_manifest(tmp_path: Path) -> None:
    path = _aux_fixture(tmp_path)
    _, value = builder._load_auxiliary(path)
    assert len(value["entries"]) == 4
    assert len(value["frozen_frame_manifest"]) == 401

    broken = json.loads(path.read_text())
    broken["entries"][0]["content_hash_status"] = "PENDING_PARENT_GUARD_CONTENT_SHA256"
    broken["sha256"] = builder.canonical_sha(broken)
    path.write_text(json.dumps(broken) + "\n")
    with pytest.raises(builder.V38RequestError, match="not parent-guarded"):
        builder._load_auxiliary(path)

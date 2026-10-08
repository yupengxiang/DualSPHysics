from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_v37_auxiliary_chain_v1.py"
SPEC = importlib.util.spec_from_file_location("f2_v37_auxiliary_chain_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
chain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chain)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecar_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "producer" / "data"
    root.mkdir(parents=True)
    paths: list[Path] = []
    for index in range(chain.FRAME_COUNT):
        path = root / f"Part_{index:04d}.bi4"
        path.write_bytes(f"frame-{index}".encode())
        paths.append(path)
    for name in chain.AUX_NAMES:
        path = root / name
        path.write_bytes(f"aux-{name}".encode())
        paths.append(path)
    records = []
    for path in paths:
        records.append({"path": path.name, "bytes": path.stat().st_size, "sha256": _sha(path)})
    records.sort(key=lambda item: item["path"])
    pre = {item["path"]: chain._stat(root / item["path"], "pre") for item in records}
    post = {item["path"]: chain._stat(root / item["path"], "post") for item in records}
    frozen = [
        {"frame": index, "relative_path": f"Part_{index:04d}.bi4",
         "path": str(root / f"Part_{index:04d}.bi4"), "bytes": (root / f"Part_{index:04d}.bi4").stat().st_size,
         "sha256": _sha(root / f"Part_{index:04d}.bi4"),
         "frozen_sha256": _sha(root / f"Part_{index:04d}.bi4"),
         "content_hash_status": "FROZEN_AND_PARENT_GUARDED_SHA_MATCH"}
        for index in range(chain.FRAME_COUNT)
    ]
    entries = [
        {"filename": name, "path": str(root / name), "bytes": (root / name).stat().st_size,
         "sha256": _sha(root / name), "content_hash_status": "PARENT_GUARDED_CONTENT_SHA256"}
        for name in chain.AUX_NAMES
    ]
    report = {
        "schema": chain.AUX_SCHEMA,
        "snapshot_schema": "ds02.stage2.f2-raw-auxiliary-snapshot.v1",
        "status": "COMPLETE_PARENT_GUARDED", "role": "DEVELOPMENT",
        "qualification": dict(chain.UNKNOWN), "source_data_root": str(root),
        "expected_raw_tree": {"file_count": 405, "tree_sha256": chain.EXPECTED_TREE},
        "raw_manifest": {"file_count": 405, "tree_sha256": chain.EXPECTED_TREE, "files": records},
        "frozen_frame_manifest": frozen, "entries": entries,
        "content_read_during_build": False, "snapshot_content_read": True,
        "payload_hashes_computed": True,
        "stat_pre_post": {"files": pre, "post_hash_files": post, "stable": True},
        "execution_boundary": {"hdf5_opened": False},
    }
    report["sha256"] = chain.canonical_sha(report)
    sidecar = tmp_path / "aux-sidecar.json"
    _write(sidecar, report)
    return sidecar, root, chain.EXPECTED_TREE


def _v36_fixture(tmp_path: Path, root: Path) -> tuple[Path, Path]:
    executable = tmp_path / "venv" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    info = chain._stat(executable, "python")
    runtime = [{
        "role": "python_executable", "path": str(executable),
        "invocation_path": str(executable), "target_relative_path": "runtime/python/python",
        "bytes": info["st_size"], "source_mode_bits": info["mode_bits"],
        "required_executable": True, "preserve_mode": True,
        "source_stat_expected": info,
    }]
    bundle = tmp_path / "bundle.json"
    bundle_value = {
        "schema": "ds02.stage2.f2-native-raw-to-label-bundle.v5",
        "raw_producer_binding": {"expected_file_count": 405,
                                  "expected_raw_tree_sha256": chain.EXPECTED_TREE,
                                  "frame_count": 401, "frame_pattern": "Part_%04d.bi4"},
    }
    bundle_value["sha256"] = chain.V37.canonical_sha(bundle_value)
    _write(bundle, bundle_value)
    request = {
        "schema": chain.V34_SCHEMA, "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_STAGE2_GUARD", "qualification": dict(chain.UNKNOWN),
        "forward_v36": {"schema": "ds02.stage2.f2-portable-executor-v36-forward.v1"},
        "source_entries": [], "runtime_sources": runtime,
        "v5_bundle": {"path": str(bundle), "canonical_sha256": bundle_value["sha256"]},
    }
    request["sha256"] = chain.V37.canonical_sha(request)
    request_path = tmp_path / "v36-request.json"
    _write(request_path, request)
    overlay = {"schema": chain.OVERLAY_SCHEMA, "entries": [],
               "bundle": {"canonical_sha256": bundle_value["sha256"]}}
    overlay["sha256"] = chain.V37.canonical_sha(overlay)
    overlay_path = tmp_path / "v36-overlay.json"
    _write(overlay_path, overlay)
    return request_path, overlay_path


def test_completed_sidecar_validates_frozen_scope_without_payload_open(tmp_path: Path) -> None:
    sidecar, root, expected = _sidecar_fixture(tmp_path)
    result = chain._validate_auxiliary_sidecar(sidecar)
    assert result["file_count"] == 405
    assert result["frame_count"] == 401
    assert result["expected_tree_sha256"] == expected
    assert result["entry_names"] == sorted(chain.AUX_NAMES)
    assert all(not str(item["path"]).endswith(".h5") for item in result["raw_manifest_files"].values())
    assert root.is_dir()


def test_sidecar_cannot_replace_frozen_tree_or_leave_pending_aux(tmp_path: Path) -> None:
    sidecar, _, _ = _sidecar_fixture(tmp_path)
    value = json.loads(sidecar.read_text(encoding="utf-8"))
    value["expected_raw_tree"]["tree_sha256"] = "a" * 64
    value["raw_manifest"]["tree_sha256"] = "a" * 64
    value["sha256"] = chain.canonical_sha(value)
    bad = tmp_path / "bad.json"
    _write(bad, value)
    with pytest.raises(chain.V37ChainError, match="replace the frozen"):
        chain._validate_auxiliary_sidecar(bad)


def test_v36_metadata_gate_keeps_literal_python_and_mode_contract(tmp_path: Path) -> None:
    request, overlay = _v36_fixture(tmp_path, tmp_path / "producer")
    value, _ = chain._load_v36_metadata(request, overlay)
    runtime = value["runtime_sources"][0]
    assert runtime["invocation_path"] == str(tmp_path / "venv" / "bin" / "python")
    assert runtime["required_executable"] is True
    broken = json.loads(request.read_text(encoding="utf-8"))
    broken["runtime_sources"][0]["source_mode_bits"] = 0o644
    broken["sha256"] = chain.V37.canonical_sha(broken)
    broken_path = tmp_path / "broken-request.json"
    _write(broken_path, broken)
    with pytest.raises(chain.V37ChainError, match="executable mode"):
        chain._load_v36_metadata(broken_path, overlay)


def test_preflight_is_metadata_only_and_writes_new_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sidecar, _, _ = _sidecar_fixture(tmp_path)
    request, overlay = _v36_fixture(tmp_path, tmp_path / "producer")
    report_path = tmp_path / "chain-preflight.json"
    result = chain.preflight(v36_request=request, v36_overlay=overlay,
                             auxiliary_manifest=sidecar, output=report_path)
    assert result["status"] == "READY_FOR_PARENT_V37_BUILD"
    assert result["metadata_only"] is True
    assert result["payload_read"] is False
    assert json.loads(report_path.read_text(encoding="utf-8"))["sha256"] == result["sha256"]

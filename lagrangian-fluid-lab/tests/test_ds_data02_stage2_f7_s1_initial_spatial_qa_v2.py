from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f7_s1_initial_spatial_qa_v2.py"
REQUEST_DIR = ROOT / "campaigns/ds-data-02/stage2/requests/f7-s1-initial-spatial-qa-v2-root-prepared-142-001"
MANIFEST = REQUEST_DIR / "f7-s1-initial-spatial-qa-v2-manifest.json"
REQUEST = REQUEST_DIR / "f7-s1-initial-spatial-qa-v2-request.json"


def loaded():
    spec = importlib.util.spec_from_file_location("f7_s1_initial_spatial_qa_v2", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_manifest_and_request_bind_declared_paths_without_root_clone_assumption():
    module = loaded()
    manifest, _, _ = module._validate_static_manifest(MANIFEST)
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "ds02.stage2.f7.s1.initial-spatial-qa.manifest.v2"
    assert manifest["contract"]["post_hash_after_all_payload_reads"] is True
    assert manifest["contract"]["array_reader_content_sha256"] == "NOT_COMPUTED"
    script_path = Path(request["command"][1])
    manifest_path = Path(request["command"][3])
    assert script_path.is_file()
    assert manifest_path.is_file()
    assert request["input_sha256"][str(script_path)] == hashlib.sha256(script_path.read_bytes()).hexdigest()
    assert request["input_sha256"][str(manifest_path)] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert request["guard_policy"]["worker_post_hash_after_all_payload_reads"] is True


def _fake_scan(module):
    record = lambda name, type_code, count, byte_count: SimpleNamespace(
        name=name,
        type_code=type_code,
        count=count,
        byte_count=byte_count,
        item_path=["Part"],
    )
    arrays = [
        record("Posd", 23, 3, 72),
        record("Idp", 7, 3, 12),
        record("Type", 7, 3, 12),
        record("Mk", 7, 3, 12),
        record("Mass", 23, 3, 24),
    ]
    values = [
        SimpleNamespace(name="CaseNp", value=3),
        SimpleNamespace(name="CaseNfluid", value=2),
        SimpleNamespace(name="CaseNfixed", value=1),
        SimpleNamespace(name="CaseNmoving", value=0),
        SimpleNamespace(name="MassFluid", value=0.2),
        SimpleNamespace(name="Data2d", value=0),
    ]
    root = SimpleNamespace(children=[SimpleNamespace(name="Part")], values=values)
    return SimpleNamespace(root=root, arrays=arrays, input_sha256="scanner-digest", input_bytes=123)


def test_post_hash_is_after_every_array_payload_read(monkeypatch, tmp_path: Path):
    module = loaded()
    path = tmp_path / "frame.bi4"
    path.write_bytes(b"fixture")
    events: list[tuple[str, str]] = []
    scan = _fake_scan(module)

    def fake_sha(_path: Path) -> str:
        events.append(("sha", "file"))
        return "full-file-digest"

    def fake_scan(_fd: int, _pre_sha: str):
        events.append(("scan", "fd"))
        return scan

    scanner = SimpleNamespace(scan_bi4_fd=fake_scan)

    payloads = {
        "Posd": np.asarray([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0]]),
        "Idp": np.asarray([0, 1, 2], dtype=np.int32),
        "Type": np.asarray([0, 3, 3], dtype=np.int32),
        "Mk": np.asarray([0, 1, 1], dtype=np.int32),
        "Mass": np.asarray([0.1, 0.1, 0.1]),
    }

    def fake_read(_path: Path, record):
        events.append(("array", record.name))
        return payloads[record.name]

    monkeypatch.setattr(module, "sha256_file", fake_sha)
    monkeypatch.setattr(module, "_read_array", fake_read)
    result = module._frame_summary(path, scanner, {"expected_fluid": 2}, "fixture")

    assert result["post_after_all_payload_reads"] is True
    assert result["array_reader_content_sha256"] == "NOT_COMPUTED"
    assert events[0] == ("sha", "file")
    assert events[1] == ("scan", "fd")
    assert [kind for kind, _ in events[2:-1]] == ["array"] * 5
    assert events[-1] == ("sha", "file")


def test_post_hash_detects_mutation_during_array_reads(monkeypatch, tmp_path: Path):
    module = loaded()
    path = tmp_path / "frame.bi4"
    path.write_bytes(b"fixture")
    scan = _fake_scan(module)
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    payloads = {
        "Posd": np.zeros((3, 3)),
        "Idp": np.asarray([0, 1, 2], dtype=np.int32),
        "Type": np.asarray([0, 3, 3], dtype=np.int32),
        "Mk": np.asarray([0, 1, 1], dtype=np.int32),
        "Mass": np.asarray([0.1, 0.1, 0.1]),
    }

    def fake_read(target: Path, record):
        if record.name == "Mass":
            target.write_bytes(b"changed")
        return payloads[record.name]

    monkeypatch.setattr(module, "sha256_file", digest)
    scanner = SimpleNamespace(scan_bi4_fd=lambda _fd, _pre_sha: scan)
    monkeypatch.setattr(module, "_read_array", fake_read)
    with pytest.raises(module.SpatialQAError, match="changed during bounded BI4 read"):
        module._frame_summary(path, scanner, {"expected_fluid": 2}, "fixture")

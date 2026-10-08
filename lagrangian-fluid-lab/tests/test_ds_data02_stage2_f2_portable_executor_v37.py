from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v37.py"
SPEC = importlib.util.spec_from_file_location("f2_portable_executor_v37", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
v37 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v37)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _binding(path: Path, role: str, relative: str) -> dict[str, object]:
    return {
        "role": role,
        "path": str(path),
        "target_relative_path": relative,
        "bytes": path.stat().st_size,
        "mtime_ns": path.stat().st_mtime_ns,
        "sha256": _sha(path),
    }


def _overlay_item(path: Path, role: str, relative: str) -> dict[str, object]:
    return {
        "role": role,
        "bundle_relative_path": relative,
        "original_path": str(path),
        "expected_bytes": path.stat().st_size,
        "expected_sha256": _sha(path),
        "original_mtime_ns": path.stat().st_mtime_ns,
        "content_hash_status": "PARENT_GUARD_CONTENT_SHA_BOUND",
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source_root = tmp_path / "producer" / "solver_output" / "data"
    source_root.mkdir(parents=True)
    frames = []
    entries = []
    overlay_entries = []
    for index in range(2):
        path = source_root / f"Part_{index:04d}.bi4"
        path.write_bytes(f"frame-{index}".encode())
        frames.append(path)
        entries.append(_binding(path, "raw_frame_input", path.name))
        overlay_entries.append(_overlay_item(path, "raw_frame_input", f"Part_{index:04d}.bi4"))
    aux_paths = {
        "PartInfo.ibi4": b"part-info",
        "PartMotionRef.ibi4": b"motion-ref",
        "PartOut_000.obi4": b"part-out",
        "Part_Head.ibi4": b"part-head",
    }
    part_out = None
    for name, payload in aux_paths.items():
        path = source_root / name
        path.write_bytes(payload)
        if name == "PartOut_000.obi4":
            part_out = path
            entries.append(_binding(path, "v2:native_partout", "sources/0016-PartOut_000.obi4"))
            overlay_entries.append(_overlay_item(path, "v2:native_partout", "sources/0016-PartOut_000.obi4"))
    assert part_out is not None
    manifest_path = tmp_path / "auxiliary.json"
    manifest = {
        "schema": v37.AUX_SCHEMA,
        "content_read_during_build": False,
        "source_data_root": str(source_root.resolve()),
        "expected_raw_tree": {"file_count": 6, "tree_sha256": "a" * 64},
        "entries": [
            {"filename": name, "path": str((source_root / name).resolve()),
             "bytes": (source_root / name).stat().st_size,
             "sha256": _sha(source_root / name)}
            for name in v37.RAW_AUX_NAMES
        ],
    }
    _write_json(manifest_path, manifest)

    bundle = {
        "schema": "ds02.stage2.f2-native-raw-to-label-bundle.v5",
        "role": "DEVELOPMENT", "qualification": dict(v37.UNKNOWN),
        "raw_producer_binding": {
            "expected_file_count": 6, "expected_raw_tree_sha256": "a" * 64,
            "frame_count": 2, "frame_pattern": "Part_%04d.bi4",
            "original_data_root": str(source_root.resolve()),
        },
    }
    bundle["sha256"] = v37.canonical_sha(bundle)
    bundle_path = tmp_path / "bundle.json"
    _write_json(bundle_path, bundle)

    overlay = {
        "schema": v37.OVERLAY_SCHEMA,
        "bundle": {"canonical_sha256": bundle["sha256"]},
        "entries": overlay_entries,
        "status": "READY_FOR_PARENT_COPY", "role": "DEVELOPMENT",
        "qualification": dict(v37.UNKNOWN), "content_hash_verified": False,
    }
    overlay["sha256"] = v37.canonical_sha(overlay)
    overlay_path = tmp_path / "v36-overlay.json"
    _write_json(overlay_path, overlay)

    request = {
        "schema": v37.V34_SCHEMA, "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "qualification": dict(v37.UNKNOWN), "model_invoked": False, "cfd_invoked": False,
        "forward_v36": {"schema": "ds02.stage2.f2-portable-executor-v36-forward.v1"},
        "permissions_contract": {"schema": "ds02.stage2.f2-portable-permissions.v1",
                                  "preserve_mode": True, "target_inode_must_differ": True},
        "v5_bundle": {"path": str(bundle_path), "sha256": "b" * 64,
                       "canonical_sha256": bundle["sha256"]},
        "v5_overlay_template": {"path": str(overlay_path), "sha256": "c" * 64,
                                 "canonical_sha256": overlay["sha256"]},
        "source_entries": entries, "runtime_sources": [],
        "fresh_roots": {"target_root": str(tmp_path / "old-target"),
                        "output_root": str(tmp_path / "old-output")},
    }
    request["sha256"] = v37.canonical_sha(request)
    request_path = tmp_path / "v36-request.json"
    _write_json(request_path, request)
    return request_path, overlay_path, manifest_path, source_root


def test_build_forward_isolates_raw_scope_and_keeps_frozen_tree_binding(tmp_path: Path,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    request, overlay, manifest, _ = _fixture(tmp_path)
    real_hash = v37.sha256_file

    def no_raw_payload_hash(path: Path | str) -> str:
        assert Path(path).suffix not in {".bi4", ".h5"}, f"payload hash attempted: {path}"
        return real_hash(path)

    monkeypatch.setattr(v37, "sha256_file", no_raw_payload_hash)
    result = v37.build_forward(
        v36_request=request, v36_overlay=overlay, auxiliary_manifest=manifest,
        output_request=tmp_path / "v37-request.json", output_overlay=tmp_path / "v37-overlay.json",
        target_root=tmp_path / "fresh" / "target", output_root=tmp_path / "fresh" / "output",
    )

    assert result["content_read"] is False
    assert result["payload_hashes_computed"] is False
    new_request = json.loads((tmp_path / "v37-request.json").read_text(encoding="utf-8"))
    new_overlay = json.loads((tmp_path / "v37-overlay.json").read_text(encoding="utf-8"))
    assert new_request["forward_v37"]["expected_file_count"] == 6
    assert new_request["forward_v37"]["expected_raw_tree_sha256"] == "a" * 64
    assert new_request["forward_v37"]["raw_data_root_relative"] == "raw"
    raw_sources = [item for item in new_request["source_entries"]
                   if item["target_relative_path"].startswith("raw/")]
    assert len(raw_sources) == 6
    assert {item["role"] for item in raw_sources} >= {
        "raw_frame_input", "v2:native_partout", "raw_aux_partinfo",
        "raw_aux_partmotionref", "raw_aux_part_head",
    }
    raw_overlay = [item for item in new_overlay["entries"]
                   if item["bundle_relative_path"].startswith("raw/")]
    assert len(raw_overlay) == 6
    assert all(item["bundle_relative_path"] != "raw/sources" for item in raw_overlay)
    assert new_request["sha256"] == v37.canonical_sha(new_request)
    assert new_overlay["sha256"] == v37.canonical_sha(new_overlay)


def test_build_forward_rejects_unbound_auxiliary_sha(tmp_path: Path) -> None:
    request, overlay, manifest, _ = _fixture(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["entries"][0]["sha256"] = "PENDING_PARENT_GUARD_CONTENT_SHA256"
    _write_json(manifest, value)
    with pytest.raises(v37.PortableV37Error, match="lowercase SHA-256"):
        v37.build_forward(
            v36_request=request, v36_overlay=overlay, auxiliary_manifest=manifest,
            output_request=tmp_path / "request.json", output_overlay=tmp_path / "overlay.json",
            target_root=tmp_path / "fresh-target", output_root=tmp_path / "fresh-output",
        )


def test_diagnose_scope_is_stat_only_and_finds_auxiliary_gap(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    frozen_root = tmp_path / "frozen"
    copied_root = tmp_path / "copied"
    frozen_root.mkdir()
    copied_root.mkdir()
    for name in ("Part_0000.bi4", "Part_0001.bi4", *v37.RAW_AUX_NAMES):
        (frozen_root / name).write_bytes(name.encode())
    for name in ("Part_0000.bi4", "Part_0001.bi4"):
        (copied_root / name).write_bytes(name.encode())
    (copied_root / "sources").mkdir()
    (copied_root / "sources" / "metadata.json").write_text("{}", encoding="utf-8")
    frozen_report = tmp_path / "frozen-report.json"
    copied_report = tmp_path / "copied-report.json"
    report = lambda count, tree: {"source_provenance": {"raw_tree": {
        "after_file_count": count, "after_tree_sha256": tree,
        "before_file_count": count, "before_tree_sha256": tree, "unchanged": True,
    }}}
    _write_json(frozen_report, report(6, "a" * 64))
    _write_json(copied_report, report(3, "b" * 64))
    real_hash = v37.sha256_file

    def reject_payload(path: Path | str) -> str:
        assert Path(path).suffix not in {".bi4", ".h5"}
        return real_hash(path)

    monkeypatch.setattr(v37, "sha256_file", reject_payload)
    output = tmp_path / "diagnostic.json"
    result = v37.diagnose_raw_tree_scope(
        frozen_report=frozen_report, copied_report=copied_report,
        frozen_data_root=frozen_root, copied_data_root=copied_root, output=output,
    )
    assert result["stat_only_scope"]["payload_read"] is False
    assert "PartInfo.ibi4" in result["missing_from_copied_scope"]
    assert "Part_Head.ibi4" in result["missing_from_copied_scope"]
    assert {item["relative_path"] for item in result["producer_auxiliary_files"]} == set(v37.RAW_AUX_NAMES)
    assert "sources/metadata.json" in result["unexpected_in_copied_scope"]
    assert result["required_repair"]["raw_data_root_relative"] == "raw"
    assert result["sha256"] == v37.canonical_sha(result)

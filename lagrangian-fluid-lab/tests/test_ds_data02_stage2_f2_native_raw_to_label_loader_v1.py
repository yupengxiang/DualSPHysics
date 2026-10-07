from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_native_raw_to_label_bundle_v2 as bundle_v2  # noqa: E402
import ds_data02_stage2_f2_native_raw_to_label_loader_v1 as loader  # noqa: E402


def _binding(role: str, original: Path, relative: str) -> dict:
    return {
        "role": role,
        "original_path": str(original.resolve()),
        "bundle_relative_path": relative,
        "bytes": original.stat().st_size,
        "content_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
    }


def _manifest(tmp_path: Path) -> tuple[dict, dict, Path, Path]:
    original = tmp_path / "producer"
    target = tmp_path / "overlay"
    original.mkdir()
    target.mkdir()
    source = original / "Part_0000.bi4"
    source.write_bytes(b"raw fixture")
    relocated = target / "Part_0000.bi4"
    relocated.write_bytes(source.read_bytes())
    manifest = {
        "schema": "ds02.stage2.f2-native-raw-to-label-bundle.v2",
        "status": "PORTABLE_RAW_TO_LABEL_OVERLAY_REQUIRED",
        "bundle_kind": "RAW_TO_TYPED_TO_LABEL_REPLAY_BUNDLE",
        "typed_only": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_bindings": [_binding("raw_frame_0000", source, "raw/Part_0000.bi4")],
        "raw_producer_binding": {
            "expected_raw_tree_sha256": "a" * 64,
            "frame_bindings": [{"frame": 0}],
            "per_frame_sha256_status": "VERIFIED_BY_PARENT_WORKER_REPORT",
        },
    }
    path_map = {
        "schema": "ds02.stage2.f2-native-raw-to-label-path-map.v1",
        "status": "COMPLETE_PARENT_OVERLAY",
        "original_path_fallback": "FORBIDDEN",
        "role_to_path": {"raw_frame_0000": str(relocated)},
    }
    return manifest, path_map, source, relocated


def test_loader_accepts_verified_overlay_and_preserves_provenance(tmp_path: Path) -> None:
    manifest, path_map, source, relocated = _manifest(tmp_path)
    roles = loader._manifest_roles(manifest)
    path_map_file = tmp_path / "path-map.json"
    path_map_file.write_text(json.dumps(path_map))
    mapped, records = loader._load_path_map(path_map_file, roles, verify_content=True)
    assert mapped["raw_frame_0000"] == str(relocated)
    assert records["raw_frame_0000"]["content_hash_status"] == "VERIFIED_NOW"
    value = loader._replace_paths(
        {"path": str(source), "path_provenance": str(source), "nested": [str(source)]},
        {str(source.resolve()): str(relocated.resolve())},
    )
    assert value["path"] == str(relocated.resolve())
    assert value["path_provenance"] == str(source)
    assert value["nested"][0] == str(relocated.resolve())


def test_loader_rejects_template_or_original_fallback(tmp_path: Path) -> None:
    manifest, path_map, source, relocated = _manifest(tmp_path)
    roles = loader._manifest_roles(manifest)
    template = tmp_path / "template.json"
    template.write_text(json.dumps({
        **path_map,
        "status": "TEMPLATE_ONLY_PARENT_OVERLAY_REQUIRED",
        "role_to_path": {"raw_frame_0000": "OVERLAY_REQUIRED/raw/Part_0000.bi4"},
    }))
    with pytest.raises(loader.NativeRawToLabelLoaderError, match="template"):
        loader._load_path_map(template, roles, verify_content=False)
    fallback = tmp_path / "fallback.json"
    fallback.write_text(json.dumps({
        **path_map,
        "role_to_path": {"raw_frame_0000": str(source)},
    }))
    with pytest.raises(loader.NativeRawToLabelLoaderError, match="falls back"):
        loader._load_path_map(fallback, roles, verify_content=False)


def test_v2_run_out_binding_requires_exact_receipt_scope(tmp_path: Path) -> None:
    producer = tmp_path / "producer"
    solver_output = producer / "solver_output"
    solver_output.mkdir(parents=True)
    run_out = solver_output / "Run.out"
    run_out.write_text("solver output")
    receipt = producer / "execution-receipt.json"
    receipt.write_text(json.dumps({
        "command": ["solver", str(solver_output)],
        "output_root": str(producer),
    }))
    manifest = {"source_bindings": [{
        "role": "v2:solver_receipt",
        "original_path": str(receipt),
    }]}
    resolved, role, receipt_path = bundle_v2._resolve_run_out(manifest)
    assert resolved == run_out.resolve()
    assert role == "v2:solver_receipt"
    assert receipt_path == str(receipt.resolve())
    binding = bundle_v2._run_out_binding(resolved)
    assert binding["role"] == "solver_run_out"
    assert binding["content_sha256"] == hashlib.sha256(run_out.read_bytes()).hexdigest()

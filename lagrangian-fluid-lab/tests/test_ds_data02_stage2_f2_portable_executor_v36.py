from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v36.py"
SPEC = importlib.util.spec_from_file_location("f2_portable_executor_v36", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
v36 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v36)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value), encoding="utf-8")


def _mode_item(path: Path, role: str) -> dict[str, object]:
    item = {"path": str(path), "role": role}
    item.update(v36._source_mode_contract(item))
    return item


def test_decoder_copy_preserves_execute_mode_and_distinct_inode(tmp_path: Path) -> None:
    source = tmp_path / "bi4_dump"
    source.write_bytes(b"decoder-fixture\n")
    os.chmod(source, 0o755)
    item = _mode_item(source, "native_bi4_decoder")
    target = tmp_path / "relocated" / "sources" / "bi4_dump"

    record = v36.copy_one_preserving_mode(
        source, target, v36.sha256_file(source), source.stat().st_size, item
    )

    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    assert (target.stat().st_dev, target.stat().st_ino) != (
        source.stat().st_dev, source.stat().st_ino
    )
    assert record["target_inode_distinct"] is True
    assert record["source_sha256_pre"] == record["source_sha256_post"]
    assert record["target_mode_bits"] == 0o755


def test_decoder_mode_contract_rejects_source_without_execute_bit(tmp_path: Path) -> None:
    source = tmp_path / "bi4_dump"
    source.write_bytes(b"decoder-fixture\n")
    os.chmod(source, 0o644)

    with pytest.raises(v36.PortableV36Error, match="lacks execute"):
        _mode_item(source, "native_bi4_decoder")


def test_mode_preflight_rejects_source_mode_mutation_without_content_hash(tmp_path: Path) -> None:
    source = tmp_path / "worker.py"
    source.write_text("print('fixture')\n", encoding="utf-8")
    os.chmod(source, 0o755)
    item = _mode_item(source, "compare_worker")
    request = {
        "schema": v36.V34_SCHEMA,
        "forward_v36": {"schema": v36.FORWARD_SCHEMA},
        "permissions_contract": {
            "schema": v36.PERMISSIONS_SCHEMA,
            "preserve_mode": True,
            "target_inode_must_differ": True,
        },
        "source_entries": [item],
        "runtime_sources": [],
    }
    request["sha256"] = v36.canonical_sha(request)
    os.chmod(source, 0o644)

    with pytest.raises(v36.PortableV36Error, match="source stat differs"):
        v36._validate_mode_contract(request, check_current_stat=True)


def test_build_forward_binds_source_modes_and_executable_roles_without_content_read(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    frames = []
    overlay_entries = []
    for index in range(2):
        source = original / f"Part_{index:04d}.bi4"
        _write(source, f"frame-{index}")
        frames.append({
            "role": "raw_frame_input", "path": str(source),
            "bytes": source.stat().st_size, "sha256": "a" * 64,
            "target_relative_path": f"sources/{index:04d}-{source.name}",
        })
        overlay_entries.append({
            "role": "raw_frame_input", "original_path": str(source),
            "expected_bytes": source.stat().st_size, "expected_sha256": "a" * 64,
            "bundle_relative_path": f"sources/{index:04d}-{source.name}",
        })
    bundle_sha = "b" * 64
    overlay = {
        "schema": "ds02.stage2.f2-native-raw-portable-overlay.v5",
        "bundle": {"canonical_sha256": bundle_sha}, "entries": overlay_entries,
        "sha256": "",
    }
    overlay["sha256"] = v36.canonical_sha(overlay)
    overlay_path = tmp_path / "v35-overlay.json"
    _write(overlay_path, overlay)
    request = {
        "schema": v36.V34_SCHEMA, "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "role": "DEVELOPMENT", "qualification": dict(v36.UNKNOWN),
        "model_invoked": False, "cfd_invoked": False,
        "forward_v35": {"schema": "ds02.stage2.f2-portable-executor-v35-forward.v1"},
        "v5_bundle": {"canonical_sha256": bundle_sha, "path": str(tmp_path / "bundle.json"),
                       "sha256": "c" * 64},
        "v5_overlay_template": {"canonical_sha256": overlay["sha256"],
                                 "path": str(overlay_path),
                                 "sha256": v36.sha256_file(overlay_path)},
        "source_entries": frames, "runtime_sources": [],
        "fresh_roots": {"target_root": str(tmp_path / "v35-executor-051" / "target"),
                         "output_root": str(tmp_path / "v35-executor-051" / "output")},
    }
    request["sha256"] = v36.canonical_sha(request)
    request_path = tmp_path / "v35-request.json"
    _write(request_path, request)
    out_request = tmp_path / "v36-request.json"
    out_overlay = tmp_path / "v36-overlay.json"

    result = v36.build_forward(
        v35_request=request_path, v35_overlay=overlay_path,
        output_request=out_request, output_overlay=out_overlay,
        target_root=tmp_path / "v36-executor-052" / "target",
        output_root=tmp_path / "v36-executor-052" / "output",
    )

    assert result["content_read"] is False
    new_request = json.loads(out_request.read_text(encoding="utf-8"))
    assert new_request["forward_v36"]["schema"] == v36.FORWARD_SCHEMA
    assert new_request["permissions_contract"]["preserve_mode"] is True
    assert all("source_stat_expected" in item for item in new_request["source_entries"])
    assert all(item["target_relative_path"] == f"Part_{i:04d}.bi4"
               for i, item in enumerate(new_request["source_entries"]))
    assert new_request["sha256"] == v36.canonical_sha(new_request)

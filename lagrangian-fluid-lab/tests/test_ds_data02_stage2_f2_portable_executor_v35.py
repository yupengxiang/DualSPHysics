from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v35.py"
SPEC = importlib.util.spec_from_file_location("f2_portable_executor_v35", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
v35 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v35)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path, *, frame_names: tuple[str, ...] = ("Part_0000.bi4", "Part_0001.bi4")) -> tuple[Path, Path]:
    original = tmp_path / "original"
    overlay_path = tmp_path / "old-overlay.json"
    request_path = tmp_path / "old-request.json"
    raw_entries = []
    overlay_entries = []
    for index, name in enumerate(frame_names):
        source = original / name
        _write(source, f"frame-{index}")
        raw_entries.append({
            "role": "raw_frame_input",
            "path": str(source),
            "bytes": source.stat().st_size,
            "sha256": "a" * 64,
            "target_relative_path": f"sources/{index + 38:04d}-{name}",
        })
        overlay_entries.append({
            "role": "raw_frame_input",
            "original_path": str(source),
            "expected_bytes": source.stat().st_size,
            "expected_sha256": "a" * 64,
            "bundle_relative_path": f"sources/{index + 38:04d}-{name}",
        })
    bundle_sha = "b" * 64
    overlay = {
        "schema": "ds02.stage2.f2-native-raw-portable-overlay.v5",
        "bundle": {"canonical_sha256": bundle_sha},
        "entries": overlay_entries,
        "sha256": "",
    }
    overlay["sha256"] = v35.canonical_sha(overlay)
    _write(overlay_path, overlay)
    request = {
        "schema": v35.V34_SCHEMA,
        "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "role": "DEVELOPMENT",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "model_invoked": False,
        "cfd_invoked": False,
        "execution": {"original_path_fallback": "FORBIDDEN"},
        "v5_bundle": {"canonical_sha256": bundle_sha, "path": str(tmp_path / "bundle.json"), "sha256": "c" * 64},
        "v5_overlay_template": {
            "canonical_sha256": overlay["sha256"], "path": str(overlay_path),
            "sha256": v35.sha256_file(overlay_path),
        },
        "source_entries": raw_entries,
        "runtime_sources": [],
        "fresh_roots": {
            "target_root": "/var/tmp/test-v34-executor-050/bundle-target-v34",
            "output_root": "/var/tmp/test-v34-executor-050/reference-products-v34",
        },
    }
    request["sha256"] = v35.canonical_sha(request)
    _write(request_path, request)
    return request_path, overlay_path


def test_build_forward_uses_exact_top_level_part_names_without_content_reads(tmp_path: Path) -> None:
    request, overlay = _fixture(tmp_path)
    out_request = tmp_path / "v35-request.json"
    out_overlay = tmp_path / "v35-overlay.json"

    result = v35.build_forward(
        v34_request=request,
        v5_overlay=overlay,
        output_request=out_request,
        output_overlay=out_overlay,
        target_root=tmp_path / "target-051",
        output_root=tmp_path / "output-051",
    )

    assert result["content_read"] is False
    assert result["raw_frame_layout"] == "top-level Part_0000.bi4 contiguous"
    new_request = json.loads(out_request.read_text(encoding="utf-8"))
    new_overlay = json.loads(out_overlay.read_text(encoding="utf-8"))
    assert new_request["forward_v35"]["frame_count"] == 2
    assert new_request["forward_v35"]["compatibility_executor_sha256"] == v35.BOUND_V34_SHA256
    assert new_request["fresh_roots"] == {
        "target_root": str((tmp_path / "target-051").expanduser()),
        "output_root": str((tmp_path / "output-051").expanduser()),
    }
    assert [item["target_relative_path"] for item in new_request["source_entries"]] == [
        "Part_0000.bi4", "Part_0001.bi4"
    ]
    assert [item["bundle_relative_path"] for item in new_overlay["entries"]] == [
        "Part_0000.bi4", "Part_0001.bi4"
    ]
    assert any(item["role"] == "executor_v35" for item in new_request["runtime_sources"])
    assert new_request["sha256"] == v35.canonical_sha(new_request)
    assert new_overlay["sha256"] == v35.canonical_sha(new_overlay)


def test_build_forward_rejects_noncontiguous_frame_names_before_any_binary_read(tmp_path: Path) -> None:
    request, overlay = _fixture(tmp_path, frame_names=("Part_0000.bi4", "Part_0002.bi4"))

    with pytest.raises(v35.PortableV35Error, match="contiguous"):
        v35.build_forward(
            v34_request=request,
            v5_overlay=overlay,
            output_request=tmp_path / "v35-request.json",
            output_overlay=tmp_path / "v35-overlay.json",
        )

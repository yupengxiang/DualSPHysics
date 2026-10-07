from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_f2_native_raw_to_label_bundle_v1 as bundle  # noqa: E402


ANCHORS = Path(__file__).resolve().parents[1] / (
    "campaigns/ds-data-02/stage2/lineage/v14/raw-anchor-plans/"
    "family-raw-anchor-plan-index-v1.json"
)


def test_seven_family_anchor_index_connects_f2_case_78_without_raw_read() -> None:
    value = bundle._anchor_bindings(ANCHORS, current_case_index=78, family_id="F2")
    assert value["status"] == "SEVEN_FAMILY_PLAN_CONNECTED_F2_CASE_78"
    assert len(value["families"]) == 7
    selected = value["selected_anchor"]
    assert selected["family_id"] == "F2"
    assert selected["anchor_current_index"] == 78
    assert len(selected["plan_sha256"]) == 64


def test_raw_frame_binding_requires_worker_computed_sha(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    frame = data_root / "Part_0000.bi4"
    frame.write_bytes(b"fixture raw frame")
    request = {"source_closure": {"raw_frame_binding": {
        "data_root": str(data_root),
        "expected_raw_tree_sha256": "a" * 64,
        "frame_count": 1,
    }}}
    pending = {"before_tree_sha256": "a" * 64, "after_tree_sha256": "a" * 64,
               "frames": [{"frame": 0, "path": str(frame), "raw_frame_file_bytes": frame.stat().st_size}]}
    with pytest.raises(bundle.RawToLabelBundleError, match="incomplete"):
        bundle._frame_bindings(request, pending)
    complete = {"before_tree_sha256": "a" * 64, "after_tree_sha256": "a" * 64,
                "frames": [{"frame": 0, "path": str(frame),
                            "raw_frame_file_bytes": frame.stat().st_size,
                            "raw_frame_file_sha256": "b" * 64}]}
    result = bundle._frame_bindings(request, complete)
    assert result[0]["content_hash_status"] == "VERIFIED_BY_PARENT_WORKER_REPORT"
    assert result[0]["content_sha256"] == "b" * 64


def test_path_map_template_exposes_raw_and_label_roles() -> None:
    manifest = {
        "source_bindings": [
            {"role": "raw_frame_0000", "bundle_relative_path": "raw/Part_0000.bi4"},
            {"role": "reference_typed_hdf5", "bundle_relative_path": "reference/trajectory.h5"},
        ]
    }
    value = bundle._path_map_template(manifest)
    assert value["original_path_fallback"] == "FORBIDDEN"
    assert set(value["role_to_path"]) == {"raw_frame_0000", "reference_typed_hdf5"}
    assert value["role_to_path"]["raw_frame_0000"].startswith("OVERLAY_REQUIRED/")


def test_typed_only_manifest_is_rejected() -> None:
    value = {
        "schema": bundle.BUNDLE_SCHEMA,
        "typed_only": True,
        "bundle_kind": "TYPED_ONLY",
        "sha256": "a" * 64,
    }
    with pytest.raises(bundle.RawToLabelBundleError, match="typed-only"):
        bundle.validate_manifest(value)


def test_label_result_must_bind_v4_raw_tree(tmp_path: Path) -> None:
    label_path = tmp_path / "labels-v15.json"
    label_path.write_text(json.dumps({"reconstruction_binding": {
        "raw_tree_sha256": "a" * 64,
    }}))
    label_sha = hashlib.sha256(label_path.read_bytes()).hexdigest()
    labels = {"result": str(label_path), "result_sha256": label_sha}
    with pytest.raises(bundle.RawToLabelBundleError, match="raw producer tree"):
        bundle._label_bindings({}, labels, expected_raw_tree_sha="b" * 64)
    bound = bundle._label_bindings({}, labels, expected_raw_tree_sha="a" * 64)
    assert bound[0]["role"] == "v15_label_result"

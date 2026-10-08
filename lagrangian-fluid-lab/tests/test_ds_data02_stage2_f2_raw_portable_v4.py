import hashlib
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_raw_portable_v4.py"


def _module():
    spec = importlib.util.spec_from_file_location("portable_v4_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_nested_rewrite_preserves_provenance_and_audit_rejects_original():
    module = _module()
    value = {"path": "/old/root/source.json", "data_root": "/old/data",
             "original_path": "/old/root/source.json",
             "command": ["python", "/old/root/source.json", "/old/data/Part_0000.bi4"]}
    rewritten = module._rewrite(value, {"/old/root/source.json": "/new/runtime/source.json"},
                                [("/old/data", "/new/data")])
    assert rewritten["path"] == "/new/runtime/source.json"
    assert rewritten["data_root"] == "/new/data"
    assert rewritten["command"][1] == "/new/runtime/source.json"
    assert rewritten["command"][2] == "/new/data/Part_0000.bi4"
    assert rewritten["original_path"] == "/old/root/source.json"
    audit = module._AccessAudit({"target_root": "/new", "forbidden_original_prefixes": ["/old"],
                                "entries": []}, Path("/new/out"))
    with pytest.raises(module.PortableV4Error, match="original source path access rejected"):
        audit.hook("open", ("/old/root/source.json", "r"))


def test_seal_overlay_rejects_same_size_wrong_content(tmp_path):
    module = _module()
    target_root = tmp_path / "target"
    target_root.mkdir()
    target = target_root / "sources" / "one.bin"
    target.parent.mkdir()
    target.write_bytes(b"wrong")
    overlay = {
        "schema": module.OVERLAY_SCHEMA,
        "status": "READY_FOR_PARENT_COPY",
        "role": "DEVELOPMENT",
        "qualification": module.UNKNOWN,
        "bundle": {"path": "/tmp/bundle.json", "sha256": "1" * 64, "canonical_sha256": "2" * 64},
        "target_root": str(target_root),
        "entries": [{"role": "raw_frame_input", "bundle_relative_path": "sources/one.bin",
                     "original_path": "/old/one.bin", "target_path": str(target),
                     "expected_sha256": hashlib.sha256(b"right").hexdigest(),
                     "expected_bytes": 5, "original_mtime_ns": 1,
                     "content_hash_status": "PENDING_PARENT_COPY"}],
        "target_paths_are_new": True,
        "content_hash_verified": False,
        "original_path_fallback": "FORBIDDEN",
        "forbidden_original_prefixes": ["/old"],
    }
    overlay_path = tmp_path / "overlay.json"
    # The loader validates the overlay envelope before inspecting copied
    # bytes.  Bind this synthetic fixture so the assertion reaches the
    # same-size wrong-content branch it is intended to cover.
    overlay["sha256"] = module.canonical_sha(overlay)
    module.write_new(overlay_path, overlay)
    with pytest.raises(module.PortableV4Error, match="target SHA differs"):
        module.seal_overlay(overlay_path, tmp_path / "sealed.json")


def test_real_v4_bundle_metadata_preflight_has_no_h5_or_bi4_read(tmp_path):
    module = _module()
    bundle = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v4/f2-s1-native-raw-to-label-bundle-v4-001.json"
    overlay = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v4/f2-s1-native-raw-portable-overlay-v4-001.json"
    report = module.preflight_overlay(overlay, tmp_path / "test-preflight-new.json")
    assert bundle.is_file()
    assert report["status"] == "READY_FOR_PARENT_COPY"
    assert report["hdf5_or_bi4_read"] is False
    assert report["content_hash_verified"] is False

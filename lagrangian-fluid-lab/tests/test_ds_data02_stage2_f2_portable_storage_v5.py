import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_storage_v5.py"
# v5-003 is the committed canonical storage plan.  Earlier 001/002 files are
# local historical generation attempts and are intentionally not test inputs.
PLAN = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v5/f2-s1-portable-storage-plan-v5-003.json"


def _module():
    spec = importlib.util.spec_from_file_location("portable_storage_v5_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_real_plan_rechecks_parent_semantics_and_selects_nvme_namespace():
    module = _module()
    report = module.validate_plan(PLAN)
    assert report["status"] == "PASS_PARENT_SEMANTIC_AND_HEADROOM_RECHECK"
    assert report["hdf5_or_bi4_content_read"] is False
    assert report["parent_lease_semantics_preserved"] is True
    plan = module.load_json(PLAN)
    mapping = plan["storage_mapping"]
    assert mapping["index_remains_below_data_families"] is True
    assert mapping["selected_storage_root"].startswith("/var/tmp/")
    assert plan["filesystem_headroom"]["home_sufficient_for_reference_set"] is False
    assert plan["filesystem_headroom"]["var_tmp_sufficient_for_reference_set"] is True
    assert plan["reference_output_count"] == 14


def test_plan_rejects_ledger_limit_reset(tmp_path):
    module = _module()
    plan = module.load_json(PLAN)
    plan["parent_resource_binding"] = copy.deepcopy(plan["parent_resource_binding"])
    plan["parent_resource_binding"]["limits"]["new_storage_bytes"] += 1
    plan["sha256"] = module.canonical_sha(plan)
    mutated = tmp_path / "mutated-plan.json"
    mutated.write_text(json.dumps(plan, sort_keys=True))
    with pytest.raises(module.StorageV5Error, match="parent lease semantic field changed: limits"):
        module.validate_plan(mutated)


def test_plan_rejects_accessible_index_outside_data_families(tmp_path):
    module = _module()
    with pytest.raises(module.StorageV5Error, match="accessible index"):
        module._validate_index_path((tmp_path / "index.json").resolve())


def test_plan_rejects_storage_root_outside_var_tmp(tmp_path):
    module = _module()
    with pytest.raises(module.StorageV5Error, match="below /var/tmp"):
        module._validate_storage_namespace(tmp_path.resolve())


def test_v5_loader_seal_rejects_same_size_wrong_content(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "portable_v5_test_module",
        ROOT / "scripts" / "ds_data02_stage2_f2_raw_portable_v5.py",
    )
    loader = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(loader)
    target_root = tmp_path / "target"
    target = target_root / "sources" / "one.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"wrong")
    overlay = {
        "schema": loader.OVERLAY_SCHEMA,
        "status": "READY_FOR_PARENT_COPY",
        "role": "DEVELOPMENT",
        "qualification": loader.UNKNOWN,
        "bundle": {"path": "/tmp/bundle.json", "sha256": "1" * 64,
                    "canonical_sha256": "2" * 64},
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
    overlay["sha256"] = loader.canonical_sha(overlay)
    overlay_path = tmp_path / "overlay.json"
    loader.write_new(overlay_path, overlay)
    with pytest.raises(loader.PortableV5Error, match="target SHA differs"):
        loader.seal_overlay(overlay_path, tmp_path / "sealed.json")

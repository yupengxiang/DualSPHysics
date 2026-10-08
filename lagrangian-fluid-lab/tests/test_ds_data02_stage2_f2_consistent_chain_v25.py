"""Stat-only checks for the forward v7→v10 request graph.

The approved bridge path is intentionally not executed here: it would copy
the parent-bound overlay and open native inputs.  These tests do load the
actual v25 request files through the production v7/v10 loaders and exercise
the no-I/O boundary, so a stale nested v7 request cannot be hidden by a
metadata-only path assertion.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "campaigns" / "ds-data-02" / "stage2" / "native-reconstruction" / "raw-to-label-v25-consistent"
V7_REQUEST = BASE / "f2-s1-portable-orchestration-request-v7-012.json"
V7_OVERLAY = BASE / "f2-s1-native-raw-portable-overlay-v7-012.json"
V7_PLAN = BASE / "f2-s1-portable-storage-plan-v7-012.json"
V10_REQUEST = BASE / "f2-s1-portable-ledger-bridge-request-v10-012.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V7 = _load_module("ds02_v7_production_loader", ROOT / "scripts" / "ds_data02_stage2_f2_portable_orchestrator_v7.py")
V10 = _load_module("ds02_v10_production_loader", ROOT / "scripts" / "ds_data02_stage2_f2_portable_ledger_bridge_v10.py")


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_production_bridge_loads_forwarded_v7_from_disk_without_io() -> None:
    v7 = _json(V7_REQUEST)
    v10 = _json(V10_REQUEST)

    assert v10["v7_request"]["path"] == str(V7_REQUEST)
    assert v10["v7_request"]["sha256"] == _file_sha(V7_REQUEST)
    assert v10["v7_request"]["schema"] == v7["schema"]

    # This is the actual bridge loader, not a schema-only copy.  It opens the
    # request from disk and applies the production canonical/model-free gate.
    loaded = V10._load_v7(Path(v10["v7_request"]["path"]))
    assert loaded["request_id"] == v7["request_id"]
    assert V7._validate_request(v7, verify_metadata_content=False)["copy_entries"] == 443

    # The production stat-only boundary must not copy or open HDF5/BI4.
    report = V7.run(V7_REQUEST, io_slot_approved=False)
    assert report["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert report["execution_boundary"]["raw_opened"] is False
    assert report["execution_boundary"]["hdf5_opened"] is False
    assert V10._validate(v10, verify_content=False)


def test_all_target_and_output_roots_share_the_forward_namespace() -> None:
    v7 = _json(V7_REQUEST)
    v10 = _json(V10_REQUEST)
    overlay = _json(V7_OVERLAY)
    plan = _json(V7_PLAN)

    target = v7["copy_contract"]["target_root"]
    selected = v7["execution"]["output_dir"]
    index = v7["execution"]["accessible_index_path"]
    assert target == v10["external_storage_scope"]["roots"][0]
    assert selected == v10["external_storage_scope"]["roots"][1]
    assert index == v10["external_storage_scope"]["accessible_index_path"]
    assert overlay["target_root"] == target
    assert all(str(item["target_path"]).startswith(target + "/") for item in overlay["entries"])
    assert plan["storage_mapping"]["selected_storage_root"] == selected
    assert plan["storage_mapping"]["requested_namespace_root"] == selected
    assert plan["storage_mapping"]["accessible_index_path"] == index

    serialized = json.dumps(v10, sort_keys=True)
    assert "f2-s1-reference-products-v7-001" not in serialized
    assert "f2-s1-bundle-target-v7-001" not in serialized
    assert "portable-output-index.json\"" not in serialized


def test_forward_json_canonical_hashes_are_bound_to_current_files() -> None:
    v7 = _json(V7_REQUEST)
    v10 = _json(V10_REQUEST)
    overlay = _json(V7_OVERLAY)
    plan = _json(V7_PLAN)
    assert v7["sha256"] == V7.canonical_sha(v7)
    assert v10["sha256"] == V10.canonical_sha(v10)
    assert overlay["sha256"] == V7.canonical_sha(overlay)
    assert plan["sha256"] == V7.canonical_sha(plan)
    assert v7["v5_inputs"]["overlay"]["sha256"] == _file_sha(V7_OVERLAY)
    assert v7["storage_plan"]["sha256"] == _file_sha(V7_PLAN)

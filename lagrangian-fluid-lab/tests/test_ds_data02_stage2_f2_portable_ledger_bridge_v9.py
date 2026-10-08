from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_ledger_bridge_v9.py"
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v9-f2-ledger-bridge/"
    "f2-s1-portable-ledger-bridge-request-v9-001.json"
)
SPEC = importlib.util.spec_from_file_location("portable_bridge_v9_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_v9_binds_v5_guard_and_separate_home_nvme_reservations() -> None:
    value = json.loads(REQUEST.read_text())
    assert value["schema"] == module.SCHEMA
    assert value["sha256"] == module.canonical_sha(value)
    assert {item["role"] for item in value["guard_bindings"]} == set(module.V5_GUARD_ROLES)
    reservation = value["reservation"]
    scope = value["external_storage_scope"]
    assert reservation["external_product_reserved_bytes"] == scope["requested_reservation_bytes"]
    assert reservation["new_storage_bytes"] == (
        reservation["external_product_reserved_bytes"] + reservation["home_receipt_reserved_bytes"]
    )
    assert scope["home_receipt"]["included_in_parent_charge"] is True
    assert value["execution"]["source_hash_policy"]["target_seal_is_not_the_only_source_check"] is True
    assert value["model_invoked"] is False and value["cfd_invoked"] is False


def test_v9_metadata_preflight_is_read_only() -> None:
    report = module.run(REQUEST, io_slot_approved=False)
    assert report["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert report["execution_boundary"]["ledger_mutated"] is False
    assert report["execution_boundary"]["hdf5_opened"] is False
    assert report["prevalidation"]["process_and_children_cpu_seconds"] >= 0


def test_v9_rejects_static_source_content_change_before_reservation() -> None:
    value = json.loads(REQUEST.read_text())
    bad = copy.deepcopy(value)
    item = next(item for item in bad["source_bindings"] if item.get("source_kind") != "parent")
    item["sha256"] = "0" * 64
    bad["sha256"] = module.canonical_sha(bad)
    with pytest.raises(module.BridgeV9Error, match="source content SHA differs"):
        module._validate(bad, verify_content=True)


def test_v9_rejects_mutable_parent_reset_policy() -> None:
    value = json.loads(REQUEST.read_text())
    bad = copy.deepcopy(value)
    bad["parent_resource_binding"]["no_reset"] = False
    bad["sha256"] = module.canonical_sha(bad)
    with pytest.raises(module.BridgeV9Error, match="reset/new-root policy"):
        module._validate(bad, verify_content=False)


def test_v9_receipt_fixed_point_counts_home_receipt(tmp_path: Path) -> None:
    value = {
        "schema": module.REPORT_SCHEMA,
        "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "filesystem": {"home_receipt_bytes": 0, "measured_total_bytes": 0},
        "qualification": copy.deepcopy(module.UNKNOWN),
    }
    target = tmp_path / "execution-receipt.json"
    total = module._prepare_receipt_fixed_point(value, target, external_bytes=100)
    assert total > 100
    assert value["filesystem"]["home_receipt_bytes"] == total - 100
    assert value["filesystem"]["measured_total_bytes"] == total


from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_ledger_bridge_v8.py"
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v8-f2-ledger-bridge/"
    "f2-s1-portable-ledger-bridge-request-v8-001.json"
)
SPEC = importlib.util.spec_from_file_location("portable_bridge_v8_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_v8_request_binds_shared_v4_and_external_storage_charge() -> None:
    value = json.loads(REQUEST.read_text())
    assert value["schema"] == module.SCHEMA
    assert value["sha256"] == module.canonical_sha(value)
    assert value["qualification"] == module.UNKNOWN
    assert {item["role"] for item in value["guard_bindings"]} == set(module.V4_GUARD_ROLES)
    assert value["reservation"]["atomic_ledger_lock"] == "shared v4 runtime ledger_locked"
    assert value["reservation"]["same_parent_lease"] is True
    assert value["external_storage_scope"]["tree_bytes_measurement"].startswith("recursive regular-file bytes")
    assert value["execution"]["prevalidation_cost"]["included_in_same_parent_charge"] is True
    assert value["execution"]["expected_artifacts_gate"] is True
    assert value["model_invoked"] is False
    assert value["cfd_invoked"] is False


def test_v8_metadata_preflight_does_not_mutate_ledger_or_open_native_data() -> None:
    report = module.run(REQUEST, io_slot_approved=False)
    assert report["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert report["execution_boundary"] == {
        "ledger_mutated": False,
        "raw_opened": False,
        "hdf5_opened": False,
        "model_invoked": False,
        "cfd_invoked": False,
    }


def test_v8_artifact_gate_rejects_missing_outputs(tmp_path: Path) -> None:
    result = module._artifact_check([{"role": "required", "path": str(tmp_path / "missing.json")}])
    assert result["status"] == "MISSING_REQUIRED_ARTIFACTS"
    assert result["missing"] == [str((tmp_path / "missing.json").resolve())]


def test_v8_rejects_mutated_guard_sha_before_reservation() -> None:
    value = json.loads(REQUEST.read_text())
    bad = copy.deepcopy(value)
    bad["guard_bindings"][0]["sha256"] = "0" * 64
    with pytest.raises(module.BridgeV8Error, match="source content SHA differs"):
        module._stat_binding(bad["guard_bindings"][0], verify_content=True)


def test_v8_rejects_existing_external_namespace_before_reservation(tmp_path: Path) -> None:
    value = json.loads(REQUEST.read_text())
    bad = copy.deepcopy(value)
    existing = tmp_path / "already-created"
    existing.mkdir()
    bad["external_storage_scope"]["roots"][0] = str(existing)
    bad["sha256"] = module.canonical_sha(bad)
    with pytest.raises(module.BridgeV8Error, match="outside /var/tmp"):
        module._validate(bad, verify_content=False)

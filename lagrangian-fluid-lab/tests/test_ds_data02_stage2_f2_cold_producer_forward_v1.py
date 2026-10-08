from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_cold_producer_forward_v1.py"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v38-full-chain/f2-s1-fresh-v16-source-contract-v3-001.json"
SIDECAR = ROOT / "campaigns/ds-data-02/stage2/evaluator/v3/f2-s1-current-source-rebind-v1-001.json"
REQUEST = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v38-full-chain-root-059/f2-s1-portable-executor-request-v38-root-059-case-bound.json"
PARENT = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v38-full-chain-root-059/f2-s1-portable-executor-parent-request-v3-root-059-case-bound.json"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("cold_producer_v39_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V39 = _load(SCRIPT)


def test_contract_separates_actual_current_from_historical_overlay(tmp_path: Path) -> None:
    output = tmp_path / "v39-contract.json"
    result = V39.build_source_contract(source_contract=CONTRACT, rebind_sidecar=SIDECAR, output=output)
    value = json.loads(output.read_text(encoding="utf-8"))
    provenance = value["current_catalog_provenance"]
    assert result["hdf5_bi4_result_content_read"] is False
    assert provenance["actual_current_catalog"]["sha256"] == V39.ACTUAL_CURRENT_SHA
    assert provenance["historical_result_view"]["sha256"] == V39.HISTORICAL_OVERLAY_SHA
    assert provenance["actual_current_catalog"]["exact_current_source"] is True
    assert provenance["historical_result_view"]["exact_current_source"] is False
    assert value["expected"]["source_binding_scope"]["exact_current_claim"] == "REJECTED_FOR_HISTORICAL_RESULT_VIEW"
    # The legacy source map is retained for V15 compatibility, but its scope
    # is explicit and it cannot be mistaken for the actual CURRENT file.
    assert value["expected"]["source_binding"]["current_catalog_sha256"] == V39.HISTORICAL_OVERLAY_SHA
    assert value["sha256"] == V39.canonical_sha(value)


def test_request_preserves_447_roles_and_frozen_raw_tree(tmp_path: Path) -> None:
    contract_out = tmp_path / "v39-contract.json"
    V39.build_source_contract(source_contract=CONTRACT, rebind_sidecar=SIDECAR, output=contract_out)
    request_out = tmp_path / "v39-request.json"
    result = V39.build_request(
        v38_request=REQUEST, source_contract_v39=contract_out,
        rebind_sidecar=SIDECAR, output=request_out,
        request_id="f2-s1-portable-executor-v39-test",
        target_root=Path("/var/tmp/ds02-stage2/test-v39/bundle"),
        output_root=Path("/var/tmp/ds02-stage2/test-v39/products"),
        attempt_id="f2-s1-v39-test")
    value = json.loads(request_out.read_text(encoding="utf-8"))
    assert result["source_entry_count"] == 447
    assert len(value["source_entries"]) == 447
    raw = value["forward_v39"]["raw_tree"]
    assert raw == {"file_count": 405, "frame_count": 401, "tree_sha256": V39.RAW_TREE_SHA}
    assert value["source_entries"][2]["role"] == "v2:current_catalog"
    assert value["source_entries"][2]["sha256"] == V39.ACTUAL_CURRENT_SHA
    assert value["current_catalog_binding"]["original"]["exact_current_source"] is True
    assert value["current_catalog_binding"]["historical_result_view"]["exact_current_source"] is False
    assert value["parent_resource_binding"]["storage_policy"] == "home_free_floor"
    assert value["parent_resource_binding"]["ledger_reset"] is False
    assert value["qualification"] == V39.UNKNOWN
    assert value["sha256"] == V39.canonical_sha(value)


def test_parent_rebinds_new_request_and_contract_without_missing_parent_fallback(tmp_path: Path) -> None:
    contract_out = tmp_path / "v39-contract.json"
    request_out = tmp_path / "v39-request.json"
    parent_out = tmp_path / "v39-parent.json"
    V39.build_source_contract(source_contract=CONTRACT, rebind_sidecar=SIDECAR, output=contract_out)
    V39.build_request(
        v38_request=REQUEST, source_contract_v39=contract_out,
        rebind_sidecar=SIDECAR, output=request_out,
        request_id="f2-s1-portable-executor-v39-parent-test",
        target_root=Path("/var/tmp/ds02-stage2/test-v39-parent/bundle"),
        output_root=Path("/var/tmp/ds02-stage2/test-v39-parent/products"),
        attempt_id="f2-s1-v39-parent-test")
    result = V39.build_parent_request(
        v38_parent_request=PARENT, v39_request=request_out,
        source_contract_v39=contract_out, rebind_sidecar=SIDECAR,
        output=parent_out, attempt_id="f2-s1-v39-parent-test",
        output_root=Path("/var/tmp/ds02-stage2/test-v39-parent/parent"),
        home_receipt=tmp_path / "home-receipt.json",
        trace_path=Path("/var/tmp/ds02-stage2/test-v39-parent/trace"))
    value = json.loads(parent_out.read_text(encoding="utf-8"))
    assert result["executor_request_sha256"] == json.loads(request_out.read_text())["sha256"]
    assert value["executor_request"]["path"] == str(request_out)
    assert value["parent_resource_binding"]["allow_missing_parent"] is False
    assert {item["role"] for item in value["static_bindings"]} >= {"executor_v39_request", "v39_source_contract"}
    assert value["forward_v39"]["raw_tree_sha256"] == V39.RAW_TREE_SHA
    assert value["sha256"] == V39.canonical_sha(value)

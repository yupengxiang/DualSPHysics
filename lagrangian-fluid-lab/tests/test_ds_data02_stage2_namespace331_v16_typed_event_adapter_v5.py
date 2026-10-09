from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_v16_typed_event_adapter_v5.py"
SPEC = importlib.util.spec_from_file_location("namespace331_v16_typed_event_adapter_v5_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _load_fixture_helpers():
    path = ROOT / "tests/test_ds_data02_stage2_namespace331_v16_typed_event_adapter_v2.py"
    spec = importlib.util.spec_from_file_location("event_v2_fixture_helpers_for_v5", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_ref(path: Path, value: dict) -> dict[str, str]:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _scope(tmp_path: Path, *, alias: str, covered: bool, join: str, status: str = "COMPLETED") -> dict:
    case_id = "F6_TYPED_EVENT_FIXTURE"
    plan = {
        "schema": "ds02.stage2.current-lifecycle-plan.v1",
        "case_records": [{
            "physical_case_id": case_id,
            "canonical_case_id": case_id,
            "historical_alias": alias,
            "actual_saved_mask_coverage": covered,
            "source_join_status": join,
            "status": status,
        }],
    }
    registry = {
        "schema": "ds02.stage2.lifecycle-producer-registry.v1",
        "producers": [{"producer_id": "producer-fixture", "status": "COMPLETED", "case_ids": [case_id]}],
    }
    return {
        "physical_case_id": case_id,
        "current_plan": _write_ref(tmp_path / "current-plan.json", plan),
        "producer_registry": _write_ref(tmp_path / "producer-registry.json", registry),
        "expected": {
            "historical_alias": alias,
            "actual_saved_mask_coverage": covered,
            "source_join_status": join,
            "status": status,
        },
    }


def test_real_root200_unknown_short_circuits_without_current_scope_or_typed_read() -> None:
    path = ROOT / (
        "campaigns/ds-data-02/stage2/lineage/"
        "v29-namespace331-v3-role-proof-root200-source-prepared-001/"
        "root200-v3-source-event-request.json"
    )
    request = MODULE._read_json(path, role="ROOT200 request")
    context = MODULE.validate_request_v5(request)
    assert context["all_roles_known"] is False
    assert context["current_identity_scope"]["identity_admission"] == "UNKNOWN_NO_CURRENT_SCOPE"
    result = MODULE.build_unknown_event_result_from_request(request)
    assert result["status"] == "UNKNOWN_REQUIRED_ROLE_OR_CURRENT_SCOPE"
    assert result["typed_content_read"] is False
    assert result["labels"] == []
    assert result["current_identity_scope"]["typed_label_admission"] is False


def test_known_roles_cannot_cross_unresolved_historical_alias(tmp_path: Path) -> None:
    fixture = _load_fixture_helpers()
    request = fixture._request()
    request["lifecycle_scope"] = _scope(
        tmp_path,
        alias="HISTORICAL_ALIAS_REVIEW_REQUIRED",
        covered=False,
        join="SEPARATE_HISTORICAL_ALIAS_UNRESOLVED",
        status="FAILED_REQUIRES_NEW_ATTEMPT",
    )
    request["request_sha256"] = MODULE.canonical_sha(request)
    with pytest.raises(MODULE.TypedEventAdapterV5Error, match="historical alias|not actually covered"):
        MODULE.validate_request_v5(request, allow_fixture=True)


def test_known_roles_require_exact_current_scope_and_completed_producer(tmp_path: Path) -> None:
    fixture = _load_fixture_helpers()
    request = fixture._request()
    request["lifecycle_scope"] = _scope(
        tmp_path,
        alias="NONE",
        covered=True,
        join="EXACT_CURRENT_AUDIT_METADATA_JOIN",
    )
    request["request_sha256"] = MODULE.canonical_sha(request)
    context = MODULE.validate_request_v5(request, allow_fixture=True)
    assert context["current_identity_scope"]["identity_admission"] == "CURRENT_EXACT_NO_HISTORICAL_ALIAS"
    result = MODULE.build_event_stream_from_request(
        fixture._typed_result(), request, allow_fixture=True,
    )
    assert result["adapter"]["schema"] == MODULE.ADAPTER_SCHEMA
    assert result["adapter"]["identity_admission"] == "CURRENT_EXACT_NO_HISTORICAL_ALIAS"
    assert result["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_missing_scope_is_rejected_for_known_roles_even_if_case_string_is_canonical() -> None:
    fixture = _load_fixture_helpers()
    request = fixture._request()
    request["case_identity"]["identity_status"] = "CANONICAL"
    request["request_sha256"] = MODULE.canonical_sha(request)
    with pytest.raises(MODULE.TypedEventAdapterV5Error, match="strict CURRENT lifecycle scope"):
        MODULE.validate_request_v5(request, allow_fixture=True)

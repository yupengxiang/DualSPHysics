from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_v16_typed_event_adapter_v3.py"
SPEC = importlib.util.spec_from_file_location("namespace331_v16_typed_event_adapter_v3_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
V2_TEST_SPEC = importlib.util.spec_from_file_location(
    "namespace331_v16_typed_event_adapter_v2_fixture_helpers",
    ROOT / "tests/test_ds_data02_stage2_namespace331_v16_typed_event_adapter_v2.py",
)
assert V2_TEST_SPEC is not None and V2_TEST_SPEC.loader is not None
V2_TEST = importlib.util.module_from_spec(V2_TEST_SPEC)
V2_TEST_SPEC.loader.exec_module(V2_TEST)

REAL_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/lineage/"
    "v29-namespace331-v3-role-proof-root200-source-prepared-001/"
    "root200-v3-source-event-request.json"
)


def test_root200_binds_to_additive_v3_and_short_circuits_unknown_roles(tmp_path: Path) -> None:
    output = tmp_path / "root200-v3-bound.json"
    result = MODULE.bind_request(REAL_REQUEST, output)

    assert result["adapter_schema"] == MODULE.ADAPTER_SCHEMA
    assert result["all_roles_known"] is False
    request = MODULE._read_request(output)
    context = MODULE.validate_request_v3(request)
    assert context["all_roles_known"] is False
    assert request["v3_adapter_binding"]["source_request"]["canonical_sha256"] == (
        MODULE._read_request(REAL_REQUEST)["request_sha256"]
    )
    unknown = MODULE.build_unknown_event_result_from_request(request)
    assert unknown["schema"] == MODULE.UNKNOWN_ADMISSION_SCHEMA
    assert unknown["typed_content_read"] is False
    assert unknown["adapter"]["event_credit"] == "NONE_ROLE_PROOF_UNKNOWN"
    assert unknown["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_unknown_roles_short_circuit_before_opening_missing_typed_file() -> None:
    request = MODULE._read_request(REAL_REQUEST)
    result = MODULE.convert_bounded_json(
        request,
        Path("/definitely-unavailable/ROOT200-typed-result-must-not-be-opened.json"),
    )
    assert result["schema"] == MODULE.UNKNOWN_ADMISSION_SCHEMA
    assert result["labels"] == []
    assert all(value is None for value in result["metrics"].values())


def test_typed_mapping_is_rejected_when_source_or_region_owner_is_unknown() -> None:
    request = MODULE._read_request(REAL_REQUEST)
    with pytest.raises(MODULE.TypedEventAdapterV3Error, match="must not be supplied"):
        MODULE.build_event_stream_from_request({"labels": []}, request)


def test_known_fixture_delegates_to_strict_consumer_with_v3_adapter_schema() -> None:
    request = V2_TEST._request()
    document = MODULE.build_event_stream_from_request(
        V2_TEST._typed_result(), request, allow_fixture=True,
    )
    assert document["adapter"]["schema"] == MODULE.ADAPTER_SCHEMA
    assert document["adapter"]["event_credit"] == "DEVELOPMENT_UNKNOWN"
    assert document["adapter"]["production_eligible"] is False
    assert document["particles"][0]["particle_identity"] == {"Zone": 0, "Idp": 11}


def test_v3_binding_tampering_is_rejected_without_touching_source_request() -> None:
    request = MODULE._read_request(REAL_REQUEST)
    request["v3_adapter_binding"] = {
        "adapter_schema": "ds02.stage2.namespace331.v16-typed-event-adapter.v2",
        "adapter_script_path": str(SCRIPT),
        "adapter_script_file_sha256": "a" * 64,
        "source_request": {
            "path": str(REAL_REQUEST),
            "file_sha256": "b" * 64,
            "canonical_sha256": request["request_sha256"],
            "request_schema": MODULE.REQUEST_SCHEMA,
        },
    }
    request["request_sha256"] = MODULE.canonical_sha(request)
    with pytest.raises(MODULE.TypedEventAdapterV3Error, match="binding schema"):
        MODULE.validate_request_v3(request)

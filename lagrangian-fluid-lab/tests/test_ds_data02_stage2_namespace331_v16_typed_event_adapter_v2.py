"""Small, source-only tests for the V3 typed-event admission boundary."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_v16_typed_event_adapter_v2.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = _load(SCRIPT, "namespace331_v16_typed_event_adapter_v2_test")


def _role(role: str, *, known: bool = True) -> dict:
    item = {
        "requested_role": role,
        "artifact_path": f"/sealed/fixture/{role}.json",
        "artifact_sha256": hashlib.sha256(role.encode("ascii")).hexdigest(),
        "artifact_schema": "ds02.stage2.namespace331.fixture.source-contract.v1",
        "proof_status": "SOURCE_BOUND" if known else None,
        "status": "KNOWN" if known else "UNKNOWN",
        "unknown_reasons": [] if known else ["fixture_role_not_bound"],
        "derived_semantic_role": role,
    }
    if known:
        item["producer_source_closure"] = {
            "credit_boundary": "MANUFACTURED_FIXTURE_ONLY"
        }
    return item


def _typed_result() -> dict:
    current_sha = "d" * 64
    return {
        "schema": "ds02.stage2.f2-s1-replay-result.v16",
        "case_identity": {
            "family_id": "F6",
            "physical_case_id": "F6_TYPED_EVENT_FIXTURE",
            "identity_status": "CANONICAL",
        },
        "source_binding": {"current_catalog_sha256": current_sha},
        "window": {"time_start_s": 0.0, "time_stop_s": 4.0, "frame_count": 5},
        "initial_mass_denominator": {
            "denominator_kg": 2.5,
            "selected_initial_mass_kg": 2.5,
        },
        "labels": [
            {
                "zone": 0,
                "idp": 11,
                "initial_mass_kg": 2.0,
                "status": "observed",
                "event_time_s": 1.0,
                "residence_intervals": [
                    {"start_time_s": 0.5, "end_time_s": 1.0, "region": "receiver"}
                ],
            },
            {"zone": 0, "idp": 12, "initial_mass_kg": 0.5, "status": "censored"},
        ],
    }


def _request(*, unknown_role: str | None = None) -> dict:
    request = {
        "schema": A.REQUEST_SCHEMA,
        "status": "ROLE_PROOF_METADATA_PARTIAL_UNKNOWN" if unknown_role else
        "READY_FOR_PARENT_GUARD_ROLE_PROOFS",
        "case_identity": {
            "family_id": "F6",
            "physical_case_id": "F6_TYPED_EVENT_FIXTURE",
        },
        "typed_result": {
            "path": "/sealed/fixture/fresh-v16-proof.json",
            "sha256": "a" * 64,
            "content_policy": "PARENT_GUARD_READ_AFTER_ATOMIC_RESERVATION",
        },
        "current_binding": {
            "path": "/sealed/fixture/CURRENT336.json",
            "sha256": "d" * 64,
            "content_policy": "SMALL_CURRENT_METADATA_AFTER_ATOMIC_RESERVATION",
        },
        "event_contract": {
            "source_region": "initial_fluid",
            "target_region": "receiver",
            "identity_key": "(Zone,Idp)",
        },
        "execution": {
            "parent_supervision_required": True,
            "model_invoked": False,
            "h5_bi4_raw_opened": False,
        },
        "role_proof_artifacts": [
            _role(role, known=role != unknown_role)
            for role in A.REQUIRED_ROLES
        ],
    }
    request["request_sha256"] = A.canonical_sha(request)
    return request


def test_real_v3_request_is_metadata_admissible_without_typed_read() -> None:
    path = ROOT / (
        "campaigns/ds-data-02/stage2/lineage/"
        "v29-namespace331-v3-role-proof-root200-source-prepared-001/"
        "root200-v3-source-event-request.json"
    )
    request = A._read_request(path)
    context = A.validate_request_v3(request)
    assert context["case_identity"]["family_id"] == "F2"
    assert context["all_roles_known"] is False
    assert context["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_guarded_mapping_uses_strict_event_consumer_and_no_credit_for_unknown_role() -> None:
    request = _request(unknown_role="region_owner")
    document = A.build_event_stream_from_request(_typed_result(), request, allow_fixture=True)
    assert document["schema"] == A.EVENT_SCHEMA
    assert document["adapter"]["schema"] == A.ADAPTER_SCHEMA
    assert document["adapter"]["event_credit"] == "NONE_ROLE_PROOF_UNKNOWN"
    assert document["adapter"]["fixture_role_proof_credit"] is True
    assert document["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert document["particles"][0]["particle_identity"] == {"Zone": 0, "Idp": 11}


def test_all_known_fixture_is_still_development_unknown_and_not_scientific_credit() -> None:
    request = _request()
    context = A.validate_request_v3(request, allow_fixture=True)
    assert context["all_roles_known"] is True
    document = A.build_event_stream_from_request(_typed_result(), request, allow_fixture=True)
    assert document["adapter"]["event_credit"] == "DEVELOPMENT_UNKNOWN"
    assert document["adapter"]["fixture_role_proof_credit"] is True
    assert document["adapter"]["production_eligible"] is False
    assert all(value == "UNKNOWN" for value in document["qualification"].values())


def test_fixture_closure_is_rejected_by_default_for_production_admission() -> None:
    with pytest.raises(A.TypedEventAdapterV2Error, match="not production eligible"):
        A.validate_request_v3(_request())


def test_request_sha_and_schema_are_strict() -> None:
    request = _request()
    broken = copy.deepcopy(request)
    broken["request_sha256"] = "0" * 64
    with pytest.raises(A.TypedEventAdapterV2Error, match="canonical SHA"):
        A.validate_request_v3(broken)
    broken = copy.deepcopy(request)
    broken["schema"] = "ds02.stage2.namespace331.unsupported"
    broken["request_sha256"] = A.canonical_sha(broken)
    with pytest.raises(A.TypedEventAdapterV2Error, match="request schema"):
        A.validate_request_v3(broken)


def test_unknown_role_does_not_allow_missing_role_or_duplicate_role() -> None:
    request = _request()
    request["role_proof_artifacts"].pop()
    request["request_sha256"] = A.canonical_sha(request)
    with pytest.raises(A.TypedEventAdapterV2Error, match="lacks roles"):
        A.validate_request_v3(request)

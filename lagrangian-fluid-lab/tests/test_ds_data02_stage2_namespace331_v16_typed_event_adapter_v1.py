"""Source-only V16/typed to namespace331 event-stream adapter tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_v16_typed_event_adapter_v1.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = _load(SCRIPT, "namespace331_v16_typed_event_adapter_v1")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _typed(tmp_path: Path, *, identity_status: str = "CANONICAL") -> tuple[dict, dict, list[dict]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    current = tmp_path / "CURRENT336.json"
    current.write_text('{"case":"fixture-current","case_count":1}\n', encoding="utf-8")
    current_sha = _sha(current)
    bindings = []
    for role, semantic in (("source-proof", "source"),
                           ("owner-proof", "region_owner"),
                           ("control-proof", "control")):
        path = tmp_path / f"{role}.json"
        path.write_text(json.dumps({"semantic_role": semantic, "status": "verified"}), encoding="utf-8")
        digest = _sha(path)
        bindings.append({"role": role, "semantic_role": semantic, "path": str(path),
                         "sha256": digest, "observed_sha256": digest,
                         "content_verified": True, "content_policy": "SMALL_METADATA_PROOF_ONLY"})
        bindings[-1]["role_attestation"] = {
            "content_schema": f"fixture.{semantic}.proof.v1",
            "semantic_role": semantic, "proof_status": "VERIFIED",
            "content_sha256": digest,
        }
    result = {
        "schema": "ds02.stage2.f2-s1-replay-result.v16",
        "case_identity": {"family_id": "F6", "physical_case_id": "F6_TYPED_FIXTURE",
                           "identity_status": identity_status},
        "source_binding": {"current_catalog_sha256": current_sha},
        "window": {"time_start_s": 0.0, "time_stop_s": 4.0, "frame_count": 5},
        "initial_mass_denominator": {"denominator_kg": 2.5, "selected_initial_mass_kg": 2.5},
        "labels": [
            {"zone": 0, "idp": 11, "initial_mass_kg": 2.0, "status": "observed",
             "event_time_s": 1.0,
             "residence_intervals": [{"start_time_s": 0.5, "end_time_s": 1.0,
                                       "region": "receiver"}]},
            {"zone": 0, "idp": 12, "initial_mass_kg": 0.5, "status": "censored"},
        ],
    }
    current_binding = {"path": str(current), "sha256": current_sha}
    return result, current_binding, bindings


def test_adapter_converts_real_v16_shape_and_v2_consumer_accepts_it(tmp_path: Path) -> None:
    result, current, bindings = _typed(tmp_path)
    document = A.build_event_stream_from_v16(
        result, current_binding=current, source_bindings=bindings,
        source_region="initial_fluid", target_region="receiver")
    assert document["schema"] == A.EVENT_SCHEMA
    assert document["adapter"]["status"] == "BOUND"
    assert document["observation_contract"]["observation_window_s"] == [0.0, 4.0]
    assert document["particles"][0]["particle_identity"] == {"Zone": 0, "Idp": 11}
    assert document["particles"][0]["events"][0]["event_type"] == "RESIDENCE_INTERVAL"
    n331 = _load(ROOT / "scripts/ds_data02_stage2_namespace331_mass_weighted_labels_v2.py",
                 "namespace331_v2_for_adapter_test")
    normalized = n331.validate_event_stream_v2(document, verify_sources=True)
    produced = n331.produce_labels_v2(document, verify_sources=True)
    assert normalized["particles"][0]["particle_id"] == "Zone=0;Idp=11"
    assert produced["derived_status"] == "OBSERVED_METADATA_ONLY_DEVELOPMENT_UNKNOWN"
    assert produced["metrics"]["first_arrival_mass_kg"] == pytest.approx(2.0)
    assert produced["metrics"]["residence_mass_time_kg_s"] == pytest.approx(1.0)


def test_adapter_preserves_unknown_on_stale_current_or_unverified_roles(tmp_path: Path) -> None:
    result, current, bindings = _typed(tmp_path)
    result["source_binding"]["current_catalog_sha256"] = "0" * 64
    bindings[1]["observed_sha256"] = None
    bindings[1]["content_verified"] = False
    document = A.build_event_stream_from_v16(
        result, current_binding=current, source_bindings=bindings,
        source_region="initial_fluid", target_region="receiver")
    assert document["adapter"]["status"] == "UNKNOWN_UNBOUND_EVIDENCE"
    assert "current_binding_mismatch" in document["adapter"]["unknown_reasons"]
    assert "source_owner_control_roles_not_hash_bound" in document["adapter"]["unknown_reasons"]
    n331 = _load(ROOT / "scripts/ds_data02_stage2_namespace331_mass_weighted_labels_v2.py",
                 "namespace331_v2_unknown_adapter_test")
    produced = n331.produce_labels_v2(document)
    assert produced["derived_status"] == "UNKNOWN"
    assert all(value is None for value in produced["metrics"].values())


def test_adapter_does_not_treat_semantic_role_string_and_sha_as_content_attestation(tmp_path: Path) -> None:
    result, current, bindings = _typed(tmp_path)
    for binding in bindings:
        binding.pop("role_attestation")
    document = A.build_event_stream_from_v16(
        result, current_binding=current, source_bindings=bindings,
        source_region="initial_fluid", target_region="receiver")
    assert document["adapter"]["status"] == "UNKNOWN_UNBOUND_EVIDENCE"
    assert "source_owner_control_roles_not_hash_bound" in document["adapter"]["unknown_reasons"]


def test_adapter_rejects_missing_or_duplicate_zone_idp_and_wrong_region(tmp_path: Path) -> None:
    result, current, bindings = _typed(tmp_path)
    missing = json.loads(json.dumps(result))
    missing["labels"][0].pop("zone")
    with pytest.raises(A.TypedEventAdapterError, match="Zone/Idp"):
        A.build_event_stream_from_v16(
            missing, current_binding=current, source_bindings=bindings,
            source_region="initial_fluid", target_region="receiver")
    duplicate = json.loads(json.dumps(result))
    duplicate["labels"][1]["zone"] = 0
    duplicate["labels"][1]["idp"] = 11
    with pytest.raises(A.TypedEventAdapterError, match="duplicate typed"):
        A.build_event_stream_from_v16(
            duplicate, current_binding=current, source_bindings=bindings,
            source_region="initial_fluid", target_region="receiver")
    wrong_region = json.loads(json.dumps(result))
    wrong_region["labels"][0]["residence_intervals"][0]["region"] = "other"
    document = A.build_event_stream_from_v16(
        wrong_region, current_binding=current, source_bindings=bindings,
        source_region="initial_fluid", target_region="receiver")
    n331 = _load(ROOT / "scripts/ds_data02_stage2_namespace331_mass_weighted_labels_v2.py",
                 "namespace331_v2_wrong_region_adapter_test")
    with pytest.raises(n331.Namespace331V2Error, match="outside target_region"):
        n331.validate_event_stream_v2(document)


def test_adapter_rejects_mass_mismatch_and_builds_deferred_request_without_reading_result(tmp_path: Path) -> None:
    result, current, bindings = _typed(tmp_path)
    result["labels"][1]["initial_mass_kg"] = 0.25
    with pytest.raises(A.TypedEventAdapterError, match="mass sum"):
        A.build_event_stream_from_v16(
            result, current_binding=current, source_bindings=bindings,
            source_region="initial_fluid", target_region="receiver")
    missing_result = tmp_path / "deferred-v16-result.json"
    request = A.build_typed_event_request_v1(
        missing_result, typed_result_sha256="a" * 64, current_binding=current,
        source_bindings=bindings, output_event_stream=tmp_path / "events.json",
        family_id="F6", physical_case_id="F6_TYPED_FIXTURE",
        source_region="initial_fluid", target_region="receiver")
    assert request["schema"] == A.REQUEST_SCHEMA
    assert request["typed_result"]["stat"]["exists"] is False
    assert request["execution"]["h5_bi4_raw_opened"] is False


def test_adapter_unknown_case_identity_is_consumed_as_all_unknown(tmp_path: Path) -> None:
    result, current, bindings = _typed(tmp_path, identity_status="UNKNOWN")
    document = A.build_event_stream_from_v16(
        result, current_binding=current, source_bindings=bindings,
        source_region="initial_fluid", target_region="receiver")
    n331 = _load(ROOT / "scripts/ds_data02_stage2_namespace331_mass_weighted_labels_v2.py",
                 "namespace331_v2_identity_unknown_adapter_test")
    produced = n331.produce_labels_v2(document, verify_sources=True)
    assert produced["identity_status"] == "UNKNOWN"
    assert produced["derived_status"] == "UNKNOWN"
    assert all(row["label_status"] == "UNKNOWN_MISSING_CASE_IDENTITY_OR_BINDING"
               for row in produced["labels"])

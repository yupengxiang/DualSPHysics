from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_fresh_v16_proof_request_builder_v4.py"
SPEC = importlib.util.spec_from_file_location("f2_fresh_v16_builder_v4", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _sha(seed: str) -> str:
    import hashlib
    return hashlib.sha256(seed.encode()).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Path]:
    original = tmp_path / "original"
    target = tmp_path / "relocated" / "target"
    product = tmp_path / "relocated" / "products"
    original.mkdir(parents=True)
    target.mkdir(parents=True)
    product.mkdir(parents=True)

    overlay = product / "current-view.json"
    _write(overlay, {"schema": "relocated-current-view", "case": 78, "trajectory": "new"})
    relocated_sha = _sha("new-relocated-current")
    # The fixture deliberately carries a declared digest independently of the
    # tiny overlay bytes.  V4 binds producer-declared/result-declared SHAs and
    # defers new payload hashing to the parent consumer.

    expected = {
        "source_binding": {
            "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND",
            "current_catalog_sha256": relocated_sha,
            "trajectory_h5_producer_sha256": _sha("trajectory"),
            "source_files": {"current_catalog": relocated_sha, "motion_dat": _sha("motion")},
        },
        "case_identity": {"family_id": "F2", "physical_case_id": "F2-S1", "current_case_index": 78},
        "cohort": {"selected_count": 21114, "identity_key": "(Zone,Idp)",
                   "identity_sha256": builder.EXPECTED_IDENTITY_SHA,
                   "initial_type_code": 3, "initial_mk_codes": [1, 2, 3]},
        "initial_mass_denominator": {
            "denominator_kg": builder.EXPECTED_DENOMINATOR,
            "initial_missing_mass_kg": 0.0, "initially_absent_count": 0,
            "later_missing_mass_kg": builder.EXPECTED_LATER_MISSING,
            "later_missing_unique_count": 3,
            "derivation": "frozen initial mass is not augmented by later missing IDs",
        },
        "time": {"first_s": 0.0, "last_s": 4.000007783879406, "frame_count": 401,
                 "tolerance_s": 0.0, "observer_profile_sha256": _sha("profile")},
        "observer_fields": ["mass_weighted_com_m", "mass_weighted_mean_velocity_m_s",
                             "mass_weighted_kinetic_energy_J", "mass_quantile_front_m",
                             "mass_distribution_fraction", "event_status", "event_time_s"],
        "events": {
            "status_vocabulary": ["ambiguous_multiple_crossing", "failed_before_observation",
                                   "initially_inside", "observed", "right_censored"],
            "require_unknown_recross": True, "require_total_net_interval": True,
            "require_receiver_labels": True, "require_residence_semantics": True,
            "semantics_source": {key: "bound" for key in ("later_missing", "saved_bracket", "recross", "receiver_volume", "aperture")},
        },
    }
    contract = {
        "schema": builder.CONTRACT_SCHEMA, "role": "DEVELOPMENT", "quality": dict(builder.UNKNOWN),
        "original_roots": [str(original)], "expected": expected,
        "current_catalog_provenance": {
            "actual_current_catalog": {"sha256": builder.ACTUAL_CURRENT_SHA, "path": str(original / "CURRENT.json")},
            "relocated_runtime_view": {"sha256": relocated_sha, "path": str(overlay)},
            "historical_v39_overlay_sha256": builder.HISTORICAL_OVERLAY_SHA,
        },
    }
    contract["sha256"] = builder.canonical_sha(contract)
    contract_path = tmp_path / "v40-contract.json"
    _write(contract_path, contract)

    # The result SHA is intentionally a declared producer SHA whose bytes are
    # not equal to it.  The builder must stat only; the V11 consumer rehashes
    # and rejects this fixture if an approved run is attempted.
    typed = product / "typed-reconstructed.h5"
    v15 = product / "v15-result.json"
    v16 = product / "v16-result.json"
    converter = product / "raw-converter-report-v2.json"
    for path, content in ((typed, "typed"), (v15, "v15"), (v16, "v16"), (converter, "converter")):
        path.write_text(content, encoding="utf-8")
    declared_typed_sha = _sha("declared-typed")
    declared_v15_sha = _sha("declared-v15")
    declared_v16_sha = _sha("declared-v16")
    validation = {
        "status": "PASS_TYPED_IDENTITY_LIFECYCLE_DEVELOPMENT",
        "typed_shape": {"frames": 401, "particles": 418104},
        "fluid_cohort": {"count": 21114, "identity_sha256": builder.EXPECTED_IDENTITY_SHA,
                          "mass_sum_kg": builder.EXPECTED_DENOMINATOR},
    }
    worker = {
        "schema": builder.WORKER_SCHEMA, "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(product / "worker-request.json"), "sha256": _sha("worker-request")},
        "typed_output": {"path": str(typed), "bytes": typed.stat().st_size,
                          "sha256": declared_typed_sha, "validation": validation},
        "raw_to_typed": {"converter_report": str(converter), "converter_report_sha256": _sha("converter-report"),
                         "raw_evidence": {"expected_raw_tree_sha256": _sha("raw-tree"), "file_count": 405, "frame_count": 401}},
        "typed_to_label": {
            "status": "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN", "result": str(v15),
            "result_sha256": declared_v15_sha,
            "v16_forward": {"status": "COMPLETE_DEVELOPMENT_UNKNOWN", "result": str(v16),
                             "result_sha256": declared_v16_sha},
        },
        "execution_boundary": {"model_invoked": False, "cfd_invoked": False},
        "qualification": dict(builder.UNKNOWN),
    }
    worker["report_sha256"] = builder.canonical_sha(worker)
    worker_path = product / "raw-to-typed-to-label-report-v2.json"
    _write(worker_path, worker)
    engine = {
        "schema": builder.ENGINE_SCHEMA, "status": "COMPLETE_V40_RELOCATED_RAW_TYPED_LABEL",
        "original_current_identity_sha256": builder.ACTUAL_CURRENT_SHA,
        "relocated_current_view": {"path": str(overlay), "sha256": relocated_sha},
        "actual_outputs": {
            "worker_report": {"path": str(worker_path), "sha256": _sha("worker-report-file")},
            "typed_output": {"path": str(typed), "sha256": declared_typed_sha},
            "v16_label_result": {"path": str(v16), "sha256": declared_v16_sha},
        },
    }
    engine["sha256"] = builder.canonical_sha(engine)
    engine_path = product / "v40-engine-integration-report.json"
    _write(engine_path, engine)
    adapter_path = product / "v41-producer-adapter-report-v1.json"
    request_path = product / "v11-proof-request.json"
    return {"contract": contract_path, "worker": worker_path, "engine": engine_path,
            "target": target, "product": product, "adapter": adapter_path, "request": request_path,
            "v16": v16, "declared_v16_sha": declared_v16_sha, "relocated_sha": relocated_sha}


def test_v41_binding_builds_v11_request_without_reading_v16_payload(tmp_path: Path):
    f = _fixture(tmp_path)
    result = builder.build_from_v41(
        v41_worker_report=f["worker"], v40_engine_report=f["engine"], v40_contract=f["contract"],
        target_root=f["target"], output_root=f["product"], adapter_output=f["adapter"],
        request_output=f["request"], max_wall_seconds=300.0, max_result_bytes=100_000_000)
    assert result["status"] == "READY_FOR_PARENT_V11_PROOF_GUARD"
    assert result["result_content_read"] is False
    request = json.loads(f["request"].read_text())
    adapter = json.loads(f["adapter"].read_text())
    assert request["expected"]["source_binding"]["current_catalog_sha256"] == f["relocated_sha"]
    assert request["expected"]["source_binding"]["binding_status"] == builder.RELOCATED_STATUS if hasattr(builder, "RELOCATED_STATUS") else "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND"
    assert request["result"]["sha256"] == f["declared_v16_sha"]
    assert request["v11_forward"]["actual_current_catalog_sha256"] == builder.ACTUAL_CURRENT_SHA
    assert adapter["schema"] == builder.PRODUCER_SCHEMA
    assert adapter["labels"]["v16"]["sha256"] == f["declared_v16_sha"]


def test_builder_rejects_historical_overlay_scope(tmp_path: Path):
    f = _fixture(tmp_path)
    contract = json.loads(f["contract"].read_text())
    contract["expected"]["source_binding"]["current_catalog_sha256"] = builder.HISTORICAL_OVERLAY_SHA
    contract["expected"]["source_binding"]["source_files"]["current_catalog"] = builder.HISTORICAL_OVERLAY_SHA
    contract["current_catalog_provenance"]["relocated_runtime_view"]["sha256"] = builder.HISTORICAL_OVERLAY_SHA
    contract["sha256"] = builder.canonical_sha(contract)
    _write(f["contract"], contract)
    with pytest.raises(builder.V16V4BuilderError, match="distinct relocated"):
        builder.build_from_v41(
            v41_worker_report=f["worker"], v40_engine_report=f["engine"], v40_contract=f["contract"],
            target_root=f["target"], output_root=f["product"], adapter_output=f["adapter"],
            request_output=f["request"])

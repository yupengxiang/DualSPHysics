from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"


def _load():
    spec = importlib.util.spec_from_file_location("f2_proof_consumer_v12_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    else:
        path.write_bytes(value)
    return path


def _fixture(tmp_path: Path):
    v12 = _load()
    result = _write(tmp_path / "producer" / "products" / "v16-result.json", b"opaque V16 fixture")
    current = _write(tmp_path / "CURRENT336.json", b"frozen CURRENT fixture")
    nested_value = {"schema": "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2",
                    "status": "COMPLETE_DEVELOPMENT_UNKNOWN", "metadata_only": True}
    nested_value["report_sha256"] = v12.report_canonical_sha(nested_value)
    nested_path = _write(tmp_path / "producer" / "products" / "nested-report.json", nested_value)
    nested = {"path": str(nested_path), "sha256": v12.sha256_file(nested_path),
              "schema": nested_value["schema"],
              "report_canonical_sha256": nested_value["report_sha256"]}
    sidecar = {
        "schema": v12.SIDECAR_SCHEMA,
        "status": "SOURCE_BOUND_SEMANTIC_CONTRACT",
        "producer_v66_request": {
            "path": str(tmp_path / "v66-request.json"), "file_sha256": "b" * 64,
            "canonical_sha256": "c" * 64, "producer_case_id": "STAGE2_F2_ROOT145_V66",
            "producer_attempt_id": "f2-v66-179c-003",
        },
        "producer_nested_report": nested,
        "v16_result": {"path": str(result), "sha256": "d" * 64, "bytes": result.stat().st_size},
        "current_manifest": {"path": str(current), "sha256": v12.ACTUAL_CURRENT_SHA},
        "missing_scope": v12.ACCEPTED_MISSING_SCOPE,
        "denominator_semantics": v12.ACCEPTED_SCOPE_SEMANTICS,
        "scope_source": {"path": str(tmp_path / "pinned-producer.py"), "sha256": "e" * 64,
                         "missing_scope_literal": v12.ACCEPTED_MISSING_SCOPE},
        "expected": {"identity_key": "(Zone,Idp)", "selected_count": v12.EXPECTED_COUNT,
                     "identity_sha256": v12.EXPECTED_IDENTITY_SHA,
                     "denominator_kg": v12.EXPECTED_DENOMINATOR,
                     "initial_missing_mass_kg": v12.EXPECTED_INITIAL_MISSING,
                     "later_missing_mass_kg": v12.EXPECTED_LATER_MISSING,
                     "later_missing_unique_count": v12.EXPECTED_LATER_MISSING_COUNT},
        "typed_fields": sorted(v12.REQUIRED_TYPED_FIELDS),
        "status_vocabulary": sorted(v12.REQUIRED_STATUS_VOCABULARY),
        "qualification": dict(v12.UNKNOWN),
    }
    sidecar_path = _write(tmp_path / "semantic-sidecar.json", sidecar)
    sidecar["sha256"] = v12.canonical_sha(sidecar)
    sidecar_path.write_text(json.dumps(sidecar, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    request = {
        "schema": v12.REQUEST_SCHEMA,
        "v12_forward": {"schema": v12.FORWARD_SCHEMA,
                        "source_request": {"schema": v12.REQUEST_SCHEMA,
                                            "path": str(tmp_path / "v66-request.json"),
                                            "sha256": "b" * 64, "canonical_sha256": "c" * 64},
                        "semantic_sidecar": {"path": str(sidecar_path),
                                              "sha256": v12.sha256_file(sidecar_path)},},
        "v66_parent_binding": {"producer_case_id": "STAGE2_F2_ROOT145_V66",
                                "producer_attempt_id": "f2-v66-179c-003",
                                "nested_worker_report": nested},
        "result": {"path": str(result), "sha256": "d" * 64, "bytes": result.stat().st_size},
        "current_manifest_binding": {"path": str(current), "sha256": v12.ACTUAL_CURRENT_SHA},
        "expected": {"cohort": {"selected_count": v12.EXPECTED_COUNT,
                                  "identity_key": "(Zone,Idp)",
                                  "identity_sha256": v12.EXPECTED_IDENTITY_SHA},
                    "initial_mass_denominator": {
                        "denominator_kg": v12.EXPECTED_DENOMINATOR,
                        "initial_missing_mass_kg": v12.EXPECTED_INITIAL_MISSING,
                        "later_missing_mass_kg": v12.EXPECTED_LATER_MISSING,
                        "later_missing_unique_count": v12.EXPECTED_LATER_MISSING_COUNT}},
    }
    return v12, request, sidecar_path


def test_exact_v2_spelling_is_normalized_only_in_memory(tmp_path):
    v12, request, sidecar_path = _fixture(tmp_path)
    _, sidecar = v12._json(sidecar_path, "sidecar")
    contract = v12._validate_sidecar(request, sidecar_path, sidecar)
    seen = {}
    old = v12._V8_VALIDATE_RESULT
    v12._ACTIVE_SCOPE = contract

    def fake_validate(result, bound, result_sha, result_bytes):
        seen["scope"] = result["initial_mass_denominator"]["missing_scope"]
        return {"ok": True}

    v12._V8_VALIDATE_RESULT = fake_validate
    try:
        result = {"initial_mass_denominator": {"missing_scope": v12.ACCEPTED_MISSING_SCOPE}}
        assert v12._validate_result_v12(result, {}, "d" * 64, 1)["ok"] is True
        assert "denominator" in seen["scope"]
        assert v12.ACCEPTED_MISSING_SCOPE in seen["scope"]
        assert v12.ACCEPTED_SCOPE_SEMANTICS in seen["scope"]
    finally:
        v12._V8_VALIDATE_RESULT = old
        v12._ACTIVE_SCOPE = None


def test_scope_without_exact_source_binding_is_rejected(tmp_path):
    v12, request, sidecar_path = _fixture(tmp_path)
    _, sidecar = v12._json(sidecar_path, "sidecar")
    sidecar["missing_scope"] = "later missing only"
    sidecar["sha256"] = v12.canonical_sha(sidecar)
    with pytest.raises(v12.V12ProofConsumerError, match="exact producer spelling"):
        v12._validate_sidecar(request, sidecar_path, sidecar)


def test_wrong_nested_schema_cannot_be_promoted_by_the_sidecar(tmp_path):
    v12, request, sidecar_path = _fixture(tmp_path)
    _, sidecar = v12._json(sidecar_path, "sidecar")
    sidecar["producer_nested_report"] = dict(sidecar["producer_nested_report"],
                                              schema="synthetic-v1")
    sidecar["sha256"] = v12.canonical_sha(sidecar)
    with pytest.raises(v12.V12ProofConsumerError, match="real V2 schema"):
        v12._validate_sidecar(request, sidecar_path, sidecar)

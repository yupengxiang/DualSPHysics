from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_request_v67.py"


def _load():
    spec = importlib.util.spec_from_file_location("f2_v67_request_test", SCRIPT)
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


def _source(tmp_path: Path):
    v67 = _load()
    current = _write(tmp_path / "CURRENT336.json", b"current")
    result = _write(tmp_path / "producer" / "products" / "v16-result.json", b"small V16 stat fixture")
    original = tmp_path / "original"
    original.mkdir()
    target = tmp_path / "producer" / "bundle-target"
    output = tmp_path / "producer" / "products"
    target.mkdir(parents=True)
    source = {
        "schema": v67.REQUEST_SCHEMA, "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT", "model_invoked": False, "cfd_invoked": False,
        "quality": dict(v67.UNKNOWN), "ledger_mutated": False,
        "execution": {"max_wall_seconds": 900.0, "max_result_bytes": 1000000,
                       "read_hdf5_or_bi4": False, "raw_opened": False},
        "result": {"path": str(result), "sha256": "d" * 64, "bytes": result.stat().st_size},
        # V66's proof relocation target is the producer output namespace; the
        # fresh ROOT194 namespace is only where the new proof is written.
        "relocation": {"target_root": str(output), "output_root": str(output),
                       "original_roots": [str(original)]},
        "expected": {
            "source_binding": {"current_catalog_sha256": v67.ACTUAL_CURRENT_SHA,
                                "source_files": {"current_catalog": v67.ACTUAL_CURRENT_SHA}},
            "case_identity": {"family_id": "F2", "current_case_index": 78},
            "cohort": {"selected_count": v67.EXPECTED_COUNT, "identity_key": "(Zone,Idp)",
                       "identity_sha256": v67.EXPECTED_IDENTITY_SHA},
            "initial_mass_denominator": {"denominator_kg": v67.EXPECTED_DENOMINATOR,
                                          "initial_missing_mass_kg": v67.EXPECTED_INITIAL_MISSING,
                                          "later_missing_mass_kg": v67.EXPECTED_LATER_MISSING,
                                          "later_missing_unique_count": v67.EXPECTED_LATER_MISSING_COUNT},
            "time": {"first_s": 0.0, "last_s": 4.0, "frame_count": 401,
                     "tolerance_s": 1e-6},
            "observer_fields": [],
            "events": {"status_vocabulary": v67.REQUIRED_STATUS_VOCABULARY,
                        "require_unknown_recross": True, "require_total_net_interval": True,
                        "require_receiver_labels": True},
        },
        "current_manifest_binding": {"path": str(current), "sha256": v67.ACTUAL_CURRENT_SHA},
        "v66_parent_binding": {
            "producer_case_id": "STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C",
            "producer_attempt_id": "f2-v66-root179c-003",
            "request": {"file_sha256": "b" * 64, "canonical_sha256": "c" * 64},
            "nested_worker_report": {"path": str(output / "nested.json"), "sha256": "a" * 64,
                                      "schema": "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2"},
        },
    }
    source["sha256"] = v67.canonical_sha(source)
    source_path = _write(tmp_path / "v66-proof-request.json", source)
    scope_source = _write(tmp_path / "pinned-producer.py",
                           (v67.MISSING_SCOPE + "\n# producer source\n").encode())
    return v67, source_path, scope_source, result


def test_sidecar_and_root194_request_are_source_bound(tmp_path):
    v67, source_path, scope_source, result = _source(tmp_path)
    sidecar_path = tmp_path / "root194-semantic-sidecar.json"
    side = v67.build_semantic_sidecar(source_request=source_path, scope_source=scope_source,
                                      output=sidecar_path)
    assert side["payload_read"] is False
    request_path = tmp_path / "root194-proof-request.json"
    built = v67.build_request(source_request=source_path, semantic_sidecar=sidecar_path,
                              output=request_path,
                              case_id="STAGE2_F2_ROOT194_V67_FRESH_V16_PROOF",
                              attempt_id="f2-root194-v67-fresh-proof-001",
                              fresh_output_root=tmp_path / "root194-output")
    assert built["status"] == "READY_FOR_PARENT_V12_PROOF"
    validated = v67.validate_emitted_request(request_path)
    assert validated["status"] == "V67_METADATA_VALIDATED_READY_FOR_PARENT_PROOF"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["case_id"] != "STAGE2_F2_ROOT190_V66_FRESH_V16_PROOF"
    assert request["v12_forward"]["original_result_missing_scope_preserved"] is True
    assert validated["result"]["content_sha_verified"] is False


def test_sidecar_rejects_root190_identity_and_never_overwrites(tmp_path):
    v67, source_path, scope_source, _ = _source(tmp_path)
    sidecar_path = tmp_path / "sidecar.json"
    v67.build_semantic_sidecar(source_request=source_path, scope_source=scope_source,
                               output=sidecar_path)
    with pytest.raises(v67.V67RequestError, match="historical/root190"):
        v67.build_request(source_request=source_path, semantic_sidecar=sidecar_path,
                          output=tmp_path / "request.json",
                          case_id="STAGE2_F2_ROOT190_REUSE",
                          attempt_id="f2-root194-v67-fresh-proof-001",
                          fresh_output_root=tmp_path / "root194-output")
    with pytest.raises(v67.V67RequestError, match="existing output"):
        v67.build_semantic_sidecar(source_request=source_path, scope_source=scope_source,
                                   output=sidecar_path)

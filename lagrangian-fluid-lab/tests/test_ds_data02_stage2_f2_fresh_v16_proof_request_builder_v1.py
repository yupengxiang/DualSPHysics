from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_fresh_v16_proof_request_builder_v1.py"
SPEC = importlib.util.spec_from_file_location("f2_fresh_v16_request_builder_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict]:
    relocated = tmp_path / "relocated"
    target = relocated / "target"
    output = relocated / "output"
    target.mkdir(parents=True)
    output.mkdir(parents=True)
    result = output / "fresh-v16-result.json"
    result.write_text('{"schema":"ds02.stage2.f2-s1-replay-result.v16"}\n', encoding="utf-8")
    original = tmp_path / "original"
    original.mkdir()
    python_literal = tmp_path / "venv" / "bin" / "python"
    python_literal.parent.mkdir(parents=True)
    python_literal.symlink_to("/bin/sh")

    source_files = {"current_catalog": _sha_text("current"), "generated_xml": _sha_text("xml"),
                    "motion_dat": _sha_text("motion"), "scientific_scan_sidecar": _sha_text("scan")}
    expected = {
        "source_binding": {"binding_status": "FROZEN_SOURCE_METADATA",
                           "current_catalog_sha256": source_files["current_catalog"],
                           "trajectory_h5_producer_sha256": _sha_text("h5"),
                           "source_files": source_files},
        "case_identity": {"family_id": "F2", "physical_case_id": "F2-S1"},
        "cohort": {"selected_count": 1, "identity_key": "(Zone,Idp)",
                   "identity_sha256": _sha_text("0:1")},
        "initial_mass_denominator": {"denominator_kg": 1.0,
                                      "initial_missing_mass_kg": 0.0,
                                      "later_missing_unique_count": 1,
                                      "later_missing_mass_kg": 0.1},
        "time": {"frame_count": 2, "first_s": 0.0, "last_s": 1.0,
                 "tolerance_s": 1e-9, "observer_profile_sha256": _sha_text("profile")},
        "observer_fields": ["mass_weighted_com_m"],
        "events": {"status_vocabulary": sorted(builder.V8.FIRST_PASSAGE_STATUSES),
                   "require_unknown_recross": True, "require_total_net_interval": True,
                   "require_receiver_labels": True, "require_residence_semantics": True},
    }
    contract = {"schema": builder.SOURCE_SCHEMA, "role": "DEVELOPMENT",
                "quality": dict(builder.UNKNOWN), "original_roots": [str(original)],
                "expected": expected}
    contract["sha256"] = builder.canonical_sha(contract)
    contract_path = tmp_path / "source-contract.json"
    _write(contract_path, contract)
    return contract_path, result, target, output, expected


def test_builder_derives_v8_request_without_native_payload_reads(tmp_path: Path) -> None:
    contract, result, target, output, expected = _fixture(tmp_path)
    literal_python = tmp_path / "venv" / "bin" / "python"
    request_path = tmp_path / "fresh-v16-request.json"
    value = builder.build_request(source_contract=contract, result=result,
                                  target_root=target, output_root=output,
                                  output=request_path, python_executable=literal_python)
    assert value["status"] == "READY_FOR_PARENT_V8_PROOF"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["schema"] == builder.REQUEST_SCHEMA
    assert request["expected"] == expected
    assert request["execution"]["python_executable"] == str(literal_python)
    assert request["execution"]["python_invocation_path"] == str(literal_python)
    assert request["execution"]["python_binding"]["resolved_provenance_path"] == str(Path("/bin/sh").resolve())
    assert request["execution"]["read_hdf5_or_bi4"] is False
    assert request["quality"] == builder.UNKNOWN
    assert request["sha256"] == builder.V8.canonical_sha(request)
    bound = builder.V8._validate_request(request, verify_result_stat=True)
    assert bound["result_sha256"] == hashlib.sha256(result.read_bytes()).hexdigest()


def test_builder_rejects_old_result_sha_and_original_output(tmp_path: Path) -> None:
    contract, result, target, output, _ = _fixture(tmp_path)
    old = json.loads(contract.read_text(encoding="utf-8"))
    old["expected"]["source_binding"]["binding_status"] = "FROZEN_SOURCE_METADATA"
    old["sha256"] = builder.canonical_sha(old)
    _write(contract, old)
    result.write_text("old", encoding="utf-8")
    with pytest.raises(builder.V16RequestBuilderError, match="result must exist"):
        builder.build_request(source_contract=contract, result=tmp_path / "missing.json",
                              target_root=target, output_root=output,
                              output=tmp_path / "request.json")
    bad_contract = json.loads(contract.read_text(encoding="utf-8"))
    bad_contract["original_roots"] = [str(output)]
    bad_contract["sha256"] = builder.canonical_sha(bad_contract)
    bad_path = tmp_path / "bad-contract.json"
    _write(bad_path, bad_contract)
    with pytest.raises(builder.V16RequestBuilderError, match="overlap"):
        builder.build_request(source_contract=bad_path, result=result,
                              target_root=target, output_root=output,
                              output=tmp_path / "request2.json")

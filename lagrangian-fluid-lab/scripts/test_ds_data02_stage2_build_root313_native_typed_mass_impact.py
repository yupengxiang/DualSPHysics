from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import ds_data02_stage2_build_root313_native_typed_mass_impact as subject


SPEC = subject.STAGE2 / "requests/root313-native-typed-mass-impact-spec-001/root313-native-typed-mass-impact-proof-spec.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_self_test_and_exact_bundle_contract() -> None:
    result = subject._self_test()
    assert result["status"] == "PASS"
    assert set(subject.EXPECTED_BUNDLES) == {"ROOT258", "ROOT264", "ROOT268"}


def test_actual_source_only_prepare_maps_three_proof_bundles(tmp_path: Path) -> None:
    assert SPEC.is_file()
    prepared = subject.prepare(argparse.Namespace(
        proof_spec=SPEC,
        output_root=tmp_path / "prepared",
        request_output=tmp_path / "request.json",
    ))
    assert prepared["case_count"] == 17
    assert prepared["bundle_ids"] == ["ROOT258", "ROOT264", "ROOT268"]
    assert prepared["payload_content_opened"] is False
    manifest = json.loads(Path(prepared["manifest"]).read_text(encoding="utf-8"))
    assert manifest["producer_proof_merge"]["created"] is False
    assert {ref["path"] for ref in manifest["source_refs"]} >= {
        str(subject.SCRIPT), str(subject.V4_WORKER), str(subject.V3_WORKER),
        str(subject.ROOT270_V2), str(subject.ROOT266_V1),
    }
    per_bundle = {row["bundle_id"]: row for row in manifest["proof_bundles"]}
    assert (per_bundle["ROOT258"]["typed_jsonl_source_bytes"] > 0
            and per_bundle["ROOT264"]["typed_jsonl_source_bytes"] > 0
            and per_bundle["ROOT268"]["typed_jsonl_source_bytes"] > 0)
    assert sum(row["typed_jsonl_source_bytes"] for row in per_bundle.values()) == prepared["typed_jsonl_source_bytes"]
    assert sum(row["typed_jsonl_minimum_three_pass_read_bytes"] for row in per_bundle.values()) == prepared["typed_jsonl_minimum_three_pass_read_bytes"]
    request = json.loads(Path(prepared["request"]).read_text(encoding="utf-8"))
    assert request["command"][1] == str(subject.SCRIPT)
    assert request["input_sha256"][str(subject.ROOT270_V2)] == _sha(subject.ROOT270_V2)
    assert request["input_sha256"][str(subject.ROOT266_V1)] == _sha(subject.ROOT266_V1)


def test_static_manifest_validation_does_not_open_deferred_jsonl(tmp_path: Path) -> None:
    prepared = subject.prepare(argparse.Namespace(
        proof_spec=SPEC,
        output_root=tmp_path / "prepared",
        request_output=tmp_path / "request.json",
    ))
    manifest, cases = subject._validate_manifest(Path(prepared["manifest"]))
    assert manifest["read_policy"]["prepare_opened_jsonl"] is False
    assert len(cases) == 17
    assert all(case["typed_records_deferred"]["read_after_parent_reservation"] is True for case in cases)

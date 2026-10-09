from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_native_typed_mass_impact_v4 as subject


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deferred(path: Path, rows: int) -> dict:
    stat = path.stat()
    return {
        "path": str(path),
        "sha256": _sha(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "rows": rows,
        "deferred": True,
        "content_opened_by_preparer": False,
        "read_after_parent_reservation": True,
    }


def _records(path: Path, case_id: str, idp: int, *, role: str = "fluid", type_code: int = 3) -> dict:
    header = {
        "schema": subject.v3.RECORD_SCHEMA,
        "status": "COMPLETED_TYPED_LIFECYCLE_RECORDS_NO_PHYSICAL_CREDIT",
        "family_id": "F4",
        "physical_case_id": case_id,
        "record_fields": subject.v3.RECORD_FIELDS,
    }
    rows = [
        header,
        {
            "zone": 0,
            "idp": idp,
            "initial_role": role,
            "initial_type_code": type_code,
            "initial_mass_kg": 0.125 if role == "fluid" else 0.5,
            "first_disappeared_frame": 2,
            "first_disappeared_time_s": 1.0,
            "censoring": "OBSERVED_DISAPPEARANCE",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    return _deferred(path, rows=1)


def _native_report(path: Path, case_id: str, idp: int) -> tuple[Path, str]:
    _write_json(path, {
        "physical_case_id": case_id,
        "family_id": "F4",
        "rows": [{
            "zone": 0,
            "idp": idp,
            "first_missing_frame": 2,
            "first_missing_time_s": 1.0,
            "bracket_s": [0.5, 1.0],
            "motive_code": 1,
        }],
    })
    return path, _sha(path)


def _proof(path: Path, rows: list[dict]) -> tuple[Path, str]:
    proof = {
        "schema": subject.v3.root270.PROOF_SCHEMA,
        "status": "VERIFIED_ACTUAL_SOURCE_BOUND_DIAGNOSTIC_ONLY",
        "actual_completed_physical_cases": len(rows),
        "case_verifications": rows,
    }
    _write_json(path, proof)
    return path, _sha(path)


def _bundle(tmp_path: Path, bundle_id: str, case_start: int, count: int) -> tuple[dict, list[str]]:
    rows = []
    case_ids = []
    for offset in range(count):
        case_id = f"{bundle_id}_CASE_{case_start + offset}"
        case_ids.append(case_id)
        records_path = tmp_path / "payload" / f"{case_id}.jsonl"
        deferred = _records(records_path, case_id, case_start + offset)
        report_path, report_sha = _native_report(tmp_path / "reports" / f"{case_id}.json", case_id, case_start + offset)
        rows.append({
            "physical_case_id": case_id,
            "family_id": "F4",
            "report": str(report_path),
            "report_sha256": report_sha,
            "typed_records_stat_SHA_only": deferred,
        })
    proof_path, proof_sha = _proof(tmp_path / "proofs" / f"{bundle_id}.json", rows)
    return {
        "bundle_id": bundle_id,
        "family_id": "F4",
        "proof_path": str(proof_path),
        "proof_sha256": proof_sha,
        "expected_case_count": count,
        "case_ids": case_ids,
    }, case_ids


def _prepare_args(spec: Path, output_root: Path, request: Path) -> argparse.Namespace:
    return argparse.Namespace(proof_spec=spec, output_root=output_root, request_output=request)


def test_prepare_keeps_two_proof_bundles_and_accounts_three_passes(tmp_path: Path) -> None:
    bundle_a, cases_a = _bundle(tmp_path, "ROOT296", 0, 3)
    bundle_b, cases_b = _bundle(tmp_path, "ROOT297", 10, 4)
    spec_path = _write_json(tmp_path / "proof-spec.json", {
        "schema": subject.SPEC_SCHEMA,
        "bundles": [bundle_a, bundle_b],
    })
    result = subject.prepare(_prepare_args(spec_path, tmp_path / "prepared", tmp_path / "request.json"))
    assert result["bundles"] == 2
    assert result["cases"] == 7
    assert result["payload_content_opened"] is False
    assert result["typed_jsonl_minimum_three_pass_read_bytes"] == result["typed_jsonl_source_bytes"] * 3

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert [bundle["bundle_id"] for bundle in manifest["proof_bundles"]] == ["ROOT296", "ROOT297"]
    assert manifest["producer_proof_merge"]["created"] is False
    assert {case["physical_case_id"] for case in manifest["cases"]} == set(cases_a + cases_b)
    assert all(case["proof_bundle_id"] in {"ROOT296", "ROOT297"} for case in manifest["cases"])
    source_paths = {ref["path"] for ref in manifest["source_refs"]}
    assert str(subject.ROOT270_V2) in source_paths
    assert str(subject.ROOT266_V1) in source_paths
    request = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
    assert request["input_sha256"][str(subject.ROOT270_V2)] == _sha(subject.ROOT270_V2)
    assert request["input_sha256"][str(subject.ROOT266_V1)] == _sha(subject.ROOT266_V1)


def test_audit_joins_exact_mass_and_keeps_missing_mass_null(tmp_path: Path) -> None:
    bundle, _ = _bundle(tmp_path, "ROOT296", 0, 1)
    spec_path = _write_json(tmp_path / "proof-spec.json", {"schema": subject.SPEC_SCHEMA, "bundles": [bundle]})
    prepared = subject.prepare(_prepare_args(spec_path, tmp_path / "prepared", tmp_path / "request.json"))
    output = tmp_path / "audit.json"
    result = subject.audit(argparse.Namespace(manifest=Path(prepared["manifest"]), output=output))
    assert result["completed"] == 1
    assert result["failed"] == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    row = report["case_results"][0]
    assert row["proof_bundle_id"] == "ROOT296"
    assert row["selected_typed_initial_mass_sum_kg"] == pytest.approx(0.125)
    assert row["selected_native_ids"][0]["typed_initial_role"] == "fluid"
    assert row["selected_native_ids"][0]["typed_initial_type_code"] == 3
    assert row["role_average_proxy_mass_kg"] is None
    assert report["producer_proof_merge"]["created"] is False
    assert report["resource_accounting"]["typed_jsonl_minimum_three_pass_read_bytes"] == report["resource_accounting"]["typed_jsonl_source_bytes"] * 3


def test_non_fluid_or_non_type3_selected_identity_is_rejected(tmp_path: Path) -> None:
    bundle, _ = _bundle(tmp_path, "ROOT296", 0, 1)
    spec_path = _write_json(tmp_path / "proof-spec.json", {"schema": subject.SPEC_SCHEMA, "bundles": [bundle]})
    prepared = subject.prepare(_prepare_args(spec_path, tmp_path / "prepared", tmp_path / "request.json"))
    manifest = json.loads(Path(prepared["manifest"]).read_text(encoding="utf-8"))
    # Exercise the semantic gate directly without changing any prepared bytes.
    with pytest.raises(subject.MassV4Error, match="fluid/type3"):
        subject._require_fluid_roles({
            "physical_case_id": "FIXTURE",
            "selected_native_ids": [{"typed_initial_role": "fixed", "typed_initial_type_code": 0}],
        })
    assert manifest["claim_boundary"]["role_average_proxy"] == "UNVERIFIED_NOT_USED"


def test_missing_or_incomplete_proof_cannot_create_ready_output(tmp_path: Path) -> None:
    missing_spec = _write_json(tmp_path / "missing-spec.json", {
        "schema": subject.SPEC_SCHEMA,
        "bundles": [{"bundle_id": "ROOT296", "family_id": "F4", "proof_path": str(tmp_path / "missing.json"), "expected_case_count": 3}],
    })
    with pytest.raises(subject.MassV4Error, match="missing"):
        subject.prepare(_prepare_args(missing_spec, tmp_path / "missing-output", tmp_path / "missing-request.json"))
    assert not (tmp_path / "missing-output").exists()

    incomplete = _write_json(tmp_path / "incomplete.json", {
        "schema": subject.v3.root270.PROOF_SCHEMA,
        "status": "FAILED_SOURCE_PRECHECK",
        "actual_completed_physical_cases": 0,
        "case_verifications": [],
    })
    incomplete_spec = _write_json(tmp_path / "incomplete-spec.json", {
        "schema": subject.SPEC_SCHEMA,
        "bundles": [{"bundle_id": "ROOT296", "family_id": "F4", "proof_path": str(incomplete), "proof_sha256": _sha(incomplete), "expected_case_count": 3}],
    })
    with pytest.raises(subject.MassV4Error, match="completed verified proof"):
        subject.prepare(_prepare_args(incomplete_spec, tmp_path / "incomplete-output", tmp_path / "incomplete-request.json"))
    assert not (tmp_path / "incomplete-output").exists()

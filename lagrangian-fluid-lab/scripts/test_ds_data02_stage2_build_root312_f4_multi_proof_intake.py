from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_root312_f4_multi_proof_intake as subject


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(tmp_path: Path, bundle_id: str, start: int, count: int) -> Path:
    rows = []
    for offset in range(count):
        case_id = f"{bundle_id}_CASE_{start + offset}"
        report_path = _write(tmp_path / "reports" / f"{case_id}.json", {
            "physical_case_id": case_id,
            "family_id": "F4",
            "status": "COMPLETED_SAVED_FRAME_DIAGNOSTIC_ONLY",
        })
        rows.append({
            "physical_case_id": case_id,
            "family_id": "F4",
            "report": str(report_path),
            "report_sha256": _sha(report_path),
        })
    proof = _write(tmp_path / "proofs" / f"{bundle_id}.json", {
        "schema": subject.PROOF_SCHEMA,
        "status": "VERIFIED_ACTUAL_SOURCE_BOUND_DIAGNOSTIC_ONLY",
        "actual_completed_physical_cases": count,
        "case_verifications": rows,
    })
    return proof


def _args(proof_a: Path, proof_b: Path, output_root: Path, request: Path) -> argparse.Namespace:
    return argparse.Namespace(proof_a=proof_a, proof_b=proof_b, output_root=output_root, request_output=request)


def test_prepare_preserves_two_completed_proofs_without_merging(tmp_path: Path) -> None:
    proof_a = _bundle(tmp_path, "ROOT296", 0, 3)
    proof_b = _bundle(tmp_path, "ROOT297", 10, 4)
    result = subject.prepare(_args(proof_a, proof_b, tmp_path / "prepared", tmp_path / "request.json"))
    assert result["bundles"] == 2
    assert result["cases"] == 7
    assert result["producer_proof_merge_created"] is False
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert [item["bundle_id"] for item in manifest["proof_bundles"]] == ["ROOT296", "ROOT297"]
    assert [item["case_count"] for item in manifest["proof_bundles"]] == [3, 4]
    assert manifest["producer_proof_merge"]["created"] is False
    assert {case["bundle_id"] for case in manifest["cases"]} == {"ROOT296", "ROOT297"}

    output = tmp_path / "audit.json"
    audited = subject.audit(argparse.Namespace(manifest=Path(result["manifest"]), output=output))
    assert audited["bundles"] == 2
    assert audited["cases"] == 7
    report = json.loads(output.read_text(encoding="utf-8"))
    assert [item["bundle_id"] for item in report["producer_proof_bundles"]] == ["ROOT296", "ROOT297"]
    assert report["producer_proof_merge"]["created"] is False


def test_missing_or_incomplete_future_proof_does_not_create_ready_output(tmp_path: Path) -> None:
    complete = _bundle(tmp_path, "ROOT296", 0, 3)
    missing = tmp_path / "ROOT297-not-yet-available.json"
    with pytest.raises(subject.Root312Error, match="missing"):
        subject.prepare(_args(complete, missing, tmp_path / "missing-prepared", tmp_path / "missing-request.json"))
    assert not (tmp_path / "missing-prepared").exists()
    assert not (tmp_path / "missing-request.json").exists()

    incomplete = _write(tmp_path / "incomplete.json", {
        "schema": subject.PROOF_SCHEMA,
        "status": "FAILED_SOURCE_PRECHECK",
        "actual_completed_physical_cases": 0,
        "case_verifications": [],
    })
    with pytest.raises(subject.Root312Error, match="completed verified proof"):
        subject.prepare(_args(complete, incomplete, tmp_path / "incomplete-prepared", tmp_path / "incomplete-request.json"))
    assert not (tmp_path / "incomplete-prepared").exists()


def test_duplicate_case_across_producer_proofs_is_rejected(tmp_path: Path) -> None:
    proof_a = _bundle(tmp_path, "ROOT296", 0, 3)
    proof_b = _bundle(tmp_path, "ROOT297", 10, 4)
    value = json.loads(proof_b.read_text(encoding="utf-8"))
    value["case_verifications"][0]["physical_case_id"] = "ROOT296_CASE_0"
    report_path = Path(value["case_verifications"][0]["report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["physical_case_id"] = "ROOT296_CASE_0"
    _write(report_path, report)
    value["case_verifications"][0]["report_sha256"] = _sha(report_path)
    _write(proof_b, value)
    with pytest.raises(subject.Root312Error, match="overlap"):
        subject.prepare(_args(proof_a, proof_b, tmp_path / "overlap-prepared", tmp_path / "overlap-request.json"))
    assert not (tmp_path / "overlap-prepared").exists()


def test_self_test_is_payload_free() -> None:
    result = subject._self_test()
    assert result["status"] == "PASS"
    assert "no merged proof" in result["checks"]

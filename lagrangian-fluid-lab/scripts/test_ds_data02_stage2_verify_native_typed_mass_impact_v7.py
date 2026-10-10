from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_verify_native_typed_mass_impact_v7 as subject


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(path: Path) -> dict:
    st = path.stat()
    return {
        "path": str(path.resolve()), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
        "ctime_ns": st.st_ctime_ns, "st_dev": st.st_dev, "st_ino": st.st_ino,
        "sha256": _sha(path),
    }


def _make_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    case_id = "F4_FIXTURE_MASS_V4"
    typed = tmp_path / "deferred" / f"{case_id}.jsonl"
    typed.parent.mkdir(parents=True)
    # The verifier must not open this deferred payload.  Its stat/SHA contract
    # is copied into the producer proof and result as if a parent had audited it.
    typed.write_bytes(b"deferred-payload-content\n")
    typed_ref = {**_ref(typed), "rows": 2, "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
    report_path = tmp_path / "reports" / f"{case_id}.json"
    report_path.parent.mkdir(parents=True)
    report = {
        "schema": "ds02.stage2.generic-native-extract-report.v1",
        "status": "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY",
        "physical_case_id": case_id, "family_id": "F4",
        "rows": [
            {"identity_key": [0, 10], "zone": 0, "idp": 10, "motive_code": 1, "first_missing_frame": 2, "first_missing_time_s": 1.0, "bracket_s": [0.5, 1.0]},
            {"identity_key": [0, 11], "zone": 0, "idp": 11, "motive_code": 1, "first_missing_frame": 3, "first_missing_time_s": 1.5, "bracket_s": [1.0, 1.5]},
        ],
    }
    report_path.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    report_ref = _ref(report_path)
    proof_path = tmp_path / "proof.json"
    proof = {
        "schema": subject.ROOT_PROOF_SCHEMA,
        "status": "VERIFIED_ACTUAL_GENERIC_NATIVE_DIAGNOSTIC_ONLY",
        "actual_completed_physical_cases": 1,
        "case_verifications": [{
            "physical_case_id": case_id, "family_id": "F4", "report": str(report_path.resolve()), "report_sha256": report_ref["sha256"],
            "typed_records_stat_SHA_only": typed_ref,
        }],
    }
    proof_path.write_text(json.dumps(proof, sort_keys=True) + "\n", encoding="utf-8")
    proof_ref = _ref(proof_path)
    case = {
        "physical_case_id": case_id, "family_id": "F4", "proof_bundle_id": "ROOT264",
        "producer_proof": proof_ref, "native_report": report_ref,
        "selected_native_ids": [
            {"identity_key": [0, 10], "zone": 0, "idp": 10, "native_motive_code": 1, "native_first_missing_frame": 2, "native_first_missing_time_s": 1.0, "native_saved_bracket_s": [0.5, 1.0]},
            {"identity_key": [0, 11], "zone": 0, "idp": 11, "native_motive_code": 1, "native_first_missing_frame": 3, "native_first_missing_time_s": 1.5, "native_saved_bracket_s": [1.0, 1.5]},
        ],
        "selected_native_id_count": 2, "typed_records_deferred": typed_ref,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "schema": "ds02.stage2.native-typed-mass-impact.root313-manifest",
        "status": "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_ROOT313",
        "producer_proof_merge": {"created": False},
        "proof_bundles": [{"bundle_id": "ROOT264", "family_id": "F4", "proof": proof_ref, "case_count": 1}],
        "cases": [case],
        "source_refs": [proof_ref, report_ref],
        "resource_policy": {"typed_jsonl_source_bytes": typed_ref["bytes"]},
    }
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    pre = {k: typed_ref[k] for k in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")}
    result_path = tmp_path / "result.json"
    result = {
        "schema": "ds02.stage2.native-typed-mass-impact.root313-report",
        "status": "COMPLETED_ROOT313_NATIVE_TYPED_MASS_IMPACT_DIAGNOSTIC_ONLY",
        "counts": {"requested": 1, "completed": 1, "failed": 0},
        "case_results": [{
            "physical_case_id": case_id, "status": "COMPLETED_SELECTED_NATIVE_TYPED_INITIAL_MASS_DIAGNOSTIC_ONLY",
            "selected_native_id_count": 2,
            "selected_native_ids": [
                {**case["selected_native_ids"][0], "typed_initial_mass_kg": 0.125, "typed_mass_status": "EXACT_TYPED_JSONL_INITIAL_MASS", "typed_initial_role": "fluid", "typed_initial_type_code": 3},
                {**case["selected_native_ids"][1], "typed_initial_mass_kg": None, "typed_mass_status": "UNKNOWN_MISSING_TYPED_INITIAL_MASS", "typed_initial_role": "fluid", "typed_initial_type_code": 3},
            ],
            "typed_records": {"path": typed_ref["path"], "rows": 2, "pre_stat": pre, "post_stat": pre, "pre_sha256": typed_ref["sha256"], "stream_sha256": typed_ref["sha256"], "post_sha256": typed_ref["sha256"], "hash_passes": 3},
            "selected_typed_initial_mass_sum_kg": None, "selected_typed_initial_mass_status": "UNKNOWN_AT_LEAST_ONE_SELECTED_ROW_MASS_MISSING",
            "role_average_proxy_mass_kg": None, "role_average_proxy_status": "UNVERIFIED_NOT_USED_AS_PER_ID_MASS",
        }],
        "claim_boundary": {"physical_mass_flux": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    result_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path, result_path, typed


def test_independent_verifier_checks_exact_or_null_mass_without_opening_jsonl(tmp_path: Path) -> None:
    manifest, result, deferred = _make_fixture(tmp_path)
    output = tmp_path / "verification.json"
    value = subject.verify(argparse.Namespace(manifest=manifest, result=result, output=output))
    assert value["status"] == "PASS_SOURCE_IDENTITY_STAT_ONLY"
    assert value["deferred_jsonl_content_opened"] is False
    assert json.loads(output.read_text(encoding="utf-8"))["case_verifications"][0]["missing_selected_mass_rows"] == 1
    assert deferred.read_bytes() == b"deferred-payload-content\n"


def test_independent_verifier_rejects_duplicate_result_identity(tmp_path: Path) -> None:
    manifest, result, _ = _make_fixture(tmp_path)
    value = json.loads(result.read_text(encoding="utf-8"))
    value["case_results"][0]["selected_native_ids"][1]["identity_key"] = [0, 10]
    result.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(subject.VerificationError, match="not unique"):
        subject.verify(argparse.Namespace(manifest=manifest, result=result, output=tmp_path / "bad.json"))


def test_independent_verifier_rejects_non_fluid_typed_role(tmp_path: Path) -> None:
    manifest, result, _ = _make_fixture(tmp_path)
    value = json.loads(result.read_text(encoding="utf-8"))
    value["case_results"][0]["selected_native_ids"][0]["typed_initial_role"] = "fixed"
    result.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(subject.VerificationError, match="fluid/type3"):
        subject.verify(argparse.Namespace(manifest=manifest, result=result, output=tmp_path / "bad.json"))


def test_v7_captured_file_must_have_stable_stat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "small.json"
    path.write_text("{}\n", encoding="utf-8")
    original_stat = subject._stat
    calls = 0

    def changing_stat(value: Path, label: str) -> dict:
        nonlocal calls
        calls += 1
        result = original_stat(value, label)
        if calls == 2:
            result["mtime_ns"] += 1
        return result

    monkeypatch.setattr(subject, "_stat", changing_stat)
    with pytest.raises(subject.VerificationError, match="changed during capture"):
        subject._capture_bytes(path, "race fixture", limit=1024)


def test_v7_rejects_result_native_field_tamper(tmp_path: Path) -> None:
    manifest, result, _ = _make_fixture(tmp_path)
    value = json.loads(result.read_text(encoding="utf-8"))
    value["case_results"][0]["selected_native_ids"][0]["native_motive_code"] = 99
    result.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(subject.VerificationError, match="result/native motive"):
        subject.verify(argparse.Namespace(manifest=manifest, result=result, output=tmp_path / "bad.json"))


def test_v7_rejects_deferred_stat_tamper_without_opening_payload(tmp_path: Path) -> None:
    manifest, result, deferred = _make_fixture(tmp_path)
    stat = deferred.stat()
    os.utime(deferred, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000))
    with pytest.raises(subject.VerificationError, match="deferred typed records"):
        subject.verify(argparse.Namespace(manifest=manifest, result=result, output=tmp_path / "bad.json"))


def test_v7_rejects_duplicate_manifest_case_and_unbalanced_terminal_status(tmp_path: Path) -> None:
    manifest, result, _ = _make_fixture(tmp_path)
    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_value["cases"].append(manifest_value["cases"][0])
    manifest.write_text(json.dumps(manifest_value, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(subject.VerificationError, match="manifest case identities are not unique"):
        subject.verify(argparse.Namespace(manifest=manifest, result=result, output=tmp_path / "bad-duplicate.json"))

    manifest, result, _ = _make_fixture(tmp_path / "status")
    result_value = json.loads(result.read_text(encoding="utf-8"))
    result_value["status"] = "FAILED"
    result.write_text(json.dumps(result_value, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(subject.VerificationError, match="terminal status"):
        subject.verify(argparse.Namespace(manifest=manifest, result=result, output=tmp_path / "status" / "bad.json"))

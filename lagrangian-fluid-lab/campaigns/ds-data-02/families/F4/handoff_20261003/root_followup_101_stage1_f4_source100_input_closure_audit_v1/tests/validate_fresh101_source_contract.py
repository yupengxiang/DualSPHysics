#!/usr/bin/env python3
"""Validate the fresh101 non-scientific input closure audit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def assert_no_payload_digest(value: Any, where: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            low = str(key).lower()
            if any(token in low for token in ("h5", "hdf", "bi4", "csv", "vtk", "dat")):
                if low.endswith("sha256") or low.endswith("_hash"):
                    raise AssertionError(f"scientific digest leaked at {where}.{key}")
            assert_no_payload_digest(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_payload_digest(child, f"{where}[{index}]")


def main() -> None:
    source = load(PACKAGE / "source-binding.json")
    assert source["source100_commit"] == "1bb52632bc2feffc95baf21cefcbdb2de31720bb"
    assert source["requests_audited"] == 24
    assert source["source100_unchanged"] is True
    assert source["scientific_payloads_skipped"] is True
    assert source["root_owned_application_required"] is True

    audit = load(PACKAGE / "evidence/source100-input-closure-audit.json")
    assert len(audit["cases"]) == 24
    assert audit["audit_summary"]["requests_audited"] == 24
    assert audit["audit_summary"]["scientific_payloads_read_or_hashed"] is False
    assert audit["jobs_started_by_source"] is False
    assert audit["shared_registry_write_by_source"] is False
    assert audit["repair_candidate_count"] == 2
    mismatch_cases = {row["case_id"] for row in audit["cases"] if row["non_scientific_mismatch_count"]}
    assert mismatch_cases == {
        "F4_DROP_gap0p24000_xoffm0p08000_yoff0p04000_uz0p60000",
        "F4_DROP_gap0p24000_xoffm0p08000_yoffm0p04000_uz0p40000",
    }
    for row in audit["cases"]:
        assert row["all_non_scientific_input_digests_recomputed"] is True
        assert row["source_did_not_read_or_hash_scientific_payload"] is True
        assert row["non_scientific_mismatch_count"] == len(row["mismatches"])
        assert row["root561_review"] is not None
        for checked in row["checked_non_scientific_inputs"]:
            assert Path(checked["path"]).suffix.lower() not in RAW_SUFFIXES
            assert checked["status"] in {"match", "mismatch", "missing"}
            if checked["status"] == "match":
                assert checked["expected_sha256"] == checked["actual_sha256"]
        for candidate in row["repair_candidates"]:
            assert candidate["input_path"].endswith("/execution-receipt.json")
            assert candidate["actual_status"] == "completed"
            assert candidate["actual_returncode"] == 0
            assert candidate["actual_after_sha256"] == candidate["root547_manifest_typed_receipt_sha256"]
            assert candidate["before_sha256"] != candidate["actual_after_sha256"]
        assert row["root547_manifest"]["frames"] == 1201
        assert row["root547_manifest"]["particles"] == 83233
        assert row["root547_manifest"]["expected_dimension"] == 3
        assert row["root561_review"]["actual_full1201_N3"] is True
        assert row["root561_review"]["original_lifecycle_exclusions_retained_no_padding"] is True
        assert row["root561_review"]["source_and_legacy_converter_scope_remain_separate"] is True
        assert_no_payload_digest(row, row["case_id"])

    checklist = load(PACKAGE / "metadata/receipt-sha-repair-checklist.json")
    assert checklist["no_source_request_mutated"] is True
    assert checklist["no_jobs_started"] is True
    assert checklist["scientific_payload_read_or_hashed"] is False
    assert len(checklist["repair_candidates"]) == 2
    assert_no_payload_digest(checklist)

    print("fresh101 static contract: PASS")
    print(json.dumps({
        "requests_audited": 24,
        "non_scientific_receipt_repairs": 2,
        "scientific_payloads_read_or_hashed": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

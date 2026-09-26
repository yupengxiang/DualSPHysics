from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_execution_readiness_audit_v8 as audit


def test_v8_binds_complete_selector_partition_and_keeps_policy_blocked() -> None:
    value = audit.build_audit()
    selector = value["selector_domain"]
    assert value["schema"] == audit.SCHEMA
    assert value["status"] == "static_selector_domain_bound_full_runtime_readiness_blocked"
    assert selector["raw_nr_partition_complete"] is True
    assert selector["raw_nr_minimum"] == -(1 << 31)
    assert selector["raw_nr_maximum"] == (1 << 31) - 1
    assert selector["native_table_rows"] == 462
    assert selector["native_per_number_dispositions_complete"] is False
    assert selector["native_per_number_predicates_complete"] is False
    assert selector["x32_runtime_rejection_verified"] is False
    assert selector["nr_minus_one_is_attributable_to_tracer_from_selector_alone"] is False
    codes = {item["code"] for item in value["blocking_gaps"]}
    assert audit.EXPECTED_V7_GAPS <= codes
    assert "native_syscall_per_number_policy_and_target_pin_missing" in codes
    assert "ptrace_seccomp_selector_runtime_conformance_missing" in codes


def test_v8_zero_credit_and_execution_authority_remain_closed() -> None:
    value = audit.build_audit()
    assert value["readiness_pass"] is False
    assert value["full_t1_decision"] is False
    assert value["T1_numerical"] is False
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert all(item is False or item == 0 for item in value["execution_authority"].values())
    assert all(item is False or item == 0 for item in value["execution_controls"].values())


def test_v8_transitive_evidence_binds_v7_selector_and_source_baseline() -> None:
    value = audit.build_audit()
    evidence = {item["path"]: item for item in value["evidence"]}
    required = {
        audit.V7_RECEIPT.as_posix(),
        "reports/F8-R008-SYSCALL-SELECTOR-DOMAIN-V1.json",
        "scripts/f8_r008_syscall_selector_domain_v1.py",
        "tests/test_f8_r008_syscall_selector_domain_v1.py",
        "reports/F8-R008-SYSCALL-UNIVERSE-LINUX-V6.8-X86_64-BASELINE-V1.json",
        "scripts/f8_r008_syscall_universe_baseline_v1.py",
        "tests/test_f8_r008_syscall_universe_baseline_v1.py",
        "scripts/f8_r008_execution_readiness_audit_v8.py",
        "tests/test_f8_r008_execution_readiness_audit_v8.py",
    }
    assert required <= set(evidence)
    assert len(evidence) == len(value["evidence"])
    assert all(type(item["bytes"]) is int and item["bytes"] > 0 and len(item["sha256"]) == 64 for item in evidence.values())
    assert value["supersedes"]["sha256"] == evidence[audit.V7_RECEIPT.as_posix()]["sha256"]


def test_v8_receipt_roundtrip_and_tampering_rejection(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    target.write_text(json.dumps(audit.build_audit()), encoding="utf-8")
    assert audit.verify_audit(target)["record_id"] == audit.RECORD_ID
    value = json.loads(target.read_text(encoding="utf-8"))
    value["selector_domain"]["runtime_conformance_passed"] = True
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(audit.ReadinessAuditError, match="no longer matches its pinned evidence"):
        audit.verify_audit(target)


def test_v8_receipt_reader_rejects_duplicate_keys_and_nonfinite_constants(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    for payload, message in (
        (b'{"schema":"one","schema":"two"}', "duplicate JSON key"),
        (b'{"schema":NaN}', "non-standard JSON constant"),
        (b'{"schema":Infinity}', "non-standard JSON constant"),
    ):
        target.write_bytes(payload)
        with pytest.raises(audit.ReadinessAuditError, match=message):
            audit.verify_audit(target)


def test_v8_bounded_reader_rejects_traversal_and_oversize_receipts(tmp_path: Path) -> None:
    traversal = f"{tmp_path}/../{tmp_path.name}/missing.json"
    with pytest.raises(audit.ReadinessAuditError, match="absolute receipt path must be canonical"):
        audit.verify_audit(traversal)

    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.truncate(audit.MAX_RECEIPT_BYTES + 1)
    with pytest.raises(audit.ReadinessAuditError, match="32 MiB read limit"):
        audit.verify_audit(oversized)


def test_v8_fixed_receipt_verifies_and_public_writer_refuses_overwrite() -> None:
    assert audit.verify_audit()["record_id"] == audit.RECORD_ID
    with pytest.raises(FileExistsError):
        audit.write_audit()

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_execution_readiness_audit_v7 as audit


def test_v7_binds_v18_and_static_fanotify_profiles_without_readiness() -> None:
    value = audit.build_audit()
    assert value["schema"] == audit.SCHEMA
    assert value["status"] == "static_terminal_fanotify_profiles_reviewed_runtime_readiness_blocked"
    profile = value["terminal_fanotify_profile_verification"]
    assert profile["pidfd_required_for_both_groups"] is True
    assert profile["target_abi_raw_values_pinned"] is False
    assert profile["pinned_kernel_conformance_passed"] is False
    assert value["predecessor_v6"]["receipt_preserved"] is True
    codes = {item["code"] for item in value["blocking_gaps"]}
    assert "trusted_worker_execution_source_and_runtime_identity_missing" in codes
    assert "terminal_fanotify_profiles_lack_pinned_kernel_runtime_conformance" in codes
    assert "trusted_terminal_supervisor_and_final_fput_observer_missing" in codes


def test_v7_zero_credit_and_no_runtime_or_privileged_actions() -> None:
    value = audit.build_audit()
    assert value["readiness_pass"] is False
    assert value["full_t1_decision"] is False
    assert value["T1_numerical"] is False
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert all(item is False or item == 0 for item in value["execution_authority"].values())
    assert all(item is False or item == 0 for item in value["execution_controls"].values())


def test_v7_transitive_evidence_binds_v17_v18_manifest_verifier_and_predecessor() -> None:
    value = audit.build_audit()
    evidence = {item["path"]: item for item in value["evidence"]}
    required = {
        audit.V6_RECEIPT.as_posix(),
        audit.V17.as_posix(),
        audit.V18.as_posix(),
        audit.PROFILE_MANIFEST.as_posix(),
        "scripts/f8_r008_terminal_fanotify_profile_verifier_v1.py",
        "tests/test_f8_r008_terminal_fanotify_profile_verifier_v1.py",
        "scripts/f8_r008_execution_readiness_audit_v7.py",
        "tests/test_f8_r008_execution_readiness_audit_v7.py",
    }
    assert required <= set(evidence)
    assert all(len(item["sha256"]) == 64 and item["bytes"] > 0 for item in evidence.values())
    assert len(evidence) == len(value["evidence"])
    assert value["supersedes"]["sha256"] == evidence[audit.V6_RECEIPT.as_posix()]["sha256"]


def test_v7_writer_is_immutable_and_verifier_detects_tampering(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    with pytest.raises(TypeError):
        audit.write_audit(target)
    assert audit._write_test_receipt(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == audit.verify_audit(target)
    with pytest.raises(FileExistsError, match="immutable R008 execution-readiness audit v7"):
        audit._write_test_receipt(target)
    receipt = json.loads(target.read_text(encoding="utf-8"))
    receipt["readiness_pass"] = True
    target.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(audit.ReadinessAuditError, match="no longer matches its pinned evidence"):
        audit.verify_audit(target)


def test_v7_rejects_absolute_traversal_and_symlinked_evidence_paths(tmp_path: Path) -> None:
    with pytest.raises(audit.ReadinessAuditError, match="canonical and beneath"):
        audit._read_beneath_lab("/etc/passwd")
    with pytest.raises(audit.ReadinessAuditError, match="canonical and beneath"):
        audit._read_beneath_lab("../outside.json")

    real = tmp_path / "real"
    real.mkdir()
    (real / "receipt.json").write_text("{}", encoding="utf-8")
    (tmp_path / "alias").symlink_to(real, target_is_directory=True)
    with pytest.raises(audit.ReadinessAuditError, match="pinned root"):
        audit._read_from_root(tmp_path, ("alias", "receipt.json"), "alias/receipt.json")

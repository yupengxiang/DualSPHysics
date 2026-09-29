from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f3_graph_raw_hidden16_diagnostic_admission_v3_security_reaudit_v1 as audit


def test_reaudit_is_source_bound_blocked_and_zero_credit() -> None:
    report = audit.build_audit_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is True
    assert report["readiness"]["readiness_pass"] is False
    assert report["readiness"]["launch_allowed"] is False
    assert report["readiness"]["independent_terminal_proof"] is False
    assert report["readiness"]["popen_wait_observed"] == "0/0"
    assert report["side_effects"]["popen_attempts"] == 0
    assert report["side_effects"]["wait_attempts"] == 0
    assert report["side_effects"]["nvidia_smi_invocations"] == 0
    assert report["side_effects"]["gpu_used_for_execution"] is False
    assert report["side_effects"]["processes_started"] == 0
    assert report["side_effects"]["source_files_written"] == 0
    assert report["credit"] == 0
    assert report["formal"] is False


def test_scope_is_locked_to_requested_p1_fix_commits_and_no_import_execution() -> None:
    report = audit.build_audit_report()
    assert tuple(report["scope"]["audited_commits"]) == audit.AUDITED_COMMITS
    assert report["scope"]["no_audited_module_import"] is True
    assert report["scope"]["no_popen_or_wait"] is True
    assert report["scope"]["no_gpu_or_nvidia_smi"] is True
    assert "subprocess" not in audit.__dict__


def test_source_inventory_is_regular_single_link_and_hash_bound() -> None:
    report = audit.build_audit_report()
    assert len(report["audited_files"]) == len(audit.AUDITED_FILES)
    for item in report["audited_files"]:
        assert item["content_opened"] is True
        assert item["bytes"] > 0
        assert len(item["sha256"]) == audit.SHA256_HEX
        assert item["nlink"] == 1
        assert ".." not in Path(item["path"]).parts


def test_replay_owner_and_nonce_controls_are_local_but_external_authority_is_missing() -> None:
    checks = audit.build_audit_report()["static_checks"]
    assert checks["local_atomic_one_shot"] is True
    assert checks["owner_inode_nonce_binding"] is True
    assert checks["external_replay_authority"] is False
    assert checks["external_owner_attestation"] is False
    assert checks["caller_supplied_resource_snapshot"] is True


def test_path_hardening_distinguishes_stable_reads_from_remaining_toc_tou_gaps() -> None:
    report = audit.build_audit_report()
    checks = report["static_checks"]
    assert checks["admission_stable_fd_reads"] is True
    assert checks["runner_stable_fd_artifact_reads"] is True
    assert checks["launcher_path_based_preflight_reader"] is True
    assert checks["admission_cross_binds_launcher_training_file_digest"] is False
    assert checks["runner_output_atomic_reservation_before_popen"] is False
    assert report["control_matrix"]["full_path_toc_tou"]["verdict"] == "P1_blocked"


def test_symlink_hardlink_and_hdf5_link_controls_are_present() -> None:
    report = audit.build_audit_report()
    checks = report["static_checks"]
    assert checks["admission_stable_fd_reads"] is True
    assert checks["runner_stable_fd_artifact_reads"] is True
    assert checks["hdf5_nonhard_and_vds_rejection"] is True
    assert checks["hdf5_external_storage_rejection"] is False
    matrix = report["control_matrix"]["symlink_hardlink_external_vds"]
    assert matrix["hdf5_nonhard_and_vds_rejected"] is True
    assert matrix["hdf5_external_storage_rejected"] is False


def test_gpu_mapping_shape_is_bound_but_live_and_child_attestation_are_absent() -> None:
    report = audit.build_audit_report()
    checks = report["static_checks"]
    assert checks["gpu_uuid_pci_logical_shape_bound"] is True
    assert checks["gpu_probe_emits_uuid_pci_identity"] is False
    assert checks["child_runtime_gpu_attestation"] is False
    assert report["control_matrix"]["gpu_uuid_pci_logical_mapping"]["verdict"] == "P1_blocked"


def test_environment_executable_and_sealed_witness_controls_are_non_authorizing() -> None:
    report = audit.build_audit_report()
    checks = report["static_checks"]
    assert checks["allowlisted_environment_digest"] is True
    assert checks["executable_content_and_runtime_identity"] is True
    assert checks["sealed_real_popen_wait_witness"] is True
    matrix = report["control_matrix"]
    assert matrix["environment_executable_identity"]["verdict"] == "closed_locally_pending_external_trust_anchor"
    assert matrix["sealed_real_popen_wait"]["capability_admitted"] is False
    assert matrix["sealed_real_popen_wait"]["terminal_proof_observed"] is False


def test_formal_credit_isolation_remains_zero_but_report_binding_has_p2() -> None:
    report = audit.build_audit_report()
    checks = report["static_checks"]
    assert checks["formal_credit_isolation"] is True
    assert checks["terminal_report_receipt_identity_bound"] is False
    ids = {item["id"] for item in report["findings"]}
    assert "F3-DAV3-SA-006" in ids
    assert report["control_matrix"]["formal_credit_isolation"]["verdict"] == "P2_report_binding_gap"


def test_expected_p1_p2_findings_are_explicit() -> None:
    report = audit.build_audit_report()
    findings = {item["id"]: item for item in report["findings"]}
    assert set(findings) == {
        "F3-DAV3-SA-001",
        "F3-DAV3-SA-002",
        "F3-DAV3-SA-003",
        "F3-DAV3-SA-004",
        "F3-DAV3-SA-005",
        "F3-DAV3-SA-006",
        "F3-DAV3-SA-007",
    }
    assert all(item["current_status"] == "blocked_fail_closed" for item in findings.values())
    assert sum(item["severity"] == "P1" for item in findings.values()) == 6
    assert sum(item["severity"] == "P2" for item in findings.values()) == 1


def test_dangerous_existing_job_control_calls_are_absent() -> None:
    report = audit.build_audit_report()
    assert all(not calls for calls in report["static_checks"]["dangerous_process_control_calls"].values())


def test_report_verifier_rejects_promotion_or_tampering() -> None:
    report = audit.build_audit_report()
    assert audit.validate_audit_report(report) == []

    promoted = deepcopy(report)
    promoted["readiness"]["launch_allowed"] = True
    assert audit.validate_audit_report(promoted)

    tampered = deepcopy(report)
    tampered["side_effects"]["popen_attempts"] = 1
    assert audit.validate_audit_report(tampered)


def test_cli_report_verify_is_read_only(tmp_path: Path) -> None:
    report = audit.build_audit_report()
    path = tmp_path / "reaudit.json"
    path.write_text(audit.json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    assert audit.main(["--verify-report", str(path)]) == 0


@pytest.mark.parametrize("forbidden", ["kill", "killpg", "terminate", "send_signal", "pkill", "systemctl", "reboot"])
def test_reaudit_source_contract_reports_no_process_control_calls(forbidden: str) -> None:
    calls = audit.build_audit_report()["static_checks"]["dangerous_process_control_calls"]
    assert all(forbidden not in values for values in calls.values())

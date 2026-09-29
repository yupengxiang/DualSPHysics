from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f3_graph_raw_hidden16_diagnostic_admission_v2_security_audit_v1 as audit


def test_build_report_is_blocked_zero_credit_and_read_only() -> None:
    report = audit.build_audit_report()
    assert report["status"] == "blocked_fail_closed"
    assert report["v2_admission"]["safe_to_upgrade_now"] is False
    assert report["v2_admission"]["launch_allowed"] is False
    assert report["v2_admission"]["required_blocker_count"] >= 8
    assert report["side_effects"]["processes_started"] == 0
    assert report["side_effects"]["popen_attempts"] == 0
    assert report["side_effects"]["nvidia_smi_invocations"] == 0
    assert report["side_effects"]["gpu_used_for_execution"] is False
    assert report["side_effects"]["processes_stopped"] == 0
    assert report["side_effects"]["processes_restarted"] == 0
    assert report["credit"] == 0
    assert report["formal"] is False


def test_source_inventory_is_bound_to_regular_single_link_files() -> None:
    report = audit.build_audit_report()
    assert len(report["audited_files"]) == len(audit.AUDITED_FILES)
    for item in report["audited_files"]:
        assert item["content_opened"] is True
        assert item["bytes"] > 0
        assert len(item["sha256"]) == audit.SHA256_HEX
        assert item["nlink"] == 1
        assert "../" not in item["path"]


def test_expected_v1_deny_gates_are_observed() -> None:
    checks = audit.build_audit_report()["static_checks"]
    assert checks["runner_execute_capability_is_uninstalled"] is True
    assert checks["production_validator_capability_is_uninstalled"] is True
    assert checks["bridge_explicit_execute_fails_before_popen"] is True
    assert checks["executor_explicit_execute_fails_before_popen"] is True
    assert checks["zero_credit_and_launch_denial_are_explicit"] is True


def test_all_required_security_blockers_are_reported() -> None:
    report = audit.build_audit_report()
    ids = {finding["id"] for finding in report["findings"]}
    assert ids == {
        "F3-DAV2-SA-001",
        "F3-DAV2-SA-002",
        "F3-DAV2-SA-003",
        "F3-DAV2-SA-004",
        "F3-DAV2-SA-005",
        "F3-DAV2-SA-006",
        "F3-DAV2-SA-007",
        "F3-DAV2-SA-008",
    }
    assert all(finding["blocking_for_v2"] is True for finding in report["findings"])
    assert all(finding["severity"] == "P1" for finding in report["findings"])


def test_gpu_mapping_is_explicit_but_not_stable_physical_identity() -> None:
    report = audit.build_audit_report()
    checks = report["static_checks"]
    matrix = report["boundary_matrix"]["gpu_env_device_mapping"]
    assert checks["numeric_gpu_env_mapping_present"] is True
    assert checks["stable_gpu_uuid_or_pci_binding_absent"] is True
    assert checks["resource_admission_is_snapshot_not_reservation"] is True
    assert matrix["shared_occupancy_allowed"] is True
    assert matrix["safe_now"] is False


def test_toc_tou_and_hdf5_link_gaps_are_distinguished() -> None:
    report = audit.build_audit_report()
    checks = report["static_checks"]
    assert checks["production_validator_has_path_based_bounded_reader"] is True
    assert checks["production_validator_reopens_hdf5_path"] is True
    assert checks["common_hdf5_descriptor_and_link_hardening_exists"] is True
    assert checks["hdf5_link_rejection_is_byte_snapshot_only"] is True
    assert report["boundary_matrix"]["toctou"]["safe_now"] is False
    assert report["boundary_matrix"]["output_hdf5_external_links"]["safe_now"] is False


def test_receipt_replay_and_popen_identity_are_not_self_authorizing() -> None:
    report = audit.build_audit_report()
    checks = report["static_checks"]
    assert checks["namespace_consumption_ledger_is_absent"] is True
    assert checks["executor_does_not_materialize_namespace_reservation"] is True
    assert checks["production_process_pid_is_receipt_field"] is True
    assert checks["bridge_terminal_attestation_is_serialized_mapping"] is True
    assert checks["sealed_in_memory_record_exists_but_is_not_admitted"] is True


def test_no_existing_job_stop_restart_calls_are_present() -> None:
    report = audit.build_audit_report()
    calls = report["static_checks"]["dangerous_process_control_calls"]
    assert all(values == [] for values in calls.values())
    assert report["boundary_matrix"]["existing_job_stop_restart"]["safe_now"] is True
    assert report["side_effects"]["processes_stopped"] == 0
    assert report["side_effects"]["processes_restarted"] == 0


def test_v2_contract_requires_environment_and_executable_hardening() -> None:
    report = audit.build_audit_report()
    checks = report["static_checks"]
    minimum = report["v2_admission"]["minimum_contract"]
    assert checks["ambient_environment_is_copied_for_future_popen"] is True
    assert checks["executable_content_hash_is_not_required_by_snapshot"] is True
    assert minimum["allowlisted_effective_environment_digest"] is True
    assert minimum["trusted_executable_identity"] is True


def test_report_verifier_accepts_untampered_report_and_rejects_promotion() -> None:
    report = audit.build_audit_report()
    assert audit.validate_audit_report(report) == []

    promoted = deepcopy(report)
    promoted["v2_admission"]["safe_to_upgrade_now"] = True
    errors = audit.validate_audit_report(promoted)
    assert errors
    assert "does not exactly match" in errors[0]


def test_report_verifier_rejects_nonzero_side_effect_claim() -> None:
    report = audit.build_audit_report()
    tampered = deepcopy(report)
    tampered["side_effects"]["popen_attempts"] = 1
    errors = audit.validate_audit_report(tampered)
    assert errors
    assert "does not exactly match" in errors[0]


@pytest.mark.parametrize("forbidden", ["kill", "killpg", "terminate", "send_signal", "pkill", "systemctl"])
def test_audit_contract_contains_no_process_control_call_claims(forbidden: str) -> None:
    report = audit.build_audit_report()
    calls = report["static_checks"]["dangerous_process_control_calls"]
    assert all(forbidden not in values for values in calls.values())

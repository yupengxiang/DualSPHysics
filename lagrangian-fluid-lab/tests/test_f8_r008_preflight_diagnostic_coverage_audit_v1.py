from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f8_r008_preflight_diagnostic_coverage_audit_v1 as audit


def test_current_preflight_to_core_boundary_is_explicitly_fail_closed() -> None:
    result = audit.build_audit()

    assert result["schema"] == audit.SCHEMA
    assert result["status"] == (
        "preflight_verified_diagnostic_core_selector_coverage_blocked"
    )
    assert result["authority_boundary"] == {
        "diagnostic_only": True,
        "execution_authority": False,
        "formal_admission": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
        "safe_fail_closed": True,
    }
    assert result["preflight"]["status"] == (
        "cpu_native_preflight_passed_zero_credit"
    )
    assert result["preflight"]["execution_controls"]["solver_invoked"] is False
    assert result["preflight"]["execution_controls"]["worker_started"] is False
    assert result["preflight"]["execution_controls"]["gpu_invoked"] is False
    assert result["namespace_observation"]["preflight_contains_native_fluid_table"] is False
    assert result["namespace_observation"]["preflight_contains_core_trajectory"] is False


def test_case_selector_distinguishes_one_preflight_input_from_zero_trajectory_rows() -> None:
    result = audit.build_audit()
    selector = result["case_selector_coverage"]

    assert selector["denominator_case_count"] == 15
    assert selector["preflight_selected_case_id"] == "space-q0p5-dp0p0075"
    assert selector["preflight_selected_case_is_in_denominator"] is True
    assert selector["observed_diagnostic_trajectory_case_count"] == 0
    assert selector["coverage_fraction"] == {"numerator": 0, "denominator": 15}
    assert selector["missing_diagnostic_trajectory_case_ids"] == selector["denominator_case_ids"]


def test_static_bridges_do_not_consume_the_one_shot_preflight_namespace() -> None:
    contracts = audit.build_audit()["static_bridge_contracts"]

    assert contracts["trajectory_adapter"]["requires_verified_native_fluid_table"] is True
    assert contracts["trajectory_adapter"]["requires_raw_source_frame_factory"] is True
    assert contracts["trajectory_adapter"]["requires_at_least_two_time_rows"] is True
    assert contracts["trajectory_adapter"]["preflight_receipt_consumer"] is False
    assert contracts["postrun_case_bridge"]["requires_b_c_d_roots"] is True
    assert contracts["postrun_case_bridge"]["preflight_receipt_consumer"] is False
    assert contracts["postrun_matrix_bridge"]["fixed_case_count_15"] is True
    assert contracts["postrun_matrix_bridge"]["preflight_receipt_consumer"] is False


def test_mutated_preflight_execution_control_is_rejected() -> None:
    receipt_path = (
        Path(audit.LAB)
        / audit.PREFLIGHT_REL
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(receipt)
    mutated["execution_controls"]["solver_invoked"] = True

    with pytest.raises(audit.CoverageAuditError, match="execution_controls"):
        audit._validate_execution_controls(mutated)


def test_syscall_selector_report_keeps_static_partition_separate_from_runtime_authority() -> None:
    result = audit.build_audit()["syscall_selector_coverage"]

    assert result["raw_nr_partition_complete"] is True
    assert result["static_default_deny"] is True
    assert result["native_source_interval_count"] == 462
    assert result["native_per_number_dispositions_complete"] is False
    assert result["runtime_conformance_passed"] is False
    assert result["target_kernel_build_pinned"] is False
    assert result["target_kernel_config_pinned"] is False
    assert result["qualification_credit"] == 0

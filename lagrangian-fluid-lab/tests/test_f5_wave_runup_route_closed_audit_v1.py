from __future__ import annotations

import importlib.util
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f5_wave_runup_route_closed_audit_v1.py"
SPEC = importlib.util.spec_from_file_location("f5_route_closed_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_route_closure_is_zero_credit_and_has_no_new_physical_hypothesis():
    value = MODULE.verify(MODULE.OUTPUT)
    assert value["status"] == "f5_route_closed_no_new_hypothesis"
    assert value["qualification_only"] is True
    assert value["qualification_claim"] == "none"
    assert value["qualified"] is False
    assert value["T1_numerical"] is False
    assert value["T2_numerical"] is False
    assert value["matrix_credit"] == 0
    audit = value["independent_hypothesis_audit"]
    assert audit["new_physical_hypothesis_count"] == 0
    assert audit["status"] == "none_found_in_audited_f5_lineage"


def test_both_geometry_repairs_remain_scientific_failures():
    value = MODULE.verify(MODULE.OUTPUT)
    failures = value["scientific_failure_preserved"]
    for version in ("v3", "v4"):
        result = failures[version]
        assert result["status"] == "cpu_native_preflight_failed_geometry_repair_gate"
        assert result["blocks_endpoint_inside_count"] == 1
        assert result["failure_class"] == "frame0_fluid_endpoint_inside_transformed_blocks"
    assert failures["same_input_retry"] is False
    assert failures["failure_summary_is_authoritative"] is True


def test_route_closure_does_not_authorize_runtime_or_reuse_old_products():
    value = MODULE.verify(MODULE.OUTPUT)
    controls = value["execution_controls"]
    assert controls["read_only_audit"] is True
    assert controls["definition_written"] is False
    assert controls["gencase_invoked"] is False
    assert controls["native_decode_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_started"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_mutation"] == 0
    assert value["fixed_denominator"]["planned_rows"] == 15
    assert value["fixed_denominator"]["failed_rows_retained"] is True
    reuse = value["reuse_policy"]
    assert reuse["new_definition_written"] is False
    assert reuse["old_v2_bi4_reused"] is False
    assert reuse["old_v2_trajectory_reused"] is False
    assert reuse["v3_v4_retry"] is False

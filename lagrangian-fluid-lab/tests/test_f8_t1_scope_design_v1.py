from __future__ import annotations

import math
from pathlib import Path

from scripts import f8_t1_scope_design_v1 as design


def test_f8_t1_matrix_is_exactly_13_spatial_plus_two_controls() -> None:
    rows = design.qualification_matrix()
    assert len(rows) == 15
    assert len({row["case_id"] for row in rows}) == 15
    assert sum(row["kind"] == "spatial_anchor" for row in rows) == 9
    assert sum(row["kind"] == "independent_internal" for row in rows) == 4
    assert sum(row["kind"].endswith("control") for row in rows) == 2
    assert all(row["qualification_only"] for row in rows)


def test_parameter_mapping_period_and_observation_window_are_frozen() -> None:
    for row in design.qualification_matrix():
        assert row["alpha"] == 2.0 + 6.0 * row["q"]
        assert math.isclose(row["omega_rad_s"], row["alpha"] ** 2 * design.FLUID_NU_M2_S / design.HALF_HEIGHT_M**2)
        assert math.isclose(row["period_s"], 2.0 * math.pi / row["omega_rad_s"])
        start, end = design.observation_window(row["q"])
        assert row["observation_start_s"] == start
        assert row["observation_end_s"] == end
        assert math.isclose(end - start, 3.0 * row["period_s"])
        assert row["control_samples_per_period"] == 64
        assert math.isclose(row["observation_start_output_index"] * row["native_output_dt_s"], start, rel_tol=0.0, abs_tol=1e-12)
        assert math.isclose(row["observation_end_output_index"] * row["native_output_dt_s"], end, rel_tol=0.0, abs_tol=1e-12)
        assert row["expected_observation_output_count"] == 3 * row["native_output_samples_per_period"] + 1


def test_two_controls_change_only_the_registered_numerical_axis() -> None:
    rows = {row["case_id"]: row for row in design.qualification_matrix()}
    baseline = rows["space-q0p5-dp0p0075"]
    time_control = rows["time-q0p5-dp0p0075-cfl0p1"]
    cadence_control = rows["cadence-q0p5-dp0p0075-output128"]
    assert time_control["compare_to"] == baseline["case_id"]
    assert time_control["q"] == baseline["q"] and time_control["dp_m"] == baseline["dp_m"]
    assert time_control["cflnumber"] == design.TIGHT_CFL < baseline["cflnumber"]
    assert time_control["native_output_samples_per_period"] == baseline["native_output_samples_per_period"]
    assert cadence_control["compare_to"] == baseline["case_id"]
    assert cadence_control["q"] == baseline["q"] and cadence_control["dp_m"] == baseline["dp_m"]
    assert cadence_control["cflnumber"] == baseline["cflnumber"]
    assert cadence_control["native_output_samples_per_period"] == 128
    assert cadence_control["control_samples_per_period"] == baseline["control_samples_per_period"] == 64


def test_parent_evidence_is_input_preflight_only_and_zero_credit() -> None:
    summary = design.validate_parent_evidence()
    assert summary["r007_native_preflight_status"] == "cpu_native_preflight_passed_zero_credit"
    assert summary["r007_native_geometry_is_input_preflight_only"] is True
    assert summary["r007_T1_qualification_credit"] == 0
    assert summary["r007_time_window_reused_for_R008"] is False
    assert summary["r007_minus_r008_output_intervals"] == 2
    assert summary["r007_observation_saved_intervals"] == 194
    assert summary["r008_observation_saved_intervals"] == 192
    assert math.isclose(summary["r007_observation_duration_in_periods"], 3.03125, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(summary["r008_exact_three_cycle_end_s_at_q0p5"] - summary["r008_aligned_start_s_at_q0p5"],
                        3 * design.period_for_q(0.5), rel_tol=0.0, abs_tol=1e-12)


def test_all_32_production_manifests_and_fixed_first_eight_are_registered() -> None:
    cases = design.production_manifest()
    assert len(cases) == 32
    assert [row["production_index"] for row in cases] == list(range(32))
    assert {name: sum(row["split"] == name for row in cases) for name in ("train", "validation", "id_test", "ood_test")} == {
        "train": 16, "validation": 4, "id_test": 6, "ood_test": 6,
    }
    assert all(not row["qualification_only"] for row in cases)
    assert design.FIRST_EIGHT_INDICES == [0, 4, 8, 14, 18, 20, 22, 31]
    assert [cases[index]["production_index"] for index in design.FIRST_EIGHT_INDICES] == design.FIRST_EIGHT_INDICES
    remaining = [index for index in range(32) if index not in design.FIRST_EIGHT_INDICES]
    assert [row["production_index"] for row in cases if row["production_index"] in remaining] == remaining
    assert {cases[index]["split"] for index in design.FIRST_EIGHT_INDICES} == {"train", "validation", "id_test", "ood_test"}


def test_receipt_never_grants_execution_or_reuses_r007_inputs() -> None:
    receipt = design.build_receipt()
    assert receipt["status"] == "static_scope_design_candidate_ready_for_independent_review"
    assert receipt["qualification_credit"] == 0
    assert receipt["matrix"]["case_count"] == 15
    assert receipt["lineage_and_execution_boundary"]["execution_authority_granted"] is False
    assert receipt["lineage_and_execution_boundary"]["r007_native_BI4_reused_for_R008"] is False
    assert receipt["execution_controls"]["solver_invoked"] is False
    assert receipt["execution_controls"]["gencase_invoked"] is False
    assert receipt["execution_controls"]["queue_mutation"] == 0
    assert receipt["execution_controls"]["registry_mutation"] == 0
    assert len(receipt["frozen_physics_and_control"]["production_cases_after_qualification"]["case_manifests_in_canonical_index_order"]) == 32
    assert len(receipt["frozen_physics_and_control"]["production_cases_after_qualification"]["fixed_first_8_case_ids"]) == 8
    assert len(receipt["frozen_physics_and_control"]["production_cases_after_qualification"]["fixed_remaining_24_case_ids"]) == 24
    assert receipt["frozen_physics_and_control"]["production_cases_after_qualification"]["first_8_split_coverage"] == {
        "train": [4, 20], "validation": [8, 18], "id_test": [14, 22], "ood_test": [0, 31],
    }
    assert receipt["frozen_physics_and_control"]["sample_window_contract"]["endpoint_policy"].startswith("inclusive")
    assert "t_native <= t_end" in receipt["frozen_physics_and_control"]["sample_window_contract"]["parser_time_filter"]
    assert len(receipt["matrix"]["gate_applicability"]["cross_resolution_comparisons"]) == 8


def test_written_receipt_bindings_match_all_local_sources() -> None:
    receipt = design.load_json(design.ROOT / "t1-scope-design-v1/receipt.json")
    for item in receipt["bindings"]:
        path = Path(item["path"])
        if path.is_absolute() and not path.is_file() and item["sha256"] == design.PLAN_SHA256:
            assert item["bytes"] == design.PLAN_BYTES
            continue
        if not path.is_absolute():
            path = design.LAB / path
        assert path.stat().st_size == item["bytes"]
        assert design.sha256(path) == item["sha256"]

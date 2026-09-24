from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_t1_metric_semantics_proposal_v2 as proposal


def test_v2_closes_terra_high_findings_without_changing_frozen_scope() -> None:
    value = proposal.build_proposal()
    assert value["status"] == "awaiting_independent_terra_high_review"
    assert value["prior_independent_review"]["verdict"] == "REVISE"
    assert len(value["frozen_scope_rows"]) == 15
    assert len(value["metric_definitions"]["cross_resolution_profile_alignment"]["comparisons_from_frozen_scope"]) == 8
    assert value["amendment_boundary"]["matrix_case_count_changed"] is False
    assert value["amendment_boundary"]["observation_window_changed"] is False
    assert value["amendment_boundary"]["gate_thresholds_changed"] is False
    assert value["amendment_boundary"]["solver_or_worker_authorized"] is False


def test_v2_fixes_coefficient_convention_and_interpolates_coefficients_only() -> None:
    value = proposal.build_proposal()
    fit = value["observation_semantics"]["fixed_frequency_coefficient_fit"]
    assert fit["model"] == "u(t) = mean + a*sin(omega*t) + b*cos(omega*t)"
    assert fit["derived_amplitude_m_s"] == "hypot(a, b)"
    assert fit["derived_phase_rad"] == "atan2(b, a), in [-pi, pi] for the equivalent mean + A*sin(omega*t + phase) representation"
    alignment = value["metric_definitions"]["cross_resolution_profile_alignment"]
    assert alignment["interpolation"].startswith("linear interpolation in z of fitted sine coefficient a and cosine coefficient b separately")
    assert alignment["coefficient_fit_contract"].startswith("use observation_semantics.fixed_frequency_coefficient_fit")
    assert alignment["post_interpolation_derived_values"]["amplitude"] == "hypot(interpolated_a, interpolated_b)"


def test_v2_binds_strict_native_fluid_input_without_claiming_generic_converter_is_strict() -> None:
    value = proposal.build_proposal()
    contract = value["native_fluid_frame_contract"]
    assert contract["schema_id"] == "core.cfd.f8.r008_native_fluid_frame_table.v1"
    assert "each expected ID exactly once and no other ID" in contract["raw_id_set"]
    assert any("all position and velocity components are finite" in gate for gate in contract["selected_frame_gates"])
    assert any("mass is finite, strictly positive, and invariant" in gate for gate in contract["selected_frame_gates"])
    assert "does not reject every unknown raw ID" in contract["current_implementation_disclaimer"]
    bound = {item["path"] for item in value["evidence"]}
    assert proposal.NATIVE_SCHEMA.as_posix() in bound
    assert proposal.CORE_CFD.as_posix() in bound
    assert proposal.CORE_CFD_TEST.as_posix() in bound


def test_v2_cycle_partition_has_three_exact_periods_and_shared_seams() -> None:
    value = proposal.build_proposal()
    partition = value["observation_semantics"]["cycle_partition"]
    assert partition["selected_row_count"] == "exactly 3*N+1 rows, indexed 0 through 3*N inclusive"
    assert partition["cycle_row_ranges_inclusive"] == [
        {"cycle": 0, "first_row": 0, "last_row": "N"},
        {"cycle": 1, "first_row": "N", "last_row": "2*N"},
        {"cycle": 2, "first_row": "2*N", "last_row": "3*N"},
    ]
    assert "shared seam sample" in partition["seam_rule"]
    assert value["metric_definitions"]["cycle_mean_flux"]["cycle_partition"].startswith("use observation_semantics.cycle_partition")


def test_v2_preserves_zero_authority_and_binds_all_predecessors() -> None:
    value = proposal.build_proposal()
    assert value["qualification_credit"] == 0
    assert value["execution_authority"] == {
        "solver": False,
        "gpu": False,
        "worker": False,
        "queue": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
    }
    bound = {item["path"] for item in value["evidence"]}
    assert proposal.V1_RECEIPT.as_posix() in bound
    assert proposal.V1_SCRIPT.as_posix() in bound
    assert proposal.V1_TEST.as_posix() in bound


def test_v2_writer_is_immutable_and_verifier_recomputes(tmp_path: Path) -> None:
    target = tmp_path / "proposal.json"
    assert proposal.write_proposal(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == proposal.verify_proposal(target)
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable R008 v2 metric-semantics proposal"):
        proposal.write_proposal(target)

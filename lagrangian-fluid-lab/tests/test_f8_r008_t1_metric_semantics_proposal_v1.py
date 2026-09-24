from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_t1_metric_semantics_proposal_v1 as proposal


def test_metric_proposal_preserves_r008_geometry_and_15_row_scope() -> None:
    value = proposal.build_proposal()
    geometry = value["geometry_semantics"]

    assert geometry["interpretation"].endswith("spacing intervals, not particle planes")
    assert geometry["resolution_counts"]["production"]["spacing_intervals"] == 12
    assert geometry["resolution_counts"]["production"]["particle_planes"] == 13
    assert geometry["resolution_counts"]["fine"]["particle_planes"] == 16
    assert geometry["definition_pack_static_check"]["definition_count"] == 47
    assert geometry["production_native_check"]["native_particle_count"] == 6656
    assert len(value["frozen_scope_rows"]) == 15
    assert len(value["metric_definitions"]["cross_resolution_profile_alignment"]["common_profile_z_m"]) == 11
    assert len(value["metric_definitions"]["cross_resolution_profile_alignment"]["comparisons_from_frozen_scope"]) == 8
    assert value["amendment_boundary"]["matrix_case_count_changed"] is False
    assert value["amendment_boundary"]["gate_thresholds_changed"] is False
    assert value["amendment_boundary"]["solver_or_worker_authorized"] is False


def test_metric_proposal_defines_units_denominators_and_grid_alignment() -> None:
    value = proposal.build_proposal()
    metrics = value["metric_definitions"]

    assert value["normalization"]["u_ref_m_s"].startswith("acceleration_amplitude_m_s2 / omega")
    assert metrics["cycle_mean_flux"]["normalization"] == "divide by Uref*(2*H), the per-unit-span reference flux scale"
    assert metrics["cycle_mean_flux"]["three_cycle_reduction"].startswith("max absolute value")
    assert metrics["transverse_velocity_rms"]["limit_from_frozen_scope"] == 0.05
    assert metrics["continuum_profile"]["limits_from_frozen_scope"]["profile_amplitude_relative_max"] == 0.15
    assert metrics["cross_resolution_profile_alignment"]["interpolation"].startswith("linear interpolation in z of fitted sine coefficient")
    assert len(metrics["cross_resolution_profile_alignment"]["comparisons_from_frozen_scope"]) == 8
    assert metrics["cross_resolution_profile_alignment"]["extrapolation"] == "forbidden; all target locations must lie within both source profiles' wall-inclusive support"
    diagnostic = value["steady_reference_compatibility_diagnostic"]
    assert diagnostic["cases_evaluated"] == 15
    assert diagnostic["is_a_t1_gate_or_qualification_result"] is False
    assert diagnostic["solver_invoked"] is False
    assert diagnostic["maximum_relative_amplitude_difference"] >= 0.0
    assert diagnostic["maximum_wrapped_phase_difference_rad"] >= 0.0


def test_metric_proposal_is_not_an_execution_authorization() -> None:
    value = proposal.build_proposal()
    assert value["status"] == "awaiting_independent_terra_high_review"
    assert value["proposal_only"] is True
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
    assert proposal.SCOPE.as_posix() in {item["path"] for item in value["evidence"]}
    assert proposal.READINESS_RECEIPT.as_posix() in {item["path"] for item in value["evidence"]}


def test_metric_proposal_writer_is_immutable_and_verifier_recomputes(tmp_path: Path) -> None:
    target = tmp_path / "proposal.json"
    assert proposal.write_proposal(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == proposal.verify_proposal(target)
    with pytest.raises(FileExistsError, match="immutable R008 metric-semantics proposal"):
        proposal.write_proposal(target)

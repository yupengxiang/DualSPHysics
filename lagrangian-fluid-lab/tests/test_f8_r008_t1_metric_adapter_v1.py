from __future__ import annotations

import json
import hashlib
from pathlib import Path

import numpy as np
import pytest

import scripts.f8_r008_t1_metric_adapter_v1 as adapter
from scripts.f8_r008_t1_metric_adapter_v1 import (
    SCHEMA,
    SCOPE_ID,
    NativeFluidTable,
    assign_plane_cohorts,
    build_native_fluid_table,
    compare_profile_coefficients,
    evaluate_case_metrics,
    evaluate_metric_matrix,
    fit_harmonic_coefficients,
    read_fluid_table,
    three_cycle_mean_fluxes,
    transverse_velocity_rms,
    validate_fluid_table,
    validate_raw_frame_ids,
    verify_gencase_receipt,
    write_fluid_table,
)
from scripts.f8_womersley_oracle import ChannelParameters, steady_velocity


HALF_HEIGHT = 0.045
DP = 0.0075
ANCHOR_CASE_ID = "space-q0p5-dp0p0075"
Z = np.linspace(-HALF_HEIGHT, HALF_HEIGHT, 13)
FLUID_IDS = np.arange(1, 14, dtype=np.uint32)


def _frames(times: np.ndarray, *, analytic: bool = False, omega: float = np.pi) -> list[dict]:
    params = ChannelParameters(HALF_HEIGHT, 0.0005, omega, 0.01)
    permutation = np.arange(len(FLUID_IDS) - 1, -1, -1)
    raw_ids = np.r_[np.array([99], dtype=np.uint32), FLUID_IDS[permutation]]
    frames = []
    for time in times:
        positions = np.full((len(raw_ids), 3), np.nan, dtype=np.float64)
        velocities = np.full((len(raw_ids), 3), np.nan, dtype=np.float64)
        masses = np.full(len(raw_ids), np.nan, dtype=np.float64)
        positions[1:, 0] = 0.01
        positions[1:, 1] = 0.02
        positions[1:, 2] = Z[permutation]
        velocities[1:, 0] = steady_velocity(float(time), Z[permutation], params) if analytic else 0.0
        velocities[1:, 1:] = 0.0
        masses[1:] = 2.0
        frames.append({
            "time_s": float(time), "particle_id": raw_ids.copy(),
            "position_m": positions, "velocity_m_s": velocities, "mass_kg": masses,
        })
    return frames


def _parameter_contract() -> dict:
    return json.loads((Path(__file__).resolve().parents[1]
                       / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json")
                      .read_text(encoding="utf-8"))


def _scope_row(case_id: str) -> dict:
    scope_path = (Path(__file__).resolve().parents[1]
                  / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json")
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    return next(row for row in scope["matrix"]["rows"] if row["case_id"] == case_id)


def _generated_xml(tmp_path) -> Path:
    path = tmp_path / "generated.xml"
    path.write_text(
        "<case><particles><fixed begin='99' count='1'/><fluid begin='1' count='13'/></particles></case>",
        encoding="utf-8",
    )
    return path


def _build_table(times: np.ndarray, tmp_path, *, analytic: bool = False,
                 omega: float = np.pi, case_id: str = ANCHOR_CASE_ID) -> NativeFluidTable:
    return build_native_fluid_table(
        _frames(times, analytic=analytic, omega=omega), generated_xml_path=_generated_xml(tmp_path),
        dp_m=DP, half_height_m=HALF_HEIGHT, case_id=case_id,
    )


def test_raw_id_membership_requires_exact_unique_fluid_and_nonfluid_union() -> None:
    indices = validate_raw_frame_ids([99, 3, 1, 2], [1, 2, 3], [99])
    assert indices.tolist() == [2, 3, 1]
    with pytest.raises(ValueError, match="missing=.*unknown="):
        validate_raw_frame_ids([99, 1, 2], [1, 2, 3], [99])
    with pytest.raises(ValueError, match="duplicate native identities"):
        validate_raw_frame_ids([99, 1, 2, 2, 3], [1, 2, 3], [99])
    with pytest.raises(ValueError, match="missing=.*unknown="):
        validate_raw_frame_ids([99, 1, 2, 3, 100], [1, 2, 3], [99])


def test_build_fluid_table_sorts_ids_projects_fluid_only_and_checks_native_values(tmp_path) -> None:
    table = _build_table(np.array([0.0, 1.0]), tmp_path)
    assert table.particle_id.tolist() == FLUID_IDS.tolist()
    assert table.position_m.shape == (2, 13, 3)
    assert np.all(table.valid)
    assert np.all(table.mass_kg == 2.0)
    target = tmp_path / "fluid.h5"
    with pytest.raises(ValueError, match="without a verified GenCase receipt"):
        write_fluid_table(target, table)


def test_real_r008_preflight_inputs_bind_xml_definition_receipt_and_fluid_table(tmp_path) -> None:
    lab = Path(__file__).resolve().parents[1]
    campaign = lab / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/cpu-native-preflight-v3"
    native = campaign / "native-initial/PART_0000"
    generated_xml = campaign / "generated/space-q0p5-dp0p0075.xml"
    generation_receipt = campaign / "receipt.json"
    ids = np.fromfile(native / "Idp.bin", dtype="<u4")
    positions = np.fromfile(native / "Posd.bin", dtype="<f8").reshape(-1, 3)
    velocities = np.fromfile(native / "Vel.bin", dtype="<f4").reshape(-1, 3)
    density = np.fromfile(native / "Rhop.bin", dtype="<f4")
    masses = density * DP**3
    row = _scope_row(ANCHOR_CASE_ID)
    frame = {
        "particle_id": ids,
        "position_m": positions,
        "velocity_m_s": velocities,
        "mass_kg": masses,
    }
    frames = [
        {**frame, "time_s": 0.0},
        {**frame, "time_s": row["native_output_dt_s"]},
    ]
    table = build_native_fluid_table(
        frames, generated_xml_path=generated_xml,
        generation_receipt_path=generation_receipt,
        dp_m=DP, half_height_m=HALF_HEIGHT, case_id=ANCHOR_CASE_ID,
    )
    assert len(table.particle_id) == 6656
    assert table.definition_sha256
    target = tmp_path / "bound-fluid.h5"
    assert write_fluid_table(target, table) == target
    reread = read_fluid_table(
        target, generation_receipt_path=generation_receipt, case_id=ANCHOR_CASE_ID,
    )
    assert np.array_equal(reread.particle_id, table.particle_id)
    assert np.array_equal(reread.position_m, table.position_m)
    assert reread.source_table_sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        write_fluid_table(target, table)


def test_build_rejects_caller_selected_geometry_instead_of_frozen_case_values(tmp_path) -> None:
    with pytest.raises(ValueError, match="must match the frozen F8 R008 case row"):
        build_native_fluid_table(
            _frames(np.array([0.0, 1.0])), generated_xml_path=_generated_xml(tmp_path),
            dp_m=DP * 1.1, half_height_m=HALF_HEIGHT, case_id=ANCHOR_CASE_ID,
        )


def test_frozen_scope_hash_is_a_fixed_trust_anchor(tmp_path, monkeypatch) -> None:
    changed = tmp_path / "changed-scope.json"
    changed.write_text(adapter.FROZEN_SCOPE_RECEIPT.read_text(encoding="utf-8") + "\n",
                       encoding="utf-8")
    monkeypatch.setattr(adapter, "FROZEN_SCOPE_RECEIPT", changed)
    with pytest.raises(ValueError, match="frozen F8 R008 input changed or is missing: scope"):
        adapter._assert_frozen_inputs()


def test_unreviewed_per_case_gencase_receipts_are_not_provenance(tmp_path) -> None:
    receipt = tmp_path / "self-asserted-gencase.json"
    receipt.write_text(json.dumps({
        "schema": "core.cfd.f8.r008_gencase_materialization.v1",
        "scope_id": SCOPE_ID,
        "qualification_credit": 0,
        "case_id": ANCHOR_CASE_ID,
        "status": "gencase_materialization_passed_zero_credit",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="untrusted per-case GenCase receipt schema"):
        verify_gencase_receipt(receipt, ANCHOR_CASE_ID)


def test_table_rejects_unsorted_axis_missing_ids_mass_drift_and_nonzero_initial_time(tmp_path) -> None:
    base = _build_table(np.array([0.0, 1.0]), tmp_path)
    with pytest.raises(ValueError, match="sorted and immutable"):
        validate_fluid_table(NativeFluidTable(
            base.time_s, base.particle_id[::-1], base.position_m, base.velocity_m_s,
            base.mass_kg, base.valid, base.case_id, base.generated_xml_sha256,
        ))
    drifted_mass = base.mass_kg.copy()
    drifted_mass[1, 0] *= 2
    with pytest.raises(ValueError, match="mass changed"):
        validate_fluid_table(NativeFluidTable(
            base.time_s, base.particle_id, base.position_m, base.velocity_m_s,
            drifted_mass, base.valid, base.case_id, base.generated_xml_sha256,
        ))
    with pytest.raises(ValueError, match="start exactly at zero"):
        validate_fluid_table(NativeFluidTable(
            np.array([0.1, 1.1]), base.particle_id, base.position_m, base.velocity_m_s,
            base.mass_kg, base.valid, base.case_id, base.generated_xml_sha256,
        ))


def test_plane_cohorts_include_wall_endpoints_and_reject_off_plane_rows() -> None:
    planes, z = assign_plane_cohorts(Z, FLUID_IDS, DP, HALF_HEIGHT)
    assert len(z) == 13
    assert planes.tolist() == list(range(13))
    bad = Z.copy()
    bad[5] += 1e-4
    with pytest.raises(ValueError, match="does not map uniquely"):
        assign_plane_cohorts(bad, FLUID_IDS, DP, HALF_HEIGHT)


def test_fixed_frequency_coefficients_recover_sine_and_cosine_convention() -> None:
    omega = 2.3
    times = np.linspace(1.2, 9.2, 401)
    expected_a, expected_b = 0.37, -0.21
    signal = 0.8 + expected_a * np.sin(omega * times) + expected_b * np.cos(omega * times)
    fit = fit_harmonic_coefficients(times, signal, omega)
    assert fit["mean_m_s"] == pytest.approx(0.8, abs=1e-12)
    assert fit["sine_coefficient_a_m_s"] == pytest.approx(expected_a, abs=1e-12)
    assert fit["cosine_coefficient_b_m_s"] == pytest.approx(expected_b, abs=1e-12)
    assert fit["amplitude_m_s"] == pytest.approx(np.hypot(expected_a, expected_b), abs=1e-12)
    assert fit["phase_rad"] == pytest.approx(np.arctan2(expected_b, expected_a), abs=1e-12)
    with pytest.raises(ValueError, match="rank-three"):
        fit_harmonic_coefficients(np.arange(5, dtype=float) * 1e-20, np.ones(5), omega)


def test_three_cycle_integrals_use_exact_inclusive_shared_seams() -> None:
    samples_per_period = 4
    period = 1.0
    times = np.arange(3 * samples_per_period + 1, dtype=np.float64) / samples_per_period
    flux = times**2 - 0.2 * times
    means = three_cycle_mean_fluxes(times, flux, period, samples_per_period)
    expected = np.array([
        np.trapezoid(flux[r * samples_per_period:(r + 1) * samples_per_period + 1],
                     times[r * samples_per_period:(r + 1) * samples_per_period + 1]) / period
        for r in range(3)
    ])
    assert means == pytest.approx(expected)
    assert len(means) == 3
    with pytest.raises(ValueError, match=r"exactly 3N\+1"):
        three_cycle_mean_fluxes(times[:-1], flux[:-1], period, samples_per_period)


def test_metric_adapter_matches_analytic_solution_and_keeps_zero_credit(tmp_path) -> None:
    row = _scope_row("space-q0p5-dp0p0075")
    times = np.arange(row["observation_end_output_index"] + 1, dtype=np.float64) * row["native_output_dt_s"]
    table = _build_table(times, tmp_path, analytic=True, omega=row["omega_rad_s"], case_id=row["case_id"])
    result = evaluate_case_metrics(table, row, _parameter_contract())
    assert result["metric_gates_passed"] is True
    assert result["metrics"]["profile_amplitude_relative_error_max"] < 1e-6
    assert result["metrics"]["profile_phase_absolute_error_max_rad"] < 1e-6
    assert result["metrics"]["transverse_velocity_rms_ratio"] == 0.0
    assert result["native_integrity_gates_evaluated"] is False
    assert result["provenance_verified"] is False
    assert result["status"] == "diagnostic_metrics_only_unbound_table"
    assert result["qualification_credit"] == 0


def test_timestep_metric_requires_a_hash_verified_case_bound_audit(tmp_path) -> None:
    row = _scope_row("space-q0p5-dp0p0075")
    times = np.arange(row["observation_end_output_index"] + 1, dtype=np.float64) * row["native_output_dt_s"]
    table = _build_table(times, tmp_path, analytic=True, omega=row["omega_rad_s"], case_id=row["case_id"])
    source = tmp_path / "native.log"
    source.write_text("case-specific solver timestep evidence\n", encoding="utf-8")
    audit = tmp_path / "timestep-audit.json"
    audit.write_text(json.dumps({
        "schema": "core.cfd.f8.r008_solver_timestep_audit.v1",
        "status": "passed",
        "case_id": row["case_id"],
        "max_solver_dt_s": 0.001,
        "checks": {"finite_positive_max_step": True},
        "source_log": {
            "path": str(source), "bytes": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
    }), encoding="utf-8")
    result = evaluate_case_metrics(table, row, _parameter_contract(), solver_timestep_audit_path=audit)
    assert result["solver_max_dt_s"] == 0.001
    source.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source log changed"):
        evaluate_case_metrics(table, row, _parameter_contract(), solver_timestep_audit_path=audit)


def test_matrix_adjudicator_rejects_any_non_frozen_scope_inputs() -> None:
    with pytest.raises(ValueError, match="differ from the hash-bound frozen R008 scope"):
        evaluate_metric_matrix(
            {}, [], [], half_height_m=HALF_HEIGHT, production_dp_m=DP,
            time_step_comparison={}, output_cadence_comparison={},
        )


def test_metric_matrix_rejects_unbound_synthetic_case_results() -> None:
    root = Path(__file__).resolve().parents[1]
    scope = json.loads((root / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json")
                       .read_text(encoding="utf-8"))
    rows = scope["matrix"]["rows"]
    applicability = scope["predeclared_t1_gates"]["gate_applicability_by_case_and_comparison"]
    results = {
        row["case_id"]: {
            "schema": SCHEMA,
            "case_id": row["case_id"],
            "provenance_verified": False,
            "provenance": None,
        }
        for row in rows
    }
    with pytest.raises(ValueError, match="case-bound immutable provenance"):
        evaluate_metric_matrix(
            results, rows, applicability["cross_resolution_comparisons"],
            half_height_m=HALF_HEIGHT, production_dp_m=DP,
            time_step_comparison=applicability["time_step_comparison"],
            output_cadence_comparison=applicability["output_cadence_comparison"],
        )


def test_metric_matrix_rejects_caller_selected_cross_grid_geometry() -> None:
    root = Path(__file__).resolve().parents[1]
    scope = json.loads((root / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/t1-scope-design-v1/receipt.json")
                       .read_text(encoding="utf-8"))
    applicability = scope["predeclared_t1_gates"]["gate_applicability_by_case_and_comparison"]
    with pytest.raises(ValueError, match="frozen H and production dp"):
        evaluate_metric_matrix(
            {}, scope["matrix"]["rows"], applicability["cross_resolution_comparisons"],
            half_height_m=HALF_HEIGHT + 0.001, production_dp_m=DP,
            time_step_comparison=applicability["time_step_comparison"],
            output_cadence_comparison=applicability["output_cadence_comparison"],
        )


def test_cross_resolution_interpolates_coefficients_and_forbids_extrapolation() -> None:
    candidate = {
        "profile_z_m": [0.0, 1.0, 2.0],
        "plane_coefficients": {"sine_coefficient_a_m_s": [1.0, 2.0, 3.0],
                               "cosine_coefficient_b_m_s": [0.5, 1.0, 1.5]},
    }
    production = {
        "profile_z_m": [0.0, 0.5, 1.0, 1.5, 2.0],
        "plane_coefficients": {"sine_coefficient_a_m_s": [1.0, 1.5, 2.0, 2.5, 3.0],
                               "cosine_coefficient_b_m_s": [0.5, 0.75, 1.0, 1.25, 1.5]},
    }
    result = compare_profile_coefficients(
        candidate, production, [0.5, 1.0, 1.5],
        amplitude_relative_max=0.1, phase_absolute_max_rad=0.1,
    )
    assert result["passed"] is True
    assert result["extrapolation_performed"] is False
    with pytest.raises(ValueError, match="would extrapolate"):
        compare_profile_coefficients(candidate, production, [-0.1, 1.0],
                                      amplitude_relative_max=0.1, phase_absolute_max_rad=0.1)


def test_transverse_rms_is_mass_weighted() -> None:
    velocity = np.array([[[0, 1, 0], [0, 0, 2]]], dtype=float)
    mass = np.array([[3.0, 1.0]])
    assert transverse_velocity_rms(velocity, mass) == pytest.approx(np.sqrt(7.0 / 4.0))

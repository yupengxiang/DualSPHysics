"""Synthetic unit tests for F3 genuine adaptive paired macro audit script v1."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

# Ensure scripts and lab directories are on sys.path
LAB_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = LAB_DIR / "scripts"
for d in (str(LAB_DIR), str(SCRIPTS_DIR)):
    if d not in sys.path:
        sys.path.insert(0, d)

from ds_data02_f3_genuine_adaptive_macro_audit_v1 import (
    ENERGY_SCALE_J,
    HIGH,
    LOW,
    SCHEMA,
    TANK_LENGTH_M,
    TARGET_MASS_KG,
    U_CHAR,
    audit_f3_genuine_adaptive_macro,
    compare_frames,
    observe_single_frame,
)


def test_observe_single_frame_properties():
    """Verify observe_single_frame returns all canonical metrics, free-surface proxies, and handles outside particles."""
    n_p = 100
    p = np.zeros((n_p, 3), dtype=np.float64)
    # Place within tank: [-0.45, 0.45] x [-0.09, 0.09] x [0.0, 0.09]
    p[:, 0] = np.linspace(-0.40, 0.40, n_p)
    p[:, 1] = 0.0
    p[:, 2] = np.linspace(0.01, 0.08, n_p)

    v = np.zeros((n_p, 3), dtype=np.float64)
    v[:, 0] = 0.1  # constant 0.1 m/s in x
    m = np.full(n_p, TARGET_MASS_KG / n_p, dtype=np.float64)

    obs = observe_single_frame(p, v, m, TARGET_MASS_KG)

    # Check required top-level keys
    for k in ("hist", "momentum", "com", "q90", "mean_velocity", "energy_normalized",
              "mass_fraction", "kinetic_energy_j", "outside_count", "outside_mass_kg", "free_surface"):
        assert k in obs, f"Missing key: {k}"

    assert pytest.approx(obs["mass_fraction"], rel=1e-9) == 1.0
    assert obs["outside_count"] == 0
    assert obs["outside_mass_kg"] == 0.0
    assert pytest.approx(obs["mean_velocity"][0], rel=1e-6) == 0.1
    assert pytest.approx(obs["mean_velocity"][1], abs=1e-12) == 0.0
    assert pytest.approx(obs["mean_velocity"][2], abs=1e-12) == 0.0

    # Kinetic energy: 0.5 * 14.58 * 0.1^2 = 0.0729 J
    assert pytest.approx(obs["kinetic_energy_j"], rel=1e-6) == 0.5 * TARGET_MASS_KG * 0.01

    # Free surface proxies
    fs = obs["free_surface"]
    for k in ("z90_m", "zmax_m", "z90_left_m", "z90_right_m", "zmax_left_m", "zmax_right_m", "slosh_asymmetry_z90_m"):
        assert k in fs, f"Missing free_surface key: {k}"

    assert pytest.approx(fs["zmax_m"], rel=1e-6) == 0.08
    assert fs["zmax_left_m"] <= 0.08
    assert fs["zmax_right_m"] <= 0.08


def test_observe_single_frame_outside_particle():
    """Verify that particles outside the domain are tracked explicitly."""
    n_p = 10
    p = np.zeros((n_p, 3), dtype=np.float64)
    p[:-1, 0] = 0.0
    p[:-1, 1] = 0.0
    p[:-1, 2] = 0.05
    # One particle above open top (z = 0.60 > 0.51)
    p[-1] = [0.0, 0.0, 0.60]

    v = np.zeros((n_p, 3), dtype=np.float64)
    m = np.full(n_p, TARGET_MASS_KG / n_p, dtype=np.float64)

    obs = observe_single_frame(p, v, m, TARGET_MASS_KG)
    assert obs["outside_count"] == 1
    assert pytest.approx(obs["outside_mass_kg"], rel=1e-6) == TARGET_MASS_KG / n_p


def test_compare_frames_identity_and_perturbation():
    """Verify self-comparison yields zero deviation and perturbed states yield strictly positive discrepancies."""
    n_p = 200
    rng = np.random.RandomState(42)
    p = rng.uniform(LOW + 0.01, HIGH - 0.01, size=(n_p, 3))
    v = rng.randn(n_p, 3) * 0.05
    m = np.full(n_p, TARGET_MASS_KG / n_p, dtype=np.float64)

    obs_a = observe_single_frame(p, v, m, TARGET_MASS_KG)
    obs_b = observe_single_frame(p, v, m, TARGET_MASS_KG)

    comp_identity = compare_frames(obs_a, obs_b)

    assert pytest.approx(comp_identity["tv"], abs=1e-12) == 0.0
    assert pytest.approx(comp_identity["com_l2_over_length"], abs=1e-12) == 0.0
    assert pytest.approx(comp_identity["q90_over_length"], abs=1e-12) == 0.0
    assert pytest.approx(comp_identity["mean_velocity_over_U"], abs=1e-12) == 0.0
    assert pytest.approx(comp_identity["energy_difference"], abs=1e-12) == 0.0
    assert pytest.approx(comp_identity["common_support_velocity_over_U"], abs=1e-12) == 0.0
    assert pytest.approx(comp_identity["unmatched_support_mass"], abs=1e-12) == 0.0

    # Perturbed positions (shift x by 0.01 m)
    p_pert = p.copy()
    p_pert[:, 0] += 0.01
    obs_pert = observe_single_frame(p_pert, v, m, TARGET_MASS_KG)
    comp_pert = compare_frames(obs_a, obs_pert)

    assert comp_pert["tv"] > 0.0
    assert comp_pert["com_l2_over_length"] > 0.0
    assert comp_pert["q90_over_length"] > 0.0


def test_audit_f3_genuine_adaptive_macro_synthetic_e2e(tmp_path: Path):
    """Verify end-to-end macro audit execution on synthetic trajectory fixtures matching cohort size 34560."""
    n_fluid = 34560
    n_frames = 2
    times = [0.0, 0.01]

    # Mock trajectories
    base_h5 = tmp_path / "baseline_trajectory.h5"
    half_h5 = tmp_path / "half_trajectory.h5"

    rng = np.random.RandomState(123)
    p0 = rng.uniform([-0.40, -0.08, 0.005], [0.40, 0.08, 0.085], size=(n_fluid, 3))
    v0 = rng.randn(n_fluid, 3) * 0.02
    m0 = np.full(n_fluid, TARGET_MASS_KG / n_fluid, dtype=np.float32)

    for path, pert_scale in ((base_h5, 0.0), (half_h5, 0.001)):
        with h5py.File(path, "w") as h:
            h.create_dataset("time", data=np.array(times, dtype=np.float64))
            pos_ds = h.create_dataset("position", shape=(n_frames, n_fluid, 3), dtype=np.float32)
            vel_ds = h.create_dataset("velocity", shape=(n_frames, n_fluid, 3), dtype=np.float32)
            valid_ds = h.create_dataset("valid", shape=(n_frames, n_fluid), dtype=np.int8)
            type_ds = h.create_dataset("type", shape=(n_frames, n_fluid), dtype=np.int32)
            mass_ds = h.create_dataset("mass", shape=(n_frames, n_fluid), dtype=np.float32)

            for f_idx, t_val in enumerate(times):
                pos_ds[f_idx] = p0 + pert_scale * (f_idx + 1)
                vel_ds[f_idx] = v0 + pert_scale * 0.5 * (f_idx + 1)
                valid_ds[f_idx] = 1
                type_ds[f_idx] = 3  # FLUID
                mass_ds[f_idx] = m0

    # Mock conversion reports
    base_conv = tmp_path / "baseline_conversion.json"
    half_conv = tmp_path / "half_conversion.json"
    base_conv.write_text(json.dumps({"schema": "ds02.conversion.v1", "status": "completed"}))
    half_conv.write_text(json.dumps({"schema": "ds02.conversion.v1", "status": "completed"}))

    # Mock protocol & gate
    proto_file = tmp_path / "F3-CELL3-PROTOCOL.json"
    proto_file.write_text(json.dumps({
        "schema": "f3.cell3.protocol.v1",
        "time_output_error_budget": 0.01,
        "reference_error_budget": 0.05,
        "output_control_interval_s": 0.002,
    }))
    gate_file = tmp_path / "F3-CELL3-GATE.json"
    gate_file.write_text(json.dumps({"schema": "f3.cell3.gate.v1", "status": "active"}))

    out_file = tmp_path / "macro_audit_report.json"

    report = audit_f3_genuine_adaptive_macro(
        baseline_traj_path=base_h5,
        baseline_conversion_path=base_conv,
        half_traj_path=half_h5,
        half_conversion_path=half_conv,
        protocol_path=proto_file,
        gate_path=gate_file,
        output_path=out_file,
        max_frames=2,
    )

    assert out_file.is_file()
    assert report["schema"] == SCHEMA
    assert report["fluid_cohort"]["count"] == 34560
    assert pytest.approx(report["fluid_cohort"]["total_initial_mass_kg"], rel=1e-5) == TARGET_MASS_KG

    # Check 7 metrics in summary
    metrics = report["macro_metrics"]
    for mkey in ("tv", "com_l2_over_length", "q90_over_length", "mean_velocity_over_U",
                 "energy_difference", "common_support_velocity_over_U", "unmatched_support_mass"):
        assert mkey in metrics, f"Missing metric summary: {mkey}"
        assert "maximum_deviation" in metrics[mkey]
        assert "mean_deviation" in metrics[mkey]
        assert "within_time_output_budget_0p01" in metrics[mkey]
        assert "within_reference_budget_0p05" in metrics[mkey]

    # Check dense save study specification
    dense = report["dense_save_study"]
    assert dense["status"] == "specified_from_frozen_protocol_budget"
    assert dense["derived_dense_timeout_s"] == 0.002
    assert dense["derived_dense_frames"] == 4176
    assert dense["historical_dense_product_reuse"]["case_id"] == "F3_REV075_R075-OUTPUT"

    # Check claim boundary
    cb = report["claim_boundary"]
    assert cb["model_invoked"] is False
    assert cb["production_granted"] is False
    assert cb["q_i"] == "macro_audit_measurement_only"
    assert cb["q_n"] == "not_assessed"
    assert cb["training"] == "not_authorized"

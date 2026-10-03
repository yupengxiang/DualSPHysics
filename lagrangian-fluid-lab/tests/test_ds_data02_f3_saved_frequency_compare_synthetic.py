"""Synthetic unit tests for F3 saved-frequency transport comparison script v1."""

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

from ds_data02_f3_saved_frequency_compare_v1 import (
    DENSE_CLI_TIMEOUT_S,
    NOMINAL_XML_TIMEOUT_S,
    SCHEMA,
    align_physical_times,
    compute_exact_cdf_supremum_and_l1,
    compute_timing_stats,
    compare_destination_series,
    compare_f3_saved_frequency,
    validate_uids,
)


def test_align_physical_times_exact_ratio():
    """Verify physical time alignment maps nominal 0.01s grid to 0.002s dense grid with exact 5x stride."""
    time_nom = np.arange(0.0, 0.10 + 1e-9, 0.01)  # 11 frames: 0.00, 0.01, ..., 0.10
    time_dense = np.arange(0.0, 0.10 + 1e-9, 0.002)  # 51 frames: 0.000, 0.002, ..., 0.100

    pairs, max_delta = align_physical_times(time_nom, time_dense)
    assert len(pairs) == 11
    assert pytest.approx(max_delta, abs=1e-12) == 0.0

    for k, (nom_idx, dense_idx) in enumerate(pairs):
        assert nom_idx == k
        assert dense_idx == 5 * k
        assert pytest.approx(time_nom[nom_idx], abs=1e-9) == time_dense[dense_idx]


def test_align_physical_times_with_adaptive_jitter():
    """Verify alignment is robust to sub-microsecond adaptive save jitter."""
    rng = np.random.RandomState(42)
    time_nom = np.arange(0.0, 0.05 + 1e-9, 0.01)  # 6 frames
    # Introduce small realistic jitter (~1e-6 s) on dense times
    time_dense = np.arange(0.0, 0.05 + 1e-9, 0.002) + rng.uniform(-1e-6, 1e-6, size=26)
    time_dense[0] = 0.0  # initial frame pinned

    pairs, max_delta = align_physical_times(time_nom, time_dense)
    assert len(pairs) == 6
    # Max delta should be well within half of dense interval (0.001s)
    assert max_delta < 0.001
    for k, (nom_idx, dense_idx) in enumerate(pairs):
        assert nom_idx == k
        assert dense_idx == 5 * k


def test_uid_validation_pass_and_mismatch(tmp_path: Path):
    """Verify validate_uids confirms identical particle ordering and catches ID/zone discrepancies."""
    p_nom = tmp_path / "nom.h5"
    p_dense = tmp_path / "dense.h5"

    n_tot = 50
    ids = np.arange(1, n_tot + 1, dtype=np.uint32)
    zones = np.zeros(n_tot, dtype=np.uint16)
    src = np.array([1] * 20 + [2] * 10 + [0] * 20, dtype=np.int16)  # 30 fluid particles
    masses = np.full(n_tot, 14.58 / 30.0, dtype=np.float64)

    for p in (p_nom, p_dense):
        with h5py.File(p, "w") as h:
            h.create_dataset("particle_id", data=ids)
            h.create_dataset("particle_zone", data=zones)
            h.create_dataset("source_label", data=src)
            h.create_dataset("initial_fluid_mass_kg", data=masses)

    with h5py.File(p_nom, "r") as h_nom, h5py.File(p_dense, "r") as h_dense:
        fluid_mask, fluid_count, total_mass = validate_uids(h_nom, h_dense)
        assert fluid_count == 30
        assert pytest.approx(total_mass, rel=1e-6) == 14.58

    # Corrupt particle_id in dense
    p_bad_id = tmp_path / "bad_id.h5"
    with h5py.File(p_bad_id, "w") as h:
        bad_ids = ids.copy()
        bad_ids[0] = 9999
        h.create_dataset("particle_id", data=bad_ids)
        h.create_dataset("particle_zone", data=zones)
        h.create_dataset("source_label", data=src)

    with h5py.File(p_nom, "r") as h_nom, h5py.File(p_bad_id, "r") as h_bad:
        with pytest.raises(ValueError, match="particle_id arrays differ"):
            validate_uids(h_nom, h_bad)


def test_all_censored_cdf_handling():
    """Verify conditional zero CDF handles all-censored events without empty array indexing errors."""
    times_empty = np.array([], dtype=np.float64)
    weights_empty = np.array([], dtype=np.float64)

    res = compute_exact_cdf_supremum_and_l1(
        times_empty, weights_empty,
        times_empty, weights_empty,
        total_mass_a=14.58, total_mass_b=14.58,
        window_start=0.0, window_end=8.35,
    )
    assert res["knot_supremum_absolute_deviation"] == 0.0
    assert res["l1_integrated_cdf_deviation_fraction_s"] == 0.0
    assert res["nominal_terminal_cdf"] == 0.0
    assert res["dense_terminal_cdf"] == 0.0


def test_one_sided_censored_cdf_handling():
    """Verify one-sided censored event computes monotonic CDF step discrepancy cleanly."""
    times_a = np.array([2.0], dtype=np.float64)
    weights_a = np.array([7.29], dtype=np.float64)  # half total mass
    times_b = np.array([], dtype=np.float64)
    weights_b = np.array([], dtype=np.float64)

    res = compute_exact_cdf_supremum_and_l1(
        times_a, weights_a,
        times_b, weights_b,
        total_mass_a=14.58, total_mass_b=14.58,
        window_start=0.0, window_end=4.0,
    )
    # Jump of 0.5 at t=2.0s
    assert pytest.approx(res["knot_supremum_absolute_deviation"], rel=1e-6) == 0.5
    assert pytest.approx(res["time_at_knot_supremum_s"], rel=1e-6) == 2.0
    # L1: discrepancy of 0.5 over [2.0, 4.0] (2 seconds) -> 0.5 * 2.0 = 1.0 fraction*s
    assert pytest.approx(res["l1_integrated_cdf_deviation_fraction_s"], rel=1e-6) == 1.0


def test_full_pipeline_synthetic_hdf5(tmp_path: Path):
    """Verify complete saved-frequency comparison pipeline on synthetic nominal and dense HDF5 fixtures."""
    n_fluid = 20
    n_total = 30
    time_nom = np.arange(0.0, 0.05 + 1e-9, 0.01)  # 6 frames: 0.00, 0.01, ..., 0.05
    time_dense = np.arange(0.0, 0.05 + 1e-9, 0.002)  # 26 frames: 0.000, 0.002, ..., 0.050

    nom_h5 = tmp_path / "nominal_labels.h5"
    dense_h5 = tmp_path / "dense_labels.h5"

    ids = np.arange(1, n_total + 1, dtype=np.uint32)
    zones = np.zeros(n_total, dtype=np.uint16)
    src = np.array([1] * 10 + [2] * 10 + [0] * 10, dtype=np.int16)
    masses = np.full(n_total, 14.58 / n_fluid, dtype=np.float64)

    # Synthetic event times for 2 events
    # Event 0: left_right_exchange
    # Particle 0 crosses at t=0.023s in nominal (bracket [0.02, 0.03])
    # in dense: crosses at t=0.0234s (bracket [0.022, 0.024])
    nom_chord = np.full((n_total, 2), np.nan, dtype=np.float64)
    nom_interval = np.full((n_total, 2, 2), np.nan, dtype=np.float64)
    nom_censor = np.ones((n_total, 2), dtype=np.int8)

    dense_chord = np.full((n_total, 2), np.nan, dtype=np.float64)
    dense_interval = np.full((n_total, 2, 2), np.nan, dtype=np.float64)
    dense_censor = np.ones((n_total, 2), dtype=np.int8)

    # Particle 0: observed in both
    nom_chord[0, 0] = 0.023
    nom_interval[0, 0] = [0.02, 0.03]
    nom_censor[0, 0] = 0

    dense_chord[0, 0] = 0.0234
    dense_interval[0, 0] = [0.022, 0.024]
    dense_censor[0, 0] = 0

    # Particle 1: nominal-only observed (dense censored)
    nom_chord[1, 0] = 0.045
    nom_interval[1, 0] = [0.04, 0.05]
    nom_censor[1, 0] = 0

    # Write nominal HDF5
    with h5py.File(nom_h5, "w") as h:
        h.create_dataset("time", data=time_nom)
        h.create_dataset("particle_id", data=ids)
        h.create_dataset("particle_zone", data=zones)
        h.create_dataset("source_label", data=src)
        h.create_dataset("initial_fluid_mass_kg", data=masses)
        h.create_dataset("first_passage_chord_time", data=nom_chord)
        h.create_dataset("first_passage_interval", data=nom_interval)
        h.create_dataset("first_passage_censor", data=nom_censor)
        h.create_dataset("destination_time_series", data=np.ones((len(time_nom), n_total), dtype=np.int16))
        h.create_dataset("residence_time_s", data=np.zeros((n_total, 2), dtype=np.float64))

    # Write dense HDF5
    with h5py.File(dense_h5, "w") as h:
        h.create_dataset("time", data=time_dense)
        h.create_dataset("particle_id", data=ids)
        h.create_dataset("particle_zone", data=zones)
        h.create_dataset("source_label", data=src)
        h.create_dataset("initial_fluid_mass_kg", data=masses)
        h.create_dataset("first_passage_chord_time", data=dense_chord)
        h.create_dataset("first_passage_interval", data=dense_interval)
        h.create_dataset("first_passage_censor", data=dense_censor)
        h.create_dataset("destination_time_series", data=np.ones((len(time_dense), n_total), dtype=np.int16))
        h.create_dataset("residence_time_s", data=np.zeros((n_total, 2), dtype=np.float64))

    # Reports
    nom_rep = tmp_path / "nom_report.json"
    dense_rep = tmp_path / "dense_report.json"
    nom_rep.write_text(json.dumps({"schema": "ds-data-02.labels-report.v1", "frames": len(time_nom)}))
    dense_rep.write_text(json.dumps({"schema": "ds-data-02.labels-report.v1", "frames": len(time_dense)}))

    # Config
    cfg_file = tmp_path / "transport_config.json"
    cfg_file.write_text(json.dumps({
        "schema": "ds02.f3.legacy-plain-full-transport-config.v1",
        "destination_regions": [{"id": "left"}, {"id": "right"}],
        "events": [
            {"id": "left_right_exchange", "label": "finite x=0 exchange"},
            {"id": "top_open_exit", "label": "top open exit"},
        ],
    }))

    out_file = tmp_path / "comparison_report.json"

    report = compare_f3_saved_frequency(
        nominal_labels_path=nom_h5,
        nominal_report_path=nom_rep,
        dense_labels_path=dense_h5,
        dense_report_path=dense_rep,
        config_path=cfg_file,
        output_path=out_file,
    )

    assert out_file.is_file()
    assert report["schema"] == SCHEMA
    assert report["simulation_identity"]["total_solver_steps"] == 383190
    assert report["cohort_identity_validation"]["status"] == "exact_1to1_uid_match"
    assert report["cohort_identity_validation"]["fluid_particles"] == n_fluid
    assert report["physical_time_alignment"]["frames_aligned"] == len(time_nom)
    assert report["physical_time_alignment"]["alignment_tolerance_satisfied"] is True

    # Check event 0 results
    ev0 = report["events"]["left_right_exchange"]
    fate = ev0["fate_contingency"]
    assert fate["joint_observed_count"] == 1
    assert fate["nominal_only_observed_count"] == 1
    assert fate["dense_only_observed_count"] == 0
    assert fate["joint_censored_count"] == n_fluid - 2

    # Bracket analysis
    sb = ev0["save_bracket_analysis"]
    # Nominal bracket was [0.02, 0.03] (width 0.01)
    # Dense bracket was [0.022, 0.024] (width 0.002)
    assert pytest.approx(sb["mean_tightening_factor"], rel=1e-6) == 5.0
    assert sb["dense_chord_inside_nominal_bracket_count"] == 1
    assert sb["bracket_overlap_count"] == 1
    assert sb["bracket_non_overlap_count"] == 0

    # Event 1 (all censored)
    ev1 = report["events"]["top_open_exit"]
    assert ev1["fate_contingency"]["joint_censored_count"] == n_fluid
    assert ev1["empirical_cdf_comparison"]["knot_supremum_absolute_deviation"] == 0.0

    # Claim boundaries
    cb = report["claim_boundary"]
    assert cb["model_invoked"] is False
    assert cb["q_i"] == "saved_frequency_comparison_measurement_only"
    assert cb["q_n"] == "not_assessed"
    assert cb["production_granted"] is False

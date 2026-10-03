"""Synthetic unit tests for F3 genuine adaptive paired transport comparison script v1."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

# Ensure scripts directory is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ds_data02_f3_genuine_adaptive_transport_compare_v1 import (
    SCHEMA,
    analyze_reentry,
    compute_exact_cdf_supremum_and_l1,
    compute_timing_stats,
    compare_f3_genuine_adaptive_transport,
)


def test_compute_timing_stats_empty():
    """Verify empty delta array yields count=0 and all-null statistics without exception."""
    res = compute_timing_stats(np.array([], dtype=np.float64))
    assert res["count"] == 0
    assert res["denominator"] == 0
    assert res["mean_signed_delta_s"] is None
    assert res["median_absolute_delta_s"] is None
    assert res["max_absolute_delta_s"] is None


def test_compute_timing_stats_weighted():
    """Verify timing stats computation with non-uniform weights."""
    deltas = np.array([-0.01, 0.02, 0.05])
    weights = np.array([1.0, 2.0, 1.0])
    res = compute_timing_stats(deltas, weights)
    assert res["count"] == 3
    # Signed unweighted: (-0.01 + 0.02 + 0.05) / 3 = 0.02
    assert pytest.approx(res["mean_signed_delta_s"], rel=1e-6) == 0.02
    # Signed weighted: (-0.01*1 + 0.02*2 + 0.05*1) / 4 = 0.08 / 4 = 0.02
    assert pytest.approx(res["mass_weighted_mean_signed_delta_s"], rel=1e-6) == 0.02
    # Absolute weighted: (0.01*1 + 0.02*2 + 0.05*1) / 4 = 0.10 / 4 = 0.025
    assert pytest.approx(res["mass_weighted_mean_absolute_delta_s"], rel=1e-6) == 0.025
    assert pytest.approx(res["max_absolute_delta_s"], rel=1e-6) == 0.05
    assert pytest.approx(res["min_absolute_delta_s"], rel=1e-6) == 0.01


def test_compute_exact_cdf_supremum_and_l1_analytic():
    """Verify exact knot supremum and L1 deviation on analytically known step functions.

    CDF A: 1 unit mass jumping at t=1.0 s
    CDF B: 1 unit mass jumping at t=2.0 s
    Window: [0.0, 3.0] s.
    Over [0, 1): diff = 0.
    At t=1: left diff = 0, right diff = 1.0.
    Over [1, 2): diff = 1.0.
    At t=2: left diff = 1.0, right diff = 0.0.
    Over [2, 3]: diff = 0.
    Supremum should be exactly 1.0 at t=1.0 s.
    L1 integrated deviation should be exactly 1.0 mass*s.
    """
    times_a = np.array([1.0])
    weights_a = np.array([1.0])
    times_b = np.array([2.0])
    weights_b = np.array([1.0])

    res = compute_exact_cdf_supremum_and_l1(
        times_a, weights_a, times_b, weights_b,
        total_mass_a=1.0, total_mass_b=1.0,
        window_start=0.0, window_end=3.0,
    )

    assert pytest.approx(res["knot_supremum_absolute_deviation"], rel=1e-9) == 1.0
    assert pytest.approx(res["time_at_knot_supremum_s"], rel=1e-9) in (1.0, 2.0)
    assert pytest.approx(res["l1_integrated_cdf_deviation_mass_s"], rel=1e-9) == 1.0
    assert pytest.approx(res["baseline_terminal_cdf"], rel=1e-9) == 1.0
    assert pytest.approx(res["half_terminal_cdf"], rel=1e-9) == 1.0


def test_analyze_reentry_synthetic():
    """Verify particle reentry detection and state transition counting."""
    # 3 particles, 5 frames
    # particle 0: src 1 (left). Traj: [1, 2, 2, 1, 1] -> crosses to 2 at frame 1, returns to 1 at frame 3 -> REENTERED
    # particle 1: src 1 (left). Traj: [1, 2, 2, 2, 2] -> crosses to 2 at frame 1, never returns -> NOT reentered
    # particle 2: src 2 (right). Traj: [2, 2, 2, 2, 2] -> stays in 2 -> NOT reentered
    dest_series = np.array([
        [1, 1, 2],
        [2, 2, 2],
        [2, 2, 2],
        [1, 2, 2],
        [1, 2, 2],
    ], dtype=np.int16)

    sources = np.array([1, 1, 2], dtype=np.int16)
    fluid_mask = np.array([True, True, True])

    res = analyze_reentry(dest_series, sources, fluid_mask)
    assert res["reentered_particles_count"] == 1
    assert np.array_equal(res["reentered_mask"], np.array([True, False, False]))
    # Particle 0 has transitions: 1->2 (at f1) and 2->1 (at f3) = 2 transitions
    # Particle 1 has transitions: 1->2 (at f1) = 1 transition
    # Particle 2 has 0 transitions
    # Total = 3 transitions
    assert res["total_transition_events_count"] == 3


def test_full_pipeline_synthetic_hdf5(tmp_path: Path):
    """Verify full end-to-end comparison execution using synthetic mock HDF5 datasets."""
    n_fluid = 34560
    n_total = n_fluid + 10  # 10 non-fluid particles
    nt = 836
    ne = 2
    nr = 2

    # Create synthetic baseline H5
    base_h5_path = tmp_path / "baseline-native-labels.h5"
    with h5py.File(base_h5_path, "w") as h:
        time_arr = np.linspace(0.0, 8.35, nt)
        h.create_dataset("time", data=time_arr)
        uids = np.arange(n_total, dtype=np.int64)
        zones = np.zeros(n_total, dtype=np.int32)
        h.create_dataset("particle_id", data=uids)
        h.create_dataset("particle_zone", data=zones)

        masses = np.zeros(n_total, dtype=np.float64)
        per_fluid_m = 14.580000378191471 / n_fluid
        masses[:n_fluid] = per_fluid_m
        h.create_dataset("initial_fluid_mass_kg", data=masses)

        sources = np.zeros(n_total, dtype=np.int16)
        sources[:n_fluid // 2] = 1
        sources[n_fluid // 2:n_fluid] = 2
        h.create_dataset("source_label", data=sources)

        # Censors: Event 0 has first 10,000 observed, Event 1 has 5,000 observed
        censor = np.ones((n_total, ne), dtype=np.int8)
        censor[:10000, 0] = 0
        censor[:5000, 1] = 0
        h.create_dataset("first_passage_censor", data=censor)

        # Chord times
        chord = np.full((n_total, ne), np.nan, dtype=np.float64)
        chord[:10000, 0] = np.linspace(0.5, 7.5, 10000)
        chord[:5000, 1] = np.linspace(1.0, 8.0, 5000)
        h.create_dataset("first_passage_chord_time", data=chord)

        # Intervals
        intervals = np.full((n_total, ne, 2), np.nan, dtype=np.float64)
        intervals[:10000, 0, 0] = chord[:10000, 0] - 0.005
        intervals[:10000, 0, 1] = chord[:10000, 0] + 0.005
        intervals[:5000, 1, 0] = chord[:5000, 1] - 0.005
        intervals[:5000, 1, 1] = chord[:5000, 1] + 0.005
        h.create_dataset("first_passage_interval", data=intervals)

        # Residence
        residence = np.zeros((n_total, nr), dtype=np.float64)
        residence[:n_fluid, 0] = 4.0
        residence[:n_fluid, 1] = 4.35
        h.create_dataset("residence_time_s", data=residence)
        h.create_dataset("unresolved_interval_time_s", data=np.zeros(n_total, dtype=np.float64))

        # Flux
        flux = np.zeros((nt, ne), dtype=np.float64)
        flux[:, 0] = np.linspace(0.0, 1.2, nt)
        flux[:, 1] = np.linspace(0.0, 0.4, nt)
        h.create_dataset("cumulative_net_flux_kg", data=flux)

        fwd_bwd = np.zeros((nt, ne, 2), dtype=np.float64)
        fwd_bwd[:, 0, 0] = np.linspace(0.0, 1.5, nt)
        fwd_bwd[:, 0, 1] = np.linspace(0.0, 0.3, nt)
        h.create_dataset("forward_backward_mass_kg", data=fwd_bwd)

        # Destination series
        dest = np.zeros((nt, n_total), dtype=np.int16)
        dest[:, :n_fluid // 2] = 1
        dest[:, n_fluid // 2:n_fluid] = 2
        h.create_dataset("destination_time_series", data=dest)

        h.create_dataset("numerical_loss_mass_kg", data=np.zeros(nt))
        h.create_dataset("unknown_mass_kg", data=np.zeros(nt))
        h.create_dataset("invalid_state_mass_kg", data=np.zeros(nt))
        h.attrs["complete"] = True

    # Create synthetic half H5 (slightly shifted times for comparison)
    half_h5_path = tmp_path / "half-native-labels.h5"
    with h5py.File(half_h5_path, "w") as h:
        time_arr = np.linspace(0.0, 8.35, nt)
        h.create_dataset("time", data=time_arr)
        h.create_dataset("particle_id", data=uids)
        h.create_dataset("particle_zone", data=zones)
        h.create_dataset("initial_fluid_mass_kg", data=masses)
        h.create_dataset("source_label", data=sources)

        # 9,990 observed in event 0 (10 fewer)
        censor_h = np.ones((n_total, ne), dtype=np.int8)
        censor_h[:9990, 0] = 0
        censor_h[:5010, 1] = 0
        h.create_dataset("first_passage_censor", data=censor_h)

        chord_h = np.full((n_total, ne), np.nan, dtype=np.float64)
        # Shift chord by +0.001s
        chord_h[:9990, 0] = chord[:9990, 0] + 0.001
        chord_h[:5000, 1] = chord[:5000, 1] - 0.001
        chord_h[5000:5010, 1] = 8.1
        h.create_dataset("first_passage_chord_time", data=chord_h)

        intervals_h = np.full((n_total, ne, 2), np.nan, dtype=np.float64)
        intervals_h[:9990, 0, 0] = chord_h[:9990, 0] - 0.0025
        intervals_h[:9990, 0, 1] = chord_h[:9990, 0] + 0.0025
        intervals_h[:5010, 1, 0] = chord_h[:5010, 1] - 0.0025
        intervals_h[:5010, 1, 1] = chord_h[:5010, 1] + 0.0025
        h.create_dataset("first_passage_interval", data=intervals_h)

        residence_h = np.zeros((n_total, nr), dtype=np.float64)
        residence_h[:n_fluid, 0] = 4.01
        residence_h[:n_fluid, 1] = 4.34
        h.create_dataset("residence_time_s", data=residence_h)
        h.create_dataset("unresolved_interval_time_s", data=np.zeros(n_total, dtype=np.float64))

        flux_h = np.zeros((nt, ne), dtype=np.float64)
        flux_h[:, 0] = np.linspace(0.0, 1.21, nt)
        flux_h[:, 1] = np.linspace(0.0, 0.39, nt)
        h.create_dataset("cumulative_net_flux_kg", data=flux_h)

        fwd_bwd_h = np.zeros((nt, ne, 2), dtype=np.float64)
        fwd_bwd_h[:, 0, 0] = np.linspace(0.0, 1.51, nt)
        fwd_bwd_h[:, 0, 1] = np.linspace(0.0, 0.30, nt)
        h.create_dataset("forward_backward_mass_kg", data=fwd_bwd_h)

        # In half, 1 particle re-enters
        dest_h = dest.copy()
        dest_h[200:, 0] = 2  # particle 0 crosses to 2 at frame 200
        dest_h[400:, 0] = 1  # returns to 1 at frame 400
        h.create_dataset("destination_time_series", data=dest_h)

        h.create_dataset("numerical_loss_mass_kg", data=np.zeros(nt))
        h.create_dataset("unknown_mass_kg", data=np.zeros(nt))
        h.create_dataset("invalid_state_mass_kg", data=np.zeros(nt))
        h.attrs["complete"] = True

    # Calculate actual sha256 for mock reports
    import hashlib
    base_sha = hashlib.sha256(base_h5_path.read_bytes()).hexdigest()
    half_sha = hashlib.sha256(half_h5_path.read_bytes()).hexdigest()

    base_rep_path = tmp_path / "baseline-report.json"
    base_rep_path.write_text(json.dumps({"sha256": base_sha, "frames": nt, "identities": n_total}))

    half_rep_path = tmp_path / "half-report.json"
    half_rep_path.write_text(json.dumps({"sha256": half_sha, "frames": nt, "identities": n_total}))

    base_rec_path = tmp_path / "baseline-receipt.json"
    base_rec_path.write_text(json.dumps({"status": "completed", "returncode": 0}))

    half_rec_path = tmp_path / "half-receipt.json"
    half_rec_path.write_text(json.dumps({"status": "completed", "returncode": 0}))

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "events": [
            {"id": "left_right_exchange", "axis": 0, "value": 0.0},
            {"id": "top_open_exit", "axis": 2, "value": 0.51},
        ],
        "destination_regions": [
            {"id": "left"},
            {"id": "right"},
        ],
    }))

    prereg_path = tmp_path / "prereg.json"
    prereg_path.write_text(json.dumps({"schema": "prereg.v1", "status": "registered"}))

    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps({"protocol_schema": "f3.cell3.protocol.v1", "cfl": [0.05, 0.025]}))

    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps({"status": "passed", "panels_passed_count": 13}))

    out_json = tmp_path / "output_report.json"

    report = compare_f3_genuine_adaptive_transport(
        base_h5_path, base_rep_path, base_rec_path,
        half_h5_path, half_rep_path, half_rec_path,
        config_path, prereg_path, protocol_path, gate_path,
        out_json,
    )

    assert out_json.is_file()
    assert report["schema"] == SCHEMA
    assert report["family_id"] == "F3"
    assert report["fluid_cohort"]["count"] == 34560
    assert pytest.approx(report["fluid_cohort"]["total_initial_mass_kg"], rel=1e-9) == 14.580000378191471

    # Check timestepping
    assert report["timestepping_provenance"]["timestepping_classification"] == "genuine_adaptive_cfl_halving_zero_clamps"
    assert pytest.approx(report["timestepping_provenance"]["step_ratio"], rel=1e-4) == 2.0

    # Check events output
    events = {e["event_id"]: e for e in report["events"]}
    assert "left_right_exchange" in events
    assert "top_open_exit" in events

    ev0 = events["left_right_exchange"]
    # Joint observed should be 9990
    assert ev0["cohort_breakdown"]["joint_observed"]["count"] == 9990
    assert ev0["cohort_breakdown"]["baseline_only"]["count"] == 10
    assert ev0["cohort_breakdown"]["half_only"]["count"] == 0
    assert ev0["cohort_breakdown"]["switching_identities"]["count"] == 10

    # Mean signed delta should be +0.001s
    assert pytest.approx(ev0["per_identity_chord_deltas_joint"]["mean_signed_delta_s"], rel=1e-5) == 0.001

    # Check reentry
    assert report["reentry_comparison"]["half_reentered_particles_count"] == 1
    assert report["reentry_comparison"]["baseline_reentered_particles_count"] == 0

    # Check claim boundary
    assert report["claim_boundary"]["q_i"] == "transport_comparison_measurement_only"
    assert report["claim_boundary"]["q_n"] == "not_assessed"
    assert report["claim_boundary"]["production"] == "not_evaluated"

"""Synthetic unit tests for F3 saved-frequency transport comparison script v2."""

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

from ds_data02_f3_saved_frequency_compare_v2 import (
    DENSE_CLI_TIMEOUT_S,
    NOMINAL_XML_TIMEOUT_S,
    REQUIRED_CLOSURE_CHECKS,
    REQUIRED_HDF5_DATASETS,
    SCHEMA,
    align_physical_times,
    compare_asynchronous_destination_observations,
    compare_f3_saved_frequency_v2,
    compute_exact_cdf_supremum_and_l1,
    compute_timing_stats,
    validate_input_artifacts,
    validate_uids_and_cohort,
)


def test_align_physical_times_offsets():
    """Verify physical time alignment reports exact asynchronous offset statistics."""
    time_nom = np.arange(0.0, 0.10 + 1e-9, 0.01)  # 11 frames: 0.00, 0.01, ..., 0.10
    time_dense = np.arange(0.0, 0.10 + 1e-9, 0.002)  # 51 frames: 0.000, 0.002, ..., 0.100

    pairs, offset_summary = align_physical_times(time_nom, time_dense)
    assert offset_summary["frames_aligned"] == 11
    assert pytest.approx(offset_summary["max_absolute_offset_s"], abs=1e-12) == 0.0
    assert pytest.approx(offset_summary["mean_absolute_offset_s"], abs=1e-12) == 0.0
    assert offset_summary["alignment_tolerance_satisfied"] is True
    assert "asynchronous" in offset_summary["asynchronous_observation_note"].lower()

    for k, (nom_idx, dense_idx) in enumerate(pairs):
        assert nom_idx == k
        assert dense_idx == 5 * k


def test_align_physical_times_with_submicrosecond_jitter():
    """Verify offset statistics reflect asynchronous observation time deltas accurately."""
    rng = np.random.RandomState(42)
    time_nom = np.arange(0.0, 0.05 + 1e-9, 0.01)  # 6 frames
    # Jitter dense times
    jitter = rng.uniform(-1e-4, 1e-4, size=26)
    jitter[0] = 0.0
    time_dense = np.arange(0.0, 0.05 + 1e-9, 0.002) + jitter

    pairs, offset_summary = align_physical_times(time_nom, time_dense)
    assert offset_summary["frames_aligned"] == 6
    assert offset_summary["max_absolute_offset_s"] > 0.0
    assert offset_summary["max_absolute_offset_s"] < 0.001
    assert offset_summary["rms_offset_s"] > 0.0


def test_empty_censored_quantiles_null():
    """Verify empty/censored cohorts report NULL (None) for all quantiles rather than missing/zero."""
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
    # Deciles should all have keys p10..p90 mapping to None
    for p in range(10, 100, 10):
        key = f"p{p}"
        assert key in res["nominal_deciles"]
        assert res["nominal_deciles"][key] is None
        assert key in res["dense_deciles"]
        assert res["dense_deciles"][key] is None

    # Timing stats on empty
    stats = compute_timing_stats(np.array([]))
    assert stats["count"] == 0
    assert stats["mean_signed_delta_s"] is None
    assert stats["median_absolute_delta_s"] is None
    assert stats["p90_absolute_delta_s"] is None
    assert stats["max_absolute_delta_s"] is None


def test_uid_validation_strict_no_fallbacks(tmp_path: Path):
    """Verify strict validation catches missing ledgers, non-unique UIDs, and mass dataset absence."""
    p_nom = tmp_path / "nom.h5"
    p_dense = tmp_path / "dense.h5"

    n_tot = 50
    ids = np.arange(1, n_tot + 1, dtype=np.uint32)
    zones = np.zeros(n_tot, dtype=np.uint16)
    src = np.array([1] * 20 + [2] * 10 + [0] * 20, dtype=np.int16)
    masses = np.full(n_tot, 14.58 / 30.0, dtype=np.float64)

    for p in (p_nom, p_dense):
        with h5py.File(p, "w") as h:
            h.create_dataset("particle_id", data=ids)
            h.create_dataset("particle_zone", data=zones)
            h.create_dataset("source_label", data=src)
            h.create_dataset("initial_fluid_mass_kg", data=masses)

    with h5py.File(p_nom, "r") as h_nom, h5py.File(p_dense, "r") as h_dense:
        fluid_mask, fluid_count, n_tot_ret, total_mass = validate_uids_and_cohort(h_nom, h_dense)
        assert fluid_count == 30
        assert n_tot_ret == n_tot
        assert pytest.approx(total_mass, rel=1e-6) == 14.58

    # Test missing initial_fluid_mass_kg in dense
    p_no_mass = tmp_path / "no_mass.h5"
    with h5py.File(p_no_mass, "w") as h:
        h.create_dataset("particle_id", data=ids)
        h.create_dataset("particle_zone", data=zones)
        h.create_dataset("source_label", data=src)

    with h5py.File(p_nom, "r") as h_nom, h5py.File(p_no_mass, "r") as h_bad:
        with pytest.raises(KeyError, match="initial_fluid_mass_kg dataset missing"):
            validate_uids_and_cohort(h_nom, h_bad)

    # Test duplicate UIDs
    p_dup = tmp_path / "dup.h5"
    dup_ids = ids.copy()
    dup_ids[1] = dup_ids[0]
    with h5py.File(p_dup, "w") as h:
        h.create_dataset("particle_id", data=dup_ids)
        h.create_dataset("particle_zone", data=zones)
        h.create_dataset("source_label", data=src)
        h.create_dataset("initial_fluid_mass_kg", data=masses)

    with h5py.File(p_dup, "r") as h_bad, h5py.File(p_dense, "r") as h_dense:
        with pytest.raises(ValueError, match="keys \\(Zone, Idp\\) are not unique"):
            validate_uids_and_cohort(h_bad, h_dense)


def test_closure_checks_and_receipt_validation(tmp_path: Path):
    """Verify validation requires all 23 closure checks and successful execution receipts."""
    p_nom = tmp_path / "nom.h5"
    p_dense = tmp_path / "dense.h5"
    p_cfg = tmp_path / "config.json"
    p_nom_rep = tmp_path / "nom_rep.json"
    p_dense_rep = tmp_path / "dense_rep.json"
    p_nom_rcpt = tmp_path / "nom_rcpt.json"
    p_dense_rcpt = tmp_path / "dense_rcpt.json"

    # Setup dummy valid HDF5s with all required datasets
    for p in (p_nom, p_dense):
        with h5py.File(p, "w") as h:
            h.create_dataset("time", data=np.array([0.0, 0.01]))
            h.create_dataset("particle_id", data=np.array([1, 2], dtype=np.uint32))
            h.create_dataset("particle_zone", data=np.array([0, 0], dtype=np.uint16))
            h.create_dataset("source_label", data=np.array([1, 2], dtype=np.int16))
            h.create_dataset("initial_fluid_mass_kg", data=np.array([7.29, 7.29]))
            h.create_dataset("first_passage_censor", data=np.ones((2, 1), dtype=np.int8))
            h.create_dataset("first_passage_chord_time", data=np.full((2, 1), np.nan))
            h.create_dataset("first_passage_interval", data=np.full((2, 1, 2), np.nan))
            h.create_dataset("destination_time_series", data=np.ones((2, 2), dtype=np.int16))
            h.create_dataset("residence_time_s", data=np.zeros((2, 1), dtype=np.float64))
            h.create_dataset("invalid_state_mass_kg", data=np.zeros(2))
            h.create_dataset("numerical_loss_mass_kg", data=np.zeros(2))
            h.create_dataset("unknown_mass_kg", data=np.zeros(2))
            h.create_dataset("source_final_mass_kg", data=np.zeros((2, 4)))

    import hashlib
    nom_sha = hashlib.sha256(p_nom.read_bytes()).hexdigest()
    dense_sha = hashlib.sha256(p_dense.read_bytes()).hexdigest()

    all_23 = {c: True for c in REQUIRED_CLOSURE_CHECKS}
    closure_dict = {"passed": True, "checks": all_23}

    p_nom_rep.write_text(json.dumps({"sha256": nom_sha, "closure": closure_dict}))
    p_dense_rep.write_text(json.dumps({"sha256": dense_sha, "closure": closure_dict}))
    p_cfg.write_text(json.dumps({"events": []}))

    p_nom_rcpt.write_text(json.dumps({"status": "completed", "returncode": 0}))
    p_dense_rcpt.write_text(json.dumps({"status": "completed", "returncode": 0}))

    # Validation should pass
    digests = validate_input_artifacts(
        p_nom, p_nom_rep, p_dense, p_dense_rep, p_cfg,
        nom_rcpt_p=p_nom_rcpt, dense_rcpt_p=p_dense_rcpt,
    )
    assert len(digests) >= 5

    # Corrupt closure check
    bad_closure = {"passed": False, "checks": {**all_23, "complete": False}}
    p_nom_rep.write_text(json.dumps({"sha256": nom_sha, "closure": bad_closure}))
    with pytest.raises(ValueError, match="closure did not pass"):
        validate_input_artifacts(
            p_nom, p_nom_rep, p_dense, p_dense_rep, p_cfg,
            nom_rcpt_p=p_nom_rcpt, dense_rcpt_p=p_dense_rcpt,
        )


def test_full_pipeline_v2_synthetic(tmp_path: Path):
    """Verify complete v2 saved-frequency comparison pipeline with timestep audit and claim boundaries."""
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
        h.create_dataset("invalid_state_mass_kg", data=np.zeros(len(time_nom)))
        h.create_dataset("numerical_loss_mass_kg", data=np.zeros(len(time_nom)))
        h.create_dataset("unknown_mass_kg", data=np.zeros(len(time_nom)))
        h.create_dataset("source_final_mass_kg", data=np.zeros((len(time_nom), 4)))

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
        h.create_dataset("invalid_state_mass_kg", data=np.zeros(len(time_dense)))
        h.create_dataset("numerical_loss_mass_kg", data=np.zeros(len(time_dense)))
        h.create_dataset("unknown_mass_kg", data=np.zeros(len(time_dense)))
        h.create_dataset("source_final_mass_kg", data=np.zeros((len(time_dense), 4)))

    import hashlib
    nom_sha = hashlib.sha256(nom_h5.read_bytes()).hexdigest()
    dense_sha = hashlib.sha256(dense_h5.read_bytes()).hexdigest()

    all_23 = {c: True for c in REQUIRED_CLOSURE_CHECKS}
    closure_dict = {"passed": True, "checks": all_23}

    # Reports
    nom_rep = tmp_path / "nom_report.json"
    dense_rep = tmp_path / "dense_report.json"
    nom_rep.write_text(json.dumps({"schema": "ds-data-02.labels-report.v1", "sha256": nom_sha, "frames": len(time_nom), "closure": closure_dict}))
    dense_rep.write_text(json.dumps({"schema": "ds-data-02.labels-report.v1", "sha256": dense_sha, "frames": len(time_dense), "closure": closure_dict}))

    # Receipts
    nom_rcpt = tmp_path / "nom_receipt.json"
    dense_rcpt = tmp_path / "dense_receipt.json"
    nom_rcpt.write_text(json.dumps({"status": "completed", "returncode": 0}))
    dense_rcpt.write_text(json.dumps({"status": "completed", "returncode": 0}))

    # Timestep reports
    nom_ts = tmp_path / "nom_ts.json"
    dense_ts = tmp_path / "dense_ts.json"
    nom_ts.write_text(json.dumps({"total_steps": 383190, "total_DT_adjustments": 0, "floor_incidence_fraction": 0.0}))
    dense_ts.write_text(json.dumps({"total_steps": 383190, "active_steps": 383190, "initial_sentinel_steps": 0, "total_DT_adjustments": 0, "floor_incidence_fraction": 0.0}))

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

    report = compare_f3_saved_frequency_v2(
        nominal_labels_path=nom_h5,
        nominal_report_path=nom_rep,
        dense_labels_path=dense_h5,
        dense_report_path=dense_rep,
        config_path=cfg_file,
        output_path=out_file,
        nominal_receipt_path=nom_rcpt,
        dense_receipt_path=dense_rcpt,
        nominal_timestep_report_path=nom_ts,
        dense_timestep_report_path=dense_ts,
    )

    assert out_file.is_file()
    assert report["schema"] == SCHEMA
    assert report["cohort_identity_validation"]["status"] == "exact_1to1_uid_match"
    assert report["cohort_identity_validation"]["uid_uniqueness_verified"] is True
    assert report["cohort_identity_validation"]["fluid_particles"] == n_fluid

    # Cadence refinement factor must be exactly 5.0 (0.01 / 0.002)
    assert report["save_cadence_provenance"]["cadence_refinement_factor"] == 5.0
    assert pytest.approx(report["save_cadence_provenance"]["saved_frame_count_ratio"], rel=1e-3) == len(time_dense) / len(time_nom)

    # Simulation context step parity assessment
    sc = report["simulation_context"]
    assert "not prove bitwise equal" in sc["solver_step_parity_assessment"].lower()
    assert sc["timestep_audit_evidence"]["nominal"]["total_steps"] == 383190
    assert sc["timestep_audit_evidence"]["dense"]["total_steps"] == 383190

    # Alignment offset summary
    align = report["physical_time_alignment"]
    assert align["frames_aligned"] == len(time_nom)
    assert "max_absolute_offset_s" in align
    assert "rms_offset_s" in align

    # Asynchronous observation
    dest_obs = report["asynchronous_destination_observation"]
    assert dest_obs["observation_kind"] == "asynchronous_nearest_saved_frame_sampling"
    assert "interpolation" in dest_obs["semantic_note"].lower()

    # Event 1 (all censored): deciles must be None
    ev1 = report["events"]["top_open_exit"]
    assert ev1["fate_contingency"]["joint_censored_count"] == n_fluid
    assert ev1["empirical_cdf_comparison"]["knot_supremum_absolute_deviation"] == 0.0
    for p in range(10, 100, 10):
        assert ev1["empirical_cdf_comparison"]["nominal_deciles"][f"p{p}"] is None
        assert ev1["empirical_cdf_comparison"]["dense_deciles"][f"p{p}"] is None

    # Claim boundaries
    cb = report["claim_boundary"]
    assert cb["model_invoked"] is False
    assert cb["q_i"] == "saved_frequency_comparison_measurement_only"
    assert cb["q_n"] == "not_assessed"
    assert cb["production_granted"] is False
    assert "no arbitrary 5% cdf gate" in cb["governance_note"].lower()

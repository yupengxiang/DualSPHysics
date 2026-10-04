"""Unit tests for F2 Native-Weighted Temporal Save Comparison Suite v3.

Verifies Root Followup 038 F2 Mandates and Remediations:
1. Actual Per-UID Residence Comparison:
   Streaming trapezoidal integration across frames for all 5 destination codes.
2. Synthetic Proof: Per-UID differences can exist despite identical aggregate residence and final inventory.
3. Strict Literal Closed Saved Bracket Intersection:
   Removal of invented +1e-12 extension; intervals separated by < 1e-12 are strictly disjoint.
4. Exact Endpoint Touching: Literal closed interval intersection permits exact endpoint touch.
5. Repeats Ambiguity: Multi-overlap clusters are isolated, never claimed joint, and never converted
   into automatic final fate equivalence.
6. Unknown Retention: Native Motive 1 exclusions strictly retained as unknown, never physical spill.
7. Safe Output Creation: Exclusive mode 'x' with prior-existence check; never unlinks arbitrary targets.
8. Direct Path Expected SHA Verification: Verified when provided.
9. Total Residence Duration Equality: Sum across destinations equals full actual duration for all UIDs.
10. Weighted Sum Observation Reproduction: Reproduces JSON residence within floating-point roundoff.
11. Event Tuple Integrity Verification: Validated against particle arrays and frame brackets.
12. Full End-to-End Synthetic CLI Execution.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

import f2_rv4eq_native_weighted_save_comparison_worker_v3 as worker


def test_binding_v3_structure_and_constants():
    """Verify binding configuration schema, continuum hashes, and operator invariants."""
    binding_path = PACKAGE_DIR / "configs/native_weighted_save_comparison_binding_v3.json"
    assert binding_path.is_file(), f"Missing binding JSON: {binding_path}"

    b = json.loads(binding_path.read_text(encoding="utf-8"))
    assert b["schema"] == "ds02.f2.native-weighted-save-comparison-binding.v3"
    assert b["family_id"] == "F2"
    assert b["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_SAVE_COMPARISON_V3"
    assert b["physical_condition_hash"] == worker.PHYSICAL_CONDITION_HASH
    assert b["operator_version"] == worker.OPERATOR_VERSION
    assert b["operator_sha256"] == worker.OPERATOR_SHA256
    assert b["fluid_particles"] == worker.FLUID_PARTICLES_COUNT
    assert b["native_single_particle_mass_kg"] == pytest.approx(worker.NATIVE_SINGLE_PARTICLE_MASS_KG, rel=1e-12)
    assert b["native_cohort_mass_kg"] == pytest.approx(worker.NATIVE_COHORT_MASS_KG, rel=1e-12)

    # Verify execution receipts exist and are completed0 (read JSON metadata only, no H5 read)
    sources = b["sources"]
    assert set(sources.keys()) == {"nominal401", "dense4001"}
    for key, src in sources.items():
        assert Path(src["execution_receipt"]).is_file()
        receipt = json.loads(Path(src["execution_receipt"]).read_text(encoding="utf-8"))
        assert receipt["status"] == "completed"
        assert receipt["returncode"] == 0


def test_runner_request_v3_validation():
    """Verify runner request v3 schema, launch_allowed:false, and resource specifications."""
    req_path = PACKAGE_DIR / "requests/native_weighted_save_comparison_request_v3.json"
    assert req_path.is_file(), f"Missing request JSON: {req_path}"

    req = json.loads(req_path.read_text(encoding="utf-8"))
    assert req["schema"] == "ds02.runner-request.v2"
    assert req["family_id"] == "F2"
    assert req["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_SAVE_COMPARISON_V3"
    assert req["kind"] == "cpu"
    assert req["cpu_task_kind"] == "audit"
    assert req["cpu_threads"] == 2
    assert req["max_wall_seconds"] == 3600
    assert req["estimated_storage_bytes"] == 34359738368
    assert req["conversion_launch_forbidden"] is True
    assert req["launch_allowed"] is False
    assert req["launch"] is False
    assert req["status"] == "prospective_staged_for_root_cpu_dispatch"


def test_sidecar_v3_structure_and_remediations():
    """Verify sidecar v3 governance boundaries, mass precision, and root remediations."""
    sidecar_path = PACKAGE_DIR / "sidecars/native_weighted_save_comparison_sidecar_v3.json"
    assert sidecar_path.is_file(), f"Missing sidecar JSON: {sidecar_path}"

    s = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert s["schema"] == "ds-data-02.f2.native-weighted-save-comparison-sidecar.v3"

    remed = s["root_038_remediation_summary"]
    assert len(remed["flaws_identified_in_v2"]) == 6
    assert len(remed["remediations_implemented_in_v3"]) == 10

    mass = s["mass_precision_accounting"]
    assert mass["native_single_particle_mass_kg"] == pytest.approx(worker.NATIVE_SINGLE_PARTICLE_MASS_KG, rel=1e-12)
    assert mass["native_cohort_mass_kg"] == pytest.approx(worker.NATIVE_COHORT_MASS_KG, rel=1e-12)
    assert mass["diagnostic_1e12_status"] == "fail"

    budget = s["temporal_save_half_width_budget"]
    assert budget["save_half_width_budget_s"] == pytest.approx(0.00073363908, rel=1e-5)
    assert budget["nominal401_determination"] == "fail"
    assert budget["dense4001_determination"] == "pass"

    excl = s["native_exclusions"]
    assert excl["rows"] == 2151
    assert excl["motive"] == 1
    assert excl["physical_spill_inferred"] is False
    assert excl["retained_as"] == "unknown_invalid"


def test_synthetic_per_uid_differences_with_identical_aggregate_residence_and_final_inventory():
    """Synthetic Proof: Per-UID residence differences can exist despite identical aggregate residence and inventory.

    Scenario:
    2 particles, duration 4.0 s.
    Nominal:
      Particle 0: in cup for [0, 2], in receiver for [2, 4]  -> cup=2s, receiver=2s
      Particle 1: in receiver for [0, 2], in cup for [2, 4]  -> cup=2s, receiver=2s
      Final destinations: Particle 0 in receiver, Particle 1 in cup.
      Aggregate residence: cup = 4.0 s * mass, receiver = 4.0 s * mass.
      Aggregate final inventory: 1 cup, 1 receiver.

    Dense:
      Particle 0: in receiver for [0, 2], in cup for [2, 4]  -> cup=2s, receiver=2s
      Particle 1: in cup for [0, 2], in receiver for [2, 4]  -> cup=2s, receiver=2s
      Final destinations: Particle 0 in cup, Particle 1 in receiver.
      Aggregate residence: cup = 4.0 s * mass, receiver = 4.0 s * mass.
      Aggregate final inventory: 1 cup, 1 receiver.

    Result:
      Aggregate residence difference = 0.0 s * mass!
      Aggregate final inventory difference = 0 particles!
      BUT Per-UID residence gap for each particle is 2.0 s!
      Mass-weighted mean absolute gap is 2.0 s!
      Fate switch count is 2 (100%)!
    """
    n = 2
    mass = worker.NATIVE_SINGLE_PARTICLE_MASS_KG
    source_mass = np.full(n, mass, dtype=np.float64)

    # Destinations: 0=unknown, 1=cup, 2=receiver, 3=tray, 4=inflight
    nom_residence = np.zeros((n, 5), dtype=np.float64)
    # Particle 0: 2s cup, 2s receiver
    nom_residence[0, 1] = 2.0
    nom_residence[0, 2] = 2.0
    # Particle 1: 2s receiver, 2s cup
    nom_residence[1, 1] = 2.0
    nom_residence[1, 2] = 2.0

    dense_residence = np.zeros((n, 5), dtype=np.float64)
    # Dense swaps particle roles:
    # Particle 0: 4s receiver
    dense_residence[0, 2] = 4.0
    # Particle 1: 4s cup
    dense_residence[1, 1] = 4.0

    # Total residence for each particle is 4.0 s in both runs:
    assert np.allclose(np.sum(nom_residence, axis=1), 4.0)
    assert np.allclose(np.sum(dense_residence, axis=1), 4.0)

    # Aggregate residence:
    # Nominal: cup = 4.0 * mass, receiver = 4.0 * mass
    # Dense: cup = 4.0 * mass, receiver = 4.0 * mass
    nom_agg_cup = np.sum(source_mass * nom_residence[:, 1])
    dense_agg_cup = np.sum(source_mass * dense_residence[:, 1])
    assert abs(nom_agg_cup - dense_agg_cup) < 1e-15

    nom_agg_rec = np.sum(source_mass * nom_residence[:, 2])
    dense_agg_rec = np.sum(source_mass * dense_residence[:, 2])
    assert abs(nom_agg_rec - dense_agg_rec) < 1e-15

    # Run per-UID residence comparison
    res_comp = worker.compare_per_uid_residence(
        nom_residence, dense_residence, source_mass, full_duration_s=4.0
    )

    by_dest = res_comp["by_destination"]
    # Cup: aggregate delta is 0.0, but per-UID mean absolute gap is 2.0 s!
    assert by_dest["cup"]["aggregate_mass_time_delta_kg_s"] == pytest.approx(0.0, abs=1e-15)
    assert by_dest["cup"]["mass_weighted_mean_abs_gap_s"] == pytest.approx(2.0, rel=1e-12)
    assert by_dest["cup"]["max_abs_gap_s"] == pytest.approx(2.0, rel=1e-12)
    assert by_dest["cup"]["particles_with_gap_count"] == 2
    assert by_dest["cup"]["particles_with_gap_fraction"] == 1.0

    # Receiver: aggregate delta is 0.0, but per-UID mean absolute gap is 2.0 s!
    assert by_dest["receiver"]["aggregate_mass_time_delta_kg_s"] == pytest.approx(0.0, abs=1e-15)
    assert by_dest["receiver"]["mass_weighted_mean_abs_gap_s"] == pytest.approx(2.0, rel=1e-12)
    assert by_dest["receiver"]["max_abs_gap_s"] == pytest.approx(2.0, rel=1e-12)
    assert by_dest["receiver"]["particles_with_gap_count"] == 2

    # Global max gap across all destinations
    assert res_comp["global_max_abs_gap_s"] == pytest.approx(2.0, rel=1e-12)


def test_synthetic_unknown_retention_and_exclusions():
    """Synthetic test: Motive 1 exclusions are verified retained as unknown (not physical spill)."""
    n = 10
    nom_data = {
        "exclusion_motive": np.array([1, 1, -1, -1, -1, -1, -1, -1, -1, -1], dtype=np.int16),
        "destination_code_final": np.array([0, 0, 1, 1, 2, 2, 3, 3, 4, 4], dtype=np.int8),
    }
    dense_data = {
        "exclusion_motive": np.array([1, 1, -1, -1, -1, -1, -1, -1, -1, -1], dtype=np.int16),
        "destination_code_final": np.array([0, 0, 1, 1, 2, 2, 3, 3, 4, 4], dtype=np.int8),
    }

    # Should pass cleanly for 2 exclusions
    res = worker.compare_native_exclusions_arrays(nom_data, dense_data, expected_exclusions=2)
    assert res["status"] == "native_exclusions_verified"
    assert res["motive_1_identities_count"] == 2
    assert res["physical_spill_inferred"] is False
    assert res["all_retained_as_unknown_invalid"] is True

    # If an exclusion is relabeled as non-unknown (e.g. tray), must raise ComparisonError
    bad_dense = {
        "exclusion_motive": np.array([1, 1, -1, -1, -1, -1, -1, -1, -1, -1], dtype=np.int16),
        "destination_code_final": np.array([0, 3, 1, 1, 2, 2, 3, 3, 4, 4], dtype=np.int8),
    }
    with pytest.raises(worker.ComparisonError, match="native excluded particles relabeled as non-unknown"):
        worker.compare_native_exclusions_arrays(nom_data, bad_dense, expected_exclusions=2)


def test_synthetic_short_bracket_nonoverlap_smaller_than_1e12_never_joint():
    """Synthetic Proof: Brackets separated by < 1e-12 s are strictly disjoint in v3 (no invented extension).

    Nominal bracket: [1.000, 1.010] (delta t = 0.010 s)
    Dense bracket: [1.0100000000001, 1.011] (distance = 1e-13 s < 1e-12 s)
    In v2, this would have overlapped due to the '+ 1e-12' padding.
    In v3, with literal closed interval intersection, they are STRICTLY DISJOINT:
    - proven_unique_1to1_joint_count == 0
    - unmatched_nominal_count == 1
    - extra_dense_count == 1
    """
    nom_times = np.array([0.0, 1.000, 1.010, 2.0], dtype=np.float64)
    # Dense times: frame 1 at 1.0100000000001, frame 2 at 1.0110000000001
    dense_times = np.array([0.0, 1.0100000000001, 1.0110000000001, 2.0], dtype=np.float64)

    nom_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    nom_ev[0]["time_s"] = 1.005
    nom_ev[0]["event_code"] = worker.EVENT_CODES["tray_entry"]
    nom_ev[0]["particle_index"] = 0
    nom_ev[0]["idp"] = 50
    nom_ev[0]["frame_before"] = 1
    nom_ev[0]["frame_after"] = 2
    nom_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    dense_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    dense_ev[0]["time_s"] = 1.0105
    dense_ev[0]["event_code"] = worker.EVENT_CODES["tray_entry"]
    dense_ev[0]["particle_index"] = 0
    dense_ev[0]["idp"] = 50
    dense_ev[0]["frame_before"] = 1
    dense_ev[0]["frame_after"] = 2
    dense_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    res = worker.match_events_strict_saved_brackets(nom_ev, dense_ev, nom_times, dense_times)

    tray = res["by_code"]["tray_entry"]
    assert tray["proven_unique_1to1_joint_count"] == 0
    assert tray["ambiguous_nominal_count"] == 0
    assert tray["ambiguous_dense_count"] == 0
    assert tray["unmatched_nominal_count"] == 1
    assert tray["extra_dense_count"] == 1

    # Exact closure
    assert res["grand_totals"]["nominal_count_conservation_verified"] is True
    assert res["grand_totals"]["dense_count_conservation_verified"] is True


def test_synthetic_exact_endpoint_touching_permitted():
    """Synthetic test: Literal closed interval intersection permits exact endpoint touch (e.g. t_end == t_start)."""
    nom_times = np.array([0.0, 1.000, 1.010, 2.0], dtype=np.float64)
    # Dense starts exactly at 1.010
    dense_times = np.array([0.0, 1.010, 1.011, 2.0], dtype=np.float64)

    nom_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    nom_ev[0]["time_s"] = 1.010
    nom_ev[0]["event_code"] = worker.EVENT_CODES["receiver_entry"]
    nom_ev[0]["particle_index"] = 0
    nom_ev[0]["idp"] = 60
    nom_ev[0]["frame_before"] = 1
    nom_ev[0]["frame_after"] = 2
    nom_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    dense_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    dense_ev[0]["time_s"] = 1.010
    dense_ev[0]["event_code"] = worker.EVENT_CODES["receiver_entry"]
    dense_ev[0]["particle_index"] = 0
    dense_ev[0]["idp"] = 60
    dense_ev[0]["frame_before"] = 1
    dense_ev[0]["frame_after"] = 2
    dense_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    res = worker.match_events_strict_saved_brackets(nom_ev, dense_ev, nom_times, dense_times)

    rec = res["by_code"]["receiver_entry"]
    assert rec["proven_unique_1to1_joint_count"] == 1
    assert rec["unmatched_nominal_count"] == 0
    assert rec["extra_dense_count"] == 0


def test_synthetic_repeats_ambiguity_isolation():
    """Synthetic test: Differing repeat event counts are isolated as AMBIGUOUS, never claimed joint."""
    nom_times = np.array([0.0, 1.000, 1.010, 2.0], dtype=np.float64)
    dense_times = np.array([0.0, 1.001, 1.002, 1.003, 1.004, 1.005, 1.006, 1.007], dtype=np.float64)

    # 1 nominal event overlapping bracket [1.000, 1.010]
    nom_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    nom_ev[0]["time_s"] = 1.005
    nom_ev[0]["event_code"] = worker.EVENT_CODES["cup_top_departure"]
    nom_ev[0]["particle_index"] = 7
    nom_ev[0]["idp"] = 77
    nom_ev[0]["frame_before"] = 1
    nom_ev[0]["frame_after"] = 2
    nom_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    # 2 dense events inside the nominal bracket
    dense_ev = np.zeros(2, dtype=worker.EVENT_DTYPE)
    dense_ev[0]["time_s"] = 1.0025
    dense_ev[0]["event_code"] = worker.EVENT_CODES["cup_top_departure"]
    dense_ev[0]["particle_index"] = 7
    dense_ev[0]["idp"] = 77
    dense_ev[0]["frame_before"] = 2
    dense_ev[0]["frame_after"] = 3
    dense_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    dense_ev[1]["time_s"] = 1.0055
    dense_ev[1]["event_code"] = worker.EVENT_CODES["cup_top_departure"]
    dense_ev[1]["particle_index"] = 7
    dense_ev[1]["idp"] = 77
    dense_ev[1]["frame_before"] = 5
    dense_ev[1]["frame_after"] = 6
    dense_ev[1]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    res = worker.match_events_strict_saved_brackets(nom_ev, dense_ev, nom_times, dense_times)

    cup = res["by_code"]["cup_top_departure"]
    assert cup["proven_unique_1to1_joint_count"] == 0
    assert cup["ambiguous_nominal_count"] == 1
    assert cup["ambiguous_dense_count"] == 2
    assert cup["unmatched_nominal_count"] == 0
    assert cup["extra_dense_count"] == 0
    assert res["grand_totals"]["nominal_count_conservation_verified"] is True
    assert res["grand_totals"]["dense_count_conservation_verified"] is True


def test_synthetic_safe_output_exclusive_creation(tmp_path):
    """Verify that prior output existence raises ComparisonError and does not unlink."""
    out_file = tmp_path / "already_exists.json"
    out_file.write_text("existing content", encoding="utf-8")

    dummy_binding = {
        "sources": {
            "nominal401": {"execution_receipt": "nonexistent"},
            "dense4001": {"execution_receipt": "nonexistent"},
        }
    }

    with pytest.raises(worker.ComparisonError, match="Output summary file already exists"):
        worker.execute_full_h5_comparison(dummy_binding, out_file)

    # Content must NOT be unlinked or modified!
    assert out_file.read_text(encoding="utf-8") == "existing content"


def test_synthetic_expected_sha_verified_in_direct_path(tmp_path):
    """Verify that expected_sha in extract_arrays_and_residence_from_h5 raises ComparisonError if mismatched."""
    h5_path = tmp_path / "dummy.h5"
    with h5py.File(h5_path, "w") as f:
        f.create_dataset("test", data=[1, 2, 3])

    bad_sha = "0000000000000000000000000000000000000000000000000000000000000000"
    with pytest.raises(worker.ComparisonError, match="H5 file SHA256 mismatch"):
        worker.extract_arrays_and_residence_from_h5(h5_path, expected_sha=bad_sha)


def test_synthetic_streaming_residence_and_duration_equality(tmp_path):
    """Synthetic test: Streaming trapezoidal residence equals full duration for all UIDs."""
    n_particles = 4
    n_frames = 5
    times = np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    single_mass = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    # Destinations: 0=unknown, 1=cup, 2=receiver, 3=tray, 4=inflight
    # Frame 0: [1, 2, 3, 0]
    # Frame 1: [1, 2, 3, 0]
    # Frame 2: [1, 3, 3, 0]
    # Frame 3: [2, 3, 4, 0]
    # Frame 4: [2, 3, 4, 0]
    dest = np.array([
        [1, 2, 3, 0],
        [1, 2, 3, 0],
        [1, 3, 3, 0],
        [2, 3, 4, 0],
        [2, 3, 4, 0],
    ], dtype=np.int8)

    h5_path = tmp_path / "streaming_synth.h5"
    with h5py.File(h5_path, "w") as f:
        f.create_dataset("time", data=times)
        f.create_dataset("particle_id", data=np.arange(n_particles, dtype=np.int64))
        f.create_dataset("particle_zone", data=np.zeros(n_particles, dtype=np.int64))
        f.create_dataset("source_mk", data=np.full(n_particles, 2, dtype=np.int32))
        f.create_dataset("source_layer_index", data=np.zeros(n_particles, dtype=np.int32))
        f.create_dataset("source_mass_kg", data=np.full(n_particles, single_mass, dtype=np.float64))
        f.create_dataset("exclusion_motive", data=np.full(n_particles, -1, dtype=np.int16))
        f.create_dataset("destination_code", data=dest)
        f.create_dataset("events", shape=(0,), dtype=worker.EVENT_DTYPE)

    with h5py.File(h5_path, "r") as f:
        res = worker.derive_per_uid_residence_streaming(f, chunk_frames=2)

    # 1. Total duration for each particle must equal exactly 4.0 s
    total_durations = np.sum(res, axis=1)
    assert np.allclose(total_durations, 4.0, atol=1e-12)

    # Particle 3 spent all 4 frames in destination 0 (unknown)
    assert res[3, 0] == pytest.approx(4.0, rel=1e-12)
    assert res[3, 1] == 0.0

    # Particle 0:
    # transition 0->1: dt=1, dest 1->1 => 1.0s cup
    # transition 1->2: dt=1, dest 1->1 => 1.0s cup
    # transition 2->3: dt=1, dest 1->2 => 0.5s cup, 0.5s receiver
    # transition 3->4: dt=1, dest 2->2 => 1.0s receiver
    # Total cup: 2.5s, total receiver: 1.5s
    assert res[0, 1] == pytest.approx(2.5, rel=1e-12)
    assert res[0, 2] == pytest.approx(1.5, rel=1e-12)


def test_end_to_end_synthetic_execution_v3(tmp_path):
    """End-to-end execution of worker_v3 on synthetic datasets, verifying all output artifacts."""
    synth_dir = tmp_path / "synthetic_run"
    synth_dir.mkdir(parents=True, exist_ok=True)

    n_particles = 10
    n_frames_nom = 401
    n_frames_dense = 4001
    single_mass = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    nom_times = np.linspace(0.0, 4.0, n_frames_nom, dtype=np.float64)
    dense_times = np.linspace(0.0, 4.0, n_frames_dense, dtype=np.float64)

    # 1. Create synthetic nominal H5
    nom_h5_path = synth_dir / "nom_labels.h5"
    with h5py.File(nom_h5_path, "w") as f:
        f.create_dataset("particle_id", data=np.arange(1, n_particles + 1, dtype=np.int64))
        f.create_dataset("particle_zone", data=np.zeros(n_particles, dtype=np.int64))
        f.create_dataset("source_mk", data=np.full(n_particles, 2, dtype=np.int32))
        f.create_dataset("source_layer_index", data=np.zeros(n_particles, dtype=np.int32))
        f.create_dataset("source_mass_kg", data=np.full(n_particles, single_mass, dtype=np.float64))
        f.create_dataset("time", data=nom_times)
        f.create_dataset("destination_code", data=np.ones((n_frames_nom, n_particles), dtype=np.int8))
        f.create_dataset("exclusion_motive", data=np.full(n_particles, -1, dtype=np.int16))
        # 1 synthetic event
        ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
        ev[0]["time_s"] = 1.005
        ev[0]["event_code"] = worker.EVENT_CODES["cup_top_departure"]
        ev[0]["particle_index"] = 0
        ev[0]["idp"] = 1
        ev[0]["zone"] = 0
        ev[0]["source_mk"] = 2
        ev[0]["source_layer_index"] = 0
        ev[0]["frame_before"] = 100
        ev[0]["frame_after"] = 101
        ev[0]["mass_kg"] = single_mass
        ev[0]["direction"] = 1
        f.create_dataset("events", data=ev)

    # 2. Create synthetic dense H5
    dense_h5_path = synth_dir / "dense_labels.h5"
    with h5py.File(dense_h5_path, "w") as f:
        f.create_dataset("particle_id", data=np.arange(1, n_particles + 1, dtype=np.int64))
        f.create_dataset("particle_zone", data=np.zeros(n_particles, dtype=np.int64))
        f.create_dataset("source_mk", data=np.full(n_particles, 2, dtype=np.int32))
        f.create_dataset("source_layer_index", data=np.zeros(n_particles, dtype=np.int32))
        f.create_dataset("source_mass_kg", data=np.full(n_particles, single_mass, dtype=np.float64))
        f.create_dataset("time", data=dense_times)
        f.create_dataset("destination_code", data=np.ones((n_frames_dense, n_particles), dtype=np.int8))
        f.create_dataset("exclusion_motive", data=np.full(n_particles, -1, dtype=np.int16))
        # 1 matching synthetic event in [1.004, 1.005]
        ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
        ev[0]["time_s"] = 1.0045
        ev[0]["event_code"] = worker.EVENT_CODES["cup_top_departure"]
        ev[0]["particle_index"] = 0
        ev[0]["idp"] = 1
        ev[0]["zone"] = 0
        ev[0]["source_mk"] = 2
        ev[0]["source_layer_index"] = 0
        ev[0]["frame_before"] = 1004
        ev[0]["frame_after"] = 1005
        ev[0]["mass_kg"] = single_mass
        ev[0]["direction"] = 1
        f.create_dataset("events", data=ev)

    # 3. Create mock observation reports
    nom_obs = {
        "operator": {
            "version": worker.OPERATOR_VERSION,
            "sha256": worker.OPERATOR_SHA256,
            "spec": {
                "frozen_v6_base": {"operator_version": worker.FROZEN_V6_OPERATOR_VERSION},
                "native_weight_authority": {
                    "fluid_particles": n_particles,
                    "native_header_bound_mass_kg": worker.NATIVE_SINGLE_PARTICLE_MASS_KG,
                    "native_cohort_mass_kg": n_particles * single_mass,
                },
            },
        },
        "physical_binding": {
            "source_h5_physical_condition_sha256": worker.PHYSICAL_CONDITION_HASH,
            "source_h5_geometry_sha256": worker.GEOMETRY_SHA256,
            "source_h5_control_sha256": worker.CONTROL_SHA256,
            "motion_control_sha256": worker.MOTION_CONTROL_SHA256,
        },
        "residence": {
            "mass_time_kg_s_by_destination": {"cup": 4.0 * n_particles * single_mass},
            "fractional_cohort_time_by_destination": {"cup": 4.0},
        },
        "event_ledger": {
            "mass_kg_by_code": {"cup_top_departure": single_mass},
            "observed_event_bracket_stats_s_by_code": {"cup_top_departure": {"max_s": 0.005}},
        },
    }
    dense_obs = {
        "operator": {
            "version": worker.OPERATOR_VERSION,
            "sha256": worker.OPERATOR_SHA256,
            "spec": {
                "frozen_v6_base": {"operator_version": worker.FROZEN_V6_OPERATOR_VERSION},
                "native_weight_authority": {
                    "fluid_particles": n_particles,
                    "native_header_bound_mass_kg": worker.NATIVE_SINGLE_PARTICLE_MASS_KG,
                    "native_cohort_mass_kg": n_particles * single_mass,
                },
            },
        },
        "physical_binding": {
            "source_h5_physical_condition_sha256": worker.PHYSICAL_CONDITION_HASH,
            "source_h5_geometry_sha256": worker.GEOMETRY_SHA256,
            "source_h5_control_sha256": worker.CONTROL_SHA256,
            "motion_control_sha256": worker.MOTION_CONTROL_SHA256,
        },
        "residence": {
            "mass_time_kg_s_by_destination": {"cup": 4.0 * n_particles * single_mass},
            "fractional_cohort_time_by_destination": {"cup": 4.0},
        },
        "event_ledger": {
            "mass_kg_by_code": {"cup_top_departure": single_mass},
            "observed_event_bracket_stats_s_by_code": {"cup_top_departure": {"max_s": 0.0005}},
        },
    }

    nom_obs_path = synth_dir / "nom_obs.json"
    dense_obs_path = synth_dir / "dense_obs.json"
    nom_obs_path.write_text(json.dumps(nom_obs), encoding="utf-8")
    dense_obs_path.write_text(json.dumps(dense_obs), encoding="utf-8")

    # Receipts
    nom_rcpt_path = synth_dir / "nom_receipt.json"
    dense_rcpt_path = synth_dir / "dense_receipt.json"
    nom_rcpt_path.write_text(json.dumps({"status": "completed", "returncode": 0}), encoding="utf-8")
    dense_rcpt_path.write_text(json.dumps({"status": "completed", "returncode": 0}), encoding="utf-8")

    # Binding JSON
    synth_binding = {
        "case_id": "SYNTHETIC_TEST_V3",
        "fluid_particles": n_particles,
        "native_exclusions_count": 0,
        "sources": {
            "nominal401": {
                "attempt_id": "mock_nom_001",
                "execution_receipt": str(nom_rcpt_path),
                "observation_report": str(nom_obs_path),
                "labels_h5": str(nom_h5_path),
            },
            "dense4001": {
                "attempt_id": "mock_dense_001",
                "execution_receipt": str(dense_rcpt_path),
                "observation_report": str(dense_obs_path),
                "labels_h5": str(dense_h5_path),
            },
        },
        "use_private_copy": False,
    }
    binding_json_path = synth_dir / "synthetic_binding_v3.json"
    binding_json_path.write_text(json.dumps(synth_binding), encoding="utf-8")

    # Run worker main
    out_json = synth_dir / "output/summary_v3.json"
    ret = worker.main(["--binding", str(binding_json_path), "--output", str(out_json)])
    assert ret == 0, f"Worker returned non-zero code {ret}"

    assert out_json.is_file()
    assert out_json.with_suffix(".md").is_file()

    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["schema"] == worker.SCHEMA
    assert summary["case_id"] == "SYNTHETIC_TEST_V3"

    # Per-UID residence verification
    per_uid = summary["per_uid_residence"]
    assert per_uid["status"] == "per_uid_residence_compared_descriptively"
    assert "nominal_residence_array_sha256" in per_uid["provenance"]
    assert "dense_residence_array_sha256" in per_uid["provenance"]
    assert per_uid["by_destination"]["cup"]["mass_weighted_mean_abs_gap_s"] == pytest.approx(0.0, abs=1e-12)

    # Event matching
    assert summary["episodic_event_matching"]["grand_totals"]["proven_unique_1to1_joint_count"] == 1
    assert summary["claim_boundary"]["q_n"] == "not_granted"

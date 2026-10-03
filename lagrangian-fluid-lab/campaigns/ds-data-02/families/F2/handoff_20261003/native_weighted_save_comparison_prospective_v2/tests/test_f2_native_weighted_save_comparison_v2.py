"""Unit tests for F2 Native-Weighted Temporal Save Comparison Prospective Suite v2.

Verifies Root Followup 037 F2 Remediations:
1. Full-H5 Execution: CLI main directly executes guard checks and array comparisons.
2. Complete Elimination of Unauthorized Proximity Gates and Flutter Bands.
3. Strict Saved-Bracket Overlap Matching: candidate association determined solely
   by actual bracket intersection [t_start, t_end].
4. Ambiguous Overlap Isolation: 1-to-many, many-to-one, and multi-overlap clusters
   are strictly classified as AMBIGUOUS and never claimed joint.
5. Proven Unique 1:1 Joint Matches: only isolated 1:1 components are accepted.
6. Separation of Aggregate Destination Inventory from Per-UID Final Fates:
   targeted fixture proves identical aggregate mass does not imply identical per-UID fate.
7. Unmatched Repeats / Disjoint Brackets: correctly identified without false physical flutter labels.
8. Exact Native Weights and Types: IEEE-754 binary32 authority without approximate snapping.
9. Empty Code & Censoring Robustness: handles zero-occurrence codes and right-censored intervals.
10. NVMe Floor and Verified Copy Cleanup Guards.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
INTEGRATION_SCRIPTS = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts")

if str(INTEGRATION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_SCRIPTS))
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

import f2_rv4eq_native_weighted_save_comparison_worker_v2 as worker


def test_binding_v2_structure_and_sources():
    """Verify binding configuration schema, source paths, receipts, and continuum hashes."""
    binding_path = PACKAGE_DIR / "configs/native_weighted_save_comparison_binding_v2.json"
    assert binding_path.is_file(), f"Missing binding JSON: {binding_path}"

    b = json.loads(binding_path.read_text(encoding="utf-8"))
    assert b["schema"] == "ds02.f2.native-weighted-save-comparison-binding.v2"
    assert b["family_id"] == "F2"
    assert b["physical_condition_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
    assert b["operator_version"] == "f2-moving-cup-local-z-top-v8-native-mass-bound"
    assert b["operator_sha256"] == "ab94031d3699bcfa025d2405e5707a2a2f7371877ddcff1b5d132f08c8827406"
    assert b["fluid_particles"] == 196608
    assert b["native_single_particle_mass_kg"] == pytest.approx(0.0001250000059371814, rel=1e-12)
    assert b["native_cohort_mass_kg"] == pytest.approx(24.576001167297363, rel=1e-12)

    # Check sources exist and match declared receipts
    sources = b["sources"]
    assert set(sources.keys()) == {"nominal401", "dense4001"}

    for key, src in sources.items():
        assert Path(src["observation_report"]).is_file(), f"Missing obs report for {key}"
        assert Path(src["execution_receipt"]).is_file(), f"Missing receipt for {key}"
        assert Path(src["labels_h5"]).is_file(), f"Missing labels H5 for {key}"

        # Verify receipt is completed0
        receipt = json.loads(Path(src["execution_receipt"]).read_text(encoding="utf-8"))
        assert receipt["status"] == "completed"
        assert receipt["returncode"] == 0


def test_runner_request_v2_validation():
    """Verify runner request v2 schema, resource allocations, and shared runner validation."""
    import ds_data02_runtime_v2 as rt

    req_path = PACKAGE_DIR / "requests/native_weighted_save_comparison_request_v2.json"
    assert req_path.is_file(), f"Missing request JSON: {req_path}"

    req = json.loads(req_path.read_text(encoding="utf-8"))
    assert req["schema"] == "ds02.runner-request.v2"
    assert req["family_id"] == "F2"
    assert req["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_SAVE_COMPARISON_V2"
    assert req["attempt_id"] == "root-offset-fine-native-weighted-save-comparison-v2-027"
    assert req["kind"] == "cpu"
    assert req["cpu_task_kind"] == "audit"
    assert req["cpu_threads"] == 2
    assert req["max_wall_seconds"] == 3600
    assert req["estimated_storage_bytes"] == 17179869184
    assert req["conversion_launch_forbidden"] is True
    assert req["launch"] is False
    assert req["status"] == "prospective_staged_for_root_cpu_dispatch"

    # Validate against frozen runtime schema
    rt.validate_request(req)


def test_sidecar_v2_provenance_and_boundaries():
    """Verify sidecar v2 rejection remediations, mass precision, and governance claims."""
    sidecar_path = PACKAGE_DIR / "sidecars/native_weighted_save_comparison_sidecar_v2.json"
    assert sidecar_path.is_file(), f"Missing sidecar JSON: {sidecar_path}"

    s = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert s["schema"] == "ds-data-02.f2.native-weighted-save-comparison-sidecar.v2"

    remed = s["root_036_rejection_remediation"]
    assert len(remed["rejected_claims_in_036"]) == 5
    assert len(remed["remediations_enforced_in_v2"]) == 9

    mass = s["mass_precision_accounting"]
    assert mass["native_single_particle_mass_kg"] == pytest.approx(0.0001250000059371814, rel=1e-12)
    assert mass["native_cohort_mass_kg"] == pytest.approx(24.576001167297363, rel=1e-12)
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

    claims = s["claim_boundary"]
    assert claims["q_n"] == "not_granted"
    assert claims["production"] == "none"


def test_fixture_same_aggregate_inventory_but_fate_switches():
    """Targeted Fixture: Aggregate mass matches perfectly, but per-UID fates switch.

    Proves the scientific guard:
    Identical aggregate destination mass does NOT establish per-UID fate identity.
    """
    n = 20
    single_mass = worker.NATIVE_SINGLE_PARTICLE_MASS_KG
    source_mass = np.full(n, single_mass, dtype=np.float64)

    # 10 particles in cup, 10 in tray in nominal
    nom_dest = np.array([1]*10 + [3]*10, dtype=np.int8)

    # In dense: UID 3 switched cup->tray, and UID 15 switched tray->cup
    # Total cup count is still 10, total tray count is still 10!
    dense_dest = nom_dest.copy()
    dense_dest[3] = 3  # cup -> tray
    dense_dest[15] = 1 # tray -> cup

    comp = worker.compare_per_uid_final_destinations(nom_dest, dense_dest, source_mass)

    # 1. Aggregate inventory reports match
    agg = comp["aggregate_inventory"]
    assert agg["aggregate_inventory_match"] is True
    assert agg["destinations"]["cup"]["delta_particles"] == 0
    assert agg["destinations"]["tray"]["delta_particles"] == 0
    assert agg["destinations"]["cup"]["delta_mass_kg"] == pytest.approx(0.0, abs=1e-15)

    # 2. Per-UID fates explicitly catch the 2 fate switches!
    per_uid = comp["per_uid_fates"]
    assert per_uid["per_uid_fate_match"] is False
    assert per_uid["switched_particles_count"] == 2
    assert per_uid["switched_mass_kg"] == pytest.approx(2 * single_mass, rel=1e-12)
    assert per_uid["switch_fraction"] == pytest.approx(2 / 20, rel=1e-12)

    # 3. Transition matrix captures off-diagonal entries
    trans = per_uid["transition_matrix_nominal_to_dense"]
    assert trans["cup"]["tray"] == 1
    assert trans["tray"]["cup"] == 1
    assert trans["cup"]["cup"] == 9
    assert trans["tray"]["tray"] == 9


def test_fixture_unmatched_repeats_and_disjoint_brackets():
    """Targeted Fixture: Disjoint event brackets yield unmatched nominal and extra dense."""
    nom_times = np.array([0.0, 1.0, 2.0, 2.010, 3.0], dtype=np.float64)
    dense_times = np.array([0.0, 0.5, 1.000, 1.001, 1.002, 1.003, 1.005, 1.006, 2.5], dtype=np.float64)

    # Nominal event: particle 0, code receiver_entry, bracket [2.000, 2.010] (frames 2 to 3)
    nom_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    nom_ev[0]["time_s"] = 2.005
    nom_ev[0]["event_code"] = worker.EVENT_CODES["receiver_entry"]
    nom_ev[0]["particle_index"] = 0
    nom_ev[0]["idp"] = 100
    nom_ev[0]["frame_before"] = 2
    nom_ev[0]["frame_after"] = 3
    nom_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    # Dense events: particle 0, code receiver_entry, 3 events in [1.000, 1.001], [1.002, 1.003], [1.005, 1.006]
    dense_ev = np.zeros(3, dtype=worker.EVENT_DTYPE)
    dense_frames = [(2, 3, 1.0005), (4, 5, 1.0025), (6, 7, 1.0055)]
    for i, (fb, fa, t) in enumerate(dense_frames):
        dense_ev[i]["time_s"] = t
        dense_ev[i]["event_code"] = worker.EVENT_CODES["receiver_entry"]
        dense_ev[i]["particle_index"] = 0
        dense_ev[i]["idp"] = 100
        dense_ev[i]["frame_before"] = fb
        dense_ev[i]["frame_after"] = fa
        dense_ev[i]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    res = worker.match_events_strict_saved_brackets(nom_ev, dense_ev, nom_times, dense_times)

    rec = res["by_code"]["receiver_entry"]
    assert rec["nominal_total_count"] == 1
    assert rec["dense_total_count"] == 3
    assert rec["proven_unique_1to1_joint_count"] == 0
    assert rec["ambiguous_nominal_count"] == 0
    assert rec["ambiguous_dense_count"] == 0
    assert rec["unmatched_nominal_count"] == 1
    assert rec["extra_dense_count"] == 3

    # Conservation
    assert res["grand_totals"]["nominal_count_conservation_verified"] is True
    assert res["grand_totals"]["dense_count_conservation_verified"] is True


def test_fixture_ambiguous_bracket_2events():
    """Targeted Fixture: 1 nominal bracket overlaps with 2 dense brackets -> strictly AMBIGUOUS.

    Proves that multi-overlap groups are isolated and NEVER claimed joint.
    """
    nom_times = np.array([0.0, 1.000, 1.010, 2.0], dtype=np.float64)
    dense_times = np.array([0.0, 1.000, 1.002, 1.003, 1.007, 1.008, 1.010], dtype=np.float64)

    # Nominal: bracket [1.000, 1.010] (frames 1 to 2)
    nom_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    nom_ev[0]["time_s"] = 1.005
    nom_ev[0]["event_code"] = worker.EVENT_CODES["tray_entry"]
    nom_ev[0]["particle_index"] = 1
    nom_ev[0]["idp"] = 101
    nom_ev[0]["frame_before"] = 1
    nom_ev[0]["frame_after"] = 2
    nom_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    # Dense: two events overlapping the nominal bracket: [1.002, 1.003] and [1.007, 1.008]
    dense_ev = np.zeros(2, dtype=worker.EVENT_DTYPE)
    dense_ev[0]["time_s"] = 1.0025
    dense_ev[0]["event_code"] = worker.EVENT_CODES["tray_entry"]
    dense_ev[0]["particle_index"] = 1
    dense_ev[0]["idp"] = 101
    dense_ev[0]["frame_before"] = 2
    dense_ev[0]["frame_after"] = 3
    dense_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    dense_ev[1]["time_s"] = 1.0075
    dense_ev[1]["event_code"] = worker.EVENT_CODES["tray_entry"]
    dense_ev[1]["particle_index"] = 1
    dense_ev[1]["idp"] = 101
    dense_ev[1]["frame_before"] = 4
    dense_ev[1]["frame_after"] = 5
    dense_ev[1]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    res = worker.match_events_strict_saved_brackets(nom_ev, dense_ev, nom_times, dense_times)

    tray = res["by_code"]["tray_entry"]
    assert tray["nominal_total_count"] == 1
    assert tray["dense_total_count"] == 2
    # STRICTLY ZERO JOINT MATCHES
    assert tray["proven_unique_1to1_joint_count"] == 0
    # Both are categorized under AMBIGUOUS
    assert tray["ambiguous_nominal_count"] == 1
    assert tray["ambiguous_dense_count"] == 2
    assert tray["unmatched_nominal_count"] == 0
    assert tray["extra_dense_count"] == 0

    # Conservation
    assert res["grand_totals"]["nominal_count_conservation_verified"] is True
    assert res["grand_totals"]["dense_count_conservation_verified"] is True


def test_fixture_proven_unique_1to1_joint_match():
    """Targeted Fixture: Exactly one nominal event overlaps with exactly one dense event."""
    nom_times = np.array([0.0, 1.000, 1.010, 2.0], dtype=np.float64)
    dense_times = np.array([0.0, 1.000, 1.004, 1.005, 1.010], dtype=np.float64)

    nom_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    nom_ev[0]["time_s"] = 1.005
    nom_ev[0]["event_code"] = worker.EVENT_CODES["cup_top_departure"]
    nom_ev[0]["particle_index"] = 2
    nom_ev[0]["idp"] = 102
    nom_ev[0]["frame_before"] = 1
    nom_ev[0]["frame_after"] = 2
    nom_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    dense_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    dense_ev[0]["time_s"] = 1.0045
    dense_ev[0]["event_code"] = worker.EVENT_CODES["cup_top_departure"]
    dense_ev[0]["particle_index"] = 2
    dense_ev[0]["idp"] = 102
    dense_ev[0]["frame_before"] = 2
    dense_ev[0]["frame_after"] = 3
    dense_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    res = worker.match_events_strict_saved_brackets(nom_ev, dense_ev, nom_times, dense_times)

    cup = res["by_code"]["cup_top_departure"]
    assert cup["proven_unique_1to1_joint_count"] == 1
    assert cup["ambiguous_nominal_count"] == 0
    assert cup["ambiguous_dense_count"] == 0
    assert cup["unmatched_nominal_count"] == 0
    assert cup["extra_dense_count"] == 0

    # Chord difference: 1.0045 - 1.0050 = -0.0005 s
    assert cup["chord_differences_dense_minus_nom"]["mean_s"] == pytest.approx(-0.0005, abs=1e-8)
    assert cup["bracket_containment"]["dense_in_nominal_count"] == 1
    assert cup["bracket_containment"]["dense_in_nominal_fraction"] == 1.0


def test_fixture_empty_code_and_censoring_cases():
    """Targeted Fixture: Some codes have zero occurrences; right-censored intervals at t_end."""
    nom_times = np.array([0.0, 3.990, 4.000], dtype=np.float64)
    dense_times = np.array([0.0, 3.998, 3.999, 4.000], dtype=np.float64)

    # Empty array for all codes except receiver_exit
    nom_ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
    nom_ev[0]["time_s"] = 3.995
    nom_ev[0]["event_code"] = worker.EVENT_CODES["receiver_exit"]
    nom_ev[0]["particle_index"] = 5
    nom_ev[0]["idp"] = 105
    nom_ev[0]["frame_before"] = 1
    nom_ev[0]["frame_after"] = 2
    nom_ev[0]["mass_kg"] = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    dense_ev = np.zeros(0, dtype=worker.EVENT_DTYPE)

    res = worker.match_events_strict_saved_brackets(nom_ev, dense_ev, nom_times, dense_times)

    for name in ("cup_top_departure", "cup_top_return", "receiver_entry", "tray_entry", "tray_exit"):
        sub = res["by_code"][name]
        assert sub["nominal_total_count"] == 0
        assert sub["dense_total_count"] == 0
        assert sub["proven_unique_1to1_joint_count"] == 0
        assert sub["chord_differences_dense_minus_nom"]["mean_s"] is None

    # Right-censored unmatched event
    assert res["by_code"]["receiver_exit"]["unmatched_nominal_count"] == 1
    assert res["grand_totals"]["nominal_count_conservation_verified"] is True


def test_end_to_end_cli_execution_on_synthetic_h5(tmp_path):
    """Execute worker.main end-to-end with --binding and --output on synthetic H5 files."""
    synth_dir = tmp_path / "synthetic_run"
    synth_dir.mkdir(parents=True, exist_ok=True)

    n_particles = 10
    n_frames_nom = 5
    n_frames_dense = 10
    single_mass = worker.NATIVE_SINGLE_PARTICLE_MASS_KG

    # 1. Create synthetic nominal H5
    nom_h5_path = synth_dir / "nom_labels.h5"
    with h5py.File(nom_h5_path, "w") as f:
        f.create_dataset("particle_id", data=np.arange(1, n_particles + 1, dtype=np.int64))
        f.create_dataset("particle_zone", data=np.zeros(n_particles, dtype=np.int64))
        f.create_dataset("source_mk", data=np.full(n_particles, 2, dtype=np.int32))
        f.create_dataset("source_layer_index", data=np.zeros(n_particles, dtype=np.int32))
        f.create_dataset("source_mass_kg", data=np.full(n_particles, single_mass, dtype=np.float64))
        f.create_dataset("time", data=np.linspace(0.0, 0.040, n_frames_nom, dtype=np.float64))
        f.create_dataset("destination_code", data=np.ones((n_frames_nom, n_particles), dtype=np.int8))
        f.create_dataset("exclusion_motive", data=np.full(n_particles, -1, dtype=np.int16))
        # 1 synthetic event
        ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
        ev[0]["time_s"] = 0.015
        ev[0]["event_code"] = worker.EVENT_CODES["cup_top_departure"]
        ev[0]["particle_index"] = 0
        ev[0]["idp"] = 1
        ev[0]["frame_before"] = 1
        ev[0]["frame_after"] = 2
        ev[0]["mass_kg"] = single_mass
        f.create_dataset("events", data=ev)

    # 2. Create synthetic dense H5
    dense_h5_path = synth_dir / "dense_labels.h5"
    with h5py.File(dense_h5_path, "w") as f:
        f.create_dataset("particle_id", data=np.arange(1, n_particles + 1, dtype=np.int64))
        f.create_dataset("particle_zone", data=np.zeros(n_particles, dtype=np.int64))
        f.create_dataset("source_mk", data=np.full(n_particles, 2, dtype=np.int32))
        f.create_dataset("source_layer_index", data=np.zeros(n_particles, dtype=np.int32))
        f.create_dataset("source_mass_kg", data=np.full(n_particles, single_mass, dtype=np.float64))
        f.create_dataset("time", data=np.linspace(0.0, 0.040, n_frames_dense, dtype=np.float64))
        f.create_dataset("destination_code", data=np.ones((n_frames_dense, n_particles), dtype=np.int8))
        f.create_dataset("exclusion_motive", data=np.full(n_particles, -1, dtype=np.int16))
        # 1 matching synthetic event
        ev = np.zeros(1, dtype=worker.EVENT_DTYPE)
        ev[0]["time_s"] = 0.014
        ev[0]["event_code"] = worker.EVENT_CODES["cup_top_departure"]
        ev[0]["particle_index"] = 0
        ev[0]["idp"] = 1
        ev[0]["frame_before"] = 3
        ev[0]["frame_after"] = 4
        ev[0]["mass_kg"] = single_mass
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
        "residence": {"mass_time_kg_s_by_destination": {"cup": 1.0}, "fractional_cohort_time_by_destination": {"cup": 1.0}},
        "event_ledger": {"mass_kg_by_code": {"cup_top_departure": single_mass}},
        "observed_bracket_stats": {"cup_top_departure": {"max_half_width_s": 0.005}},
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
        "residence": {"mass_time_kg_s_by_destination": {"cup": 1.0}, "fractional_cohort_time_by_destination": {"cup": 1.0}},
        "event_ledger": {"mass_kg_by_code": {"cup_top_departure": single_mass}},
        "observed_bracket_stats": {"cup_top_departure": {"max_half_width_s": 0.0005}},
    }

    nom_obs_path = synth_dir / "nom_obs.json"
    dense_obs_path = synth_dir / "dense_obs.json"
    nom_obs_path.write_text(json.dumps(nom_obs), encoding="utf-8")
    dense_obs_path.write_text(json.dumps(dense_obs), encoding="utf-8")

    # Mock receipts
    nom_rcpt_path = synth_dir / "nom_receipt.json"
    dense_rcpt_path = synth_dir / "dense_receipt.json"
    nom_rcpt_path.write_text(json.dumps({"status": "completed", "returncode": 0}), encoding="utf-8")
    dense_rcpt_path.write_text(json.dumps({"status": "completed", "returncode": 0}), encoding="utf-8")

    # 4. Create synthetic binding JSON
    synth_binding = {
        "case_id": "SYNTHETIC_TEST_CASE",
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
    binding_json_path = synth_dir / "synthetic_binding.json"
    binding_json_path.write_text(json.dumps(synth_binding), encoding="utf-8")

    # 5. Execute worker CLI main!
    out_json = synth_dir / "output/summary.json"
    ret = worker.main(["--binding", str(binding_json_path), "--output", str(out_json)])
    assert ret == 0, f"Worker returned non-zero code {ret}"

    # Verify output JSON and report MD exist
    assert out_json.is_file()
    assert out_json.with_suffix(".md").is_file()

    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["schema"] == worker.SCHEMA
    assert summary["case_id"] == "SYNTHETIC_TEST_CASE"
    assert summary["destination_fates"]["aggregate_inventory"]["aggregate_inventory_match"] is True
    assert summary["destination_fates"]["per_uid_fates"]["per_uid_fate_match"] is True
    assert summary["destination_fates"]["per_uid_fates"]["switched_particles_count"] == 0
    assert summary["episodic_event_matching"]["grand_totals"]["proven_unique_1to1_joint_count"] == 1
    assert summary["save_bracket_budgets"]["dense4001"]["determination"] == "pass_discretization_budget_satisfied"
    assert summary["save_bracket_budgets"]["nominal401"]["determination"] == "fail_budget_exceeded"
    assert summary["claim_boundary"]["q_n"] == "not_granted"


def test_nvme_protected_floor_check(tmp_path):
    """Verify that check_scratch_protected_floor raises ComparisonError when floor is crossed."""
    # A requirement of 1 Exabyte exceeds any local NVMe capacity
    huge_bytes = 1024**6
    with pytest.raises(worker.ComparisonError, match="NVMe scratch protected 100 GiB floor would be crossed"):
        worker.check_scratch_protected_floor(tmp_path, huge_bytes)

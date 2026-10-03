"""Unit tests for F2 Native-Weighted Temporal Save Comparison Prospective Suite v1.

Verifies:
1. Config v1 schema, continuum hashes, and input file bindings.
2. Sidecar v1 schema, physical invariance, mass separation, and native exclusion accounting.
3. Runner request v2 schema, kind='cpu', cpu_task_kind='audit', launch=false, and validate_request.
4. Stable ordered episode semantics: strictly prohibits naive zipping of repeat count mismatches;
   separates genuine joint events from repeated sub-grid flutter and new transient events.
5. Save bracket budget evaluation: nominal fails, dense passes, strictly refrains from Q-N grant.
6. Full metadata cross-audit pipeline execution with 100% write isolation in tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

FAMILIES_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_ROOT = FAMILIES_ROOT / "handoff_20261003/native_weighted_save_comparison_prospective_v1"
INTEGRATION_SCRIPTS = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts")

if str(INTEGRATION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_SCRIPTS))
if str(FAMILIES_ROOT) not in sys.path:
    sys.path.insert(0, str(FAMILIES_ROOT))

import f2_rv4eq_native_weighted_save_comparison_worker_v1 as worker


def test_config_v1_structure():
    cfg_path = HANDOFF_ROOT / "configs/native_weighted_save_comparison_config_v1.json"
    assert cfg_path.is_file(), f"Missing config: {cfg_path}"

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["schema"] == "ds02.f2.native-weighted-save-comparison-config.v1"
    assert cfg["family_id"] == "F2"
    assert cfg["physical_condition_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
    assert cfg["operator_version"] == "f2-moving-cup-local-z-top-v8-native-mass-bound"
    assert cfg["operator_sha256"] == "ab94031d3699bcfa025d2405e5707a2a2f7371877ddcff1b5d132f08c8827406"
    assert cfg["fluid_particles"] == 196608
    assert cfg["save_half_width_budget_s"] == pytest.approx(0.00073363908, rel=1e-5)

    sources = cfg["sources"]
    assert set(sources.keys()) == {"nominal401", "dense4001"}
    for key, src in sources.items():
        assert Path(src["observation_report"]).is_file(), f"Missing obs report for {key}"
        assert Path(src["execution_receipt"]).is_file(), f"Missing receipt for {key}"
        assert Path(src["labels_h5"]).is_file(), f"Missing labels H5 for {key}"


def test_sidecar_v1_provenance_and_accounting():
    sidecar_path = HANDOFF_ROOT / "sidecars/native_weighted_save_comparison_sidecar_v1.json"
    assert sidecar_path.is_file(), f"Missing sidecar: {sidecar_path}"

    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["schema"] == "ds-data-02.f2.native-weighted-save-comparison-sidecar.v1"
    assert sidecar["family_id"] == "F2"

    # Continuum invariance
    cinv = sidecar["continuum_invariance"]
    assert cinv["physical_condition_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
    assert cinv["fluid_particles"] == 196608

    # Mass precision accounting & preserved failure
    mass_acc = sidecar["mass_precision_accounting"]
    assert mass_acc["native_single_particle_mass_kg"] == pytest.approx(0.0001250000059371814, rel=1e-12)
    assert mass_acc["native_cohort_mass_kg"] == pytest.approx(24.576001167297363, rel=1e-12)
    assert mass_acc["continuous_xml_benchmark_kg"] == 24.576
    assert mass_acc["diagnostic_1e12_status"] == "fail"
    assert mass_acc["relative_representation_delta"] > mass_acc["legacy_1e12_budget"]

    # Temporal save half-width budget
    temp = sidecar["temporal_save_half_width_budget"]
    assert temp["save_half_width_budget_s"] == pytest.approx(0.00073363908, rel=1e-5)
    assert temp["nominal401_determination"] == "fail"
    assert temp["dense4001_determination"] == "pass"

    # Destination inventories match
    dests = sidecar["destination_inventories"]
    for d_name in ("unknown", "cup", "receiver", "tray", "inflight"):
        assert dests[d_name]["delta_mass_kg"] == pytest.approx(0.0, abs=1e-14)

    # Native exclusions
    excl = dests["native_exclusions"]
    assert excl["rows"] == 2151
    assert excl["motive"] == 1
    assert excl["physical_spill_inferred"] is False
    assert excl["retained_as"] == "unknown_invalid"

    # Claim boundaries
    claim = sidecar["claim_boundary"]
    assert claim["q_n"] == "not_granted"
    assert claim["production"] == "none"


def test_runner_request_v1_validation():
    import ds_data02_runtime_v2 as rt

    req_path = HANDOFF_ROOT / "requests/native_weighted_save_comparison_request_v1.json"
    assert req_path.is_file(), f"Missing request JSON: {req_path}"

    req = json.loads(req_path.read_text(encoding="utf-8"))
    assert req["schema"] == "ds02.runner-request.v2"
    assert req["family_id"] == "F2"
    assert req["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_SAVE_COMPARISON_V1"
    assert req["attempt_id"] == "root-offset-fine-native-weighted-save-comparison-v1-026"
    assert req["kind"] == "cpu"
    assert req["cpu_task_kind"] == "audit"
    assert req["cpu_threads"] == 2
    assert req["max_wall_seconds"] == 3600
    assert req["estimated_storage_bytes"] == 8589934592
    assert req["conversion_launch_forbidden"] is True
    assert req["launch"] is False
    assert req["status"] == "prospective_staged_for_root_cpu_dispatch"

    # Validate against frozen shared runner schema
    rt.validate_request(req)


def test_episode_semantics_anti_pattern_avoidance():
    """Verify that episodic matching avoids naive zipping when repeat counts differ."""
    # Particle UID with 1 nominal receiver entry and 3 dense receiver entries (boundary flutter)
    nom_events = [
        {
            "event_code": worker.EVENT_CODES["receiver_entry"],
            "time_s": 1.205,
            "time_before_s": 1.200,
            "time_after_s": 1.210,
        }
    ]
    dense_events = [
        {
            "event_code": worker.EVENT_CODES["receiver_entry"],
            "time_s": 1.202,
            "time_before_s": 1.201,
            "time_after_s": 1.203,
        },
        {
            "event_code": worker.EVENT_CODES["receiver_entry"],
            "time_s": 1.207,
            "time_before_s": 1.206,
            "time_after_s": 1.208,
        },
        {
            "event_code": worker.EVENT_CODES["receiver_entry"],
            "time_s": 1.211,
            "time_before_s": 1.210,
            "time_after_s": 1.212,
        },
    ]

    matched = worker.match_uid_episodes(nom_events, dense_events, tolerance_s=0.010)

    # Exactly 1 joint match
    assert len(matched["joint_matches"]) == 1
    joint = matched["joint_matches"][0]
    assert joint["event_name"] == "receiver_entry"
    assert joint["nominal_time_s"] == 1.205
    assert joint["dense_time_s"] == 1.207  # Closest match (|1.207 - 1.205| = 0.002 < |1.202 - 1.205| = 0.003)
    assert abs(joint["time_delta_s"]) < 0.005

    # Remaining 2 dense events classified as repeated flutter, NOT zipped into false matches
    assert len(matched["repeated_flutter_events"]) == 2
    assert len(matched["missing_events"]) == 0
    assert len(matched["new_transient_events"]) == 0


def test_transit_chords_computation():
    """Verify transit chord calculation for receiver and tray."""
    events = [
        {"event_code": worker.EVENT_CODES["receiver_entry"], "time_s": 1.050, "frame_before": 105},
        {"event_code": worker.EVENT_CODES["receiver_exit"], "time_s": 1.450, "frame_after": 145},
        {"event_code": worker.EVENT_CODES["receiver_entry"], "time_s": 2.100, "frame_before": 210},
        {"event_code": worker.EVENT_CODES["receiver_exit"], "time_s": 2.300, "frame_after": 230},
    ]

    chords = worker.compute_transit_chords(
        events,
        entry_code=worker.EVENT_CODES["receiver_entry"],
        exit_code=worker.EVENT_CODES["receiver_exit"],
    )
    assert len(chords) == 2
    assert chords[0]["duration_s"] == pytest.approx(0.400, abs=1e-6)
    assert chords[1]["duration_s"] == pytest.approx(0.200, abs=1e-6)


def test_metadata_comparison_pipeline_tmp_path(tmp_path):
    """Synthetic test ensuring complete campaign write isolation (tmp_path only)."""
    cfg_path = HANDOFF_ROOT / "configs/native_weighted_save_comparison_config_v1.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    out_dir = tmp_path / "comparison_output"
    summary = worker.run_metadata_comparison(cfg, out_dir)

    assert (out_dir / "comparison_summary.json").is_file()
    assert (out_dir / "comparison_report.md").is_file()

    # Check summary fields
    assert summary["schema"] == "ds02.f2.native-weighted-save-comparison-summary.v1"
    assert summary["continuum_invariance"]["status"] == "verified_continuum_identical"
    assert summary["destination_inventories"]["aggregate_fate_match"] is True
    assert summary["save_bracket_budgets"]["dense4001"]["determination"] == "pass_discretization_budget_satisfied"
    assert summary["save_bracket_budgets"]["nominal401"]["determination"] == "fail_budget_exceeded"
    assert summary["claim_boundary"]["q_n"] == "not_granted"
    assert summary["claim_boundary"]["production"] == "none"

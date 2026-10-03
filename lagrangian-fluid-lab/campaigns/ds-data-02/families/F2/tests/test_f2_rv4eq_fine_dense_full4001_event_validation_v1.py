"""Unit tests for F2 RV4EQ fine dense full4001 event-semantic validation suite v1.

Verifies:
1. Sidecar and config provenance and schema adherence.
2. Temporal save bracket compliance (0.0005s <= 0.0007336s contract pass).
3. Native float32 mass authority vs historical XML decimal benchmark.
4. Strict distinction between repeat-count event transition flux and cohort inventory.
5. Unknown native exclusions policy (unknown_invalid, no physical spill, zero defect unasserted).
6. Execution of event validation runner on synthetic fixture with 100% tmp_path isolation.
7. Runner request validation via ds_data02_runtime_v2.validate_request.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import sys
import pytest

import h5py
import numpy as np

F2_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
sys.path.insert(0, str(INTEGRATION_LAB / "scripts"))
sys.path.insert(0, str(F2_ROOT))

from ds_data02_runtime_v2 import validate_request
from f2_rv4eq_fine_dense_full4001_event_validation_v1 import (
    audit_static_provenance,
    audit_temporal_save_gate,
    audit_mass_precision_authority,
    audit_repeat_count_vs_cohort_mass,
    audit_unknown_native_exclusions,
    audit_trajectory_payload,
    run_dense_full4001_event_validation,
    ValidationError,
    PHYSICAL_HASH,
    SAVE_ALLOWANCE_S,
    MANDATORY_PAYLOAD_DATASETS,
)

HANDOFF_DIR = F2_ROOT / "handoff_20261003/dense_full4001_event_validation_v1"
CONFIG_PATH = HANDOFF_DIR / "configs/f2_rv4eq_fine_dense_full4001_event_validation_config_v1.json"
SIDECAR_PATH = HANDOFF_DIR / "f2_rv4eq_fine_dense_full4001_event_validation_sidecar_v1.json"
REQUEST_PATH = HANDOFF_DIR / "requests/f2_rv4eq_fine_dense_full4001_event_validation_request_v1.json"


def test_sidecar_and_config_provenance_and_schema():
    assert CONFIG_PATH.is_file(), f"Config missing: {CONFIG_PATH}"
    assert SIDECAR_PATH.is_file(), f"Sidecar missing: {SIDECAR_PATH}"
    assert REQUEST_PATH.is_file(), f"Request missing: {REQUEST_PATH}"

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sidecar = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))

    assert config["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001"
    assert config["base_case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001"
    assert config["physical_condition_hash"] == PHYSICAL_HASH
    assert config["total_frames"] == 4001
    assert config["dt_save_s"] == 0.001

    provenance = audit_static_provenance(config, sidecar)
    assert provenance["physical_condition_hash"] == PHYSICAL_HASH
    assert provenance["solver_receipt"]["verified"] is True
    assert provenance["run_out"]["verified"] is True
    assert provenance["conversion_review"]["verified"] is True
    assert provenance["conversion_owner"]["verified"] is True
    assert provenance["motion"]["verified"] is True
    assert provenance["xml"]["verified"] is True


def test_temporal_save_bracket_compliance():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sidecar = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))

    audit = audit_temporal_save_gate(config, sidecar)
    assert audit["dt_save_s"] == 0.001
    assert audit["effective_save_half_width_s"] == 0.0005
    assert audit["contract_save_allowance_s"] == SAVE_ALLOWANCE_S
    assert audit["compliance_status"] == "pass_satisfied"
    assert audit["margin_fraction"] > 0.31  # ~31.8% margin

    # Verify historical 0.010s fails
    hist = audit["historical_coarse_medium_fine_status"]
    assert hist["historical_dt_save_s"] == 0.010
    assert hist["historical_save_half_width_s"] == 0.0050
    assert hist["historical_compliance_status"] == "fail_budget_exceeded"
    assert hist["historical_margin_fraction"] < 0


def test_mass_precision_dual_authority_accounting():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sidecar = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))

    audit = audit_mass_precision_authority(config, sidecar)
    native_auth = audit["native_float32_authority"]
    xml_bench = audit["historical_xml_decimal_benchmark"]

    assert math.isclose(native_auth["massfluid_particle_kg"], 0.0001250000059371814, rel_tol=1e-12)
    assert math.isclose(native_auth["cohort_total_mass_kg"], 24.576001167297363, rel_tol=1e-12)
    assert math.isclose(xml_bench["cohort_total_mass_kg"], 24.576, rel_tol=1e-12)
    assert math.isclose(native_auth["delta_to_continuous_kg"], 1.167297363e-6, rel_tol=1e-6)
    assert audit["policy_compliance"]["no_rescaling_old_v6"] is True


def test_repeat_count_vs_cohort_mass_distinction():
    # Simulate high event crossing count (e.g. repeated splashing/sloshing across apertures)
    event_counts = {
        "cup_mouth_departure": 194457,
        "receiver_entry": 250000,  # particles splashing back and forth
        "receiver_exit": 80000,
        "tray_entry": 90000,
        "tray_exit": 20000,
    }
    # Mutually exclusive destination partitioning strictly summing to 196,608 particles
    destination_counts = {
        "receiver": 140000,
        "tray": 44457,
        "inflight": 10000,
        "cup": 0,
        "unknown": 2151,  # 140000 + 44457 + 10000 + 0 + 2151 = 196608
    }

    audit = audit_repeat_count_vs_cohort_mass(
        n_fluid=196608,
        event_counts=event_counts,
        destination_counts=destination_counts,
    )

    flux = audit["event_transition_flux"]
    inv = audit["terminal_destination_inventory"]

    # Total crossings is 634,457 crossings > 196,608 particles
    assert flux["total_event_crossings"] == 634457
    # Transition mass is > 79 kg, far exceeding 24.576 kg!
    assert flux["total_transition_mass_native_kg"] > 79.0
    assert flux["flux_exceeds_cohort_mass"] is True

    # Terminal inventory strictly sums to 24.576001167 kg (native) and 24.576 kg (XML)
    assert inv["inventory_intact_native"] is True
    assert inv["inventory_intact_xml"] is True
    assert math.isclose(inv["sum_destination_native_kg"], 24.576001167297363, rel_tol=1e-9)
    assert math.isclose(inv["sum_destination_xml_kg"], 24.576, rel_tol=1e-9)
    assert audit["semantic_guard_satisfied"] is True


def test_unknown_native_exclusions_policy():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sidecar = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))

    audit = audit_unknown_native_exclusions(config, sidecar)
    assert audit["native_invalid_particles_npout"] == 2151
    assert audit["classification"] == "unknown_invalid"
    assert audit["physical_spill_inferred"] is False
    assert audit["closed_wall_crossing_count"] == 0
    assert audit["zero_physical_mass_defect_asserted"] is False
    assert audit["policy_verified"] is True

    # Check that asserting spill raises ValidationError
    bad_sidecar = json.loads(json.dumps(sidecar))
    bad_sidecar["native_exclusion_and_boundary_policy"]["physical_spill_inferred"] = True
    with pytest.raises(ValidationError, match="Physical spill cannot be inferred"):
        audit_unknown_native_exclusions(config, bad_sidecar)


def test_trajectory_payload_audit_with_synthetic_h5(tmp_path: Path):
    h5_path = tmp_path / "synthetic_trajectory.h5"
    n_frames = 11
    n_particles = 100

    times = np.linspace(0.0, 0.010, n_frames, dtype=np.float64)
    ids = np.arange(1470641, 1470641 + n_particles, dtype=np.int64)

    with h5py.File(h5_path, "w") as f:
        f.create_dataset("time", data=times)
        f.create_dataset("id", data=ids)
        f.create_dataset("position", data=np.zeros((n_frames, n_particles, 3), dtype=np.float32))
        f.create_dataset("velocity", data=np.zeros((n_frames, n_particles, 3), dtype=np.float32))
        f.create_dataset("rhop", data=np.full((n_frames, n_particles), 1000.0, dtype=np.float32))
        f.create_dataset("mass", data=np.full(n_particles, 0.000125, dtype=np.float32))
        f.create_dataset("initial_mass", data=np.full(n_particles, 0.000125, dtype=np.float32))
        f.create_dataset("type", data=np.zeros(n_particles, dtype=np.int32))
        f.create_dataset("part_type", data=np.zeros(n_particles, dtype=np.int32))
        f.create_dataset("fluid_type", data=np.zeros(n_particles, dtype=np.int32))
        f.create_dataset("substance", data=np.zeros(n_particles, dtype=np.int32))
        f.create_dataset("actual_angle_rad", data=np.zeros(n_frames, dtype=np.float32))
        f.create_dataset("angular_velocity_rad_s", data=np.zeros(n_frames, dtype=np.float32))

    audit = audit_trajectory_payload(h5_path, dt_target=0.001)
    assert audit["mandatory_datasets_present"] is True
    assert len(audit["missing_mandatory_datasets"]) == 0
    assert audit["temporal_metrics"]["frames"] == 11
    assert audit["temporal_metrics"]["finite"] is True
    assert audit["temporal_metrics"]["strictly_increasing"] is True
    assert audit["temporal_metrics"]["dt_close_to_target"] is True
    assert audit["uid_metrics"]["min_id"] == 1470641


def test_full_validation_run_with_synthetic_isolation(tmp_path: Path):
    out_dir = tmp_path / "reports_out"

    # Run with default config (prospective mode since conversion is running)
    summary = run_dense_full4001_event_validation(
        config_path=CONFIG_PATH,
        output_dir=out_dir,
    )

    assert summary["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001"
    assert summary["temporal_audit"]["compliance_status"] == "pass_satisfied"
    assert summary["mass_precision_audit"]["policy_compliance"]["no_rescaling_old_v6"] is True
    assert summary["repeat_count_vs_cohort_mass_audit"]["semantic_guard_satisfied"] is True

    summary_file = out_dir / "f2_rv4eq_fine_dense_full4001_event_validation_summary.json"
    report_file = out_dir / "f2_rv4eq_fine_dense_full4001_event_validation_report.md"

    assert summary_file.is_file()
    assert report_file.is_file()
    report_text = report_file.read_text(encoding="utf-8")
    assert "Temporal Save Bracket Contract Compliance" in report_text
    assert "Repeat-Count Crossing Event Mass vs. Unique Cohort Inventory" in report_text


def test_runner_request_passes_runtime_validation():
    request_data = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    verified_hashes = validate_request(request_data)
    assert len(verified_hashes) >= 12
    assert request_data["kind"] == "cpu"
    assert request_data["cpu_task_kind"] == "labels"
    assert request_data["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001"

"""Unit tests for OFFSET terminal Q-I closure and sidecar generation."""

from __future__ import annotations

import json
from pathlib import Path
import pytest


MODULE_DIR = Path(__file__).resolve().parents[1]
HANDOFF_OFFSET = MODULE_DIR / "handoff_20261003/offset_baseline_terminal_v1"
QI_AUDIT_DIR = HANDOFF_OFFSET / "qi_audit"
METADATA_PATH = QI_AUDIT_DIR / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001_actual_qi_metadata_v1.json"
CASE_ID = "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001"


def test_offset_metadata_structure_and_boundaries():
    assert METADATA_PATH.is_file()
    meta = json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    assert meta["case_id"] == CASE_ID
    assert meta["family_id"] == "F2"
    assert meta["mechanism_id"] == "offset_spill"
    assert meta["physical_condition_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
    assert meta["numerical_recipe_hash"] == "1c3a2f0d1bf2feb8a470375dabd07fac548ff2c5b449e39917cf7b4cb5d4bfc7"

    # Verify native unknown count is 2151
    assert len(meta["native_exclusion_ledger"]["excluded_particles"]) == 2151
    assert meta["claims"]["native_unknown_not_spill"] is True
    assert meta["claims"]["q_n"] == "not_assessed"
    assert meta["claims"]["production"] == "not_evaluated"

    # Quality contract
    qc = meta["quality_contract_binding"]
    assert qc["save_half_width_budget_s"] == 0.0007336390799938275
    assert qc["event_time_absolute_budget_s"] == 0.0036681953999691376
    assert qc["observed_save_interval_s"] == 0.01


def test_offset_rigid_body_state_is_from_completed_pose():
    meta = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    rb = meta["rigid_body_state"]

    assert rb["moving_node_count"] == 76676
    assert rb["moving_type_code"] == 1
    assert rb["frames"] == 401
    assert rb["dataset"] == "rigid_body_state"


def test_offset_actual_pose_labels_qi_sidecar():
    sidecar_path = QI_AUDIT_DIR / "F2_RV4EQ_DP005_OFFSET_actual_pose_labels_qi_sidecar_v1.json"
    assert sidecar_path.is_file()
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

    assert sidecar["schema"] == "ds-data-02.f2.offset-baseline-actual-pose-labels-qi-sidecar.v1"
    assert sidecar["case_id"] == CASE_ID
    assert sidecar["family_id"] == "F2"
    assert sidecar["background"] == "OFFSET"
    assert sidecar["mechanism_id"] == "offset_spill"

    # Actual runtime verification
    runtime = sidecar["actual_runtime"]
    assert runtime["labels_status"] == "completed"
    assert runtime["labels_returncode"] == 0
    assert runtime["qi_status"] == "completed"
    assert runtime["qi_returncode"] == 0
    assert runtime["qi_attempt_id"] == "qi-f2-rv4eq-offset-v1-baseline-save001-pose-labels-actual-002"

    # Q-I structure pass
    qi = sidecar["qi_audit"]
    assert qi["q_i_status"] == "Q-I-structure-pass"
    assert qi["structural_failures"] == []
    assert qi["missing_requirements"] == []
    assert qi["native_exclusion_ledger"]["status"] == "pass"
    assert qi["native_exclusion_ledger"]["native_motive_counts"] == {"1": 2151, "2": 0, "3": 0}

    # Strict scientific boundary
    claims = sidecar["claims"]
    assert claims["q_i"] == "actual integrity structure pass only"
    assert claims["q_n"] == "not_assessed"
    assert claims["production"] == "not_evaluated"

    limits = sidecar["frozen_limits_and_open_gaps"]
    assert limits["q_n_granted"] is False
    assert limits["production_granted"] is False
    assert limits["native_unknown_count"] == 2151
    assert limits["native_unknown_is_not_physical_spill"] is True
    assert limits["observed_save_interval_s"] == 0.01

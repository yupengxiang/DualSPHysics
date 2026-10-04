"""Unit tests for F1 Lower-Head Three-DP Macro Worker and Request Builder.

Tests:
1. Rejection of forbidden old normalizers (ECC H=0.3/80.4, DUAL H=0.55/616.0).
2. Acceptance of correct lower-head scales (ECC H=0.15/40.2, DUAL H=0.3/300.0).
3. Canonical physical condition SHA256 hashes validation.
4. Initial QA 031 and all 6 solver receipts verification (status=completed, returncode=0).
5. Retention of failed historical run 033 (status=failed, returncode=-15).
6. Preflight audit (--check-only) and pending evaluation (--allow-pending) execution.
7. Direct unequal DP macro comparison operator calculations without cross-DP UID matching.
8. Truthful retention of threshold exceedance (no silent dropping).
9. Runner request builder execution and schema validation (launch_allowed=False, root_review_before_execution=True).
10. Strict claim boundaries (q_n: not_granted, production_approval: none).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import pytest

HANDOFF_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HANDOFF_DIR / "scripts"))

from ds_data02_f1_lower_head_macro_worker import (
    compare_pair,
    run_macro_worker,
    verify_canonical_physical_binding,
    verify_initial_qa_record,
    verify_scale_registration,
    verify_solver_receipts,
    EXPECTED_PHYSICAL_HASHES,
    FORBIDDEN_OLD_NORMALIZERS,
)
from build_runner_requests import build_request

ECC_BINDING_PATH = HANDOFF_DIR / "bindings/ecc-lower-head-macro-binding.json"
DUAL_BINDING_PATH = HANDOFF_DIR / "bindings/dual-lower-head-macro-binding.json"
ECC_SCALE_REG_PATH = HANDOFF_DIR / "definitions/ecc_lower_head_scale_registration.json"
DUAL_SCALE_REG_PATH = HANDOFF_DIR / "definitions/dual_lower_head_scale_registration.json"


def test_rejection_of_forbidden_old_normalizers():
    """Verify strict rejection of old ECC H=0.3/80.4 and old DUAL H=0.55/616.0."""
    ecc_reg = json.loads(ECC_SCALE_REG_PATH.read_text(encoding="utf-8"))
    dual_reg = json.loads(DUAL_SCALE_REG_PATH.read_text(encoding="utf-8"))

    # Test valid registrations pass
    ecc_audit = verify_scale_registration(ecc_reg, "F1_ECC_THICK_DBC_LOWER_HEAD_V1")
    assert ecc_audit["H0_m"] == 0.15
    assert ecc_audit["continuous_initial_mass_kg"] == 40.2
    assert ecc_audit["expected_frames"] == 161
    assert ecc_audit["full_window_s"] == [0.0, 1.6]
    assert ecc_audit["forbidden_old_normalizers_rejected"] is True

    dual_audit = verify_scale_registration(dual_reg, "F1_DUAL_THICK_DBC_LOWER_HEAD_V1")
    assert dual_audit["H0_m"] == 0.3
    assert dual_audit["continuous_initial_mass_kg"] == 300.0
    assert dual_audit["expected_frames"] == 401
    assert dual_audit["full_window_s"] == [0.0, 4.0]
    assert dual_audit["forbidden_old_normalizers_rejected"] is True

    # Mutate to forbidden ECC H0
    bad_ecc = copy.deepcopy(ecc_reg)
    bad_ecc["H0_m"] = FORBIDDEN_OLD_NORMALIZERS["F1_ECC_THICK_DBC_LOWER_HEAD_V1"]["H0_m"]
    with pytest.raises(ValueError, match="forbidden old normalizer"):
        verify_scale_registration(bad_ecc, "F1_ECC_THICK_DBC_LOWER_HEAD_V1")

    # Mutate to forbidden ECC mass
    bad_ecc2 = copy.deepcopy(ecc_reg)
    bad_ecc2["continuous_initial_mass_kg"] = FORBIDDEN_OLD_NORMALIZERS["F1_ECC_THICK_DBC_LOWER_HEAD_V1"]["continuous_initial_mass_kg"]
    with pytest.raises(ValueError, match="forbidden old mass"):
        verify_scale_registration(bad_ecc2, "F1_ECC_THICK_DBC_LOWER_HEAD_V1")

    # Mutate to forbidden DUAL H0
    bad_dual = copy.deepcopy(dual_reg)
    bad_dual["H0_m"] = FORBIDDEN_OLD_NORMALIZERS["F1_DUAL_THICK_DBC_LOWER_HEAD_V1"]["H0_m"]
    with pytest.raises(ValueError, match="forbidden old normalizer"):
        verify_scale_registration(bad_dual, "F1_DUAL_THICK_DBC_LOWER_HEAD_V1")

    # Mutate to forbidden DUAL mass
    bad_dual2 = copy.deepcopy(dual_reg)
    bad_dual2["continuous_initial_mass_kg"] = FORBIDDEN_OLD_NORMALIZERS["F1_DUAL_THICK_DBC_LOWER_HEAD_V1"]["continuous_initial_mass_kg"]
    with pytest.raises(ValueError, match="forbidden old mass"):
        verify_scale_registration(bad_dual2, "F1_DUAL_THICK_DBC_LOWER_HEAD_V1")


def test_canonical_physical_bindings_and_hashes():
    """Verify physical condition hashes match expected canonical values."""
    ecc_b = json.loads(ECC_BINDING_PATH.read_text(encoding="utf-8"))
    dual_b = json.loads(DUAL_BINDING_PATH.read_text(encoding="utf-8"))

    ecc_phys = verify_canonical_physical_binding(
        ecc_b["canonical_physical_binding"],
        EXPECTED_PHYSICAL_HASHES["F1_ECC_THICK_DBC_LOWER_HEAD_V1"],
    )
    assert ecc_phys["passed"] is True
    assert ecc_phys["physical_condition_sha256"] == "687c069f836dd81b3c4c85ea6f977f9f2775debea01d3657b81356801ced71d3"

    dual_phys = verify_canonical_physical_binding(
        dual_b["canonical_physical_binding"],
        EXPECTED_PHYSICAL_HASHES["F1_DUAL_THICK_DBC_LOWER_HEAD_V1"],
    )
    assert dual_phys["passed"] is True
    assert dual_phys["physical_condition_sha256"] == "feb710be76c89fb67074b1bbbf6c9c22869652ce5760c4d7e4721187b4d580bf"


def test_initial_qa_and_all_six_solver_receipts():
    """Verify initial QA 031 and all 6 solver receipts (032/033/035) are completed with returncode 0."""
    ecc_b = json.loads(ECC_BINDING_PATH.read_text(encoding="utf-8"))
    dual_b = json.loads(DUAL_BINDING_PATH.read_text(encoding="utf-8"))

    ecc_case_ids = [c["case_id"] for c in ecc_b["cases"]]
    dual_case_ids = [c["case_id"] for c in dual_b["cases"]]

    ecc_qa = verify_initial_qa_record(ecc_b["initial_qa"]["receipt"], ecc_case_ids)
    assert ecc_qa["passed"] is True
    assert len(ecc_qa["cases"]) == 3

    dual_qa = verify_initial_qa_record(dual_b["initial_qa"]["receipt"], dual_case_ids)
    assert dual_qa["passed"] is True
    assert len(dual_qa["cases"]) == 3

    ecc_solvers = verify_solver_receipts(ecc_b["cases"], ecc_b.get("excluded_historical_attempts", []))
    assert ecc_solvers["passed"] is True
    for cid, s_info in ecc_solvers["active_cases"].items():
        assert s_info["status"] == "completed"
        assert s_info["returncode"] == 0

    dual_solvers = verify_solver_receipts(dual_b["cases"], dual_b.get("excluded_historical_attempts", []))
    assert dual_solvers["passed"] is True
    for cid, s_info in dual_solvers["active_cases"].items():
        assert s_info["status"] == "completed"
        assert s_info["returncode"] == 0

    # Verify excluded historical run 033 is retained as failed with returncode -15
    assert len(dual_solvers["verified_exclusions"]) == 1
    exc = dual_solvers["verified_exclusions"][0]
    assert exc["attempt_id"] == "root-fallback-dual-fine-full401-native-033"
    assert exc["status"] == "failed"
    assert exc["returncode"] == -15
    assert exc["retained_as_excluded"] is True


def test_macro_worker_preflight_check_only(tmp_path: Path):
    """Verify --check-only mode produces valid audit artifact."""
    ecc_out = tmp_path / "ecc_audit.json"
    dual_out = tmp_path / "dual_audit.json"

    res_ecc = run_macro_worker(ECC_BINDING_PATH, ecc_out, check_only=True)
    assert res_ecc["status"] == "preflight_audit_passed"
    assert res_ecc["claim_boundary"]["q_n"] == "not_granted"
    assert res_ecc["claim_boundary"]["production_approval"] == "none"
    assert ecc_out.is_file()

    res_dual = run_macro_worker(DUAL_BINDING_PATH, dual_out, check_only=True)
    assert res_dual["status"] == "preflight_audit_passed"
    assert res_dual["claim_boundary"]["q_n"] == "not_granted"
    assert res_dual["claim_boundary"]["production_approval"] == "none"
    assert dual_out.is_file()


def test_macro_worker_allow_pending(tmp_path: Path):
    """Verify --allow-pending generates accurate pending comparison sidecar."""
    ecc_out = tmp_path / "ecc_pending.json"
    dual_out = tmp_path / "dual_pending.json"

    res_ecc = run_macro_worker(ECC_BINDING_PATH, ecc_out, allow_pending=True)
    assert res_ecc["numerical_status"] == "pending_converter_execution"
    assert res_ecc["expected_frames"] == 161
    assert res_ecc["physical_window_s"] == [0.0, 1.6]
    assert res_ecc["claim_boundary"]["q_n"] == "not_granted"
    assert res_ecc["claim_boundary"]["production_approval"] == "none"
    assert ecc_out.is_file()

    res_dual = run_macro_worker(DUAL_BINDING_PATH, dual_out, allow_pending=True)
    assert res_dual["numerical_status"] == "pending_converter_execution"
    assert res_dual["expected_frames"] == 401
    assert res_dual["physical_window_s"] == [0.0, 4.0]
    assert res_dual["claim_boundary"]["q_n"] == "not_granted"
    assert res_dual["claim_boundary"]["production_approval"] == "none"
    assert dual_out.is_file()


def test_direct_unequal_dp_macro_operator():
    """Verify compare_pair calculation without UID matching across DP."""
    times = [0.0, 0.01, 0.02]
    cand_rows = [
        {
            "time_s": t,
            "center_of_mass_m": [0.1, 0.2, 0.05],
            "coordinate_quantiles_m": [[0.05, 0.1, 0.15], [0.1, 0.2, 0.3], [0.02, 0.05, 0.08]],
            "kinetic_energy_J": 1.0,
            "fluid_mass_kg": 40.2,
            "mean_velocity_m_s": [0.0, 0.1, 0.0],
        }
        for t in times
    ]
    ref_rows = [
        {
            "time_s": t,
            "center_of_mass_m": [0.101, 0.201, 0.051],
            "coordinate_quantiles_m": [[0.051, 0.101, 0.151], [0.101, 0.201, 0.301], [0.021, 0.051, 0.081]],
            "kinetic_energy_J": 1.05,
            "fluid_mass_kg": 40.21,
            "mean_velocity_m_s": [0.01, 0.11, 0.01],
        }
        for t in times
    ]

    cand = {
        "case_id": "CAND_CASE",
        "role": "fine",
        "observation": {"rows": cand_rows},
        "initial_mass_kg": 40.2,
        "initial_mass_relative_error": 0.0,
    }
    ref = {
        "case_id": "REF_CASE",
        "role": "coarse",
        "observation": {"rows": ref_rows},
        "initial_mass_kg": 40.21,
        "initial_mass_relative_error": 0.00025,
    }

    res = compare_pair(
        cand,
        ref,
        cadence=0.01,
        max_offset=0.0002,
        H0=0.15,
        continuous_mass=40.2,
        macro_budget=0.05,
    )

    assert res["time_alignment"]["uid_matching_across_dp"] is False
    assert res["time_alignment"]["common_frame_count"] == 3
    assert res["macro_budget"] == 0.05
    assert res["macro_screening_within_budget"] is True
    assert res["q_n_status"] == "not_granted"


def test_macro_operator_retains_failure_when_budget_exceeded():
    """Verify that when macro difference exceeds budget, it truthfully fails and is not silently dropped."""
    times = [0.0, 0.01, 0.02]
    cand_rows = [
        {
            "time_s": t,
            "center_of_mass_m": [0.1, 0.2, 0.05],
            "coordinate_quantiles_m": [[0.05, 0.1, 0.15], [0.1, 0.2, 0.3], [0.02, 0.05, 0.08]],
            "kinetic_energy_J": 1.0,
            "fluid_mass_kg": 40.2,
            "mean_velocity_m_s": [0.0, 0.1, 0.0],
        }
        for t in times
    ]
    ref_rows = [
        {
            "time_s": t,
            "center_of_mass_m": [0.15, 0.25, 0.10],  # diff = 0.05 m >> 0.0075 m (5% of 0.15)
            "coordinate_quantiles_m": [[0.05, 0.1, 0.15], [0.1, 0.2, 0.3], [0.02, 0.05, 0.08]],
            "kinetic_energy_J": 1.0,
            "fluid_mass_kg": 40.2,
            "mean_velocity_m_s": [0.0, 0.1, 0.0],
        }
        for t in times
    ]

    cand = {
        "case_id": "CAND_CASE",
        "role": "fine",
        "observation": {"rows": cand_rows},
        "initial_mass_kg": 40.2,
        "initial_mass_relative_error": 0.0,
    }
    ref = {
        "case_id": "REF_CASE",
        "role": "coarse",
        "observation": {"rows": ref_rows},
        "initial_mass_kg": 40.2,
        "initial_mass_relative_error": 0.0,
    }

    res = compare_pair(
        cand,
        ref,
        cadence=0.01,
        max_offset=0.0002,
        H0=0.15,
        continuous_mass=40.2,
        macro_budget=0.05,
    )

    assert res["macro_screening_within_budget"] is False
    assert res["macro_metric_max"] > 0.05


def test_runner_request_builder(tmp_path: Path):
    """Verify runner request builder pins exact hashes, scope limits, and sets launch_allowed=False."""
    ecc_req = build_request(
        "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        ECC_BINDING_PATH,
        tmp_path / "ecc_req.json",
    )
    assert ecc_req["schema"] == "ds02.runner-request.v2"
    assert ecc_req["launch_allowed"] is False
    assert ecc_req["root_review_before_execution"] is True
    assert ecc_req["production_approval"] == "none"
    assert ecc_req["independent_case_count_increment"] == 0
    assert ecc_req["scale_parameters"]["H0_m"] == 0.15
    assert ecc_req["scale_parameters"]["continuous_initial_mass_kg"] == 40.2
    assert ecc_req["scale_parameters"]["expected_frames"] == 161
    assert ecc_req["scale_parameters"]["full_window_s"] == [0.0, 1.6]

    dual_req = build_request(
        "F1_DUAL_THICK_DBC_LOWER_HEAD_V1",
        DUAL_BINDING_PATH,
        tmp_path / "dual_req.json",
    )
    assert dual_req["schema"] == "ds02.runner-request.v2"
    assert dual_req["launch_allowed"] is False
    assert dual_req["root_review_before_execution"] is True
    assert dual_req["production_approval"] == "none"
    assert dual_req["independent_case_count_increment"] == 0
    assert dual_req["scale_parameters"]["H0_m"] == 0.3
    assert dual_req["scale_parameters"]["continuous_initial_mass_kg"] == 300.0
    assert dual_req["scale_parameters"]["expected_frames"] == 401
    assert dual_req["scale_parameters"]["full_window_s"] == [0.0, 4.0]
    assert dual_req["historical_exclusion_enforced"] == ["root-fallback-dual-fine-full401-native-033"]

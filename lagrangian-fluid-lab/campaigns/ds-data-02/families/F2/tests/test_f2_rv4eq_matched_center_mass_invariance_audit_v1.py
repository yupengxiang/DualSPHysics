"""Unit tests for F2 RV4 matched CENTER native mass and invariance scientific audit v1.

Verifies:
1. Native float32 mass vs XML decimal mass comparison (24.576 kg vs float32 sum).
2. Bitwise particle dataset invariance between source and postprocessed trajectory.
3. Formal validity: no non-finite values where valid == True.
4. Distinguishing native measurement vs normalized diagnostic.
5. Runner requests compliance with shared runtime ds_data02_runtime_v2.validate_request.
6. Execution via run_audit writes valid audit report and manifest.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys
import numpy as np
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "f2_rv4eq_matched_center_mass_invariance_audit_v1.py"
spec = importlib.util.spec_from_file_location("f2_matched_center_mass_audit_v1", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
audit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_mod)

FAMILY_ROOT = audit_mod.FAMILY_ROOT
INTEGRATION_LAB = audit_mod.INTEGRATION_LAB
AUDIT_ROOT = audit_mod.AUDIT_ROOT
CONFIGS_DIR = audit_mod.CONFIGS_DIR
REQUESTS_DIR = audit_mod.REQUESTS_DIR
CASES = audit_mod.CASES
F2_DATA = audit_mod.F2_DATA

# Import shared runtime validator
sys.path.insert(0, str(INTEGRATION_LAB / "scripts"))
from ds_data02_runtime_v2 import validate_request


def test_mass_audit_configs_and_requests_generation():
    audit_mod.build_audit_requests()
    assert CONFIGS_DIR.is_dir()
    assert REQUESTS_DIR.is_dir()

    for name, info in CASES.items():
        short = info["short_name"]
        cfg_path = CONFIGS_DIR / f"{short}_mass_invariance_audit_config_v1.json"
        req_path = REQUESTS_DIR / f"{short}_mass_invariance_audit_request_v1.json"
        assert cfg_path.is_file(), f"missing config: {cfg_path}"
        assert req_path.is_file(), f"missing request: {req_path}"

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["schema"] == "ds02.f2.matched-center-mass-invariance-audit-config.v1"
        assert cfg["case_id"] == info["case_id"]
        assert cfg["attempt_id"] == info["audit_attempt_id"]
        assert cfg["resolution"] == info["resolution"]
        assert cfg["physical_condition_hash"] == audit_mod.PHYSICAL_HASH

        req = json.loads(req_path.read_text(encoding="utf-8"))
        assert req["schema"] == "ds02.runner-request.v2"
        assert req["family_id"] == "F2"
        assert req["case_id"] == info["case_id"]
        assert req["attempt_id"] == info["audit_attempt_id"]
        assert req["kind"] == "cpu"
        assert req["cpu_task_kind"] == "audit"
        assert req["cpu_threads"] == 2
        assert req["max_wall_seconds"] <= 3600
        assert req["conversion_launch_forbidden"] is True
        assert req["claim_boundary"]["q_n"] == "not_assessed"

        # Validate with shared runner
        verified_hashes = validate_request(req)
        assert len(verified_hashes) == len(req["input_files"])


def test_audit_dry_run_scientific_numerical_checks():
    info = CASES["coarse"]
    report = audit_mod.audit_case(info)
    assert report["schema"] == "ds02.f2.matched-center-mass-invariance-audit.v1"
    assert report["case_id"] == info["case_id"]

    # 1. Native mass checks
    mass_sec = report["mass_comparison"]
    assert mass_sec["generated_xml_total_fluid_mass_kg"] == 24.576
    assert mass_sec["relative_mass_error"] < 1e-7
    assert math.isclose(mass_sec["native_float32_fluid_sum_kg"], 24.576001167297363, rel_tol=1e-9)

    diag = mass_sec["native_measurement_vs_normalized_diagnostic"]
    assert diag["normalization_applied_to_source"] is False
    assert math.isclose(diag["native_measurement_fluid_mass_kg"], 24.576001167297363, rel_tol=1e-9)
    assert diag["normalized_diagnostic_nominal_mass_kg"] == 24.576

    # 2. Bitwise preservation & augmentation invariance
    invar_sec = report["augmentation_invariance"]
    assert invar_sec["bitwise_particle_invariance_verified"] is True
    assert invar_sec["additive_rigid_body_state_verified"] is True
    assert invar_sec["formal_validity_all_finite"] is True
    assert invar_sec["cohort_status_preserved"] is True
    assert invar_sec["fluid_particles"] == info["fluid_particles"]
    assert invar_sec["moving_boundary_particles"] == info["case_nmoving"]

    # 3. Scientific qualification boundary
    boundary = report["scientific_qualification_boundary"]
    assert boundary["q_i_status"] == "audit_evidence_complete"
    assert boundary["q_n_status"] == "not_assessed"
    assert boundary["production_status"] == "not_evaluated"


def test_run_audit_end_to_end(tmp_path: Path):
    cfg_path = CONFIGS_DIR / "center_medium_mass_invariance_audit_config_v1.json"
    assert cfg_path.is_file()

    out_dir = tmp_path / "audit_output"
    manifest = audit_mod.run_audit(cfg_path, out_dir)

    assert manifest["schema"] == "ds02.f2.matched-center-audit-manifest.v1"
    assert manifest["status"] == "completed_evidence_only"
    assert manifest["q_i_status"] == "audit_evidence_complete"
    assert manifest["q_n_status"] == "not_assessed"
    assert manifest["production_status"] == "not_evaluated"

    report_file = out_dir / "center-mass-invariance-audit-report.json"
    assert report_file.is_file()
    rep = json.loads(report_file.read_text(encoding="utf-8"))
    assert rep["schema"] == "ds02.f2.matched-center-mass-invariance-audit.v1"
    assert rep["mass_comparison"]["relative_mass_error"] < 1e-7
    assert math.isclose(rep["mass_comparison"]["native_float32_fluid_sum_kg"], 24.575999937951565, rel_tol=1e-9)
    assert rep["augmentation_invariance"]["bitwise_particle_invariance_verified"] is True

    # Negative test: refusing to overwrite existing report
    with pytest.raises(audit_mod.AuditError, match="refusing to overwrite"):
        audit_mod.run_audit(cfg_path, out_dir)

"""Unit tests for F2 root_budget_scope_audit_003 sidecar (timing budget scope separation)."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import pytest


MODULE_DIR = Path(__file__).resolve().parents[1]
HANDOFF_ROOT = MODULE_DIR / "handoff_20261003"
PRIMARY_SIDECAR = HANDOFF_ROOT / "root_budget_scope_audit_003/root_budget_scope_audit_003.json"
QI_SIDECAR = HANDOFF_ROOT / "offset_baseline_terminal_v1/qi_audit/root_budget_scope_audit_003.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_sidecar_existence_and_identity():
    assert PRIMARY_SIDECAR.is_file(), f"missing primary sidecar: {PRIMARY_SIDECAR}"
    assert QI_SIDECAR.is_file(), f"missing qi audit sidecar: {QI_SIDECAR}"

    primary_data = json.loads(PRIMARY_SIDECAR.read_text(encoding="utf-8"))
    qi_data = json.loads(QI_SIDECAR.read_text(encoding="utf-8"))

    assert primary_data == qi_data
    assert sha256(PRIMARY_SIDECAR) == sha256(QI_SIDECAR)


def test_root_partvtkout_independent_mapping():
    data = json.loads(PRIMARY_SIDECAR.read_text(encoding="utf-8"))
    partvtk = data["root_partvtkout_independent_mapping"]

    assert partvtk["status"] == "confirmed_supported_by_root_and_family_owner"
    assert partvtk["total_native_unknown_fluid_particles"] == 2151
    assert partvtk["initial_fluid_particle_count"] == 196608
    assert partvtk["retained_valid_fluid_particle_count"] == 194457
    assert partvtk["intact_moving_type1_particle_count"] == 76676
    assert math.isclose(partvtk["unknown_fluid_mass_kg"], 0.268875, rel_tol=1e-6)
    assert partvtk["native_motive_counts"] == {"1": 2151, "2": 0, "3": 0}


def test_retracted_terminology_and_scope_separation():
    data = json.loads(PRIMARY_SIDECAR.read_text(encoding="utf-8"))
    term_scope = data["terminology_correction_and_scope_separation"]

    assert "Retracted" in term_scope["retracted_erroneous_terminology"]
    assert "cumulative timing integration error" in term_scope["retracted_erroneous_terminology"]

    allowances = term_scope["authoritative_allowances_by_scope"]
    baseline_scope = allowances["baseline_contract_scope"]
    matched_scope = allowances["matched_preregistration_scope"]

    assert baseline_scope["scope_name"] == "original_rv4_baseline_contract"
    assert baseline_scope["governing_contract"] == "quality_contract.json"
    assert math.isclose(baseline_scope["event_time_absolute_budget_s"], 0.0036681953999691376, rel_tol=1e-9)
    assert math.isclose(baseline_scope["save_fraction_of_total_error_budget_max"], 0.2, rel_tol=1e-9)
    assert math.isclose(baseline_scope["authoritative_save_allowance_s"], 0.0007336390799938275, rel_tol=1e-9)

    assert matched_scope["scope_name"] == "rv4_matched_three_dp_reference_preregistration"
    assert math.isclose(matched_scope["authoritative_save_allowance_s"], 0.0001467278159987655, rel_tol=1e-9)
    assert math.isclose(matched_scope["matched_prereg_fraction"], 0.2, rel_tol=1e-9)
    assert "Never applied retroactively to original baselines" in matched_scope["applicability"]


def test_evaluations_under_own_allowance_fail_with_zero_loosening():
    data = json.loads(PRIMARY_SIDECAR.read_text(encoding="utf-8"))
    evals = data["audit_evaluations_under_own_allowance"]

    offset = evals["offset_baseline_fine_dp005"]
    assert offset["applicable_scope"] == "original_rv4_baseline_contract"
    assert math.isclose(offset["applicable_save_allowance_s"], 0.0007336390799938275, rel_tol=1e-9)
    assert offset["evaluation_status"] == "FAIL / PENDING"
    assert offset["ratio_observed_to_own_allowance"] > 6.0

    spatial = evals["spatial_save010_reference_cases"]
    assert spatial["applicable_scope"] == "rv4_matched_three_dp_reference_preregistration"
    assert math.isclose(spatial["applicable_save_allowance_s"], 0.0001467278159987655, rel_tol=1e-9)
    assert spatial["evaluation_status"] == "FAIL / PENDING"
    assert spatial["ratio_observed_to_own_allowance"] > 30.0
    assert len(spatial["case_ids"]) == 4

    qual = data["jurisdictional_and_operational_boundaries"]["qualification_status"]
    assert qual["q_n_granted"] is False
    assert qual["production_granted"] is False


def test_jurisdictional_boundaries_and_policies():
    data = json.loads(PRIMARY_SIDECAR.read_text(encoding="utf-8"))
    bounds = data["jurisdictional_and_operational_boundaries"]

    policy = bounds["converter_authorization_policy"]
    assert "Root retains full authority to authorize macro converters" in policy
    assert "Delegated family owners simply cannot launch them" in policy

    limits = bounds["delegated_authority_limits"]
    assert limits["gpu_launches_forbidden_to_delegates"] is True
    assert limits["delegate_trajectory_conversion_launch_forbidden"] is True
    assert limits["root_macro_converter_authorization_supported"] is True
    assert limits["bounded_cpu_audit_permitted"] is True
    assert limits["approved_qualification_cap"] == 320
    assert limits["approved_home_floor_gib"] == 500

    hist = bounds["historical_artifacts_preservation"]
    assert hist["commit_2f9905d1_preserved_unchanged"] is True
    assert hist["root_budget_scope_audit_002_preserved_as_review_artifact"] is True


def test_source_bindings_integrity():
    data = json.loads(PRIMARY_SIDECAR.read_text(encoding="utf-8"))
    bindings = data["source_bindings"]

    assert len(bindings) >= 13
    assert "root_budget_scope_audit_002" in bindings

    for name, item in bindings.items():
        p = Path(item["path"])
        assert p.is_file(), f"bound source missing: {name} at {p}"
        actual_sha = sha256(p)
        assert actual_sha == item["sha256"], f"SHA mismatch for bound source {name}: {actual_sha} != {item['sha256']}"
        assert p.stat().st_size == item["bytes"], f"Byte mismatch for bound source {name}"

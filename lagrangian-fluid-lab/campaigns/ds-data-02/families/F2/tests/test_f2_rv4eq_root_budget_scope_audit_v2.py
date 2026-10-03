"""Unit tests for F2 root_budget_scope_audit_002 sidecar."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import pytest


MODULE_DIR = Path(__file__).resolve().parents[1]
HANDOFF_ROOT = MODULE_DIR / "handoff_20261003"
PRIMARY_SIDECAR = HANDOFF_ROOT / "root_budget_scope_audit_002/root_budget_scope_audit_002.json"
QI_SIDECAR = HANDOFF_ROOT / "offset_baseline_terminal_v1/qi_audit/root_budget_scope_audit_002.json"


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


def test_timing_budget_hierarchy_and_distinction():
    data = json.loads(PRIMARY_SIDECAR.read_text(encoding="utf-8"))
    hier = data["budget_hierarchy_and_definitions"]
    dist = data["distinction_analysis"]

    total_budget = hier["save_integration_total_budget_s"]
    applicable_alloc = hier["authoritative_applicable_save_allocation_s"]

    assert math.isclose(total_budget, 0.0007336390799938275, rel_tol=1e-9)
    assert math.isclose(applicable_alloc, 0.0001467278159987655, rel_tol=1e-9)
    assert math.isclose(total_budget / applicable_alloc, 5.0, rel_tol=1e-9)

    assert dist["total_budget"]["value_s"] == total_budget
    assert dist["allocated_output_contribution"]["value_s"] == applicable_alloc


def test_evaluations_retain_original_negatives():
    data = json.loads(PRIMARY_SIDECAR.read_text(encoding="utf-8"))
    evals = data["audit_evaluations"]

    offset = evals["offset_baseline_fine_dp005"]
    assert offset["evaluation_against_total_budget_0p0007336s"]["status"] == "FAIL / PENDING"
    assert offset["evaluation_against_authoritative_allocation_0p0001467s"]["status"] == "FAIL / PENDING"
    assert offset["evaluation_against_total_budget_0p0007336s"]["ratio_observed_to_budget"] > 6.0
    assert offset["evaluation_against_authoritative_allocation_0p0001467s"]["ratio_observed_to_budget"] > 30.0

    spatial = evals["spatial_save010_reference_cases"]
    assert spatial["evaluation_against_authoritative_allocation_0p0001467s"]["status"] == "FAIL / PENDING"
    assert len(spatial["case_ids"]) == 4

    preserved = data["preserved_boundaries_and_policies"]
    assert preserved["retain_original_negatives"] is True
    assert preserved["no_loosening_permitted"] is True
    assert preserved["q_n_granted"] is False
    assert preserved["production_granted"] is False


def test_source_bindings_integrity():
    data = json.loads(PRIMARY_SIDECAR.read_text(encoding="utf-8"))
    bindings = data["source_bindings"]

    assert len(bindings) >= 12
    for name, item in bindings.items():
        p = Path(item["path"])
        assert p.is_file(), f"bound source missing: {name} at {p}"
        actual_sha = sha256(p)
        assert actual_sha == item["sha256"], f"SHA mismatch for bound source {name}: {actual_sha} != {item['sha256']}"
        assert p.stat().st_size == item["bytes"], f"Byte mismatch for bound source {name}"

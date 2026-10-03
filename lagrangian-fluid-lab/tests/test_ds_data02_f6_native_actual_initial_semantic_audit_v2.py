"""Targeted synthetic unit tests for DS-DATA-02 F6 Prospective Angular Release Semantic Audit v2.

Adheres strictly to Root Continuation 015 instructions:
- Synthetic small fixtures and syntax checks only.
- Does NOT execute solver, PartVTK, conversion, labels, or actual campaign H5/CSV data audit.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile

import numpy as np
import pytest

from scripts.ds_data02_f6_native_actual_initial_semantic_audit_v2 import (
    ADAPTERS_ROOT,
    BODY_INERTIA,
    BODY_MASS_KG,
    BODY_VOLUME_M3,
    CASE_CONFIGS,
    RECIPE_ID,
    REQUESTS_ROOT,
    ROLES,
    SCHEMA_ADAPTER,
    SCHEMA_MANIFEST,
    SCHEMA_REPORT,
    SCHEMA_REQUEST,
    SUPPORT_LATTICE_WEIGHT_KG,
    _parse_and_audit_semantic_csv,
    prepare,
    sha256_file,
    MANIFEST_PATH,
    BINDINGS_PATH,
)


def test_prepare_output_structure():
    """Verify prepare() generates valid manifest, bindings, adapters, and requests."""
    res = prepare()
    assert res["status"] == "prepared"
    assert Path(res["manifest"]).is_file()
    assert Path(res["bindings"]).is_file()

    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert manifest["schema"] == SCHEMA_MANIFEST
    assert manifest["recipe_id"] == RECIPE_ID
    assert manifest["family_id"] == "F6"
    assert manifest["launch_allowed"] is False
    assert manifest["root_review_required"] is True
    assert "UNTESTED HYPOTHESIS" in manifest["untested_hypothesis_notice"]
    assert "JSph.cpp:1162" in manifest["velocity_propagation_notice"]
    assert manifest["semantic_mass_resolution"]["declared_physical_rigid_mass_kg"] == 128.0
    assert manifest["semantic_mass_resolution"]["support_lattice_weight_sum_kg"] == 256.0

    bindings = json.loads(Path(res["bindings"]).read_text(encoding="utf-8"))
    assert len(bindings["cases"]) == 3
    for role in ROLES:
        assert role in bindings["cases"]
        case_data = bindings["cases"][role]
        assert Path(case_data["adapter"]).is_file()
        assert Path(case_data["audit_request"]).is_file()
        assert Path(case_data["gpu_request"]).is_file()


def test_gencase_receipt_adapters():
    """Verify adapters satisfy ds_data02_runtime_v2.py preflight validation rules."""
    for role in ROLES:
        cfg = CASE_CONFIGS[role]
        adapter_path = ADAPTERS_ROOT / f"{role}-actual-gencase-adapter.json"
        assert adapter_path.is_file()
        adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
        assert adapter["schema"] == SCHEMA_ADAPTER
        assert adapter["returncode"] == 0
        assert adapter["total_particles"] == cfg["expected_counts"]["total"]
        assert adapter["fluid_particles"] == cfg["expected_counts"]["fluid"]
        assert adapter["solver_dimension_from_gencase"] == 3
        assert adapter["total_particles"] > adapter["fluid_particles"] > 0
        assert Path(adapter["actual_parent_receipt"]).is_file()
        assert sha256_file(adapter["actual_parent_receipt"]) == adapter["actual_parent_receipt_sha256"]


def test_runner_requests_compliance():
    """Verify audit and GPU requests meet strict runner v2 requirements."""
    for role in ROLES:
        cfg = CASE_CONFIGS[role]
        case_id = cfg["case_id"]

        # Audit Request (CPU)
        audit_path = REQUESTS_ROOT / f"{case_id}_SEMANTIC_AUDIT_REQUEST.json"
        assert audit_path.is_file()
        audit_req = json.loads(audit_path.read_text(encoding="utf-8"))
        assert audit_req["schema"] == SCHEMA_REQUEST
        assert audit_req["kind"] == "cpu"
        assert audit_req["cpu_task_kind"] == "audit"
        assert audit_req["cpu_threads"] == 2
        assert audit_req["max_wall_seconds"] <= 1800
        assert audit_req["estimated_storage_bytes"] <= 2147483648
        assert audit_req["launch_allowed"] is False
        assert audit_req["root_review_required"] is True

        # Solver Request (GPU Qualification)
        gpu_path = REQUESTS_ROOT / f"{case_id}_SOLVER_GPU_REQUEST.json"
        assert gpu_path.is_file()
        gpu_req = json.loads(gpu_path.read_text(encoding="utf-8"))
        assert gpu_req["schema"] == SCHEMA_REQUEST
        assert gpu_req["kind"] == "qualification"
        assert gpu_req["estimated_peak_gpu_mib"] > 0
        assert gpu_req["gencase_receipt_sha256"] == sha256_file(gpu_req["gencase_receipt"])
        assert gpu_req["launch_allowed"] is False
        assert gpu_req["root_review_required"] is True
        assert gpu_req["root_only"] is True
        assert gpu_req["initial_body_mass_semantics"]["declared_rigid_mass_kg"] == 128.0


def test_mass_and_inertia_theoretical_consistency():
    """Verify physical body mass, support lattice weight, and continuous inertia."""
    assert BODY_MASS_KG == 128.0
    assert abs(BODY_VOLUME_M3 - 0.256) < 1e-9
    assert abs(SUPPORT_LATTICE_WEIGHT_KG - 256.0) < 1e-9
    # Ratio s = rho_body / rho_fluid = 128 / 256 = 0.5
    s = BODY_MASS_KG / SUPPORT_LATTICE_WEIGHT_KG
    assert abs(s - 0.5) < 1e-9

    # Continuous box: lx=0.8, ly=0.8, lz=0.4, M=128
    # Ixx = M/12 * (ly^2 + lz^2) = 128/12 * (0.64 + 0.16) = 128/12 * 0.8 = 8.53333333333
    # Iyy = M/12 * (lx^2 + lz^2) = 128/12 * (0.64 + 0.16) = 8.53333333333
    # Izz = M/12 * (lx^2 + ly^2) = 128/12 * (0.64 + 0.64) = 128/12 * 1.28 = 13.6533333333
    ixx = (128.0 / 12.0) * (0.8**2 + 0.4**2)
    iyy = (128.0 / 12.0) * (0.8**2 + 0.4**2)
    izz = (128.0 / 12.0) * (0.8**2 + 0.8**2)
    assert abs(BODY_INERTIA[0] - ixx) < 1e-9
    assert abs(BODY_INERTIA[1] - iyy) < 1e-9
    assert abs(BODY_INERTIA[2] - izz) < 1e-9


def test_synthetic_csv_semantic_audit_parser():
    """Test _parse_and_audit_semantic_csv on a small synthetic fixture.

    Ensures the parser properly distinguishes between native support mass (summing to 256)
    and physical rigid body mass (128), validating derived node mass without altering CSV.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_file = Path(tmp_dir) / "synthetic_partvtk.csv"
        # Create a synthetic CSV with 8 floating particles, 10 fluid particles, 10 fixed particles
        # For floating particles, native mass is 256.0 / 8 = 32.0 kg
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["TimeStep [s]", "Np", "Nbound", "Nfixed", "Nmoving", "Nfloat", "Nfluid"])
            writer.writerow([0, 28, 18, 10, 0, 8, 10])
            writer.writerow([])
            writer.writerow(["Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]", "Mass [kg]", "Type", "Mk"])
            # 10 fixed particles (Type 0, Mk 1)
            for i in range(10):
                writer.writerow([0.0, 0.0, 0.0, 0, i, 0.0, 0.0, 0.0, 1000.0, 0.1, 0, 1])
            # 10 fluid particles (Type 3, Mk 2)
            for i in range(10):
                writer.writerow([1.0, 1.0, 0.5, 0, 10 + i, 0.0, 0.0, 0.0, 1000.0, 512.0, 3, 2])
            # 8 floating particles (Type 2, Mk 60), distributed symmetrically in body box [2.0, 0.8, 0.88] to [2.8, 1.6, 1.28]
            # Center is [2.4, 1.2, 1.08]
            # Native support mass sum = 8 * 32.0 = 256.0 kg
            # Physical mass = 128.0 kg -> derived node mass = 128 / 8 = 16.0 kg
            pts = [
                (2.1, 0.9, 0.98), (2.1, 0.9, 1.18), (2.1, 1.5, 0.98), (2.1, 1.5, 1.18),
                (2.7, 0.9, 0.98), (2.7, 0.9, 1.18), (2.7, 1.5, 0.98), (2.7, 1.5, 1.18),
            ]
            for i, (x, y, z) in enumerate(pts):
                writer.writerow([x, y, z, 0, 20 + i, 0.0, 0.0, 0.0, 1000.0, 32.0, 2, 60])

        cfg = {
            "expected_counts": {
                "fixed": 10,
                "moving": 0,
                "floating": 8,
                "fluid": 10,
                "total": 28,
            },
            "dp_m": 0.025,
        }

        audit = _parse_and_audit_semantic_csv(csv_file, "synthetic", cfg)

        assert audit["typed_counts"]["floating"] == 8
        assert audit["typed_counts"]["fluid"] == 10
        assert audit["typed_counts"]["fixed"] == 10
        assert audit["rows_read"] == 28
        assert audit["uid_uniqueness"]["all_uids_unique_and_consecutive"] is True

        # Check native CSV mass semantics vs declared physical mass
        mass_audit = audit["rigid_body_semantic_mass_audit"]
        assert mass_audit["native_csv_mass_sum_kg"] == 256.0
        assert mass_audit["declared_physical_mass_kg"] == 128.0
        assert mass_audit["derived_node_mass_kg"] == 16.0
        assert mass_audit["derived_total_mass_kg"] == 128.0
        assert mass_audit["declared_relative_density"] == 0.5
        assert mass_audit["native_csv_matches_fluid_density_mass"] is True
        assert mass_audit["derived_mass_matches_physical"] is True

        # Check centroid
        assert abs(mass_audit["centroid_m"][0] - 2.4) < 1e-6
        assert abs(mass_audit["centroid_m"][1] - 1.2) < 1e-6
        assert abs(mass_audit["centroid_m"][2] - 1.08) < 1e-6

        # Check velocities
        assert mass_audit["gencase_particles_zero_vel"] is True

"""Unit tests for DS-DATA-02 F6 Prospective Angular Release Native Initial QA Evaluator."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from scripts.ds_data02_f6_native_actual_initial_qa_v1 import (
    CASE_CONFIGS,
    RECIPE_ID,
    ROLES,
    prepare,
    _verify_generated_xml,
    _compare_with_frozen_parent,
    _parse_and_audit_csv,
    sha256_file,
    MANIFEST_PATH,
    BINDINGS_PATH,
)


def test_prepare_and_manifest():
    """Verify prepare() generates valid manifest, bindings, and runner requests."""
    res = prepare()
    assert res["status"] == "prepared"
    assert Path(res["manifest"]).is_file()
    assert Path(res["bindings"]).is_file()

    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert manifest["recipe_id"] == RECIPE_ID
    assert manifest["family_id"] == "F6"
    assert manifest["launch_allowed"] is False
    assert manifest["root_review_required"] is True
    assert "UNTESTED HYPOTHESIS" in manifest["untested_hypothesis_notice"]
    assert "JSph.cpp:1162" in manifest["velocity_propagation_notice"]

    bindings = json.loads(Path(res["bindings"]).read_text(encoding="utf-8"))
    assert len(bindings["cases"]) == 3
    for role in ROLES:
        assert role in bindings["cases"]
        case_data = bindings["cases"][role]
        assert Path(case_data["preflight_017"]["receipt"]).is_file()
        assert Path(case_data["preflight_017"]["generated_bi4"]).is_file()
        assert Path(case_data["preflight_017"]["generated_xml"]).is_file()

    requests = manifest["requests"]
    assert len(requests) == 6
    for key, req_path in requests.items():
        assert Path(req_path).is_file()
        req_obj = json.loads(Path(req_path).read_text(encoding="utf-8"))
        assert req_obj["schema"] == "ds02.runner-request.v2"
        assert req_obj["cpu_threads"] == 2
        assert req_obj["max_wall_seconds"] == 1800
        assert req_obj["estimated_storage_bytes"] <= 2147483648
        assert req_obj["launch_allowed"] is False
        assert req_obj["root_review_required"] is True


def test_verify_generated_xml_preflights():
    """Verify generated XMLs from ROOT preflights 017 contain expected parameters."""
    for role in ROLES:
        cfg = CASE_CONFIGS[role]
        xml_path = cfg["preflight_dir"] / f"{cfg['case_id']}.xml"
        assert xml_path.is_file()

        audit = _verify_generated_xml(xml_path)
        assert audit["all_xml_checks_passed"] is True
        assert audit["angularvelini_match"] is True
        assert audit["angularvelini_rad_s"] == [0.08, 0.12, 0.06]
        assert audit["is_free_6dof"] is True
        assert audit["translation_dof"] == [1, 1, 1]
        assert audit["rotation_dof"] == [1, 1, 1]
        assert audit["time_max_12s"] is True
        assert audit["visco_treatment_2_laminar_sps"] is True
        assert audit["visco_1e_6"] is True
        assert audit["massbody_match"] is True
        assert audit["center_match"] is True


def test_frozen_parent_fluid_vtk_integrity():
    """Verify fluid VTK payloads from preflight 017 are byte-identical to parent VTKs."""
    for role in ROLES:
        cfg = CASE_CONFIGS[role]
        comp = _compare_with_frozen_parent(cfg, cfg["preflight_dir"])
        assert comp["fluid_payload_byte_identical"] is True
        assert comp["fixed_prefix_payload_byte_identical"] is True


def test_preflight_017_receipts_bound():
    """Verify source execution receipts from preflight 017 match documented elapsed times and returncode 0."""
    for role in ROLES:
        cfg = CASE_CONFIGS[role]
        receipt_path = cfg["preflight_receipt"]
        assert receipt_path.is_file()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["returncode"] == 0
        assert receipt["status"] == "completed"
        assert abs(receipt["elapsed_seconds"] - cfg["preflight_017_elapsed_s"]) < 0.01
        assert receipt["total_particles"] == cfg["expected_counts"]["total"]
        assert receipt["fluid_particles"] == cfg["expected_counts"]["fluid"]


def test_errata_sidecar_consistency():
    """Verify analysis-summary-errata.json exists and contains authoritative findings."""
    sidecar_path = (
        Path(__file__).resolve().parents[1]
        / "campaigns/ds-data-02/families/F6/handoff_20261003/f6_existing_floating_descriptive_analysis_001/analysis-summary-errata.json"
    )
    assert sidecar_path.is_file()
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["schema"] == "ds02.f6.descriptive-analysis-and-prereg-errata.v1"
    assert sidecar["family_id"] == "F6"

    # Verify peak angular amplitude finding
    peak_corr = next(c for c in sidecar["corrections"] if c["subject"] == "angular_peak_amplitude")
    assert peak_corr["exact_values_rad"]["fine_dp0125"]["yaw"] == 0.09473341
    assert "0.09473341" in peak_corr["authoritative_finding"]

    # Verify RMSE finding
    rmse_corr = next(c for c in sidecar["corrections"] if c["subject"] == "orientation_rmse_scaling")
    assert rmse_corr["exact_absolute_rmse_rad"]["fine_vs_coarse"]["yaw"] == 0.06269848
    assert "0.06269848" in rmse_corr["authoritative_finding"]
    assert "3.59" in rmse_corr["authoritative_finding"]

    # Verify velocity propagation architecture finding
    vel_corr = next(c for c in sidecar["corrections"] if c["subject"] == "initial_angular_node_velocity_propagation")
    assert "JSph.cpp:1162" in vel_corr["authoritative_finding"]
    assert "Part_0000.bi4" in vel_corr["authoritative_finding"]


def test_csv_audit_with_mock_data():
    """Verify _parse_and_audit_csv on a synthetic dataset."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "test_initial_all.csv"

        # Construct a synthetic CSV with 1 fixed, 2 floating, 2 fluid particles
        cfg = {
            "dp_m": 0.025,
            "expected_counts": {
                "fixed": 1,
                "moving": 0,
                "floating": 2,
                "fluid": 2,
                "total": 5,
            },
        }

        # Write lines
        lines = [
            "TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid",
            "0,5,3,1,0,2,2",
            "",
            "Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3],Mass [kg],Press [Pa],Vol [m^3],Ace.x [m/s^2],Ace.y [m/s^2],Ace.z [m/s^2],Vor.x [1/s],Vor.y [1/s],Vor.z [1/s],EnKin [J],EnPot [J],EnInt [J],EnTot [J],Type,Mk,",
            # Fixed wall: x=0.0125, y=0.0125, z=0.0125
            "  1.2500000E-02,  1.2500000E-02,  1.2500000E-02,0,0,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  1.0000000E+03,  1.5625000E-02,  0.0000000E+00,  1.5625001E-05,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,0,30,",
            # Floating body 1: x=2.39, y=1.2, z=1.08, mass=64
            "  2.3900000E+00,  1.2000000E+00,  1.0800000E+00,0,1,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  1.0000000E+03,  6.4000000E+01,  0.0000000E+00,  1.5625001E-05,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,2,60,",
            # Floating body 2: x=2.41, y=1.2, z=1.08, mass=64
            "  2.4100000E+00,  1.2000000E+00,  1.0800000E+00,0,2,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  1.0000000E+03,  6.4000000E+01,  0.0000000E+00,  1.5625001E-05,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,2,60,",
            # Fluid 1: x=2.4, y=1.2, z=0.5, mass=2560
            "  2.4000000E+00,  1.2000000E+00,  5.0000000E-01,0,3,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  1.0000000E+03,  2.5600000E+03,  0.0000000E+00,  1.5625001E-05,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,3,1,",
            # Fluid 2: x=2.4, y=1.2, z=0.6, mass=2560
            "  2.4000000E+00,  1.2000000E+00,  6.0000000E-01,0,4,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  1.0000000E+03,  2.5600000E+03,  0.0000000E+00,  1.5625001E-05,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,  0.0000000E+00,3,1,",
        ]
        csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        audit = _parse_and_audit_csv(csv_file, "coarse", cfg)
        assert audit["rows_read"] == 5
        assert audit["counts_match"] is True
        assert audit["uid_uniqueness"]["all_uids_unique_and_consecutive"] is True
        assert audit["rigid_body"]["mass_match"] is True
        assert audit["rigid_body"]["total_mass_kg"] == 128.0
        assert audit["rigid_body"]["centroid_match"] is True
        assert audit["fluid"]["mass_match"] is True
        assert audit["fluid"]["native_total_mass_kg"] == 5120.0
        assert audit["clearance_body_fluid_no_subsampling"]["min_distance_m"] > 0.0
        assert audit["rigid_body"]["gencase_particles_zero_vel"] is True

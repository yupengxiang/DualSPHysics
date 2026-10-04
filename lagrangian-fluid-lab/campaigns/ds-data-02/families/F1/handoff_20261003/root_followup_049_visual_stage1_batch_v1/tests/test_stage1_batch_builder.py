#!/usr/bin/env python3
"""Test suite for Family F1 Stage 1 Visual Product and Batch Builder."""
from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

SCOPE_DIR = Path(__file__).resolve().parent.parent
MATRIX_FILE = SCOPE_DIR / "batch_definitions" / "batch_8_physical_parameter_matrix.json"
BINDINGS_DIR = SCOPE_DIR / "bindings"
REQUESTS_DIR = SCOPE_DIR / "requests"
DEFS_DIR = SCOPE_DIR / "definitions"
META_DIR = SCOPE_DIR / "metadata"


def test_audit_and_plan_documentation_exist():
    audit_file = SCOPE_DIR / "SOURCE_AUDIT_027_035_AND_CANONICAL_034.md"
    plan_file = SCOPE_DIR / "STAGE1_VISUAL_PRODUCT_PLAN.md"
    assert audit_file.exists() and audit_file.stat().st_size > 1000
    assert plan_file.exists() and plan_file.stat().st_size > 1000

    content = audit_file.read_text()
    assert "687c069f836dd81b3c4c85ea6f977f9f2775debea01d3657b81356801ced71d3" in content
    assert "feb710be76c89fb67074b1bbbf6c9c22869652ce5760c4d7e4721187b4d580bf" in content


def test_physical_parameter_matrix_integrity():
    assert MATRIX_FILE.exists()
    matrix = json.loads(MATRIX_FILE.read_text())

    assert matrix["schema"] == "ds02.stage1.physical-batch-matrix.v1"
    assert matrix["family_id"] == "F1"
    assert matrix["target_batch_size"] == 8
    assert len(matrix["rows"]) == 8

    ecc_rows = [r for r in matrix["rows"] if r["mechanism_id"] == "eccentric_obstacle"]
    dual_rows = [r for r in matrix["rows"] if r["mechanism_id"] == "asymmetric_dual_channel"]
    assert len(ecc_rows) == 4
    assert len(dual_rows) == 4

    roles = {"anchor_mother", "endpoint_min_head", "endpoint_max_head", "interior_check"}
    assert {r["variation_role"] for r in ecc_rows} == roles
    assert {r["variation_role"] for r in dual_rows} == roles

    for row in matrix["rows"]:
        proof = row["safe_variation_proof"]
        assert proof["fill_below_failed_mother"] is True
        assert proof["freeboard_margin_m"] >= 0.20
        assert proof["legal_wall_clearance_m"] >= 0.10
        assert proof["genuine_3d"] is True

        params = row["physical_parameters"]
        assert params["expected_frames"] in (161, 401)
        assert params["time_out_s"] == 0.01

        # Check multi-dp policy
        resolutions = row["resolutions"]
        assert "coarse" in resolutions and "medium" in resolutions


def test_xml_definitions_validity():
    xml_files = list(DEFS_DIR.glob("*_Def.xml"))
    assert len(xml_files) == 16  # 8 cases * 2 resolutions

    for xf in xml_files:
        tree = ET.parse(xf)
        root = tree.getroot()
        assert root.tag == "case"

        # Check casedef and geometry
        casedef = root.find("casedef")
        assert casedef is not None
        constants = casedef.find("constantsdef")
        assert constants is not None
        assert constants.find("gravity").get("z") == "-9.81"
        assert constants.find("gamma").get("value") == "7"

        geom = casedef.find("geometry")
        definition = geom.find("definition")
        assert float(definition.get("dp")) > 0

        # Check thick boundary commands
        commands = geom.find(".//commands/mainlist")
        assert commands is not None
        mkbounds = commands.findall("setmkbound")
        assert len(mkbounds) >= 2  # mk 0 and mk 1

        # Check execution parameters
        exec_node = root.find("execution/parameters")
        assert exec_node is not None
        tmax = None
        for p in exec_node.findall("parameter"):
            if p.get("key") == "TimeMax":
                tmax = float(p.get("value"))
        assert tmax in (1.6, 4.0)


def test_metadata_files_validity():
    meta_files = list(META_DIR.glob("*.metadata.json"))
    assert len(meta_files) == 16

    for mf in meta_files:
        data = json.loads(mf.read_text())
        assert data["schema"] == "ds02.stage1.case-metadata.v1"
        assert data["family_id"] == "F1"
        assert data["predicted_fluid_particles"] > 10000
        assert data["continuum_mass_kg"] > 0
        if "ANCHOR" not in data["physical_case_id"]:
            assert data["dispatch_gate"] == "disabled_pending_root_visual_review"


def test_runner_requests_conformance():
    req_files = list(REQUESTS_DIR.glob("*.json"))
    assert len(req_files) >= 36  # 16 gencase + 16 solver + 4 visual requests

    gencase_reqs = list(REQUESTS_DIR.glob("*_gencase_request.json"))
    solver_reqs = list(REQUESTS_DIR.glob("*_solver_request.json"))
    assert len(gencase_reqs) == 16
    assert len(solver_reqs) == 16

    for gr in gencase_reqs:
        d = json.load(open(gr))
        assert d["schema"] == "ds02.runner-request.v2"
        assert d["kind"] == "cpu"
        assert d["cpu_task_kind"] == "preflight"
        if "ANCHOR" not in d["case_id"]:
            assert d["launch_allowed"] is False
            assert d["dispatch_status"] == "disabled_pending_root_visual_review"

    for sr in solver_reqs:
        d = json.load(open(sr))
        assert d["schema"] == "ds02.runner-request.v2"
        assert d["kind"] == "qualification"
        assert d["launch_allowed"] is False
        if "COARSE" in d["case_id"]:
            assert d["independent_case_count_increment"] == 1
        else:
            assert d["independent_case_count_increment"] == 0
        assert "numerical_precision_pending" in d["gate"]


def test_visual_bindings_and_xdmf_requests():
    bindings = list(BINDINGS_DIR.glob("*.json"))
    assert len(bindings) == 6

    for b in bindings:
        d = json.load(open(b))
        assert d["family_id"] == "F1"
        assert d["expected_frames"] in (161, 401)
        assert "not_accepted_for_stage1_product" in d["numerical_precision_status"]

    ecc_coarse_xdmf = REQUESTS_DIR / "ecc-coarse-xdmf-request.json"
    ecc_medium_xdmf = REQUESTS_DIR / "ecc-medium-xdmf-request.json"
    assert ecc_coarse_xdmf.exists() and ecc_medium_xdmf.exists()

    d_c = json.load(open(ecc_coarse_xdmf))
    assert d_c["launch_allowed"] is True
    assert d_c["independent_case_count_increment"] == 0

    d_m = json.load(open(ecc_medium_xdmf))
    assert d_m["launch_allowed"] is True
    assert d_m["independent_case_count_increment"] == 0


def test_zero_side_effects():
    # Verify no raw data was touched or written into DualSPHysics-data by builder
    new_dirs = list(Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1").glob("*PHYS*"))
    assert len(new_dirs) == 0, "Builder must NOT create directories in raw data store"

"""Pytest unit test suite for Family F1 prospective fallback conformance."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest


BASE_DIR = Path(__file__).resolve().parents[1]
DEFINITIONS_DIR = BASE_DIR / "definitions"
LABELS_DIR = BASE_DIR / "labels"
REQUESTS_DIR = BASE_DIR / "requests"


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def test_reference_matrix_and_mass_conservation():
    matrix_path = DEFINITIONS_DIR / "fallback_reference_matrix.json"
    assert matrix_path.is_file()
    with open(matrix_path, "r", encoding="utf-8") as f:
        matrix = json.load(f)

    pair = matrix["legal_fallback_pair"]
    assert "eccentric_obstacle" in pair
    assert "asymmetric_dual_channel" in pair

    # Eccentric Obstacle
    ecc = pair["eccentric_obstacle"]
    assert ecc["physical_case_id"] == "F1_FALLBACK_ECC_V1"
    assert math.isclose(ecc["mass_kg"], 40.200, rel_tol=1e-12)
    for case in ecc["cases"]:
        assert math.isclose(case["fluid_mass_kg"], 40.200, rel_tol=1e-12)
        calc = case["fluid_particles"] * 1000.0 * (case["dp_m"] ** 3)
        assert math.isclose(calc, 40.200, rel_tol=1e-12)

    # Asymmetric Dual Channel
    dual = pair["asymmetric_dual_channel"]
    assert dual["physical_case_id"] == "F1_FALLBACK_DUAL_V1"
    assert math.isclose(dual["mass_kg"], 300.000, rel_tol=1e-12)
    for case in dual["cases"]:
        assert math.isclose(case["fluid_mass_kg"], 300.000, rel_tol=1e-12)
        calc = case["fluid_particles"] * 1000.0 * (case["dp_m"] ** 3)
        assert math.isclose(calc, 300.000, rel_tol=1e-12)


def test_xml_thick_dbc_and_drawmodes():
    xmls = list(DEFINITIONS_DIR.glob("*_Def.xml"))
    assert len(xmls) == 6
    for x in xmls:
        root = ET.parse(x).getroot()
        mainlist = root.find("./casedef/geometry/commands/mainlist")
        assert mainlist is not None
        drawmode = mainlist.find("setdrawmode")
        assert drawmode is not None
        assert drawmode.attrib.get("mode") == "full"

        # Check boxfill=solid on all drawboxes
        for b in mainlist.findall("drawbox"):
            assert b.findtext("boxfill") == "solid"


def test_label_event_configs():
    for name in ["eccentric_fallback_event_config.json", "dual_channel_fallback_event_config.json"]:
        path = LABELS_DIR / name
        assert path.is_file()
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        dest_ids = {r["id"] for r in cfg["destination_regions"]}
        assert {"upstream", "lower_channel", "upper_channel", "downstream"}.issubset(dest_ids)


def test_runner_requests_integrity():
    reqs = list(REQUESTS_DIR.glob("*.json"))
    assert len(reqs) == 12
    for r in reqs:
        with open(r, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema"] == "ds02.runner.request.v2"
        assert data["family_id"] == "F1"
        assert data["parent_review_required"] is True

        for infile in data["input_files"]:
            p = Path(infile)
            assert p.is_file(), f"File {infile} does not exist"
            assert sha256_file(p) == data["input_hashes"][infile]

"""Pytest unit test suite for Family F1 Followup 042 prospective fallback conformance."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import pytest


BASE_DIR = Path(__file__).resolve().parents[1]
DEFINITIONS_DIR = BASE_DIR / "definitions"
LABELS_DIR = BASE_DIR / "labels"
REQUESTS_DIR = BASE_DIR / "requests"
SCRIPTS_DIR = BASE_DIR / "scripts"


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def test_erratum_retractions():
    erratum_path = BASE_DIR / "ERRATUM_AND_PROSPECTIVE_BINDING_REWRITE.md"
    assert erratum_path.is_file(), f"Missing erratum file at {erratum_path}"
    text = erratum_path.read_text(encoding="utf-8")

    # Retraction 1: 75% peak kinetic suppression
    assert "75% Peak Kinetic Energy Suppression" in text
    # Retraction 2: Laminar stable stagnation
    assert "Laminar Stable Stagnation" in text
    # Retraction 3: Fate switches, overtopping, droplet loss
    assert "Fate Switches" in text
    # Retraction 4: Unauthorized gate |vy|max > 0.4 m/s
    assert "0.4" in text and ("|vy|max" in text or "|v_y|" in text)
    # Native weights representation
    assert "Native Weights Reporting" in text
    # Preservation of 041 bytes
    assert "root_followup_041_bounded_fallback_v1" in text


def test_reference_matrix_and_native_weights():
    matrix_path = DEFINITIONS_DIR / "fallback_reference_matrix.json"
    assert matrix_path.is_file()
    with open(matrix_path, "r", encoding="utf-8") as f:
        matrix = json.load(f)

    assert matrix["schema"] == "ds02.f1.fallback-reference-matrix.v2"
    pair = matrix["legal_fallback_pair"]
    assert "eccentric_obstacle" in pair
    assert "asymmetric_dual_channel" in pair

    # Eccentric Obstacle
    ecc = pair["eccentric_obstacle"]
    assert ecc["physical_case_id"] == "F1_FALLBACK_ECC_V1"
    assert math.isclose(ecc["controlled_depth_H0_m"], 0.150, abs_tol=1e-12)
    # Ensure no invented gate
    assert "0.4" not in ecc.get("transverse_effect_descriptor", "")
    for case in ecc["cases"]:
        assert math.isclose(case["theoretical_mass_kg"], 40.200, rel_tol=1e-12)
        calc_float32 = 1000.0 * (case["dp_m"] ** 3)
        assert math.isclose(case["native_weight_float32_kg"], calc_float32, rel_tol=1e-4)

    # Asymmetric Dual Channel
    dual = pair["asymmetric_dual_channel"]
    assert dual["physical_case_id"] == "F1_FALLBACK_DUAL_V1"
    assert math.isclose(dual["controlled_depth_H0_m"], 0.300, abs_tol=1e-12)
    assert "0.4" not in dual.get("transverse_effect_descriptor", "")
    for case in dual["cases"]:
        assert math.isclose(case["theoretical_mass_kg"], 300.000, rel_tol=1e-12)
        calc_float32 = 1000.0 * (case["dp_m"] ** 3)
        assert math.isclose(case["native_weight_float32_kg"], calc_float32, rel_tol=1e-4)


def test_thick_dbc_xml_and_drawmodes():
    xmls = list(DEFINITIONS_DIR.glob("*_Def.xml"))
    assert len(xmls) == 6
    for x in xmls:
        root = ET.parse(x).getroot()
        defn = root.find("./casedef/geometry/definition")
        assert defn is not None
        dp = float(defn.attrib["dp"])

        pref = defn.find("pointref")
        assert pref is not None
        assert math.isclose(float(pref.attrib["x"]), dp / 2, rel_tol=1e-5)
        assert math.isclose(float(pref.attrib["y"]), dp / 2, rel_tol=1e-5)
        assert math.isclose(float(pref.attrib["z"]), dp / 2, rel_tol=1e-5)

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
        assert len(cfg["events"]) >= 3


def test_runner_requests_integrity_and_threads():
    reqs = list(REQUESTS_DIR.glob("*.json"))
    assert len(reqs) == 12
    for r in reqs:
        with open(r, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema"] == "ds02.runner-request.v2"
        assert data["family_id"] == "F1"
        assert data["launch_allowed"] is False
        assert data["launch_owner"] == "root"

        if data["kind"] == "cpu":
            assert data["cpu_threads"] == 4
            assert "--threads" in data["command"]
            idx = data["command"].index("--threads")
            assert data["command"][idx + 1] == "4"

        for infile in data["input_files"]:
            p = Path(infile)
            assert p.is_file(), f"File {infile} does not exist (in {r.name})"
            assert sha256_file(p) == data["input_sha256"][infile]


def test_rootguard_prepworker_dry_run():
    worker = SCRIPTS_DIR / "rootguard_prepworker.py"
    assert worker.is_file() and os.access(worker, os.X_OK)

    with tempfile.TemporaryDirectory(prefix="pytest-prepworker-") as tmpdir:
        cmd = [
            sys.executable,
            str(worker),
            "--all-cases",
            "--attempt-root",
            tmpdir,
            "--definitions-dir",
            str(DEFINITIONS_DIR),
            "--threads",
            "4",
            "--dry-run",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, f"Worker dry-run failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"

        # Check reports
        for case_id in [
            "F1_FALLBACK_ECC_COARSE", "F1_FALLBACK_ECC_MEDIUM", "F1_FALLBACK_ECC_FINE",
            "F1_FALLBACK_DUAL_COARSE", "F1_FALLBACK_DUAL_MEDIUM", "F1_FALLBACK_DUAL_FINE"
        ]:
            report_file = Path(tmpdir) / case_id / f"{case_id}_preflight_report.json"
            assert report_file.is_file()
            with open(report_file, "r", encoding="utf-8") as f:
                rep = json.load(f)
            assert rep["schema"] == "ds02.f1.gencase-preflight-report.v1"
            assert rep["threads"] == 4
            assert rep["threads_matching_reservation"] is True
            assert "predictions" in rep
            assert "actual" in rep
            assert rep["coherence"]["coherence_passed"] is True

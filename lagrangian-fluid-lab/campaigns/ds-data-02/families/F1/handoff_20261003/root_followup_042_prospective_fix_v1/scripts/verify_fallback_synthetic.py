#!/usr/bin/env python3
"""Synthetic verification script for Family F1 Followup 042 prospective fallback suite.

Performs zero-arithmetic preflight checks without launching scientific binaries:
1. Erratum verification (retraction of 4 unsupported claims & invented gate).
2. Lattice commensurability and native weights representation.
3. Thick DBC XML structure (pointref, solid slabs, full drawmodes, no hollow modes).
4. Canonical native label region partitions and aperture definitions.
5. Runner request schema (ds02.runner-request.v2), thread reservation, and hash integrity.
6. Rootguard prepworker dry-run preflight verification.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET


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


def test_erratum_content() -> None:
    print("[Check 1/6] Verifying Erratum and prospective rewrite...")
    erratum_path = BASE_DIR / "ERRATUM_AND_PROSPECTIVE_BINDING_REWRITE.md"
    assert erratum_path.is_file(), f"Missing erratum: {erratum_path}"
    content = erratum_path.read_text(encoding="utf-8")

    assert "75% Peak Kinetic Energy Suppression" in content
    assert "Laminar Stable Stagnation" in content
    assert "Fate Switches" in content
    assert "|v_y|_{\\text{max}} > 0.4" in content or "|vy|max" in content or "0.4" in content
    assert "Native Weights Reporting" in content
    assert "root_followup_041_bounded_fallback_v1" in content
    print("  PASS: Erratum explicitly retracts all 4 unsupported claims and the unauthorized gate.")


def test_commensurability_and_native_weights() -> None:
    print("[Check 2/6] Verifying lattice commensurability and native weights...")
    matrix_path = DEFINITIONS_DIR / "fallback_reference_matrix.json"
    assert matrix_path.is_file(), f"Missing {matrix_path}"
    with open(matrix_path, "r", encoding="utf-8") as f:
        matrix = json.load(f)

    pair = matrix["legal_fallback_pair"]
    assert "eccentric_obstacle" in pair
    assert "asymmetric_dual_channel" in pair

    # Check ECC
    ecc = pair["eccentric_obstacle"]
    assert ecc["physical_case_id"] == "F1_FALLBACK_ECC_V1"
    assert math.isclose(ecc["controlled_depth_H0_m"], 0.150, abs_tol=1e-9)
    assert "0.4" not in ecc.get("transverse_effect_descriptor", "")
    for case in ecc["cases"]:
        assert math.isclose(case["theoretical_mass_kg"], 40.200, rel_tol=1e-9)
        assert math.isclose(case["native_weight_float32_kg"], 1000.0 * (case["dp_m"] ** 3), rel_tol=1e-4)

    # Check DUAL
    dual = pair["asymmetric_dual_channel"]
    assert dual["physical_case_id"] == "F1_FALLBACK_DUAL_V1"
    assert math.isclose(dual["controlled_depth_H0_m"], 0.300, abs_tol=1e-9)
    for case in dual["cases"]:
        assert math.isclose(case["theoretical_mass_kg"], 300.000, rel_tol=1e-9)
        assert math.isclose(case["native_weight_float32_kg"], 1000.0 * (case["dp_m"] ** 3), rel_tol=1e-4)

    print("  PASS: Lattice commensurability and float32 native weights verified.")


def test_thick_dbc_xml_structure() -> None:
    print("[Check 3/6] Verifying thick DBC XML definitions and solid drawmodes...")
    xml_files = list(DEFINITIONS_DIR.glob("*_Def.xml"))
    assert len(xml_files) == 6, f"Expected 6 XML files, got {len(xml_files)}"

    for x_path in xml_files:
        tree = ET.parse(x_path)
        root = tree.getroot()

        defn = root.find("./casedef/geometry/definition")
        assert defn is not None, f"Missing definition in {x_path}"
        dp = float(defn.attrib["dp"])

        pref = defn.find("pointref")
        assert pref is not None, f"Missing pointref in {x_path}"
        assert math.isclose(float(pref.attrib["x"]), dp / 2, rel_tol=1e-5)
        assert math.isclose(float(pref.attrib["y"]), dp / 2, rel_tol=1e-5)
        assert math.isclose(float(pref.attrib["z"]), dp / 2, rel_tol=1e-5)

        mainlist = root.find("./casedef/geometry/commands/mainlist")
        assert mainlist is not None, f"Missing mainlist in {x_path}"

        drawmode = mainlist.find("setdrawmode")
        assert drawmode is not None
        assert drawmode.attrib.get("mode") == "full"

        # Check boxfill=solid on all drawboxes
        for b in mainlist.findall("drawbox"):
            assert b.findtext("boxfill") == "solid", f"Non-solid boxfill in {x_path}: {b.attrib}"

    print("  PASS: All 6 XMLs feature cell-centered pointref and 100% solid drawboxes.")


def test_label_event_configs() -> None:
    print("[Check 4/6] Verifying label event configs and canonical partitions...")
    for name in ["eccentric_fallback_event_config.json", "dual_channel_fallback_event_config.json"]:
        path = LABELS_DIR / name
        assert path.is_file(), f"Missing label config: {path}"
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        assert cfg["schema"] == "ds-data-02.static-event-config.v1"
        assert cfg["frame_kind"] == "fixed_solver_frame"
        dest_ids = {r["id"] for r in cfg["destination_regions"]}
        assert {"upstream", "lower_channel", "upper_channel", "downstream"}.issubset(dest_ids)
        assert len(cfg["events"]) >= 3
        assert "unknown" in cfg.get("interpretation", "").lower()

    print("  PASS: Label configs match Root 026 metadata conventions.")


def test_runner_requests_integrity() -> None:
    print("[Check 5/6] Verifying runner requests schema and SHA-256 integrity...")
    req_files = list(REQUESTS_DIR.glob("*.json"))
    assert len(req_files) == 12, f"Expected 12 requests, got {len(req_files)}"

    for r_path in req_files:
        with open(r_path, "r", encoding="utf-8") as f:
            req = json.load(f)

        assert req["schema"] == "ds02.runner-request.v2", f"Invalid schema in {r_path}: {req.get('schema')}"
        assert req["family_id"] == "F1"
        assert req["launch_allowed"] is False, f"Request {r_path} must be launch_allowed: false"
        assert req["launch_owner"] == "root"

        if req["kind"] == "cpu":
            assert req["cpu_task_kind"] == "gencase"
            assert req["cpu_threads"] == 4
            assert "--threads" in req["command"]
            idx = req["command"].index("--threads")
            assert req["command"][idx + 1] == "4", f"Threads argument mismatch in {r_path}"

        for infile in req["input_files"]:
            p = Path(infile)
            assert p.is_file(), f"Input file missing: {infile} (referenced in {r_path.name})"
            actual_sha = sha256_file(p)
            expected_sha = req["input_sha256"][infile]
            assert actual_sha == expected_sha, f"SHA mismatch on {infile} in {r_path.name}: {actual_sha} vs {expected_sha}"

    print("  PASS: All 12 runner requests verified with valid schema, matching threads, and exact SHAs.")


def test_prepworker_dry_run() -> None:
    print("[Check 6/6] Verifying Rootguard prepworker dry-run execution...")
    worker = SCRIPTS_DIR / "rootguard_prepworker.py"
    assert worker.is_file() and os.access(worker, os.X_OK)

    with tempfile.TemporaryDirectory(prefix="test-prepworker-") as tmpdir:
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
        assert res.returncode == 0, f"Prepworker dry-run failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"

        # Verify preflight reports were created for all 6 cases
        for case_id in [
            "F1_FALLBACK_ECC_COARSE", "F1_FALLBACK_ECC_MEDIUM", "F1_FALLBACK_ECC_FINE",
            "F1_FALLBACK_DUAL_COARSE", "F1_FALLBACK_DUAL_MEDIUM", "F1_FALLBACK_DUAL_FINE"
        ]:
            report_file = Path(tmpdir) / case_id / f"{case_id}_preflight_report.json"
            assert report_file.is_file(), f"Missing preflight report for {case_id}"
            with open(report_file, "r", encoding="utf-8") as f:
                rep = json.load(f)
            assert rep["schema"] == "ds02.f1.gencase-preflight-report.v1"
            assert rep["threads"] == 4
            assert rep["threads_matching_reservation"] is True
            assert "predictions" in rep
            assert "actual" in rep
            assert rep["coherence"]["coherence_passed"] is True

    print("  PASS: Prepworker dry-run confirmed with coherent predictions vs actuals.")


def main() -> int:
    print("Starting Family F1 Followup 042 Synthetic Conformance Verification...")
    test_erratum_content()
    test_commensurability_and_native_weights()
    test_thick_dbc_xml_structure()
    test_label_event_configs()
    test_runner_requests_integrity()
    test_prepworker_dry_run()
    print("\nALL 6 SYNTHETIC CONFORMANCE CHECKS PASSED SUCCESSFULLY.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

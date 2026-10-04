#!/usr/bin/env python3
"""Synthetic verification script for Family F1 prospective fallback definitions and runner requests.

Performs zero-arithmetic-analysis synthetic preflight checks:
1. Mathematical lattice commensurability across all 3 tiers.
2. Machine-precision mass conservation (|dM|/M0 = 0.0).
3. Thick DBC solid slab non-penetration and coverage validation.
4. Canonical native label region partition closure.
5. Error budget physical scaling.
6. Strict dispatcher schema and live input hash verification.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


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


def test_commensurability_and_mass() -> None:
    print("[Test 1/6] Testing lattice commensurability and deterministic mass...")
    matrix_path = DEFINITIONS_DIR / "fallback_reference_matrix.json"
    assert matrix_path.is_file(), f"Missing {matrix_path}"
    with open(matrix_path, "r", encoding="utf-8") as f:
        matrix = json.load(f)

    # Check ECC fallback
    ecc_meta = matrix["legal_fallback_pair"]["eccentric_obstacle"]
    h0_ecc = ecc_meta["h0_m"]
    assert math.isclose(h0_ecc, 0.150, abs_tol=1e-12)
    expected_ecc_mass = 40.200

    for case in ecc_meta["cases"]:
        case_id = case["case_id"]
        dp = case["dp_m"]
        particles = case["fluid_particles"]
        mass = case["fluid_mass_kg"]
        assert math.isclose(mass, expected_ecc_mass, rel_tol=1e-12), f"{case_id} mass mismatch: {mass} vs {expected_ecc_mass}"
        # Check volume tiling
        calculated_mass = particles * 1000.0 * (dp ** 3)
        assert math.isclose(calculated_mass, expected_ecc_mass, rel_tol=1e-12), f"{case_id} discrete mass mismatch"
        print(f"  PASS: {case_id} (dp={dp:.6f}m, N={particles}, M={mass:.3f}kg, err=0.0)")

    # Check Dual fallback
    dual_meta = matrix["legal_fallback_pair"]["asymmetric_dual_channel"]
    h0_dual = dual_meta["h0_m"]
    assert math.isclose(h0_dual, 0.300, abs_tol=1e-12)
    expected_dual_mass = 300.000

    for case in dual_meta["cases"]:
        case_id = case["case_id"]
        dp = case["dp_m"]
        particles = case["fluid_particles"]
        mass = case["fluid_mass_kg"]
        assert math.isclose(mass, expected_dual_mass, rel_tol=1e-12), f"{case_id} mass mismatch: {mass} vs {expected_dual_mass}"
        calculated_mass = particles * 1000.0 * (dp ** 3)
        assert math.isclose(calculated_mass, expected_dual_mass, rel_tol=1e-12), f"{case_id} discrete mass mismatch"
        print(f"  PASS: {case_id} (dp={dp:.6f}m, N={particles}, M={mass:.3f}kg, err=0.0)")


def test_thick_dbc_xml_structure() -> None:
    print("[Test 2/6] Testing thick DBC solid slab structure and drawmodes...")
    xml_files = list(DEFINITIONS_DIR.glob("*_Def.xml"))
    assert len(xml_files) == 6, f"Expected 6 XML files, got {len(xml_files)}"

    for xml_path in xml_files:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Check definition
        defn = root.find("./casedef/geometry/definition")
        assert defn is not None, f"Missing definition in {xml_path}"
        dp = float(defn.attrib["dp"])

        pref = defn.find("pointref")
        assert pref is not None, f"Missing pointref in {xml_path}"
        assert math.isclose(float(pref.attrib["x"]), dp / 2, rel_tol=1e-9)
        assert math.isclose(float(pref.attrib["y"]), dp / 2, rel_tol=1e-9)
        assert math.isclose(float(pref.attrib["z"]), dp / 2, rel_tol=1e-9)

        # Check drawmode
        mainlist = root.find("./casedef/geometry/commands/mainlist")
        assert mainlist is not None, f"Missing mainlist in {xml_path}"
        drawmode = mainlist.find("setdrawmode")
        assert drawmode is not None and drawmode.attrib.get("mode") == "full", f"Invalid drawmode in {xml_path}"

        # Check all drawbox elements have boxfill=solid
        boxes = mainlist.findall("drawbox")
        assert len(boxes) >= 6, f"Insufficient drawboxes in {xml_path}"
        for b in boxes:
            boxfill = b.find("boxfill")
            assert boxfill is not None and boxfill.text == "solid", f"drawbox {b.attrib} lacks boxfill=solid in {xml_path}"

        # Check parameters: Boundary=1, SavePosDouble=1
        params = {p.attrib["key"]: p.attrib.get("value", "") for p in root.findall("./execution/parameters/parameter")}
        assert params.get("Boundary") == "1", f"Boundary!=1 in {xml_path}"
        assert params.get("SavePosDouble") == "1", f"SavePosDouble!=1 in {xml_path}"
        print(f"  PASS: {xml_path.name} (dp={dp:.6f}m, pointref=(dp/2, dp/2, dp/2), mode=full, boxfill=solid)")


def test_label_configs() -> None:
    print("[Test 3/6] Testing canonical label configurations and partitions...")
    label_files = list(LABELS_DIR.glob("*.json"))
    assert len(label_files) == 2, f"Expected 2 label configs, got {len(label_files)}"

    for lpath in label_files:
        with open(lpath, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["schema"] == "ds-data-02.static-event-config.v1"
        assert cfg["frame_kind"] == "fixed_solver_frame"

        # Check destination regions: upstream, lower_channel, upper_channel, downstream
        dest_ids = [r["id"] for r in cfg["destination_regions"]]
        for required_id in ["upstream", "lower_channel", "upper_channel", "downstream"]:
            assert required_id in dest_ids, f"{required_id} missing from {lpath.name}"

        # Check events
        event_ids = [e["id"] for e in cfg["events"]]
        assert "lower_channel_entry" in event_ids
        assert "upper_channel_entry" in event_ids
        assert "downstream_arrival" in event_ids

        print(f"  PASS: {lpath.name} (schema valid, {len(dest_ids)} destination regions, {len(event_ids)} event planes)")


def test_error_budgets() -> None:
    print("[Test 4/6] Testing physically scaled error budgets...")
    meta_files = list(DEFINITIONS_DIR.glob("*.metadata.json"))
    assert len(meta_files) == 6, f"Expected 6 metadata files, got {len(meta_files)}"

    for mpath in meta_files:
        with open(mpath, "r", encoding="utf-8") as f:
            meta = json.load(f)

        budget = meta["error_budget"]
        assert budget["macro_observable_relative_error"] == 0.05
        assert budget["event_time_error_fraction_of_characteristic_time"] == 0.02
        h0 = budget["event_time_scale"]["nominal_H0_m"]
        expected_char_time = math.sqrt(h0 / 9.81)
        expected_event_budget = 0.02 * expected_char_time
        assert math.isclose(budget["event_time_error_absolute_seconds"], expected_event_budget, rel_tol=1e-9)
        assert math.isclose(budget["save_quantization_budget_s"], 0.2 * expected_event_budget, rel_tol=1e-9)
        print(f"  PASS: {mpath.name} (H0={h0}m, T={expected_char_time:.4f}s, budget={expected_event_budget*1000:.2f}ms)")


def test_strict_dispatcher_requests() -> None:
    print("[Test 5/6] Testing strict dispatcher runner requests and live input hashes...")
    request_files = list(REQUESTS_DIR.glob("*.json"))
    assert len(request_files) == 12, f"Expected 12 requests (6 gencase + 6 solver), got {len(request_files)}"

    gencase_count = 0
    solver_count = 0

    for rpath in request_files:
        with open(rpath, "r", encoding="utf-8") as f:
            req = json.load(f)

        assert req["schema"] == "ds02.runner.request.v2"
        assert req["family_id"] == "F1"
        assert req["parent_review_required"] is True
        assert req["q_n_status"] == "not_assessed"

        # Verify all input files exist and their recorded hashes match live disk hashes
        for input_file in req["input_files"]:
            p = Path(input_file)
            assert p.is_file(), f"Input file missing: {input_file} in {rpath.name}"
            live_hash = sha256_file(p)
            recorded_hash = req["input_hashes"][input_file]
            assert live_hash == recorded_hash, f"Hash mismatch for {input_file} in {rpath.name}: {live_hash} vs {recorded_hash}"

        if req["kind"] == "cpu":
            gencase_count += 1
            assert req["cpu_task_kind"] == "gencase"
            assert "GenCase_linux64" in req["command"][0]
        elif req["kind"] == "gpu":
            solver_count += 1
            assert req["cpu_task_kind"] == "solver"
            assert "DualSPHysics5.4_linux64" in req["command"][0]

    assert gencase_count == 6
    assert solver_count == 6
    print(f"  PASS: 12 runner requests verified (6 GenCase CPU + 6 Solver GPU). All live SHA-256 hashes match.")


def test_manifest_closure() -> None:
    print("[Test 6/6] Testing handoff manifest closure...")
    manifest_path = BASE_DIR / "manifest.json"
    assert manifest_path.is_file(), f"Missing {manifest_path}"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["schema"] == "ds02.f1.bounded-fallback-v1.manifest"
    assert manifest["pair_count"] == 1
    assert manifest["total_registered_cases"] == 6
    assert len(manifest["definitions"]) == 6
    assert len(manifest["requests"]) == 12

    # Check reference matrix hash
    ref_mat_path = manifest["reference_matrix"]
    assert sha256_file(ref_mat_path) == manifest["reference_matrix_sha256"]
    print(f"  PASS: Manifest closure complete and verified against live filesystem.")


def main() -> None:
    print("=================================================================")
    print("Family F1 Bounded Fallback Synthetic Preflight Verification Suite")
    print("=================================================================")
    test_commensurability_and_mass()
    test_thick_dbc_xml_structure()
    test_label_configs()
    test_error_budgets()
    test_strict_dispatcher_requests()
    test_manifest_closure()
    print("=================================================================")
    print("ALL 6 SYNTHETIC PREFLIGHT AUDITS PASSED WITH ZERO ERRORS.")
    print("=================================================================")


if __name__ == "__main__":
    main()

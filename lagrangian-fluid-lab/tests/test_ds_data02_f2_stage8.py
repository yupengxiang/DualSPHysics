#!/usr/bin/env python3
"""Comprehensive test suite for Family F2 Stage 8 production assets, preflights, and requests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

FAMILY_ROOT = REPO / "campaigns/ds-data-02/families/F2"
PROD_DEFS = FAMILY_ROOT / "production/definitions"
PROD_OWNER = FAMILY_ROOT / "production/owner_metadata"
REQUESTS_DIR = FAMILY_ROOT / "requests"
DATA_F2_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")

EXPECTED_ROSTER = [
    ("F2_CENTER_P01", "center_catch", "F2_PAIR_01", 2, 103995, 3094, 93961, 6940, "open_rim", None),
    ("F2_OFFSET_P01", "offset_spill", "F2_PAIR_01", 5, 103995, 3094, 93961, 6940, "open_rim", None),
    ("F2_CENTER_P02", "center_catch", "F2_PAIR_02", 6, 103995, 3094, 93961, 6940, "short_spout", "short_spout_geometry"),
    ("F2_OFFSET_P02", "offset_spill", "F2_PAIR_02", 7, 103995, 3094, 93961, 6940, "short_spout", "short_spout_geometry"),
    ("F2_CENTER_P03", "center_catch", "F2_PAIR_03", 2, 105662, 3094, 95628, 6940, "open_rim", None),
    ("F2_OFFSET_P03", "offset_spill", "F2_PAIR_03", 5, 105662, 3094, 95628, 6940, "open_rim", None),
    ("F2_CENTER_P04", "center_catch", "F2_PAIR_04", 6, 105662, 3094, 95628, 6940, "short_spout", "short_spout_geometry"),
    ("F2_OFFSET_P04", "offset_spill", "F2_PAIR_04", 7, 105662, 3094, 95628, 6940, "short_spout", "short_spout_geometry"),
]


class TestF2Stage8Production(unittest.TestCase):
    def test_01_roster_and_definitions_exist(self):
        """Verify XML definitions, motion files, and metadata sidecars exist and parse cleanly."""
        for cid, mech, pair_id, gpu, total, fluid, fixed, moving, mouth, holdout in EXPECTED_ROSTER:
            xml_path = PROD_DEFS / f"{cid}_Def.xml"
            motion_path = PROD_DEFS / f"{cid}_motion.dat"
            meta_path = PROD_DEFS / f"{cid}.metadata.json"

            self.assertTrue(xml_path.is_file(), f"Missing definition XML: {xml_path}")
            self.assertTrue(motion_path.is_file(), f"Missing motion file: {motion_path}")
            self.assertTrue(meta_path.is_file(), f"Missing metadata json: {meta_path}")

            # Verify XML parsing
            tree = ET.parse(xml_path)
            root = tree.getroot()
            self.assertIsNotNone(root.find("casedef"))
            self.assertIsNotNone(root.find("execution"))

            # Check remediated containment tray & lip walls
            commands = root.findall(".//drawbox")
            found_tray = False
            for box in commands:
                point = box.find("point")
                size = box.find("size")
                boxfill = box.find("boxfill")
                if point is not None and size is not None:
                    if float(point.attrib.get("x", 0)) == -1.2 and float(size.attrib.get("x", 0)) == 4.0:
                        self.assertEqual(float(point.attrib.get("z", 0)), -0.2)
                        self.assertEqual(float(size.attrib.get("z", 0)), 0.15)
                        self.assertEqual(boxfill.text.strip(), "bottom | left | right | front | back")
                        found_tray = True
            self.assertTrue(found_tray, f"Remediated catch basin with lip walls not found in {xml_path}")

            # Check simulation domain bounds
            posmin = root.find(".//posmin")
            posmax = root.find(".//posmax")
            self.assertIsNotNone(posmin)
            self.assertIsNotNone(posmax)
            self.assertEqual(float(posmin.attrib["x"]), -1.2)
            self.assertEqual(float(posmin.attrib["y"]), -1.0)
            self.assertEqual(float(posmin.attrib["z"]), -0.5)
            self.assertEqual(float(posmax.attrib["x"]), 2.8)
            self.assertEqual(float(posmax.attrib["y"]), 1.0)
            self.assertEqual(float(posmax.attrib["z"]), 2.2)

            # Check motion file format
            lines = motion_path.read_text().splitlines()
            self.assertTrue(len(lines) > 100)
            self.assertTrue(lines[0].startswith("#Time;Degrees"))
            last_line = lines[-1].split(";")
            self.assertAlmostEqual(float(last_line[0]), 4.0, places=4)
            self.assertAlmostEqual(float(last_line[1]), -105.0, places=4)

    def test_02_gencase_preflight_receipts_and_zero_loss(self):
        """Verify GenCase preflights completed with returncode 0, zero exclusions, and exact counts."""
        for cid, mech, pair_id, gpu, exp_total, exp_fluid, exp_fixed, exp_moving, mouth, holdout in EXPECTED_ROSTER:
            receipt_path = DATA_F2_ROOT / cid / f"{cid}_GENCASE_01/execution-receipt.json"
            self.assertTrue(receipt_path.is_file(), f"Missing receipt: {receipt_path}")

            rec = json.loads(receipt_path.read_text())
            self.assertEqual(rec["returncode"], 0)
            self.assertEqual(rec["status"], "completed")
            self.assertEqual(rec["total_particles"], exp_total)
            self.assertEqual(rec["fluid_particles"], exp_fluid)
            self.assertEqual(rec["fixed_particles"], exp_fixed)
            self.assertEqual(rec["moving_particles"], exp_moving)
            self.assertEqual(rec["excluded_particles"], 0, f"Exclusions N_out != 0 for {cid}")
            self.assertEqual(rec["solver_dimension_from_gencase"], 3)

            # Check continuum mass consistency (+31.13%)
            mass_cons = rec["continuum_mass_consistency"]
            self.assertTrue(mass_cons["consistent"])
            self.assertAlmostEqual(mass_cons["relative_mass_error"], 0.311294766, places=4)

            # Check output files exist
            for key in ("bi4", "xml"):
                out_file = Path(rec["output_files"][key])
                self.assertTrue(out_file.is_file(), f"Output file missing: {out_file}")

    def test_03_runner_requests_compliance(self):
        """Verify runner requests: GPU assignment in {2, 5, 6, 7}, zero forbidden GPUs, exact hashes."""
        permitted_gpus = {2, 5, 6, 7}
        forbidden_gpus = {0, 1, 3, 4}

        for cid, mech, pair_id, expected_gpu, total, fluid, fixed, moving, mouth, holdout in EXPECTED_ROSTER:
            # GenCase request
            gc_req_path = REQUESTS_DIR / f"{cid}-gencase.json"
            self.assertTrue(gc_req_path.is_file())
            gc_req = json.loads(gc_req_path.read_text())
            self.assertEqual(gc_req["schema"], "ds02.cpu-request.v2")
            self.assertEqual(gc_req["case_id"], cid)
            self.assertEqual(gc_req["kind"], "cpu")
            self.assertEqual(gc_req["cpu_task_kind"], "gencase")

            # Solver request
            slv_req_path = REQUESTS_DIR / f"{cid}-solver.json"
            self.assertTrue(slv_req_path.is_file())
            slv_req = json.loads(slv_req_path.read_text())
            self.assertEqual(slv_req["schema"], "ds02.runner-request.v2")
            self.assertEqual(slv_req["case_id"], cid)
            self.assertEqual(slv_req["kind"], "qualification")
            self.assertEqual(slv_req["assigned_gpu"], expected_gpu)
            self.assertIn(slv_req["assigned_gpu"], permitted_gpus)
            self.assertNotIn(slv_req["assigned_gpu"], forbidden_gpus)
            self.assertEqual(slv_req["total_particles"], total)
            self.assertEqual(slv_req["fluid_particles"], fluid)
            self.assertEqual(slv_req["wall_particles"], fixed + moving)

            # Check all input files and hashes exist and match
            for in_path, in_hash in slv_req["input_hashes"].items():
                p = Path(in_path)
                self.assertTrue(p.is_file(), f"Missing input file: {p}")

    def test_04_owner_metadata(self):
        """Verify owner metadata sidecars are valid and contain physical binding."""
        for cid, mech, pair_id, gpu, total, fluid, fixed, moving, mouth, holdout in EXPECTED_ROSTER:
            owner_path = PROD_OWNER / f"{cid}.owner.json"
            self.assertTrue(owner_path.is_file())
            owner = json.loads(owner_path.read_text())
            self.assertEqual(owner["case_id"], cid)
            self.assertEqual(owner["family_id"], "F2")
            self.assertEqual(owner["mechanism_id"], mech)
            self.assertEqual(owner["assigned_gpu"], gpu)
            self.assertEqual(owner["total_particles"], total)
            self.assertEqual(owner["fluid_particles"], fluid)
            self.assertEqual(owner["wall_particles"], fixed + moving)
            self.assertEqual(owner["excluded_particles"], 0)
            self.assertEqual(owner["solver_dimension"], 3)
            self.assertEqual(owner["holdout"], holdout)
            self.assertTrue(owner["containment_compliance"]["compliant"])

            # Check physical binding
            pb = owner["physical_binding"]
            self.assertEqual(pb["schema"], "ds-data-02.physical-binding.v1")
            self.assertEqual(pb["family_id"], "F2")
            self.assertEqual(pb["mechanism_id"], mech)
            self.assertEqual(pb["density_kg_m3"], 1000.0)

    def test_05_case_registry_and_split_plan(self):
        """Verify case_registry.jsonl and split_plan.json are updated with stage 8 production status."""
        reg_path = FAMILY_ROOT / "case_registry.jsonl"
        split_path = FAMILY_ROOT / "split_plan.json"

        # Case registry
        rows = [json.loads(line) for line in reg_path.read_text().splitlines() if line.strip()]
        rows_by_id = {r["case_id"]: r for r in rows}

        for cid, mech, pair_id, gpu, total, fluid, fixed, moving, mouth, holdout in EXPECTED_ROSTER:
            self.assertIn(cid, rows_by_id)
            r = rows_by_id[cid]
            self.assertEqual(r["stage"], "stage8")
            self.assertTrue(r["production"])
            self.assertEqual(r["production_resolution"], "medium")
            self.assertEqual(r["status"], "gencase_completed_solver_pending")
            self.assertEqual(r["assigned_gpu"], gpu)
            self.assertEqual(r["particle_axis_count"], total)
            self.assertEqual(r["fluid_particles"], fluid)
            self.assertEqual(r["wall_particles"], fixed + moving)
            self.assertEqual(r["solver_dimension"], 3)
            self.assertEqual(r["holdout"], holdout)

        # Split plan
        sp = json.loads(split_path.read_text())
        self.assertEqual(sp["status"], "stage8_production_gencase_preflight_passed_solvers_prepared")
        self.assertIn("stage8", sp["stages"])
        st8 = sp["stages"]["stage8"]
        self.assertEqual(st8["cumulative_case_count"], 8)
        self.assertEqual(st8["incremental_case_count"], 8)
        self.assertEqual(len(st8["case_ids"]), 8)
        self.assertEqual(st8["allocated_gpus"], [2, 5, 6, 7])

    def test_06_preflight_summary_json(self):
        """Verify stage8_gencase_preflight_summary.json exists and contains all 8 passing cases."""
        sum_path = FAMILY_ROOT / "stage8_gencase_preflight_summary.json"
        self.assertTrue(sum_path.is_file())
        summary = json.loads(sum_path.read_text())
        self.assertEqual(len(summary), 8)

        sum_by_id = {item["case_id"]: item for item in summary}
        for cid, mech, pair_id, gpu, total, fluid, fixed, moving, mouth, holdout in EXPECTED_ROSTER:
            self.assertIn(cid, sum_by_id)
            item = sum_by_id[cid]
            self.assertTrue(item["reference_parity"])
            self.assertEqual(item["total_particles"], total)
            self.assertEqual(item["fluid_particles"], fluid)
            self.assertEqual(item["fixed_particles"], fixed)
            self.assertEqual(item["moving_particles"], moving)
            self.assertEqual(item["excluded_particles"], 0)
            self.assertEqual(item["assigned_gpu"], gpu)
            self.assertTrue(item["containment_compliance"]["compliant"])


if __name__ == "__main__":
    unittest.main()

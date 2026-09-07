"""Contract tests for the isolated F6 mDBC zero-normal experiment."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from scripts.r3_g2_f6_mdbc_zero_normal_preflight import (
    ARTIFACT_ROOT,
    BASELINE_ID,
    CASE_ROOT,
    REPORT_JSON,
    RUN_ROOT,
    VARIANTS,
    experiment_record,
    mdbc_zero_definition_text,
)


class F6MdbcZeroNormalPreflightTests(unittest.TestCase):
    def test_matrix_is_candidate_only_and_cpu_only(self):
        self.assertGreaterEqual(len(VARIANTS), 20)
        ids = [variant["variant_id"] for variant in VARIANTS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(experiment_record(item)["gpu"] is None for item in VARIANTS))
        self.assertTrue(all(item["run_solver"] for item in VARIANTS))
        self.assertTrue(any(item["tank_radius_m"] < 2.0 for item in VARIANTS))

    def test_candidate_xml_keeps_particle_route_isolated(self):
        for variant in VARIANTS:
            record = experiment_record(variant)
            root = ET.fromstring(mdbc_zero_definition_text(record))
            boundary = root.find(".//parameter[@key='Boundary']")
            normals = root.find(".//normals[@active='true']/norgeometry")
            normal_list = root.find(".//geometry/commands/list[@name='GeometryForNormals']")
            self.assertIsNotNone(boundary)
            self.assertEqual(boundary.get("value"), "2")
            self.assertIsNotNone(normals)
            self.assertEqual(normals.find("./geometryfile").get("file"),
                             "[CaseName]_hdp_Actual.vtk")
            self.assertIsNotNone(normal_list)
            self.assertIn(
                "../../artifacts/r3-g2-f6-mdbc-zero-normal-preflight/",
                ET.tostring(root, encoding="unicode"),
            )

    def test_repair_candidates_are_not_acceptance_claims(self):
        repair = [item for item in VARIANTS if item["tank_radius_m"] in (1.97, 1.98)]
        self.assertEqual(len(repair), 2)
        self.assertEqual(BASELINE_ID, "R3_F6_mdbc_zero_normal_baseline")
        self.assertIn("r3-g2-f6-mdbc-zero-normal-preflight", str(CASE_ROOT))
        self.assertIn("r3-g2-f6-mdbc-zero-normal-preflight", str(ARTIFACT_ROOT))
        self.assertIn("r3-g2-f6-mdbc-zero-normal-preflight", str(RUN_ROOT))
        self.assertIn("r3-g2-f6-mdbc-zero-normal-preflight", str(REPORT_JSON))


if __name__ == "__main__":
    unittest.main()

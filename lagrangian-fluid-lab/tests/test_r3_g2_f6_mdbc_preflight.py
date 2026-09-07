"""Unit checks for the isolated F6 mDBC preflight route."""

from __future__ import annotations

import unittest

from scripts.r3_g2_f6_mdbc_preflight import (
    SOURCE_EVIDENCE,
    mdbc_definition_text,
    parse_gencase_normals,
    parse_solver_normals,
    preflight_record,
    xml_switch_audit,
)
from scripts.r3_g2_f6_test14 import definition_text


class F6MdbcPreflightTests(unittest.TestCase):
    def test_existing_definition_is_not_mdbc_but_isolated_candidate_is_legal(self):
        record = preflight_record()
        audit = xml_switch_audit(definition_text(record), mdbc_definition_text(record))
        self.assertEqual(audit["current_f6"]["requested_boundary"]["name"], "DBC")
        self.assertFalse(audit["current_f6"]["legal_mdbc_switch"])
        self.assertEqual(audit["candidate"]["requested_boundary"]["name"], "mDBC")
        self.assertTrue(audit["candidate"]["legal_mdbc_switch"])
        self.assertTrue(audit["candidate"]["geometry_commands"]["normals_list_run_from_main"])
        self.assertEqual(audit["candidate"]["normals"]["geometryfile"],
                         "[CaseName]_hdp_Actual.vtk")

    def test_gencase_and_solver_parsers_preserve_zero_normal_blocker(self):
        gencase = parse_gencase_normals(
            """
            FileShapes> hdp_Actual.vtk  shapes:3,386  points:1,935
            Computing normals...
              Non-zero particle normals: 16,318/24,335 Normals size range: (0.1 - 0.2).
              Final zero normals: 8,017/24,335 (32.9%) Maximum normal: 0.8 (7.7 x h)
              *** There are boundary particles without normal data.
            """
        )
        self.assertEqual(gencase["normal_geometry_shape_count"], 3386)
        self.assertEqual(gencase["nonzero_count"], 16318)
        self.assertEqual(gencase["zero_count"], 8017)
        solver = parse_solver_normals(
            'Boundary="mDBC"\nCaseNfloat=140\n'
            '*** WARNING: There are 8,017 of 24,195 fixed or moving boundary particles without normal data.\n'
            'CfgInit_NormalsGhost.vtk\nFinished execution (code=0)\n'
        )
        self.assertEqual(solver["effective_boundary"], "mDBC")
        self.assertEqual(solver["fixed_or_moving_zero_count"], 8017)
        self.assertEqual(solver["floating_zero_count"], 0)
        self.assertTrue(solver["solver_finished_code_0"])

    def test_source_evidence_is_vendored_and_explicit(self):
        self.assertIn("normal_storage", SOURCE_EVIDENCE)
        self.assertIn("JPartsLoad4.cpp", SOURCE_EVIDENCE["normal_storage"]["path"])
        self.assertIn("JSph.cpp", SOURCE_EVIDENCE["normal_and_ghost_initialization"]["path"])
        self.assertIn("JSphCpu_mdbc.cpp", SOURCE_EVIDENCE["cpu_mdbc_kernel"]["path"])


if __name__ == "__main__":
    unittest.main()

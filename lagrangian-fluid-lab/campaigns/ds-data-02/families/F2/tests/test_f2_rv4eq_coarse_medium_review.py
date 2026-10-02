"""Regression checks for the read-only RV4 coarse/medium evidence review."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


F2_ROOT = Path(__file__).resolve().parents[1]
REVIEW = F2_ROOT / "f2_rv4eq_coarse_medium_review.py"
REPORT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_COARSE_MEDIUM_REVIEW_20261002/rv4eq-coarse-medium-review.json")


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("f2_rv4eq_coarse_medium_review_test_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class F2RV4EquivalentCoarseMediumReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))

    def test_four_actual_views_and_h5_report_consistency(self):
        self.assertEqual(self.report["case_count"], 4)
        self.assertTrue(self.report["verdict"]["all_h5_structural_checks_pass"])
        for case in self.report["cases"]:
            self.assertTrue(case["structural_checks_pass"], case["case_id"])
            self.assertEqual(case["actual_h5"]["coordinate_components"], 3)
            self.assertEqual(case["actual_h5"]["frames"], 4001)
            self.assertGreater(case["actual_h5"]["fluid_particles"], 0)
            self.assertTrue(case["checks"]["all_observed_save_brackets_within_budget"])

    def test_frozen_physical_scope_is_separate_from_resolution_state(self):
        checks = self.report["physical_scale_checks"]
        for background in ("CENTER", "OFFSET"):
            self.assertTrue(checks[background]["physical_binding_sha256_equal"])
            self.assertTrue(checks[background]["source_h5_physical_condition_equal"])
            self.assertTrue(checks[background]["motion_control_equal"])
            self.assertTrue(checks[background]["geometry_and_pose_equal"])
        self.assertTrue(self.report["verdict"]["metadata_binding_mismatch_present"])
        self.assertIn("F2H10V2_CENTER_V1_COARSE_RV4D1_BASELINE_SAVE001", checks["CENTER"]["label_declared_hash_mismatches"])

    def test_macro_difference_and_exclusion_semantics_are_not_overstated(self):
        comparisons = self.report["coarse_medium_comparisons"]
        self.assertFalse(comparisons["CENTER"]["within_frozen_macro_budget"])
        self.assertFalse(comparisons["OFFSET"]["within_frozen_macro_budget"])
        self.assertTrue(self.report["verdict"]["native_exclusion_unknowns_are_separate"])
        self.assertEqual(self.report["verdict"]["q_n_status"], "pending; coarse/medium spatial differences are measured evidence, not a qualification grant")


if __name__ == "__main__":
    unittest.main()

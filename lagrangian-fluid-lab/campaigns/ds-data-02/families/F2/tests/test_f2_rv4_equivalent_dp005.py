"""Regression checks for the additive RV4-equivalent DP005 precheck."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


F2_ROOT = Path(__file__).resolve().parents[1]
DESIGN = F2_ROOT / "f2_rv4_equivalent_dp005.py"
MANIFEST = F2_ROOT / "rv4_equivalent_dp005/manifest.json"
CORRECTION = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_INITIAL_CORRECTION/audit-f2-rv4eq-dp005-initial-correction-20261002-001/correction/rv4-equivalent-dp005-initial-correction-manifest.json")


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("f2_rv4eq_dp005_test_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class F2RV4EquivalentDP005Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load(DESIGN)
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_scope_is_new_and_population_is_exact(self):
        self.assertEqual(self.manifest["scope_id"], "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002")
        self.assertEqual(self.manifest["registry_role"], "new_RV4_equivalent_finer_reference_outside_original_48_registry")
        self.assertEqual(self.manifest["expected_population"]["total_particle_count"], 196608)
        self.assertEqual(self.manifest["expected_population"]["source_band_particle_count"], 65536)
        self.assertAlmostEqual(self.manifest["continuous_fluid"]["mass_kg"], 24.576, places=12)

    def test_definitions_keep_finite_solids_and_explicit_cell_centres(self):
        self.assertEqual(len(self.manifest["cases"]), 2)
        for record in self.manifest["cases"]:
            metadata = json.loads(Path(record["metadata"]["path"]).read_text(encoding="utf-8"))
            xml = Path(record["definition"]["path"]).read_text(encoding="utf-8")
            self.assertEqual(metadata["rv4_binding"]["physical_projection_equality"]["differences"], {})
            self.assertEqual(metadata["rv4_binding"]["staged_motion"]["sha256"], record["motion"]["sha256"])
            self.assertEqual(xml.count('<setmkfluid mk='), 3)
            self.assertEqual(xml.count('size x="0.315" y="0.075" z="0.315"'), 3)
            self.assertIn('<point x="0.055" y="-0.1175" z="0.7025" />', xml)
            self.assertNotIn("<particles", xml)
            self.assertNotIn("<vtkout", xml)

    def test_requests_are_cpu_gencase_only_and_no_gpu(self):
        for record in self.manifest["cases"]:
            request = json.loads(Path(record["request"]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(request["kind"], "cpu")
            self.assertEqual(request["cpu_task_kind"], "gencase")
            self.assertLessEqual(request["cpu_threads"], 4)
            self.assertLessEqual(request["max_wall_seconds"], 300)
            self.assertLessEqual(request["estimated_storage_bytes"], 256 * 1024 * 1024)
            self.assertTrue(request["solver_launch_forbidden"])
            self.assertEqual(request["generation_status"], "new_RV4_equivalent_dp005_definition_registered_not_run")

    def test_actual_correction_binds_both_backgrounds_without_qualification(self):
        report = json.loads(CORRECTION.read_text(encoding="utf-8"))
        self.assertTrue(report["all_checks_pass"])
        self.assertEqual(len(report["cases"]), 2)
        for case in report["cases"]:
            self.assertTrue(case["all_checks_pass"])
            checks = case["checks"]
            self.assertTrue(checks["rv4_to_new_physical_projection_equal"])
            self.assertTrue(checks["rv4_to_generated_output_projection_equal"])
            self.assertTrue(checks["all_fluid_strictly_inside_initial_cup"])
            self.assertTrue(checks["no_fluid_within_dp_half_of_cup_face"])
            self.assertEqual(case["occupancy"]["receiver_overlap_count"], 0)
            self.assertEqual(case["occupancy"]["tray_overlap_count"], 0)
        self.assertEqual(report["qualification_claim"], "none")
        self.assertEqual(report["production_claim"], "none")


if __name__ == "__main__":
    unittest.main()

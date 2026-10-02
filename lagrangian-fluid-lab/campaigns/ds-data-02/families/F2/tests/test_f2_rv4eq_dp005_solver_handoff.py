"""Checks for the root-review-ready RV4-equivalent DP005 handoff."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import unittest


F2_ROOT = Path(__file__).resolve().parents[1]
HANDOFF = F2_ROOT / "rv4_equivalent_dp005/solver_handoff/solver_handoff_manifest.json"
RUNTIME = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("f2_rv4eq_solver_handoff_test_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class F2RV4EquivalentSolverHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handoff = json.loads(HANDOFF.read_text(encoding="utf-8"))
        cls.runtime = _load(RUNTIME)

    def test_two_background_requests_are_runtime_valid_and_root_owned(self):
        self.assertEqual(len(self.handoff["requests"]), 2)
        self.assertEqual(self.handoff["physical_case_count"], 2)
        self.assertEqual(self.handoff["new_independent_physical_case_count"], 0)
        for row in self.handoff["requests"]:
            request = json.loads(Path(row["request"]["path"]).read_text(encoding="utf-8"))
            self.runtime.validate_request(request)
            self.assertEqual(request["kind"], "qualification")
            self.assertEqual(request["gpu_launch"]["family_owner_launch"], False)
            self.assertEqual(request["qualification_claim"].split(";", 1)[0], "none")
            self.assertEqual(request["production_claim"], "none")
            prefix = Path(request["gencase_input_prefix"])
            self.assertEqual(str(prefix), request["command"][1])
            self.assertTrue(Path(str(prefix) + ".xml").is_file())
            self.assertTrue(Path(str(prefix) + ".bi4").is_file())
            self.assertTrue(Path(str(prefix) + "_motion.dat").is_file())
            self.assertEqual(request["numerical_recipe_fields"]["TimeMax"], "4")
            self.assertEqual(request["numerical_recipe_fields"]["TimeOut"], "0.01")

    def test_storage_formula_and_actual_domain_preflight_are_bound(self):
        for row in self.handoff["requests"]:
            request = json.loads(Path(row["request"]["path"]).read_text(encoding="utf-8"))
            basis = request["storage_estimate_basis"]
            expected = math.ceil(basis["actual_total_particles"] * 401 * 64 * 1.40)
            self.assertEqual(request["estimated_storage_bytes"], expected)
            self.assertGreater(request["estimated_storage_bytes"], 0)
            domain = json.loads(Path(row["domain_audit"]["path"]).read_text(encoding="utf-8"))
            self.assertTrue(domain["all_domain_checks_pass"])
            self.assertTrue(domain["checks"]["padded_raw_and_moving_sweep_inside_domain"])
            self.assertAlmostEqual(domain["kernel_padding"]["support_radius_m"], 0.013, places=15)
            self.assertTrue(all(value >= 0.0 for value in domain["domain_margins_after_kernel_padding_m"]["low"]))
            self.assertTrue(all(value >= 0.0 for value in domain["domain_margins_after_kernel_padding_m"]["high"]))
            self.assertGreater(domain["raw_native_initial"]["by_type"]["0"]["count"], 0)
            self.assertGreater(domain["raw_native_initial"]["by_type"]["1"]["count"], 0)
            self.assertEqual(domain["motion_curve"]["time_start_s"], 0.0)
            self.assertEqual(domain["motion_curve"]["time_end_s"], 4.0)

    def test_physical_projection_and_hashes_are_separate_from_dp005_recipe(self):
        for row in self.handoff["requests"]:
            request = json.loads(Path(row["request"]["path"]).read_text(encoding="utf-8"))
            projection = request["source_binding"]["physical_projection"]
            self.assertEqual(projection["differences"], {})
            self.assertTrue(projection["physical_solids_controls_window_equal"])
            self.assertEqual(projection["allowed_numerical_changes"]["definition_dp"]["candidate"], "0.005")
            self.assertEqual(projection["allowed_numerical_changes"]["solver_save_interval"]["candidate"], "0.01")
            self.assertEqual(projection["rv4_motion_sha256"], projection["candidate_motion_sha256"])
            self.assertEqual(request["physical_condition_hash"], request["physical_geometry_control_hash"])
            self.assertEqual(request["numerical_recipe_fields"]["dp_m"], 0.005)
            self.assertEqual(request["resolution"], "dp005")


if __name__ == "__main__":
    unittest.main()

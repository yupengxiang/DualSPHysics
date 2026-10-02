import json
import unittest
from pathlib import Path

from .. import f2_rv4eq_dp005_postprocess_handoff_v2 as handoff


class F2RV4EqDP005PostprocessHandoffTests(unittest.TestCase):
    def test_deferred_requests_use_fullframe_tool_and_keep_solver_sources_deferred(self):
        output = Path("/tmp/f2-rv4eq-postprocess-handoff-v2-test")
        manifest = handoff.build(output)
        self.assertFalse(manifest["solver_launch"])
        self.assertFalse(manifest["conversion_launch"])
        self.assertEqual(len(manifest["requests"]), 2)
        for record in manifest["requests"]:
            request = json.loads(Path(record["path"]).read_text())
            self.assertEqual(request["status"], "deferred_until_root_solver_terminal_and_conversion_slot")
            self.assertIn("PartVTK_linux64", " ".join(request["command"]))
            self.assertNotIn("PartVTKOut_linux64", " ".join(request["command"]))
            self.assertTrue(request["deferred_input_files"])
            self.assertEqual(request["cpu_threads"], 4)
            self.assertEqual(request["physical_geometry_control_hash"], request["physical_condition_hash"])
            self.assertEqual(request["new_independent_physical_case_count"], 0)
            self.assertEqual(request["qualification_claim"], "none")

    def test_storage_is_bound_to_actual_gencase_population(self):
        output = Path("/tmp/f2-rv4eq-postprocess-handoff-v2-storage-test")
        manifest = handoff.build(output)
        for record in manifest["requests"]:
            request = json.loads(Path(record["path"]).read_text())
            n = request["resource_estimate"]["actual_total_particles_from_gencase"]
            expected = int((n * 401 * 64 * 1.40) + 0.999999999)
            self.assertEqual(request["estimated_storage_bytes"], expected)
            self.assertGreater(request["max_wall_seconds"], request["resource_estimate"]["predicted_wall_seconds"])

    def test_owner_has_explicit_resolution_independent_physical_binding(self):
        output = Path("/tmp/f2-rv4eq-postprocess-handoff-v2-owner-test")
        manifest = handoff.build(output)
        for record in manifest["owner_metadata"]:
            owner = json.loads(Path(record["path"]).read_text())
            binding = owner["physical_binding"]
            self.assertEqual(binding["schema"], "ds-data-02.physical-binding.v1")
            self.assertEqual(owner["physical_condition_hash_declared"], owner["physical_binding_sha256"])
            self.assertNotIn("dp_m", binding)
            self.assertNotIn("solver_parameters", binding)


if __name__ == "__main__":
    unittest.main()

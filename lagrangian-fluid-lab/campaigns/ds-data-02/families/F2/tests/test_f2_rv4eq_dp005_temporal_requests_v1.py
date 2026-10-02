import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / "rv4_equivalent_dp005/temporal_studies_v1/requests"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class F2RV4EqDP005TemporalRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = [json.loads(path.read_text()) for path in sorted(REQUESTS.glob("*.json"))]

    def test_two_backgrounds_and_two_numerical_views(self):
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(
            {(item["mechanism_id"], item["numerical_recipe_fields"]["variant"]) for item in self.requests},
            {
                ("center_catch", "dense_save001"),
                ("center_catch", "reduced_dt_save010"),
                ("offset_spill", "dense_save001"),
                ("offset_spill", "reduced_dt_save010"),
            },
        )

    def test_physical_bytes_are_same_and_requests_are_root_only(self):
        for request in self.requests:
            self.assertEqual(request["physical_condition_hash"], request["physical_geometry_control_hash"])
            self.assertEqual(request["new_independent_physical_case_count"], 0)
            self.assertTrue(request["solver_launch_forbidden_in_this_module"])
            self.assertEqual(request["status"], "ready_for_root_gpu_review_only")
            self.assertNotIn("PartVTKOut_linux64", " ".join(request["command"]))
            for path, digest in request["input_sha256"].items():
                self.assertTrue(Path(path).is_file(), path)
                self.assertEqual(sha256(Path(path)), digest, path)
            self.assertTrue(request["source_binding"]["same_bi4_bytes"])
            self.assertTrue(request["source_binding"]["same_motion_bytes"])

    def test_dense_view_has_event_eligible_save_cadence(self):
        dense = [item for item in self.requests if item["numerical_recipe_fields"]["variant"] == "dense_save001"]
        self.assertEqual(len(dense), 2)
        for request in dense:
            fields = request["numerical_recipe_fields"]
            self.assertEqual(fields["time_out_s"], 0.001)
            self.assertEqual(fields["expected_frames"], 4001)
            self.assertEqual(fields["DtFixed_s"], 0.0)
            self.assertTrue(request["timing_and_study_role"]["timing_qualification_candidate"])
            self.assertGreaterEqual(request["estimated_storage_bytes"], 500 * 1024**3)

    def test_reduced_dt_is_half_observed_global_minimum(self):
        reduced = [item for item in self.requests if item["numerical_recipe_fields"]["variant"] == "reduced_dt_save010"]
        self.assertEqual(len(reduced), 2)
        for request in reduced:
            fields = request["numerical_recipe_fields"]
            self.assertEqual(fields["time_out_s"], 0.01)
            self.assertEqual(fields["expected_frames"], 401)
            self.assertAlmostEqual(fields["DtFixed_s"], 0.5 * fields["baseline_global_min_positive_dt_s"], places=18)
            self.assertEqual(fields["DtIni_s"], 0.0)
            self.assertEqual(fields["DtMin_s"], 0.0)
            self.assertTrue(request["timing_and_study_role"]["integration_study_candidate"])
            self.assertFalse(request["timing_and_study_role"]["timing_qualification_candidate"])


if __name__ == "__main__":
    unittest.main()

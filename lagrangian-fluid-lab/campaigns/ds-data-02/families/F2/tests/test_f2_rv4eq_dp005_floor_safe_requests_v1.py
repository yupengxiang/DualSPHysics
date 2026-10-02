import hashlib
import json
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / "rv4_equivalent_dp005/temporal_studies_floor_safe_v1/requests"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
BASELINE_ROOT = DATA_ROOT / "families/F2/F2_RV4EQ_DP005_NATIVE_INPUTS_20261002"
INTEGRATION_SCRIPTS = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parameters(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {
        node.attrib["key"]: node.attrib.get("value", "")
        for node in root.findall(".//execution/parameters/parameter")
    }


class F2RV4EqDP005FloorSafeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = [json.loads(path.read_text()) for path in sorted(REQUESTS.glob("*.json"))]

    def test_exactly_two_background_views_and_no_new_physical_cases(self):
        self.assertEqual(len(self.requests), 2)
        self.assertEqual({item["mechanism_id"] for item in self.requests}, {"center_catch", "offset_spill"})
        self.assertEqual({item["numerical_recipe_fields"]["variant"] for item in self.requests}, {"reduced_dt_save010_floorsafe001"})
        for request in self.requests:
            self.assertEqual(request["new_independent_physical_case_count"], 0)
            self.assertEqual(request["physical_condition_hash"], request["physical_geometry_control_hash"])
            self.assertEqual(request["status"], "ready_for_root_gpu_review_only")
            self.assertTrue(request["solver_launch_forbidden_in_this_module"])
            self.assertFalse(request["gpu_launch"]["family_owner_launch"])
            self.assertEqual(request["qualification_claim"], "none; floor-safe numerical temporal request only")
            self.assertEqual(request["production_claim"], "none")

    def test_explicit_floor_safe_recipe_is_below_run_out_floor(self):
        for request in self.requests:
            fields = request["numerical_recipe_fields"]
            override = request["floor_safe_override"]
            target = fields["DtFixed_s"]
            self.assertAlmostEqual(target, 0.5 * fields["baseline_global_min_positive_dt_s"], places=18)
            self.assertEqual(fields["DtFixed_s"], fields["DtIni_s"])
            self.assertEqual(fields["DtFixed_s"], fields["DtMin_s"])
            self.assertLess(target, override["default_run_out_DtMin_s"])
            self.assertEqual(fields["CoefDtMin"], 0.05)
            self.assertEqual(fields["time_out_s"], 0.01)
            self.assertEqual(fields["expected_frames"], 401)
            self.assertTrue(override["target_below_default_run_out_DtMin"])
            self.assertTrue(override["coef_dtmin_preserved"])
            self.assertFalse(request["timing_and_study_role"]["timing_qualification_candidate"])
            self.assertFalse(request["timing_and_study_role"]["save_budget_candidate_satisfied_by_cadence"])

    def test_physical_population_and_motion_are_byte_equal(self):
        for request in self.requests:
            staging = request["gencase_artifacts"]
            source_bi4 = Path(staging["copied_source_bi4"]["path"])
            source_motion = Path(staging["copied_source_motion"]["path"])
            temporal_bi4 = Path(staging["temporal_bi4"]["path"])
            temporal_motion = Path(staging["temporal_motion"]["path"])
            self.assertEqual(sha256(source_bi4), sha256(temporal_bi4))
            self.assertEqual(sha256(source_motion), sha256(temporal_motion))
            self.assertTrue(request["source_binding"]["same_bi4_bytes"])
            self.assertTrue(request["source_binding"]["same_motion_bytes"])
            self.assertEqual(parameters(Path(staging["temporal_xml"]["path"]))["TimeOut"], "0.01")
            self.assertEqual(parameters(Path(staging["temporal_xml"]["path"]))["TimeMax"], "4")
            self.assertEqual(parameters(Path(staging["temporal_xml"]["path"]))["DtFixed"], format(request["numerical_recipe_fields"]["DtFixed_s"], ".17g"))
            self.assertEqual(parameters(Path(staging["temporal_xml"]["path"]))["DtIni"], format(request["numerical_recipe_fields"]["DtIni_s"], ".17g"))
            self.assertEqual(parameters(Path(staging["temporal_xml"]["path"]))["DtMin"], format(request["numerical_recipe_fields"]["DtMin_s"], ".17g"))

    def test_strict_digest_bindings_and_runtime_shape(self):
        sys.path.insert(0, str(INTEGRATION_SCRIPTS))
        import ds_data02_runtime_v2 as runtime
        import ds_data02_strict_dispatch_v1 as strict

        for path in sorted(REQUESTS.glob("*.json")):
            request = json.loads(path.read_text())
            self.assertIn(str(strict.GUARD_PATH), request["input_files"])
            self.assertEqual(request["dispatch_guard"]["path"], str(strict.GUARD_PATH))
            self.assertEqual(request["dispatch_guard"]["sha256"], sha256(Path(strict.GUARD_PATH)))
            self.assertEqual(set(request["input_files"]), set(request["input_sha256"]))
            for input_path, digest in request["input_sha256"].items():
                self.assertTrue(Path(input_path).is_file(), input_path)
                self.assertEqual(sha256(Path(input_path)), digest, input_path)
            self.assertEqual(len(runtime.validate_request(request)), len(request["input_files"]))
            self.assertEqual(len(strict.validate_request(request)), len(request["input_files"]))


if __name__ == "__main__":
    unittest.main()

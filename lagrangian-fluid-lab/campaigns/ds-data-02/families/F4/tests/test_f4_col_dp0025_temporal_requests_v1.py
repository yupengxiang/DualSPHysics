import hashlib
import json
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / "temporal_studies_dp0025_v1/requests"
INTEGRATION_SCRIPTS = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parameters(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {node.attrib["key"]: node.attrib.get("value", "") for node in root.findall(".//execution/parameters/parameter")}


class F4ColDP0025TemporalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = [json.loads(path.read_text()) for path in sorted(REQUESTS.glob("*.json"))]

    def test_two_numerical_views_same_physical_case(self):
        self.assertEqual(len(self.requests), 2)
        self.assertEqual({item["numerical_recipe_fields"]["variant"] for item in self.requests}, {"half_dt", "dense_save"})
        for request in self.requests:
            self.assertEqual(request["physical_condition_hash"], "dbc97c0081fa8622c1f5da4348e2b78a56eca55bdcdcc39f1e601976dbdcca85")
            self.assertEqual(request["new_independent_physical_case_count"], 0)
            self.assertEqual(request["source_binding"]["continuous_mass_total_kg"], 12.672)
            self.assertEqual(request["source_binding"]["continuous_mass_by_source_kg"], {"left_column": 6.336, "right_column": 6.336})
            self.assertTrue(request["source_binding"]["fixed_support"])
            self.assertEqual(request["source_binding"]["motion_control"], "none; fixed finite DBC tank support")
            self.assertEqual(request["status"], "ready_for_root_gpu_review_only")
            self.assertTrue(request["solver_launch_forbidden_in_this_module"])
            self.assertFalse(request["gpu_launch"]["family_owner_launch"])
            self.assertEqual(request["qualification_claim"], "none; independent F4 finest COL temporal study")
            self.assertEqual(request["production_claim"], "none")

    def test_half_dt_is_explicit_and_below_actual_run_out_floor(self):
        request = next(item for item in self.requests if item["numerical_recipe_fields"]["variant"] == "half_dt")
        fields = request["numerical_recipe_fields"]
        override = request["floor_safe_override"]
        target = fields["DtFixed_s"]
        self.assertAlmostEqual(target, 0.5 * fields["baseline_global_min_positive_dt_s"], places=18)
        self.assertEqual(fields["DtFixed_s"], fields["DtIni_s"])
        self.assertEqual(fields["DtFixed_s"], fields["DtMin_s"])
        self.assertLess(target, override["default_run_out_DtMin_s"])
        self.assertTrue(override["enabled"])
        self.assertTrue(override["target_below_default_Run_out_DtMin"])
        self.assertEqual(fields["time_out_s"], 0.001)
        self.assertEqual(fields["expected_frames"], 1201)
        params = parameters(Path(request["gencase_artifacts"]["temporal_generated_xml"]["path"]))
        self.assertEqual(params["DtFixed"], format(target, ".17g"))
        self.assertEqual(params["DtIni"], format(target, ".17g"))
        self.assertEqual(params["DtMin"], format(target, ".17g"))

    def test_dense_save_changes_only_cadence(self):
        request = next(item for item in self.requests if item["numerical_recipe_fields"]["variant"] == "dense_save")
        fields = request["numerical_recipe_fields"]
        self.assertEqual(fields["time_out_s"], 0.0005)
        self.assertEqual(fields["expected_frames"], 2401)
        self.assertFalse(request["floor_safe_override"]["enabled"])
        params = parameters(Path(request["gencase_artifacts"]["temporal_generated_xml"]["path"]))
        self.assertEqual(params["TimeOut"], "0.00050000000000000001")
        self.assertEqual(params["DtFixed"], "0")
        self.assertEqual(params["DtIni"], "0")
        self.assertEqual(params["DtMin"], "0")
        self.assertEqual(request["timing_and_study_role"]["candidate_save_s"], 0.0005)
        self.assertTrue(request["timing_and_study_role"]["save_cadence_within_frozen_temporal_share"])

    def test_all_input_digests_and_strict_runtime_validation(self):
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

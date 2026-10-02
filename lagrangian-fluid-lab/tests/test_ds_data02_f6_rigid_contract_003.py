import json
import unittest
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003"
AUDIT = ROOT / "partvtk_003/strict_rigid_contract_audit_002.json"
REQUEST_MANIFEST = ROOT / "partvtk_003/qualification_request_manifest_002.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class RigidContract003Tests(unittest.TestCase):
    def test_all_six_generated_xml_contracts_pass(self):
        audit = read_json(AUDIT)
        self.assertEqual(audit["status"], "all_six_generated_native_rigid_contract_pass")
        self.assertEqual(len(audit["cases"]), 6)
        serialized = [8.53333, 8.53333, 13.6533]
        for case in audit["cases"]:
            self.assertTrue(case["preflight_pass"], case["case_id"])
            contract = case["generated_xml_rigid_contract"]
            self.assertTrue(contract["exact_massbody"])
            self.assertTrue(contract["exact_center"])
            self.assertTrue(contract["generated_inertia_matches_serialized_contract"])
            self.assertTrue(contract["generated_inertia_within_analytic_serialization_precision"])
            self.assertEqual(contract["inertia_diag_kg_m2"], serialized)
            self.assertEqual(case["gencase"]["solver_dimension_from_gencase"], 3)
            self.assertGreater(case["actual_type_counts"]["fluid"], 0)
            self.assertGreater(case["actual_type_counts"]["floating"], 0)

    def test_solver_requests_are_additive_root_only_and_prefix_bound(self):
        manifest = read_json(REQUEST_MANIFEST)
        self.assertEqual(manifest["status"], "root_dispatch_pending")
        self.assertEqual(len(manifest["requests"]), 6)
        for row in manifest["requests"]:
            request = read_json(Path(row["path"]))
            self.assertEqual(request["attempt_id"].split("_")[-2:], ["QUAL", "003"])
            self.assertTrue(request["cwd"].endswith("_GENCASE_001"), request["cwd"])
            self.assertEqual(request["complete_event_window_s"], [0.0, 12.0])
            self.assertEqual(request["output_interval_s"], 0.05)
            self.assertEqual(request["q_n_status"], "pending")
            self.assertEqual(request["command"][-2:], ["-tmax:12", "-tout:0.05"])
            self.assertTrue(request["runtime_prefix_contract"]["all_xml_references_resolve_from_prefix"])
            self.assertEqual(request["runtime_prefix_contract"]["xml_external_references"], [])
            for input_path in request["input_files"]:
                self.assertTrue(Path(input_path).is_file(), input_path)

    def test_prior_precision_failure_is_preserved(self):
        failed = ROOT / "partvtk_003/strict_rigid_contract_audit_001_failed.json"
        record = read_json(failed)
        self.assertEqual(record["status"], "generated_native_rigid_contract_failed")
        self.assertTrue(record["cases"])
        self.assertFalse(record["cases"][0]["checks"]["generated_native_mass_center_inertia_exact"])


if __name__ == "__main__":
    unittest.main()

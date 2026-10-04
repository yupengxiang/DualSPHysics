import json
from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parents[1]


def load(relative: str):
    return json.loads((PACKAGE / relative).read_text(encoding="utf-8"))


class H130NativeGeometryRenderContractTest(unittest.TestCase):
    def test_plan_keeps_future_xmf_digest_null(self):
        plan = load("metadata/source-plan.json")
        self.assertIsNone(plan["temporal_source"]["xdmf_sha256"])
        self.assertEqual(plan["temporal_source"]["xdmf_status"], "pending_root121_completion")
        self.assertEqual(plan["contact_sheet_contract"]["page_count"], 7)

    def test_bound_candidate_is_metadata_only_and_still_disabled(self):
        binding = load("metadata/bound-h130-native-geometry-render-binding.json")
        request = load("requests/F1_STAGE1_ECC_H130_DP010.full161-native-geometry-render.disabled.json")
        self.assertEqual(binding["temporal_source"]["xdmf_sha256"], "1ce812924d4281d11524ee55128edeee9de04990529c9e54747eb6550fc21d07")
        self.assertEqual(binding["temporal_source"]["xdmf_status"], "completed_and_hashed")
        self.assertEqual(binding["physical_condition_sha256"], "16ba07faf7b61f7d97f4bfc9d88a315293292107f1390ca860c15825a3bdb36e")
        self.assertFalse(request["launch_allowed"])
        self.assertTrue(request["source_only"])
        self.assertEqual(request["render_binding"]["full_saved_frames"], 161)
        self.assertEqual(len(request["render_binding"]["contact_page_keys"]), 7)
        self.assertIsNone(request["render_binding"]["diagnostic_frames"])

    def test_renderer_contract_and_no_count_claim(self):
        binding = load("metadata/bound-h130-native-geometry-render-binding.json")
        renderer = binding["renderer"]
        self.assertEqual(renderer["sha256"], "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66")
        self.assertEqual(renderer["camera_policy"], "auto-all-frame-nativebounds")
        self.assertEqual(renderer["cutaway_policy"], "actualfixedcutaway")
        self.assertFalse(binding["physical_binding"]["camera_or_source_crop"])
        self.assertEqual(binding["independent_case_count_increment"], 0)
        self.assertTrue(binding["no_numeric_array_read_by_builder"])
        self.assertTrue(binding["no_job_launch_by_builder"])


if __name__ == "__main__":
    unittest.main()

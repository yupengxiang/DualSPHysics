from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("ds_data02_stage2_build_generic_native_extract_v2_root308.py")
spec = importlib.util.spec_from_file_location("stage2_generic_native_v2_root308_test", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


BASE_DIR = SCRIPT.parents[1] / "campaigns/ds-data-02"
LIFECYCLE = BASE_DIR / "stage2/requests/root280-f4-lifecycle-prepared-001/root280-request.json"
CURRENT = BASE_DIR / "stage2/CURRENT336.json"
INVENTORY = BASE_DIR / "stage2/checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
PROOF = BASE_DIR / "stage2/checkpoints/TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_280.json"
OVERLAY = BASE_DIR / "stage2/checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"


class Root308GenericV2Tests(unittest.TestCase):
    def test_self_test_is_nonlaunching(self) -> None:
        result = module._self_test()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["selected_case_count"], 4)
        self.assertFalse(result["payload_opened"])
        self.assertFalse(result["launch_allowed"])

    def test_prepare_binds_exact_root280_four_cases_without_payload_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-root308-v2-") as tmp:
            root = Path(tmp)
            args = argparse.Namespace(
                namespace="ROOT308",
                lifecycle_request=LIFECYCLE,
                current=CURRENT,
                inventory=INVENTORY,
                terminal_proof=PROOF,
                consumed_report=[OVERLAY],
                exclude_case=[],
                output_root=root / "prepared",
                request_output=root / "request.json",
            )
            result = module.prepare(args)
            self.assertTrue(result["terminal_proof_bound"])
            self.assertEqual(result["case_ids"], json.loads(LIFECYCLE.read_text())["physical_case_ids"])
            manifest = json.loads((root / "prepared/generic-native-extract-manifest.json").read_text())
            request = json.loads((root / "request.json").read_text())
            self.assertEqual(manifest["schema"], module.V2_MANIFEST_SCHEMA)
            self.assertEqual(request["physical_case_ids"], result["case_ids"])
            self.assertEqual(request["schema"], "ds02.request.v1")
            self.assertTrue(request["launch_allowed"])
            self.assertFalse(any(Path(path).suffix.lower() in module.BASE.PAYLOAD_SUFFIXES for path in request["input_files"]))
            self.assertEqual(len(request["physical_case_ids"]), 4)

    def test_wrong_namespace_rejected_before_source_work(self) -> None:
        args = argparse.Namespace(
            namespace="ROOT309",
            lifecycle_request=LIFECYCLE,
            current=CURRENT,
            inventory=INVENTORY,
            terminal_proof=PROOF,
            consumed_report=[],
            exclude_case=[],
            output_root=Path("/tmp/unused-root308-output"),
            request_output=Path("/tmp/unused-root308-request.json"),
        )
        with self.assertRaises(module.GenericV2Root308Error):
            module.prepare(args)


if __name__ == "__main__":
    unittest.main()

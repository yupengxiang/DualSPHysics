from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("ds_data02_stage2_build_generic_native_extract_v2.py")
spec = importlib.util.spec_from_file_location("stage2_generic_native_v2_test", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


BASE_DIR = SCRIPT.parents[1] / "campaigns/ds-data-02"
SOURCE_MANIFEST = BASE_DIR / "stage2/requests/generic-native-extract-v1-root257-f4-prepared-004/generic-native-extract-manifest.json"
SOURCE_REQUEST = BASE_DIR / "stage2/requests/generic-native-extract-v1-root-forward-257-004.json"
CURRENT = BASE_DIR / "stage2/CURRENT336.json"
INVENTORY = BASE_DIR / "stage2/checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
PROOF = BASE_DIR / "stage2/checkpoints/TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_253.json"


class GenericNativeV2Tests(unittest.TestCase):
    def test_self_test_is_nonlaunching(self) -> None:
        result = module._self_test()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["selected_case_count"], 3)
        self.assertEqual(result["full_terminal_proof_case_count"], 8)
        self.assertFalse(result["payload_opened"])

    def test_real_source_prepare_selects_three_and_preserves_full_proof_count(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-generic-v2-") as tmp:
            root = Path(tmp)
            args = argparse.Namespace(
                namespace="ROOT264",
                source_manifest=SOURCE_MANIFEST,
                source_request=SOURCE_REQUEST,
                current=CURRENT,
                inventory=INVENTORY,
                terminal_proof=PROOF,
                output_root=root / "prepared",
                request_output=root / "request.json",
            )
            result = module._prepare(args)
            self.assertEqual(result["full_terminal_proof_case_count"], 8)
            self.assertEqual(result["case_ids"], list(module.HISTORICAL_CASES))
            request = json.loads((root / "request.json").read_text())
            self.assertEqual(request["physical_case_ids"], list(module.HISTORICAL_CASES))
            self.assertEqual(request["case_scope"]["full_terminal_proof_case_count"], 8)
            self.assertEqual(request["case_scope"]["diagnostic_case_count"], 5)
            self.assertFalse(any(Path(path).suffix.lower() in module.PAYLOAD_SUFFIXES for path in request["input_files"]))

    def test_wrong_global_completed_count_is_rejected(self) -> None:
        proof = json.loads(PROOF.read_text())
        proof["counts"] = dict(proof["counts"])
        proof["counts"]["completed"] = 3
        module._FULL_CASE_IDS_FOR_AUDIT = tuple(json.loads(SOURCE_REQUEST.read_text())["physical_case_ids"])
        with tempfile.TemporaryDirectory(prefix="stage2-generic-v2-proof-") as tmp:
            path = Path(tmp) / "wrong-count.json"
            path.write_text(json.dumps(proof), encoding="utf-8")
            with self.assertRaises(module.GenericV2Error):
                module._validate_subset_proof(path, list(module.HISTORICAL_CASES), "F4")

    def test_empty_typed_target_fixture_is_rejected_and_never_selected(self) -> None:
        intake = module.BASE._load_intake()
        with tempfile.TemporaryDirectory(prefix="stage2-generic-v2-empty-") as tmp:
            path = Path(tmp) / "empty-records.jsonl"
            path.write_text(json.dumps({"record_fields": "one row per static (Zone, Idp); saved-frame lifecycle only"}) + "\n", encoding="utf-8")
            stat = path.stat()
            expected = {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino, "sha256": module._digest(path, "empty fixture")}
            with self.assertRaises(intake.IntakeError):
                intake._typed_targets(path, expected)
        self.assertEqual(len(module.HISTORICAL_CASES), 3)


if __name__ == "__main__":
    unittest.main()

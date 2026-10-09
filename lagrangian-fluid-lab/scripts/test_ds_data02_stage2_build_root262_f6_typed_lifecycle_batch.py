#!/usr/bin/env python3
"""Metadata-only tests for the ROOT262 F6 continuation handoff."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("ds_data02_stage2_build_root262_f6_typed_lifecycle_batch.py")
STAGE2 = SCRIPT.parents[1] / "campaigns" / "ds-data-02" / "stage2"
PLAN = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT256_PENDING_V4.json"
OVERLAY = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT250_ACTUAL_OVERLAY_V6.json"
OUTPUT = STAGE2 / "requests/typed-lifecycle-batch-v1-f6-root-prepared-262-003"


def _module():
    spec = importlib.util.spec_from_file_location("root262_builder", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load ROOT262 builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Root262MetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _module()

    def test_self_test_is_nonlaunching(self):
        result = self.mod._self_test()
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["launch_allowed"])
        self.assertFalse(result["payload_content_opened"])

    def test_real_plan_selects_exact_f6_original118_group(self):
        plan, refs, case_ids, excluded, proofs = self.mod._load_scope(PLAN, OVERLAY)
        self.assertEqual(len(case_ids), 7)
        self.assertTrue(all(case_id.startswith("F6_STAGE1_ANGULAR_RELEASE_OMEGA_") for case_id in case_ids))
        self.assertEqual(len(excluded), 110)
        self.assertEqual(len(proofs), 14)
        self.assertTrue(set(case_ids).issubset(set(self.mod._json(OVERLAY, "overlay")["remaining_cause_not_located_case_ids"])))
        self.assertTrue(set(case_ids).isdisjoint(excluded))
        self.assertEqual(plan["coverage"]["actual_saved_mask_cases"], 102)
        self.assertEqual(plan["coverage"]["pending_no_credit_cases"], 7)
        self.assertEqual(plan["coverage"]["historical_alias_unresolved"], 1)

    def test_stale_plan_digest_is_rejected_before_json_use(self):
        with tempfile.TemporaryDirectory(prefix="root262-stale-plan-") as directory:
            stale = Path(directory) / "plan.json"
            stale.write_bytes(PLAN.read_bytes())
            with stale.open("ab") as stream:
                stream.write(b"\n")
            with self.assertRaises(self.mod.Root262Error):
                self.mod._load_scope(stale, OVERLAY)

    def test_generated_request_is_source_only_and_binds_proofs(self):
        request = OUTPUT / "typed-lifecycle-batch-v1-f6-root-forward-262-001.json"
        self.assertTrue(request.is_file(), request)
        value = json.loads(request.read_text(encoding="utf-8"))
        self.assertEqual(value["status"], "READY_NOTRUN_SOURCE_ONLY")
        self.assertFalse(value["launch_allowed"])
        self.assertFalse(value["execution_allowed"])
        self.assertFalse(value["request_submitted"])
        self.assertEqual(len(value["physical_case_ids"]), 7)
        self.assertEqual(value["continuation_group"]["actual_saved_mask_cases_excluded"], 102)
        self.assertEqual(value["continuation_group"]["pending_no_credit_cases_excluded"], 7)
        self.assertEqual(value["continuation_group"]["historical_alias_cases_excluded"], 1)
        deferred = set(value["deferred_input_files"])
        self.assertEqual(len(deferred), 7)
        self.assertFalse(any(Path(path).suffix.lower() in {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"} for path in value["input_files"]))
        proofs = value["source_closure"]["completed_producer_proofs"]
        self.assertEqual(len(proofs), 14)
        self.assertTrue(all(ref["path"] in value["input_sha256"] for ref in proofs))
        self.assertFalse(value["source_read_policy"]["trajectory_content_opened"])
        self.assertFalse(value["source_read_policy"]["trajectory_content_hashed"])


if __name__ == "__main__":
    unittest.main()

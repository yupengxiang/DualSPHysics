#!/usr/bin/env python3
"""Small source-only checks for the configurable F2 v3 request builder."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("ds_data02_stage2_build_f2_generic_native_extract_v3.py")
REQUEST_ROOT = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/requests"


def _module():
    spec = importlib.util.spec_from_file_location("f2_generic_v3_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigurableF2SourceBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _module()

    def _final_request(self, namespace: int) -> tuple[Path, dict]:
        matches = [
            path
            for path in REQUEST_ROOT.glob(f"generic-native-extract-v3-root{namespace}-f2-*-missing-join-forward-*.json")
            if not path.name.endswith("-delegated.json")
        ]
        self.assertEqual(len(matches), 1)
        return matches[0], json.loads(matches[0].read_text(encoding="utf-8"))

    def test_five_ready_batches_are_disjoint_and_complete_proofs(self):
        all_ids = []
        for namespace in range(317, 322):
            request_path, request = self._final_request(namespace)
            self.assertTrue(request_path.is_file())
            manifest_path = Path(request["manifest_contract"]["path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "v3-configurable-multi-proof-source-scope")
            bundle = manifest["typed_proof_bundles"][0]
            self.assertEqual(request["physical_case_ids"], bundle["full_case_ids"])
            self.assertEqual(bundle["selected_case_ids"], bundle["full_case_ids"])
            self.assertFalse(bundle["synthetic_merged_proof"])
            self.assertEqual(manifest["cause_scope"]["cause_bound_missing_join_case_count"], 47)
            self.assertEqual(manifest["actual_join_exclusion"]["selected_overlap_count"], 0)
            self.assertEqual(manifest["cause_scope"]["historical_alias_excluded"], [self.mod.ALIAS_CASE])
            self.assertFalse(any(Path(path).suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"} for path in request["input_files"]))
            all_ids.extend(request["physical_case_ids"])
        self.assertEqual(len(all_ids), 38)
        self.assertEqual(len(set(all_ids)), 38)

    def test_selected_subset_of_a_complete_proof_is_rejected(self):
        source = REQUEST_ROOT / "f2-generic-native-extract-v3-root317-source-spec.json"
        value = json.loads(source.read_text(encoding="utf-8"))
        value["selected_case_ids"] = value["selected_case_ids"][:-1]
        with tempfile.TemporaryDirectory(prefix="f2-v3-spec-") as directory:
            path = Path(directory) / "subset.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(self.mod.F2GenericV3Error):
                self.mod._read_spec(path)

    def test_self_test_scope_keeps_physical_credit_unknown(self):
        result = self.mod._self_test()
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["payload_opened"])
        self.assertFalse(result["launch_allowed"])
        self.assertIn("old native cause count unchanged", " ".join(result["checks"]))


if __name__ == "__main__":
    unittest.main()

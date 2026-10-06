#!/usr/bin/env python3
"""Small metadata-only regression checks for fresh143."""
import json
import subprocess
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts/ay0270_artifact_audit_xmf_adapter.py"
BINDING = ROOT / "metadata/ay0270-artifact-audit-xmf-binding.json"

class Fresh143ContractTest(unittest.TestCase):
    def test_preflight_keeps_three_receipt_roles(self):
        binding = json.loads(BINDING.read_text())
        self.assertNotIn("typed_receipt", binding)
        self.assertEqual(binding["original_conversion_receipt"]["status"], "running")
        self.assertEqual(binding["artifact_audit_receipt"]["status"], "completed")
        self.assertEqual(binding["native_receipt"]["status"], "completed")
        result = subprocess.run(
            [sys.executable, str(ADAPTER), "--binding", str(BINDING), "--metadata-preflight"],
            check=False, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "metadata_preflight_pass")

    def test_future_outputs_and_scope_split(self):
        binding = json.loads(BINDING.read_text())
        self.assertTrue(all(value is None for value in binding["future_outputs"].values()))
        self.assertNotEqual(binding["canonical_source_physical_condition_sha256"],
                            binding["actual_converter_scope_sha256"])
        self.assertEqual(binding["case_credit"], 0)

if __name__ == "__main__":
    unittest.main()

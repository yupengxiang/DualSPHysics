#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fresh111_audit", HERE / "scripts/validate_fresh111.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Fresh111AuditTests(unittest.TestCase):
    def test_fresh110_manifest_and_disabled_requests_are_closed(self):
        report = MODULE.package_audit()
        self.assertEqual(report["fresh110_manifest_files_checked"], 32)
        self.assertEqual(report["disabled_request_count"], 24)
        self.assertFalse(report["scientific_payloads_opened_or_hashed"])

    def test_publication_and_signal_findings_are_explicit(self):
        report = MODULE.package_audit()
        findings = {item["id"] for item in report["findings"]}
        self.assertEqual(findings, {"F111-SIG-PUBLISH", "F111-PATH-SCOPE", "F111-FLOOR-AFTER-RENAME"})
        self.assertTrue(all(item["status"] == "open" for item in report["findings"]))


if __name__ == "__main__":
    unittest.main()


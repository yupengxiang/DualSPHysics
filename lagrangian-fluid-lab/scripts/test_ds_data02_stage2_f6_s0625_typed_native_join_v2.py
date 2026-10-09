from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_f6_s0625_typed_native_join_v2 as subject


class F6S0625TypedNativeJoinV2Tests(unittest.TestCase):
    def test_adapter_binds_one_case_and_three_id_scope(self) -> None:
        subject._configure_base()
        contract = {
            "inputs": {
                "scientific_scan": {
                    "path": "/tmp/scientific-scan.json",
                    "bytes": 167514,
                    "sha256": "a" * 64,
                }
            },
            "deferred_inputs": {
                "typed_records": {"bytes": 417443837},
                "partout_csv": {"bytes": 470},
                "runparts_csv": {"bytes": 52394},
            },
            "resource_policy": {},
            "comparison": {},
            "source_edges": {},
            "claim_boundary": {},
        }
        result = subject._augment_contract(contract)
        self.assertEqual(result["target_scope"]["physical_case_count"], 1)
        self.assertEqual(result["target_scope"]["target_identity_count"], 3)
        self.assertFalse(result["target_scope"]["target_ids_are_physical_cases"])
        self.assertEqual(result["resource_policy"]["estimated_input_read_bytes"], 417664215)
        self.assertEqual(result["resource_policy"]["deferred_input_passes_minimum"], 4)
        self.assertTrue(result["claim_boundary"]["three_ids_are_not_three_cases"])

    def test_scan_reader_is_single_pass_and_stat_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scan = root / "scan.json"
            scan.write_text('{"schema":"ds02.stage2.scientific-scan.v1","scan_status":"SCANNED"}\n', encoding="utf-8")
            stat = subject._base._stat(scan, "fixture scan", allow_deferred=True)
            contract = {"deferred_inputs": {"scan_json": {**stat, "sha256": subject.hashlib.sha256(scan.read_bytes()).hexdigest()}}}
            evidence = subject._read_scan_after_reservation(contract)
            self.assertTrue(evidence["single_pass"])
            self.assertEqual(evidence["sha256"], contract["deferred_inputs"]["scan_json"]["sha256"])
            self.assertFalse(evidence["scan"].get("physical_fate") == "KNOWN")

    def test_cli_exposes_prepare_and_audit_without_launching(self) -> None:
        result = subprocess.run(
            [str(subject.VENV), str(subject.SCRIPT), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("prepare", result.stdout)
        self.assertIn("audit", result.stdout)

    def test_existing_contract_namespace_is_forward_only(self) -> None:
        self.assertEqual(subject.CASE_ID, "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0625_YAWM06_DP025")
        self.assertEqual(subject.FAMILY_ID, "F6")
        self.assertEqual(subject.RECORDS_BYTES, 417443837)
        self.assertEqual(subject.RECORDS_ROWS, 417505)


if __name__ == "__main__":
    unittest.main()

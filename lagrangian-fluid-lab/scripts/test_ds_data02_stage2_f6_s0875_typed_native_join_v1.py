from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_f6_s0875_typed_native_join_v1 as subject


TARGET_IDS = ((0, 91841), (0, 89835), (0, 415457))


class F6S0875TypedNativeJoinV1Tests(unittest.TestCase):
    def test_adapter_binds_one_case_and_three_id_scope(self) -> None:
        subject._configure_base()
        contract = {
            "inputs": {
                "scientific_scan": {
                    "path": "/tmp/scientific-scan-s0875.json",
                    "bytes": 167550,
                    "sha256": "a" * 64,
                }
            },
            "deferred_inputs": {
                "typed_records": {"bytes": 417443839},
                "partout_csv": {"bytes": 470},
                "runparts_csv": {"bytes": 52394},
            },
            "resource_policy": {},
            "comparison": {},
            "source_edges": {},
            "claim_boundary": {"physical_fate": "UNKNOWN"},
        }
        result = subject._augment_contract(contract)
        self.assertEqual(result["target_scope"]["physical_case_count"], 1)
        self.assertEqual(result["target_scope"]["target_identity_count"], 3)
        self.assertFalse(result["target_scope"]["target_ids_are_physical_cases"])
        self.assertEqual(result["resource_policy"]["estimated_input_read_bytes"], 417664253)
        self.assertEqual(result["resource_policy"]["deferred_input_passes_minimum"], 4)
        self.assertTrue(result["claim_boundary"]["three_ids_are_not_three_cases"])
        self.assertEqual(result["claim_boundary"]["physical_fate"], "UNKNOWN")

    def test_scan_reader_is_single_pass_and_stat_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scan = root / "scan.json"
            scan.write_text('{"schema":"ds02.stage2.scientific-scan.v1","scan_status":"SCANNED"}\n', encoding="utf-8")
            stat = subject._base._stat(scan, "fixture scan", allow_deferred=True)
            contract = {"deferred_inputs": {"scan_json": {**stat, "sha256": hashlib.sha256(scan.read_bytes()).hexdigest()}}}
            evidence = subject._read_scan_after_reservation(contract)
            self.assertTrue(evidence["single_pass"])
            self.assertEqual(evidence["sha256"], contract["deferred_inputs"]["scan_json"]["sha256"])
            self.assertFalse(evidence["scan"].get("physical_fate") == "KNOWN")

    def test_scan_join_requires_exact_identity_set_and_saved_bracket(self) -> None:
        rows = [
            {
                "zone": zone,
                "idp": idp,
                "typed_first_disappeared_frame": frame,
                "typed_first_disappeared_bracket_s": [frame * 0.01, (frame + 1) * 0.01],
            }
            for (zone, idp), frame in zip(TARGET_IDS, (7, 8, 8))
        ]
        scan_rows = [
            {
                "zone": row["zone"],
                "idp": row["idp"],
                "first_missing_frame": row["typed_first_disappeared_frame"],
                "first_missing_bracket_s": row["typed_first_disappeared_bracket_s"],
                "native_exit_cause": "EVIDENCE_UNKNOWN",
                "physical_fate": "UNKNOWN",
            }
            for row in rows
        ]
        scan = {
            "schema": "ds02.stage2.scientific-scan.v1",
            "scan_status": "SCANNED",
            "physical_case_id": subject.CASE_ID,
            "family_id": subject.FAMILY_ID,
            "missing_id_records": scan_rows,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.json"
            output = root / "joined.json"
            base.write_text(json.dumps({"rows": rows, "claim_boundary": {}}), encoding="utf-8")
            subject._enrich_with_scan(
                base,
                output,
                {"path": "fixture", "sha256": "fixture", "bytes": 1, "pre_stat": {}, "post_stat": {}, "scan": scan},
            )
            joined = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(joined["scientific_scan_evidence"]["identity_count"], 3)
            self.assertEqual(joined["claim_boundary"]["scientific_scan_saved_frame_join"], "DIAGNOSTIC_ONLY")

            wrong = json.loads(json.dumps(scan))
            wrong["missing_id_records"][0]["idp"] = 999999
            with self.assertRaises(subject._base.CrosscheckError):
                subject._enrich_with_scan(
                    base,
                    root / "wrong.json",
                    {"path": "fixture", "sha256": "fixture", "bytes": 1, "pre_stat": {}, "post_stat": {}, "scan": wrong},
                )

    def test_cli_exposes_prepare_and_audit_without_launching(self) -> None:
        result = subprocess.run(
            [str(subject.VENV), str(subject.SCRIPT), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("prepare", result.stdout)
        self.assertIn("audit", result.stdout)

    def test_case_and_resource_constants_are_exact(self) -> None:
        self.assertEqual(subject.CASE_ID, "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0875_YAWP06_DP025")
        self.assertEqual(subject.FAMILY_ID, "F6")
        self.assertEqual(subject.RECORDS_BYTES, 417443839)
        self.assertEqual(subject.RECORDS_ROWS, 417505)
        self.assertEqual(subject.PARTOUT_BYTES, 470)
        self.assertEqual(subject.RUNPARTS_BYTES, 52394)


if __name__ == "__main__":
    unittest.main()

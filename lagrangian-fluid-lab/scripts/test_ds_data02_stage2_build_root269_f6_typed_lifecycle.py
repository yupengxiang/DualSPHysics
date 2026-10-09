from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_root269_f6_typed_lifecycle as subject


class Root269F6PreparationTests(unittest.TestCase):
    def test_self_test_is_source_only(self) -> None:
        result = subprocess.run(
            [sys.executable, str(subject.SCRIPT), "self-test"],
            check=True,
            capture_output=True,
            text=True,
        )
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "PASS")
        self.assertFalse(value["launch_allowed"])
        self.assertFalse(value["payload_content_opened"])

    def test_latest_plan_selects_exact_unscheduled_historical_f6_group(self) -> None:
        _plan, case_ids, _refs, partitions, extra = subject._load_scope(
            subject.PLAN, subject.CURRENT, subject.AUDIT, subject.INVENTORY, subject.OVERLAY
        )
        self.assertEqual(len(case_ids), 7)
        self.assertTrue(all(case_id.startswith("F6_STAGE1_ANGULAR_RELEASE_OMEGA_") for case_id in case_ids))
        self.assertEqual(len(partitions["actual"]), 116)
        self.assertEqual(len(partitions["aliases"]), 1)
        self.assertEqual(len(partitions["historical"]), 118)
        self.assertEqual(extra["source_bytes"], 19_556_052_537)
        self.assertGreaterEqual(len(extra["producer_proofs"]), 1)

    def test_source_closure_excludes_payload_suffixes(self) -> None:
        _plan, case_ids, _refs, _partitions, _extra = subject._load_scope(
            subject.PLAN, subject.CURRENT, subject.AUDIT, subject.INVENTORY, subject.OVERLAY
        )
        self.assertEqual(len(case_ids), 7)
        self.assertFalse(any(Path(path).suffix.lower() in subject.PAYLOAD_SUFFIXES for path in (str(subject.PLAN), str(subject.CURRENT), str(subject.AUDIT), str(subject.INVENTORY))))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_root245_typed_lifecycle_batch as subject


PLAN = subject.PRIMARY_SCRIPTS.parent / "campaigns/ds-data-02/stage2/checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT232_V4.json"
CURRENT = subject.PRIMARY_SCRIPTS.parent / "campaigns/ds-data-02/stage2/CURRENT336.json"
AUDIT = subject.PRIMARY_SCRIPTS.parent / "campaigns/ds-data-02/stage2/checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json"
EXPECTED_CASES = [
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0875_YAWP06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1125_YAWP12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1375_YAWP18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1625_YAWM18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0375_YAWM12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0625_YAWM06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0875_YAWP06_DP025",
]


class Root245HelperTests(unittest.TestCase):
    def test_actual_after_root232_plan_selects_exact_f6_group(self) -> None:
        plan, selection, producer_refs = subject.select_group(
            PLAN,
            CURRENT,
            AUDIT,
            group_id="F6-typed-lifecycle-continuation-000",
        )
        self.assertEqual(plan["schema"], subject.PLAN_SCHEMA)
        self.assertEqual(selection["family_id"], "F6")
        self.assertEqual(selection["case_ids"], EXPECTED_CASES)
        self.assertEqual(selection["case_count"], 7)
        self.assertEqual(selection["declared_source_bytes"], 19_557_244_116)
        self.assertEqual(selection["actual_saved_mask_cases_excluded"], 87)
        self.assertEqual(selection["historical_alias_cases_excluded"], 1)
        self.assertEqual(len(producer_refs), 12)
        self.assertFalse(set(EXPECTED_CASES) & {subject.ALIAS_CASE})

    def test_plan_sha_and_current_audit_sha_are_frozen(self) -> None:
        self.assertEqual(subject._digest(PLAN), subject.EXPECTED_PLAN_SHA)
        self.assertEqual(subject._digest(CURRENT), subject.EXPECTED_CURRENT_SHA)
        self.assertEqual(subject._digest(AUDIT), subject.EXPECTED_AUDIT_SHA)

    def test_command_keeps_literal_interpreter_and_all_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = type(
                "Args",
                (),
                {
                    "python": Path("/literal/venv/bin/python"),
                    "current": root / "CURRENT336.json",
                    "audit": root / "audit.json",
                    "runtime_config": Path("/literal/DsphConfig.xml"),
                    "cwd": root,
                    "worktree_root": root,
                    "excluded_case_ids": ["DONE", subject.ALIAS_CASE],
                },
            )()
            selection = {"family_id": "F6", "case_ids": EXPECTED_CASES}
            command = subject._command(args, selection, root / "output")
            self.assertEqual(command[0], "/literal/venv/bin/python")
            self.assertEqual(command[2], "prepare")
            self.assertEqual(command.count("--case-id"), 7)
            self.assertEqual(command.count("--exclude-case"), 2)
            for flag in ("--runtime-v2", "--runtime-v6", "--runtime-v8", "--dispatch-v8", "--strict-v8", "--batch-worker", "--v4-worker"):
                self.assertIn(flag, command)

    def test_rejects_plan_with_stale_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stale = Path(directory) / "stale-plan.json"
            stale.write_bytes(PLAN.read_bytes() + b"\n")
            with self.assertRaises(subject.Root245PreparationError):
                subject.select_group(stale, CURRENT, AUDIT, group_id="F6-typed-lifecycle-continuation-000")

    def test_real_cli_self_test_is_bounded_and_does_not_launch(self) -> None:
        result = subprocess.run(
            [sys.executable, str(subject.SCRIPT), "self-test"],
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["launch_allowed"])
        self.assertFalse(report["payload_opened"])


if __name__ == "__main__":
    unittest.main()

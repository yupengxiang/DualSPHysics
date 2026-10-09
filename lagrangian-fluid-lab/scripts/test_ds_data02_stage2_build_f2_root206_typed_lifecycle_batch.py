from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_f2_root206_typed_lifecycle_batch as subject


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def make_plan(root: Path, *, overlap: bool = False) -> tuple[Path, list[Path]]:
    case_ids = [f"F2_CASE_{index:03d}" for index in range(8)]
    plan = write_json(root / "plan.json", {
        "schema": subject.PLAN_SCHEMA,
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "current_catalog": {"sha256": subject.EXPECTED_CURRENT_SHA},
        "groups": [{
            "group_id": "F2-typed-lifecycle-continuation-000",
            "family_id": "F2",
            "case_ids": case_ids,
            "case_count": 8,
            "status": "UNSCHEDULED_METADATA_ONLY",
            "request_created": False,
            "declared_source_bytes": 8 * 1024,
            "within_metadata_bounds": True,
        }],
    })
    proof = write_json(root / "proof.json", {
        "schema": "ds02.stage2.root-actual-verification.v1",
        "status": "VERIFIED_ACTUAL_TEST_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT",
        "guarded_receipt_status": "completed",
        "parent_reservation_released": True,
        "case_verifications": [{"physical_case_id": case_ids[0] if overlap else "F2_OTHER_CASE"}],
    })
    return plan, [proof]


class Root206HelperTests(unittest.TestCase):
    def test_selects_exact_eight_case_group_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, proofs = make_plan(Path(directory))
            selected = subject.select_group(plan, proofs)
            self.assertEqual(selected["group_id"], "F2-typed-lifecycle-continuation-000")
            self.assertEqual(selected["case_count"], 8)
            self.assertTrue(selected["non_overlap_with_completed_proofs"])

    def test_rejects_overlap_with_terminal_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, proofs = make_plan(Path(directory), overlap=True)
            with self.assertRaises(subject.Root206PreparationError):
                subject.select_group(plan, proofs)

    def test_command_is_metadata_builder_only_and_closes_runtime_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, proofs = make_plan(root)
            selected = subject.select_group(plan, proofs)
            args = type("Args", (), {
                "current": root / "CURRENT336.json",
                "audit": root / "audit.json",
                "python": Path("/literal/python"),
                "runtime_config": Path("/literal/DsphConfig.xml"),
                "worktree_root": root,
            })()
            command = subject._command(args, selected, root / "out")
            self.assertEqual(command[1], str(subject.SCRIPT.parent / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py"))
            self.assertEqual(command[2], "prepare")
            self.assertIn("--runtime-v8", command)
            self.assertIn("--strict-v8", command)
            self.assertNotIn("run", command[:4])
            self.assertEqual(command.count("--case-id"), 8)

    def test_literal_interpreter_ref_does_not_resolve_venv_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "python-target"
            target.write_bytes(b"python fixture")
            literal = root / "venv" / "bin" / "python"
            literal.parent.mkdir(parents=True)
            literal.symlink_to(target)
            ref = subject._small_ref(literal, "fixture interpreter", preserve_spelling=True)
            self.assertEqual(ref["path"], str(literal.absolute()))
            self.assertNotEqual(ref["path"], str(target.absolute()))
            self.assertTrue(ref["sha256"])

    def test_self_test_subprocess_does_not_launch(self) -> None:
        import subprocess
        import sys

        result = subprocess.run([sys.executable, str(subject.SCRIPT), "self-test"], check=True, capture_output=True, text=True)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "PASS")
        self.assertFalse(value["launch_allowed"])
        self.assertFalse(value["payload_opened"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_root208_typed_lifecycle_batch as subject


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _catalog_fixture(root: Path, *, alias_in_candidate: bool = False, completed_in_candidate: bool = False) -> tuple[Path, Path, Path]:
    candidate = [f"F1_CASE_{index:02d}" for index in range(8)]
    alias = subject.ALIAS_CASE
    completed = [f"F2_DONE_{index:02d}" for index in range(40)]
    ids = completed + [alias] + candidate + [f"F3_REMAINING_{index:03d}" for index in range(287)]
    assert len(ids) == 336 and len(set(ids)) == 336
    cases = []
    for index, case_id in enumerate(ids):
        is_candidate = case_id in candidate
        cases.append({
            "physical_case_id": case_id,
            "family_id": "F1" if is_candidate else ("F2" if case_id != alias else "F2"),
            "group_id": "F1-typed-lifecycle-continuation-000" if is_candidate else "other",
        })
    current = {"schema": subject.CURRENT_SCHEMA, "cases": cases}
    current_path = _write(root / "CURRENT336.json", current)
    current_digest = _sha(current_path)
    verified = [{"physical_case_id": case_id} for case_id in ids]
    audit = {
        "schema": subject.AUDIT_SCHEMA,
        "current_catalog": {"sha256": current_digest},
        "verified_cases": verified,
    }
    audit_path = _write(root / "audit.json", audit)
    audit_digest = _sha(audit_path)
    rows = []
    for index, case_id in enumerate(ids):
        in_candidate = case_id in candidate
        is_alias = case_id == alias
        is_completed = case_id in completed
        rows.append({
            "physical_case_id": case_id,
            "actual_saved_mask_coverage": is_completed,
            "historical_alias": "HISTORICAL_ALIAS_REVIEW_REQUIRED" if is_alias else "NONE",
            "family_id": "F1" if in_candidate else "F2",
            "group_id": "F1-typed-lifecycle-continuation-000" if in_candidate else "other",
            "status": "UNSCHEDULED_EXACT_CURRENT_AUDIT" if in_candidate else "ACTUAL_SAVED_MASK_COMPLETED" if is_completed else "UNSCHEDULED_EXACT_CURRENT_AUDIT",
            "source_join_status": "EXACT_CURRENT_AUDIT_METADATA_JOIN",
            "groupable": in_candidate,
            "new_attempt_identity_required": in_candidate,
            "declared_source_bytes": 10 if in_candidate else 1,
        })
    proof = _write(root / "proof.json", {"schema": "test"})
    proof_digest = _sha(proof)
    plan = {
        "schema": subject.PLAN_SCHEMA,
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "current_catalog": {"sha256": current_digest},
        "scientific_audit": {"sha256": audit_digest},
        "coverage": {"actual_saved_mask_cases": 40, "historical_alias_unresolved": 1},
        "next_batch_candidate": {"group_id": "F1-typed-lifecycle-continuation-000"},
        "case_records": rows,
        "groups": [{
            "group_id": "F1-typed-lifecycle-continuation-000",
            "family_id": "F1",
            "case_ids": ([candidate[0], alias] + candidate[1:]) if alias_in_candidate else ([candidate[0], completed[0]] + candidate[1:]) if completed_in_candidate else candidate,
            "status": "UNSCHEDULED_METADATA_ONLY",
            "request_created": False,
            "launch_allowed_by_planner": False,
            "within_metadata_bounds": True,
            "declared_source_bytes": 80,
        }],
        "producer_evidence": [{"producer_id": "ROOTTEST", "case_ids": completed, "evidence": {"proof": {"path": str(proof), "sha256": proof_digest}}}],
    }
    plan_path = _write(root / "plan.json", plan)
    return plan_path, current_path, audit_path


class Root208HelperTests(unittest.TestCase):
    def test_selects_plan_next_group_and_excludes_completed_and_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, current, audit = _catalog_fixture(Path(directory))
            values = {"EXPECTED_PLAN_SHA": _sha(plan), "EXPECTED_CURRENT_SHA": _sha(current), "EXPECTED_AUDIT_SHA": _sha(audit)}
            with mock.patch.multiple(subject, **values):
                _plan, selected, proofs = subject.select_group(plan, current, audit)
            self.assertEqual(selected["group_id"], "F1-typed-lifecycle-continuation-000")
            self.assertEqual(selected["family_id"], "F1")
            self.assertEqual(selected["case_count"], 8)
            self.assertEqual(selected["actual_saved_mask_cases_excluded"], 40)
            self.assertEqual(selected["historical_alias_cases_excluded"], 1)
            self.assertEqual(len(proofs), 1)
            self.assertFalse(set(selected["case_ids"]) & {subject.ALIAS_CASE, "F2_DONE_00"})

    def test_rejects_completed_case_in_candidate_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, current, audit = _catalog_fixture(Path(directory), completed_in_candidate=True)
            values = {"EXPECTED_PLAN_SHA": _sha(plan), "EXPECTED_CURRENT_SHA": _sha(current), "EXPECTED_AUDIT_SHA": _sha(audit)}
            with mock.patch.multiple(subject, **values), self.assertRaises(subject.Root208PreparationError):
                subject.select_group(plan, current, audit)

    def test_rejects_alias_case_in_candidate_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan, current, audit = _catalog_fixture(Path(directory), alias_in_candidate=True)
            values = {"EXPECTED_PLAN_SHA": _sha(plan), "EXPECTED_CURRENT_SHA": _sha(current), "EXPECTED_AUDIT_SHA": _sha(audit)}
            with mock.patch.multiple(subject, **values), self.assertRaises(subject.Root208PreparationError):
                subject.select_group(plan, current, audit)

    def test_command_keeps_literal_interpreter_and_all_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = type("Args", (), {
                "python": Path("/literal/venv/bin/python"),
                "current": root / "CURRENT336.json",
                "audit": root / "audit.json",
                "runtime_config": Path("/literal/DsphConfig.xml"),
                "cwd": root,
                "worktree_root": root,
                "excluded_case_ids": ["DONE", subject.ALIAS_CASE],
            })()
            selection = {"family_id": "F1", "case_ids": [f"F1_CASE_{index:02d}" for index in range(8)]}
            command = subject._command(args, selection, root / "output")
            self.assertEqual(command[0], "/literal/venv/bin/python")
            self.assertEqual(command[2], "prepare")
            self.assertEqual(command.count("--case-id"), 8)
            self.assertEqual(command.count("--exclude-case"), 2)
            self.assertNotIn("run", command[:4])
            for flag in ("--runtime-v2", "--runtime-v6", "--runtime-v8", "--dispatch-v8", "--strict-v8", "--batch-worker", "--v4-worker"):
                self.assertIn(flag, command)

    def test_real_cli_self_test_is_bounded_and_does_not_launch(self) -> None:
        result = subprocess.run([str(subject.Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")), str(subject.SCRIPT), "self-test"], check=True, capture_output=True, text=True)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["launch_allowed"])
        self.assertFalse(report["payload_opened"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_typed_lifecycle_continuation_plan_v3 as subject
from test_ds_data02_stage2_typed_lifecycle_continuation_plan_v1 import make_fixture, write_json
from test_ds_data02_stage2_typed_lifecycle_continuation_plan_v2 import add_actual_root193_evidence


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_registry(root: Path, fixture: dict[str, object], *, terminal_root193: bool = True) -> Path:
    proof192 = Path(fixture["proof"])
    proof192_value = json.loads(proof192.read_text(encoding="utf-8"))
    # The V1 fixture already has this diagnostic in the summary; retain the
    # explicit proof-side form to exercise the terminal anchor contract.
    proof192_value["typed_mask_lifecycle_diagnostic"] = {"one_physical_case_only": True, "first_disappearance_ID_count": 2}
    proof192.write_text(json.dumps(proof192_value, sort_keys=True), encoding="utf-8")
    fixture["proof_sha"] = digest(proof192)
    proof193 = add_actual_root193_evidence(root, fixture)
    if terminal_root193:
        proof193_value = json.loads(proof193.read_text(encoding="utf-8"))
        proof193_value.update({
            "status": "VERIFIED_ACTUAL_TEST_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT",
            "guarded_receipt_status": "completed",
            "parent_reservation_released": True,
        })
        proof193.write_text(json.dumps(proof193_value, sort_keys=True), encoding="utf-8")
    proof193_value = json.loads(proof193.read_text(encoding="utf-8"))
    request193 = Path(fixture["request193"])
    manifest193 = Path(fixture["manifest193"])
    # The helper rewrites the immutable fixture request/manifest pair.
    producers = [{
        "producer_id": "ROOT192", "kind": "single_typed_lifecycle", "status": "COMPLETED",
        "case_ids": [fixture["actual_case"]],
        "proof": {"path": str(proof192), "sha256": digest(proof192)},
        "summary": {"path": str(fixture["summary"]), "sha256": digest(Path(fixture["summary"]))},
    }, {
        "producer_id": "ROOT193", "kind": "typed_lifecycle_batch", "status": "COMPLETED" if terminal_root193 else "PENDING_NO_TERMINAL_PROOF",
        "case_ids": list(fixture["pending_ids"]),
        "proof": {"path": str(proof193), "sha256": digest(proof193)} if terminal_root193 else None,
        "request": {"path": str(request193), "sha256": digest(request193)},
        "manifest": {"path": str(manifest193), "sha256": digest(manifest193)},
    }]
    if terminal_root193:
        # A second producer with one separate pending identity models a future
        # ROOT198 request that has no terminal proof yet.
        pending_id = "F1_CASE_010"
        manifest198 = root / "root198-manifest.json"
        manifest198_sha = write_json(manifest198, {
            "schema": subject.BATCH_MANIFEST_SCHEMA, "status": "READY_FOR_GUARDED_BATCH", "family_id": "F1",
            "case_count": 1, "cases": [{"physical_case_id": pending_id}],
        })
        request198 = root / "root198-request.json"
        write_json(request198, {
            "schema": subject.REQUEST_SCHEMA, "family_id": "F1", "physical_case_ids": [pending_id],
            "attempt_id": "root198-ready-notrun", "manifest_contract": {"path": str(manifest198), "sha256": manifest198_sha},
        })
        producers.append({
            "producer_id": "ROOT198", "kind": "typed_lifecycle_batch", "status": "PENDING_NO_TERMINAL_PROOF", "case_ids": [pending_id],
            "request": {"path": str(request198), "sha256": digest(request198)},
            "manifest": {"path": str(manifest198), "sha256": digest(manifest198)},
        })
    registry = {
        "schema": subject.REGISTRY_SCHEMA, "status": "SOURCE_METADATA_REGISTRY",
        "current": {"path": str(fixture["current"]), "sha256": fixture["current_sha"]},
        "audit": {"path": str(fixture["audit"]), "sha256": fixture["audit_sha"]},
        "producers": producers,
    }
    path = root / "evidence-registry-v3.json"
    write_json(path, registry)
    return path


class ContinuationPlanV3Tests(unittest.TestCase):
    def test_terminal_and_pending_producers_are_partitioned_without_credit_leak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            registry = make_registry(root, fixture)
            output = root / "plan-v3.json"
            result = subject.build_plan(
                fixture["current"], fixture["audit"], registry, output,
                expected_current_sha256=fixture["current_sha"], expected_audit_sha256=fixture["audit_sha"], alias_case=fixture["alias"],
            )
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["actual_saved_mask_cases"], 2)
            self.assertEqual(plan["coverage"]["actual_saved_mask_cases"], 2)
            self.assertEqual(plan["coverage"]["pending_no_credit_cases"], 7)
            self.assertEqual(plan["coverage"]["failed_requires_new_attempt_cases"], 1)
            self.assertEqual(plan["coverage"]["remaining_exact_unscheduled_cases"], 325)
            statuses = {row["physical_case_id"]: row for row in plan["case_records"]}
            self.assertEqual(statuses[fixture["actual_case"]]["status"], "ACTUAL_SAVED_MASK_COMPLETED")
            self.assertEqual(statuses["F1_CASE_010"]["status"], "PENDING_NO_CREDIT")
            self.assertEqual(statuses[fixture["pending_ids"][2]]["status"], "FAILED_REQUIRES_NEW_ATTEMPT")
            self.assertFalse(plan["source_read_policy"]["trajectory_content_opened"])
            self.assertFalse(plan["source_read_policy"]["trajectory_content_hashed"])
            self.assertTrue(plan["next_batch_candidate"]["case_ids"])
            self.assertLessEqual(plan["next_batch_candidate"]["case_count"], 8)

    def test_nonterminal_producer_has_no_credit_without_terminal_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            registry = make_registry(root, fixture, terminal_root193=False)
            output = root / "pending.json"
            subject.build_plan(
                fixture["current"], fixture["audit"], registry, output,
                expected_current_sha256=fixture["current_sha"], expected_audit_sha256=fixture["audit_sha"], alias_case=fixture["alias"],
            )
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(plan["coverage"]["actual_saved_mask_cases"], 1)
            self.assertEqual(plan["coverage"]["pending_no_credit_cases"], 8)
            self.assertFalse(any(row["actual_saved_mask_coverage"] for row in plan["case_records"] if row["physical_case_id"] in fixture["pending_ids"]))

    def test_duplicate_registry_case_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            registry = make_registry(root, fixture)
            value = json.loads(registry.read_text(encoding="utf-8"))
            value["producers"][2]["case_ids"] = [fixture["pending_ids"][0]]
            registry.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(subject.ContinuationPlanV3Error):
                subject.build_plan(
                    fixture["current"], fixture["audit"], registry, root / "bad-duplicate.json",
                    expected_current_sha256=fixture["current_sha"], expected_audit_sha256=fixture["audit_sha"], alias_case=fixture["alias"],
                )

    def test_real_subprocess_prepare_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            registry = make_registry(root, fixture)
            output = root / "cli-plan.json"
            completed = subprocess.run([
                sys.executable, str(subject.SCRIPT), "prepare", "--current", str(fixture["current"]), "--audit-verification", str(fixture["audit"]),
                "--evidence-registry", str(registry), "--expected-current-sha256", str(fixture["current_sha"]),
                "--expected-audit-sha256", str(fixture["audit_sha"]), "--output", str(output),
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            self.assertEqual(json.loads(output.read_text())["schema"], subject.PLAN_SCHEMA)


if __name__ == "__main__":
    unittest.main()

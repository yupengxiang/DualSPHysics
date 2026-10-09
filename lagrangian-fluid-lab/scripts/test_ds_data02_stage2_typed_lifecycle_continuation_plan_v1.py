from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_typed_lifecycle_continuation_plan_v1 as subject


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return digest(path)


def make_fixture(root: Path) -> dict[str, Path | str | list[str]]:
    scan = root / "scan.json"
    receipt = root / "scan-receipt.json"
    scan.write_text("{}\n", encoding="utf-8")
    receipt.write_text("{}\n", encoding="utf-8")
    current_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    alias = subject.DEFAULT_ALIAS_CASE
    for index in range(336):
        family = "F1" if index < 168 else "F2"
        case_id = alias if index == 1 else f"{family}_CASE_{index:03d}"
        trajectory = root / "trajectories" / family / f"{index:03d}.h5"
        trajectory.parent.mkdir(parents=True, exist_ok=True)
        trajectory.write_bytes(b"metadata-only fixture\n")
        producer_sha = f"{index + 1:064x}"[-64:]
        current_rows.append({
            "family_id": family,
            "physical_case_id": case_id,
            "runtime_case_alias": f"runtime-{index}",
            "frames": 4,
            "particles": 4,
            "trajectory": {
                "path": str(trajectory),
                "producer_declared_sha256": producer_sha,
                "bytes": trajectory.stat().st_size,
            },
        })
        audit_rows.append({
            "family_id": family,
            "physical_case_id": case_id,
            "trajectory": str(trajectory),
            "trajectory_verified_sha256": producer_sha,
            "scan": str(scan),
            "scan_sha256": digest(scan),
            "receipt": str(receipt),
            "receipt_sha256": digest(receipt),
            "scan_status": "SCANNED",
            "field_failures": [],
            "exact_CURRENT_path_and_declared_sha_match": True,
        })
    current = root / "CURRENT336.json"
    current_sha = write_json(current, {"schema": subject.CURRENT_SCHEMA, "cases": current_rows})
    audit = root / "audit023.json"
    audit_sha = write_json(audit, {
        "schema": subject.AUDIT_SCHEMA,
        "current_catalog": {"path": str(current), "sha256": current_sha},
        "verified_cases": audit_rows,
    })

    actual_case = "F1_CASE_000"
    actual_request = root / "root192-request.json"
    actual_request_sha = write_json(actual_request, {
        "schema": subject.REQUEST_SCHEMA,
        "physical_case_id": actual_case,
        "family_id": "F1",
    })
    actual_receipt = root / "root192-receipt.json"
    actual_receipt_sha = write_json(actual_receipt, {
        "schema": "ds02.execution-receipt.v1",
        "status": "completed",
        "returncode": 0,
    })
    actual_summary = root / "root192-summary.json"
    actual_summary_sha = write_json(actual_summary, {
        "schema": "ds02.stage2.typed-lifecycle-sidecar.v4",
        "status": subject.COMPLETED_STATUS,
        "family_id": "F1",
        "physical_case_id": actual_case,
        "source": {"current336_sha256": current_sha},
        "typed_mask_lifecycle_diagnostic": {
            "one_physical_case_only": True,
            "first_disappearance_ID_count": 2,
        },
    })
    proof = root / "root192-proof.json"
    proof_sha = write_json(proof, {
        "schema": "ds02.stage2.root-actual-verification.v1",
        "status": "VERIFIED_ACTUAL_TYPED_LIFECYCLE_V4_SINGLE_CASE_118_SAVED_MASK_DISAPPEARANCES_NO_PHYSICAL_CREDIT",
        "request": str(actual_request),
        "request_sha256": actual_request_sha,
        "receipt": str(actual_receipt),
        "receipt_sha256": actual_receipt_sha,
        "report": str(actual_summary),
        "report_sha256": actual_summary_sha,
        "physical_case_id": actual_case,
        "guarded_receipt_status": "completed",
        "parent_reservation_released": True,
        "H5_BI4_read_by_root": False,
        "fresh_small_inputs": [
            {"path": str(current), "sha256": current_sha},
            {"path": str(audit), "sha256": audit_sha},
        ],
    })

    pending_ids = [f"F1_CASE_{index:03d}" for index in range(2, 10)]
    manifest = root / "root193-manifest.json"
    manifest_sha = write_json(manifest, {
        "schema": subject.BATCH_MANIFEST_SCHEMA,
        "status": "READY_FOR_GUARDED_BATCH",
        "family_id": "F1",
        "case_count": len(pending_ids),
        "cases": [{"physical_case_id": case_id} for case_id in pending_ids],
    })
    pending_request = root / "root193-request.json"
    pending_request_sha = write_json(pending_request, {
        "schema": subject.REQUEST_SCHEMA,
        "family_id": "F1",
        "physical_case_ids": pending_ids,
        "attempt_id": "root193-ready-notrun",
        "manifest_contract": {"path": str(manifest), "sha256": manifest_sha},
        "launch_allowed": True,
        "execution_allowed": True,
    })
    return {
        "current": current,
        "audit": audit,
        "current_sha": current_sha,
        "audit_sha": audit_sha,
        "proof": proof,
        "summary": actual_summary,
        "request192": actual_request,
        "manifest193": manifest,
        "request193": pending_request,
        "request193_sha": pending_request_sha,
        "proof_sha": proof_sha,
        "pending_ids": pending_ids,
        "actual_case": actual_case,
        "alias": alias,
    }


class ContinuationPlanTests(unittest.TestCase):
    def test_self_test(self) -> None:
        self.assertEqual(subject.self_test()["status"], "PASS")

    def test_exact_remaining_partition_pending_has_no_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            output = root / "continuation.json"
            result = subject.build_plan(
                fixture["current"], fixture["audit"], output,
                expected_current_sha256=fixture["current_sha"],
                expected_audit_sha256=fixture["audit_sha"],
                root192_proof=fixture["proof"],
                root192_summary=fixture["summary"],
                root193_request=fixture["request193"],
                root193_manifest=fixture["manifest193"],
                alias_case=fixture["alias"],
                max_cases=8,
                max_group_bytes=20 * 1024 * 1024 * 1024,
            )
            self.assertEqual(result["status"], "PREPARED_METADATA_ONLY_NO_LAUNCH")
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(plan["coverage"]["current_cases"], 336)
            self.assertEqual(plan["coverage"]["exact_current_audit_rows"], 335)
            self.assertEqual(plan["coverage"]["historical_alias_unresolved"], 1)
            self.assertEqual(plan["coverage"]["root192_actual_saved_mask_cases"], 1)
            self.assertEqual(plan["coverage"]["root193_ready_notrun_cases"], 8)
            self.assertEqual(plan["coverage"]["remaining_exact_unscheduled_cases"], 326)
            statuses = {row["physical_case_id"]: row for row in plan["case_records"]}
            self.assertTrue(statuses[fixture["actual_case"]]["actual_saved_mask_coverage"])
            self.assertEqual(statuses[fixture["actual_case"]]["status"], "ACTUAL_SAVED_MASK_COMPLETED")
            for case_id in fixture["pending_ids"]:
                self.assertEqual(statuses[case_id]["status"], "READY_NOTRUN")
                self.assertFalse(statuses[case_id]["actual_saved_mask_coverage"])
                self.assertNotIn("group_id", statuses[case_id])
            self.assertEqual(statuses[fixture["alias"]]["status"], "HISTORICAL_ALIAS_UNRESOLVED")
            self.assertFalse(statuses[fixture["alias"]]["actual_saved_mask_coverage"])
            group_ids = [case_id for group in plan["groups"] for case_id in group["case_ids"]]
            self.assertEqual(len(group_ids), 326)
            self.assertEqual(len(group_ids), len(set(group_ids)))
            self.assertTrue(set(group_ids).isdisjoint(set(fixture["pending_ids"])))
            self.assertNotIn(fixture["actual_case"], group_ids)
            self.assertNotIn(fixture["alias"], group_ids)
            for group in plan["groups"]:
                self.assertLessEqual(group["case_count"], 8)
                self.assertLessEqual(group["declared_source_bytes"], 20 * 1024 * 1024 * 1024)
                self.assertFalse(group["launch_allowed_by_planner"])
                self.assertFalse(group["request_created"])
            self.assertFalse(plan["source_read_policy"]["trajectory_content_opened"])
            self.assertFalse(plan["source_read_policy"]["trajectory_content_hashed"])
            self.assertFalse(plan["group_policy"]["request_created"])
            self.assertTrue(plan["retry_policy"]["failed_or_missing_cases_require_new_request_identity"])

    def test_mismatched_completed_proof_is_rejected_and_pending_is_not_done(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            proof = json.loads(Path(fixture["proof"]).read_text(encoding="utf-8"))
            proof["physical_case_id"] = "F1_CASE_099"
            Path(fixture["proof"]).write_text(json.dumps(proof), encoding="utf-8")
            with self.assertRaises(subject.ContinuationPlanError):
                subject.build_plan(
                    fixture["current"], fixture["audit"], root / "bad.json",
                    expected_current_sha256=fixture["current_sha"],
                    expected_audit_sha256=fixture["audit_sha"],
                    root192_proof=fixture["proof"],
                    root192_summary=fixture["summary"],
                    root193_request=fixture["request193"],
                    root193_manifest=fixture["manifest193"],
                    alias_case=fixture["alias"],
                )

    def test_duplicate_pending_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            request = json.loads(Path(fixture["request193"]).read_text(encoding="utf-8"))
            request["physical_case_ids"][-1] = request["physical_case_ids"][0]
            Path(fixture["request193"]).write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaises(subject.ContinuationPlanError):
                subject.build_plan(
                    fixture["current"], fixture["audit"], root / "bad-duplicate.json",
                    expected_current_sha256=fixture["current_sha"],
                    expected_audit_sha256=fixture["audit_sha"],
                    root192_proof=fixture["proof"],
                    root192_summary=fixture["summary"],
                    root193_request=fixture["request193"],
                    root193_manifest=fixture["manifest193"],
                    alias_case=fixture["alias"],
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_typed_lifecycle_continuation_plan_v1 as v1
import ds_data02_stage2_typed_lifecycle_continuation_plan_v2 as subject
from test_ds_data02_stage2_typed_lifecycle_continuation_plan_v1 import make_fixture


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return digest(path)


def add_actual_root193_evidence(root: Path, fixture: dict[str, object]) -> Path:
    """Make a bounded mixed RUNNING proof without opening fixture H5 files."""
    current = json.loads(Path(fixture["current"]).read_text(encoding="utf-8"))
    current_by_id = {row["physical_case_id"]: row for row in current["cases"]}
    manifest_path = Path(fixture["manifest193"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_root = root / "root193-output"
    output_root.mkdir()
    evidence: list[dict[str, object]] = []
    statuses = ["COMPLETED", "RUNNING", "FAILED"] + ["READY"] * 5
    for case_id, status in zip(fixture["pending_ids"], statuses):
        case_row = next(row for row in manifest["cases"] if row["physical_case_id"] == case_id)
        current_row = current_by_id[case_id]
        case_manifest = root / "case-manifests" / f"{case_id}.json"
        case_manifest_sha = write_json(case_manifest, {"schema": "ds02.stage2.typed-lifecycle.v4.manifest", "physical_case_id": case_id})
        case_row["case_manifest"] = str(case_manifest)
        case_row["case_manifest_sha256"] = case_manifest_sha
        if status == "COMPLETED":
            trajectory = current_row["trajectory"]
            trajectory_path = Path(trajectory["path"])
            stat = trajectory_path.stat()
            producer_sha = trajectory["producer_declared_sha256"]
            source_trajectory = {
                "path": str(trajectory_path),
                "known_sha256": producer_sha,
                "pre_sha256": producer_sha,
                "post_sha256": producer_sha,
                "pre_stat": {
                    "path": str(trajectory_path),
                    "bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "ctime_ns": stat.st_ctime_ns,
                    "st_dev": stat.st_dev,
                    "st_ino": stat.st_ino,
                },
                "post_stat": {
                    "path": str(trajectory_path),
                    "bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "ctime_ns": stat.st_ctime_ns,
                    "st_dev": stat.st_dev,
                    "st_ino": stat.st_ino,
                },
            }
            summary = output_root / "cases" / case_id / "typed-lifecycle-v4-summary.json"
            summary_sha = write_json(summary, {
                "schema": "ds02.stage2.typed-lifecycle-sidecar.v4",
                "status": v1.COMPLETED_STATUS,
                "family_id": "F1",
                "physical_case_id": case_id,
                "source": {"current336_sha256": fixture["current_sha"], "trajectory_h5": source_trajectory},
            })
            receipt = output_root / "cases" / case_id / "case-execution-receipt.json"
            receipt_sha = write_json(receipt, {
                "schema": "ds02.stage2.typed-lifecycle-case-receipt.v1",
                "status": "COMPLETED",
                "physical_case_id": case_id,
                "family_id": "F1",
                "case_manifest": str(case_manifest),
                "h5_pre_post_sha256_equal": True,
                "output_summary": {"path": str(summary), "sha256": summary_sha, "bytes": summary.stat().st_size},
            })
            evidence.append({
                "physical_case_id": case_id,
                "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
                "receipt": str(receipt),
                "receipt_sha256": receipt_sha,
                "summary": str(summary),
                "summary_sha256": summary_sha,
                "case_manifest": str(case_manifest),
                "case_manifest_sha256": case_manifest_sha,
                "source_trajectory": source_trajectory,
                "source_H5_prepost_known_SHA_and_current_stat_equal": True,
            })
        else:
            evidence.append({"physical_case_id": case_id, "status": status})
    manifest_sha = write_json(manifest_path, manifest)
    request_path = Path(fixture["request193"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["manifest_contract"] = {"path": str(manifest_path), "sha256": manifest_sha}
    write_json(request_path, request)
    batch_summary = output_root / "batch-summary.json"
    batch_summary_sha = write_json(batch_summary, {
        "schema": "ds02.stage2.typed-lifecycle-batch.v1.summary",
        "status": "RUNNING",
        "cases": [{"physical_case_id": item["physical_case_id"], "status": item["status"]} for item in evidence],
    })
    batch_receipt = output_root / "execution-receipt.json"
    batch_receipt_sha = write_json(batch_receipt, {
        "schema": "ds02.execution-receipt.v1",
        "status": "running",
        "output_root": str(output_root),
    })
    proof = root / "root193-actual-proof.json"
    write_json(proof, {
        "schema": "ds02.stage2.root-actual-verification.v1",
        "status": "RUNNING",
        "request": str(request_path),
        "request_sha256": digest(request_path),
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "receipt": str(batch_receipt),
        "receipt_sha256": batch_receipt_sha,
        "batch_summary": str(batch_summary),
        "batch_summary_sha256": batch_summary_sha,
        "case_verifications": evidence,
    })
    return proof


class ContinuationPlanV2Tests(unittest.TestCase):
    def test_self_test(self) -> None:
        self.assertEqual(subject.self_test()["status"], "PASS")

    def test_completed_case_only_receives_saved_mask_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            proof = add_actual_root193_evidence(root, fixture)
            output = root / "continuation-v2.json"
            result = subject.build_plan(
                fixture["current"], fixture["audit"], output,
                expected_current_sha256=fixture["current_sha"],
                expected_audit_sha256=fixture["audit_sha"],
                root192_proof=fixture["proof"],
                root192_summary=fixture["summary"],
                root193_request=fixture["request193"],
                root193_manifest=fixture["manifest193"],
                root193_actual_proof=proof,
                alias_case=fixture["alias"],
            )
            self.assertTrue(result["root193_actual_proof_supplied"])
            self.assertEqual(result["root193_actual_saved_mask_cases"], 1)
            plan = json.loads(output.read_text(encoding="utf-8"))
            records = {row["physical_case_id"]: row for row in plan["case_records"]}
            completed = fixture["pending_ids"][0]
            self.assertEqual(records[completed]["status"], "ACTUAL_SAVED_MASK_COMPLETED")
            self.assertTrue(records[completed]["actual_saved_mask_coverage"])
            self.assertEqual(records[fixture["pending_ids"][1]]["status"], "RUNNING_NO_CREDIT")
            self.assertEqual(records[fixture["pending_ids"][2]]["status"], "FAILED_REQUIRES_NEW_ATTEMPT")
            self.assertEqual(records[fixture["pending_ids"][3]]["status"], "PENDING_NO_CREDIT")
            self.assertFalse(records[fixture["pending_ids"][1]]["actual_saved_mask_coverage"])
            self.assertFalse(records[fixture["pending_ids"][2]]["actual_saved_mask_coverage"])
            self.assertIn(fixture["pending_ids"][2], plan["retry_policy"]["missing_or_failed_case_ids"])
            self.assertEqual(plan["coverage"]["root192_and_root193_actual_saved_mask_cases"], 2)
            self.assertEqual(plan["coverage"]["remaining_exact_unscheduled_cases"], 326)
            self.assertFalse(plan["source_read_policy"]["trajectory_content_opened"])

    def test_manifest_binding_rejects_proof_summary_from_another_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            proof = add_actual_root193_evidence(root, fixture)
            value = json.loads(proof.read_text(encoding="utf-8"))
            other = root / "other-manifest.json"
            write_json(other, {"schema": subject.BATCH_MANIFEST_SCHEMA, "status": "READY_FOR_GUARDED_BATCH", "cases": []})
            value["manifest"] = str(other)
            value["manifest_sha256"] = digest(other)
            proof.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(subject.ContinuationPlanV2Error):
                subject.build_plan(
                    fixture["current"], fixture["audit"], root / "bad.json",
                    expected_current_sha256=fixture["current_sha"],
                    expected_audit_sha256=fixture["audit_sha"],
                    root192_proof=fixture["proof"],
                    root192_summary=fixture["summary"],
                    root193_request=fixture["request193"],
                    root193_manifest=fixture["manifest193"],
                    root193_actual_proof=proof,
                    alias_case=fixture["alias"],
                )

    def test_source_stat_mismatch_remains_retry_without_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            proof = add_actual_root193_evidence(root, fixture)
            value = json.loads(proof.read_text(encoding="utf-8"))
            completed = next(item for item in value["case_verifications"] if item["status"] == "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY")
            summary = Path(completed["summary"])
            summary_value = json.loads(summary.read_text(encoding="utf-8"))
            summary_value["source"]["trajectory_h5"]["post_stat"]["bytes"] += 1
            summary.write_text(json.dumps(summary_value), encoding="utf-8")
            completed["summary_sha256"] = digest(summary)
            proof.write_text(json.dumps(value), encoding="utf-8")
            output = root / "retry.json"
            subject.build_plan(
                fixture["current"], fixture["audit"], output,
                expected_current_sha256=fixture["current_sha"],
                expected_audit_sha256=fixture["audit_sha"],
                root192_proof=fixture["proof"],
                root192_summary=fixture["summary"],
                root193_request=fixture["request193"],
                root193_manifest=fixture["manifest193"],
                root193_actual_proof=proof,
                alias_case=fixture["alias"],
            )
            plan = json.loads(output.read_text(encoding="utf-8"))
            record = next(row for row in plan["case_records"] if row["physical_case_id"] == fixture["pending_ids"][0])
            self.assertEqual(record["status"], "COMPLETED_WITHOUT_SOURCE_CLOSURE_REQUIRES_NEW_ATTEMPT")
            self.assertFalse(record["actual_saved_mask_coverage"])
            self.assertIn(fixture["pending_ids"][0], plan["retry_policy"]["missing_or_failed_case_ids"])


if __name__ == "__main__":
    unittest.main()

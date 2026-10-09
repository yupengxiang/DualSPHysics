from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_typed_lifecycle_continuation_plan_v4 as subject
from test_ds_data02_stage2_typed_lifecycle_continuation_plan_v1 import make_fixture, write_json
from test_ds_data02_stage2_typed_lifecycle_continuation_plan_v2 import add_actual_root193_evidence as _add_actual_root193_evidence


def add_actual_root193_evidence(root: Path, fixture: dict[str, object]) -> Path:
    """Use the V2 producer fixture, then add strict per-case H5 declarations."""
    proof_path = _add_actual_root193_evidence(root, fixture)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    current = json.loads(Path(fixture["current"]).read_text(encoding="utf-8"))
    current_by_id = {row["physical_case_id"]: row for row in current["cases"]}
    manifest_path = Path(fixture["manifest193"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in proof.get("case_verifications", []):
        if item.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
            continue
        case_id = item["physical_case_id"]
        trajectory = current_by_id[case_id]["trajectory"]
        case_manifest = Path(item["case_manifest"])
        case_value = json.loads(case_manifest.read_text(encoding="utf-8"))
        path = Path(trajectory["path"])
        case_value["source_refs"] = [{
            "role": "trajectory_h5", "path": str(path),
            "sha256": trajectory["producer_declared_sha256"], "bytes": path.stat().st_size,
        }]
        case_manifest.write_text(json.dumps(case_value, sort_keys=True), encoding="utf-8")
        case_sha = digest(case_manifest)
        item["case_manifest_sha256"] = case_sha
        for manifest_case in manifest["cases"]:
            if manifest_case.get("physical_case_id") == case_id:
                manifest_case["case_manifest_sha256"] = case_sha
    manifest_sha = write_json(manifest_path, manifest)
    request_path = Path(fixture["request193"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["manifest_contract"] = {"path": str(manifest_path), "sha256": manifest_sha}
    request_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
    proof["request_sha256"] = digest(request_path)
    proof["manifest_sha256"] = manifest_sha
    proof_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
    return proof_path


def _update_registry_proof_sha(registry: Path, producer_index: int, proof_path: Path) -> None:
    value = json.loads(registry.read_text(encoding="utf-8"))
    value["producers"][producer_index]["proof"]["sha256"] = digest(proof_path)
    registry.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _completed_case_item(proof: Path) -> tuple[dict[str, object], dict[str, object]]:
    value = json.loads(proof.read_text(encoding="utf-8"))
    item = next(item for item in value["case_verifications"] if item.get("status") == "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY")
    return value, item


def relabel_fixture_cases(fixture: dict[str, object], mapping: dict[str, str]) -> None:
    """Make a tiny CURRENT/audit fixture with real F4/F6 family rows."""
    current_path = Path(fixture["current"])
    audit_path = Path(fixture["audit"])
    current = json.loads(current_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    for row in current["cases"]:
        if row["physical_case_id"] in mapping:
            row["family_id"] = mapping[row["physical_case_id"]]
    for row in audit["verified_cases"]:
        if row["physical_case_id"] in mapping:
            row["family_id"] = mapping[row["physical_case_id"]]
    current_path.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")
    current_sha = digest(current_path)
    audit["current_catalog"]["sha256"] = current_sha
    audit_path.write_text(json.dumps(audit, sort_keys=True), encoding="utf-8")
    fixture["current_sha"] = current_sha
    fixture["audit_sha"] = digest(audit_path)
    summary_path = Path(fixture["summary"])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["source"]["current336_sha256"] = current_sha
    summary_path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    proof_path = Path(fixture["proof"])
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["report_sha256"] = digest(summary_path)
    for edge in proof.get("fresh_small_inputs", []):
        if edge.get("path") == str(current_path):
            edge["sha256"] = current_sha
        elif edge.get("path") == str(audit_path):
            edge["sha256"] = fixture["audit_sha"]
    proof_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")


def add_ready_family_attempt(root: Path, fixture: dict[str, object], registry: Path, case_id: str, family: str, suffix: str) -> None:
    manifest = root / f"{suffix}-manifest.json"
    manifest_sha = write_json(manifest, {
        "schema": subject.BATCH_MANIFEST_SCHEMA, "status": "READY_FOR_GUARDED_BATCH", "family_id": family,
        "case_count": 1, "cases": [{"physical_case_id": case_id}],
    })
    request = root / f"{suffix}-request.json"
    write_json(request, {
        "schema": subject.REQUEST_SCHEMA, "family_id": family, "physical_case_ids": [case_id],
        "attempt_id": f"{suffix}-attempt-001", "manifest_contract": {"path": str(manifest), "sha256": manifest_sha},
    })
    value = json.loads(registry.read_text(encoding="utf-8"))
    value["producers"].append({
        "producer_id": suffix, "attempt_id": f"{suffix}-attempt-001", "kind": "typed_lifecycle_batch",
        "status": "READY_NOTRUN", "case_ids": [case_id],
        "request": {"path": str(request), "sha256": digest(request)},
        "manifest": {"path": str(manifest), "sha256": manifest_sha},
    })
    registry.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


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
        "producer_id": "ROOT192", "attempt_id": "root192-pilot-attempt-001", "kind": "single_typed_lifecycle", "status": "COMPLETED",
        "case_ids": [fixture["actual_case"]],
        "proof": {"path": str(proof192), "sha256": digest(proof192)},
        "summary": {"path": str(fixture["summary"]), "sha256": digest(Path(fixture["summary"]))},
    }, {
        "producer_id": "ROOT193", "attempt_id": "root193-batch-attempt-001", "kind": "typed_lifecycle_batch", "status": "COMPLETED" if terminal_root193 else "PENDING_NO_TERMINAL_PROOF",
        "case_ids": list(fixture["pending_ids"]),
        "proof": {"path": str(proof193), "sha256": digest(proof193)} if terminal_root193 else None,
        "request": {"path": str(request193), "sha256": digest(request193)},
        "manifest": {"path": str(manifest193), "sha256": digest(manifest193)},
    }]
    if terminal_root193:
        # A second producer with one separate pending identity models a future
        # ROOT198 request that has no terminal proof yet.
        pending_id = "F1_CASE_020"
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
            "producer_id": "ROOT198", "attempt_id": "root198-ready-attempt-001", "kind": "typed_lifecycle_batch", "status": "PENDING_NO_TERMINAL_PROOF", "case_ids": [pending_id],
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


class ContinuationPlanV4Tests(unittest.TestCase):
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
            self.assertEqual(statuses["F1_CASE_020"]["status"], "PENDING_NO_CREDIT")
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
            with self.assertRaises(subject.ContinuationPlanV4Error):
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

    def test_stale_known_sha_is_rejected_without_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            registry = make_registry(root, fixture)
            producer = json.loads(registry.read_text(encoding="utf-8"))["producers"][1]
            proof = Path(producer["proof"]["path"])
            proof_value, item = _completed_case_item(proof)
            summary = Path(item["summary"])
            summary_value = json.loads(summary.read_text(encoding="utf-8"))
            wrong = "f" * 64
            summary_value["source"]["trajectory_h5"].update({"known_sha256": wrong, "pre_sha256": wrong, "post_sha256": wrong})
            summary.write_text(json.dumps(summary_value, sort_keys=True), encoding="utf-8")
            item["summary_sha256"] = digest(summary)
            receipt = Path(item["receipt"])
            receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
            receipt_value["output_summary"]["sha256"] = digest(summary)
            receipt.write_text(json.dumps(receipt_value, sort_keys=True), encoding="utf-8")
            item["receipt_sha256"] = digest(receipt)
            item["source_trajectory"].update({"known_sha256": wrong, "pre_sha256": wrong, "post_sha256": wrong})
            proof.write_text(json.dumps(proof_value, sort_keys=True), encoding="utf-8")
            _update_registry_proof_sha(registry, 1, proof)
            output = root / "stale-sha-plan.json"
            subject.build_plan(fixture["current"], fixture["audit"], registry, output, expected_current_sha256=fixture["current_sha"], expected_audit_sha256=fixture["audit_sha"], alias_case=fixture["alias"])
            plan = json.loads(output.read_text(encoding="utf-8"))
            record = next(row for row in plan["case_records"] if row["physical_case_id"] == fixture["pending_ids"][0])
            self.assertFalse(record["actual_saved_mask_coverage"])
            self.assertEqual(record["status"], "FAILED_REQUIRES_NEW_ATTEMPT")
            self.assertIn("CURRENT/audit/manifest", record["producer_evidence"]["reason"])

    def test_stale_stat_is_rejected_against_fresh_current_stat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            registry = make_registry(root, fixture)
            producer = json.loads(registry.read_text(encoding="utf-8"))["producers"][1]
            proof = Path(producer["proof"]["path"])
            proof_value, item = _completed_case_item(proof)
            summary = Path(item["summary"])
            summary_value = json.loads(summary.read_text(encoding="utf-8"))
            stale = dict(summary_value["source"]["trajectory_h5"]["pre_stat"])
            stale["mtime_ns"] += 1
            summary_value["source"]["trajectory_h5"]["pre_stat"] = stale
            summary_value["source"]["trajectory_h5"]["post_stat"] = dict(stale)
            summary.write_text(json.dumps(summary_value, sort_keys=True), encoding="utf-8")
            item["summary_sha256"] = digest(summary)
            receipt = Path(item["receipt"])
            receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
            receipt_value["output_summary"]["sha256"] = digest(summary)
            receipt.write_text(json.dumps(receipt_value, sort_keys=True), encoding="utf-8")
            item["receipt_sha256"] = digest(receipt)
            item["source_trajectory"]["pre_stat"] = dict(stale)
            item["source_trajectory"]["post_stat"] = dict(stale)
            proof.write_text(json.dumps(proof_value, sort_keys=True), encoding="utf-8")
            _update_registry_proof_sha(registry, 1, proof)
            output = root / "stale-stat-plan.json"
            subject.build_plan(fixture["current"], fixture["audit"], registry, output, expected_current_sha256=fixture["current_sha"], expected_audit_sha256=fixture["audit_sha"], alias_case=fixture["alias"])
            plan = json.loads(output.read_text(encoding="utf-8"))
            record = next(row for row in plan["case_records"] if row["physical_case_id"] == fixture["pending_ids"][0])
            self.assertEqual(record["status"], "FAILED_REQUIRES_NEW_ATTEMPT")
            self.assertFalse(record["actual_saved_mask_coverage"])
            self.assertIn("stat", record["producer_evidence"]["reason"])

    def test_duplicate_successful_attempt_is_rejected_but_failure_then_recovery_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            registry = make_registry(root, fixture)
            value = json.loads(registry.read_text(encoding="utf-8"))
            # A separate failed one-case attempt may precede a later completed
            # batch attempt for the same physical case.
            retry_id = fixture["pending_ids"][0]
            failed_manifest = root / "failed-attempt-manifest.json"
            failed_manifest_sha = write_json(failed_manifest, {
                "schema": subject.BATCH_MANIFEST_SCHEMA, "status": "READY_FOR_GUARDED_BATCH", "family_id": "F1",
                "case_count": 1, "cases": [{"physical_case_id": retry_id}],
            })
            failed_request = root / "failed-attempt-request.json"
            write_json(failed_request, {
                "schema": subject.REQUEST_SCHEMA, "family_id": "F1", "physical_case_ids": [retry_id],
                "attempt_id": "f1-recovery-failed-001", "manifest_contract": {"path": str(failed_manifest), "sha256": failed_manifest_sha},
            })
            value["producers"].insert(1, {
                "producer_id": "F1-FAILED-ATTEMPT", "attempt_id": "f1-recovery-failed-001", "kind": "typed_lifecycle_batch",
                "status": "FAILED", "failure_reason": "fixture_timeout_before_worker_output", "case_ids": [retry_id],
                "request": {"path": str(failed_request), "sha256": digest(failed_request)},
                "manifest": {"path": str(failed_manifest), "sha256": failed_manifest_sha},
            })
            registry.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            output = root / "recovery-plan.json"
            result = subject.build_plan(fixture["current"], fixture["audit"], registry, output, expected_current_sha256=fixture["current_sha"], expected_audit_sha256=fixture["audit_sha"], alias_case=fixture["alias"])
            self.assertGreaterEqual(result["actual_saved_mask_cases"], 2)
            plan = json.loads(output.read_text(encoding="utf-8"))
            record = next(row for row in plan["case_records"] if row["physical_case_id"] == retry_id)
            self.assertTrue(record["actual_saved_mask_coverage"])
            self.assertEqual(len(record["attempt_lineage"]), 2)
            self.assertEqual(record["attempt_lineage"][0]["status"], "FAILED_REQUIRES_NEW_ATTEMPT")
            self.assertEqual(record["attempt_lineage"][1]["status"], "ACTUAL_SAVED_MASK_COMPLETED")

            duplicate = json.loads(registry.read_text(encoding="utf-8"))
            completed_producer = next(item for item in duplicate["producers"] if item.get("producer_id") == "ROOT193")
            duplicate["producers"].append({
                "producer_id": "F1-DUPLICATE-SUCCESS", "attempt_id": "f1-recovery-success-duplicate-002", "kind": "typed_lifecycle_batch",
                "status": "COMPLETED", "case_ids": list(fixture["pending_ids"]),
                "request": completed_producer["request"], "manifest": completed_producer["manifest"],
                "proof": completed_producer["proof"],
            })
            registry.write_text(json.dumps(duplicate, sort_keys=True), encoding="utf-8")
            with self.assertRaises(subject.ContinuationPlanV4Error):
                subject.build_plan(fixture["current"], fixture["audit"], registry, root / "duplicate-success.json", expected_current_sha256=fixture["current_sha"], expected_audit_sha256=fixture["audit_sha"], alias_case=fixture["alias"])

    def test_real_cli_accepts_generic_f4_and_f6_ready_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make_fixture(root)
            relabel_fixture_cases(fixture, {"F1_CASE_010": "F4", "F1_CASE_011": "F6"})
            registry = make_registry(root, fixture)
            add_ready_family_attempt(root, fixture, registry, "F1_CASE_010", "F4", "F4-GENERIC-BATCH")
            add_ready_family_attempt(root, fixture, registry, "F1_CASE_011", "F6", "F6-GENERIC-BATCH")
            output = root / "generic-family-plan.json"
            completed = subprocess.run([
                sys.executable, str(subject.SCRIPT), "prepare", "--current", str(fixture["current"]),
                "--audit-verification", str(fixture["audit"]), "--evidence-registry", str(registry),
                "--expected-current-sha256", str(fixture["current_sha"]), "--expected-audit-sha256", str(fixture["audit_sha"]),
                "--output", str(output),
            ], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            plan = json.loads(output.read_text(encoding="utf-8"))
            producer_ids = {item["producer_id"] for item in plan["producer_evidence"]}
            self.assertIn("F4-GENERIC-BATCH", producer_ids)
            self.assertIn("F6-GENERIC-BATCH", producer_ids)
            records = {item["physical_case_id"]: item for item in plan["case_records"]}
            self.assertEqual(records["F1_CASE_010"]["status"], "PENDING_NO_CREDIT")
            self.assertEqual(records["F1_CASE_011"]["status"], "PENDING_NO_CREDIT")
            self.assertFalse(plan["group_policy"]["request_created"])


if __name__ == "__main__":
    unittest.main()

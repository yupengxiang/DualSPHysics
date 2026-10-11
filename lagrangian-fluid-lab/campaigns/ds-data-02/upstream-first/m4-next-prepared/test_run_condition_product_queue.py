from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("condition_product_queue", HERE / "run_condition_product_queue.py")
assert SPEC and SPEC.loader
QUEUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUEUE)


class ConditionProductQueueTests(unittest.TestCase):
    def test_direct_attempt_mapping_and_h060_downstream_paths(self) -> None:
        h060 = QUEUE._case_paths("UF_F1_MDBC_DP010_H060")
        h052 = QUEUE._case_paths("UF_F1_MDBC_DP010_H052")
        self.assertEqual(h060["direct_attempt"], "m4-direct-conversion-002")
        self.assertEqual(h052["direct_attempt"], "m4-direct-conversion-001")
        self.assertTrue(str(h060["candidate"]).endswith("H060-m4-direct-conversion-002.candidate.json"))
        self.assertIn("m4-direct-conversion-002/trajectory.h5", str(QUEUE._stage_specs(
            "UF_F1_MDBC_DP010_H060",
            h060,
            {"native_files": {"files": []}},
            {"path": str(h060["candidate"]), "record": json.loads(h060["candidate"].read_text())},
            {"relocation_queue_v2": {"status": "ready"}},
        )["enrichment"]["command"]))

    def test_h060_plan_reuses_immutable_direct002_request_and_grant(self) -> None:
        case = "UF_F1_MDBC_DP010_H060"
        paths = QUEUE._case_paths(case)
        candidate = QUEUE._load(paths["candidate"], "H060 direct candidate")
        request, grant = QUEUE._validate_root_direct(case, paths, candidate)
        self.assertEqual(request["attempt_id"], "m4-direct-conversion-002")
        self.assertEqual(grant["request_sha256"], QUEUE._sha256(paths["root_direct_request"]))
        self.assertIn("ds_data02_direct_convert_v2.py", candidate["command"][1])
        self.assertIn(str(QUEUE.CONVERTER), candidate["input_files"])
        self.assertIn(str(QUEUE.CONVERTER_V2), candidate["input_files"])
        self.assertIn(str(QUEUE.DECODER), candidate["input_files"])
        self.assertIn(str(QUEUE.PARTVTK), candidate["input_files"])

    def test_default_plan_path_is_fresh_and_owned(self) -> None:
        path = QUEUE._fresh_plan_path("UF_F1_MDBC_DP010_H060")
        self.assertFalse(path.exists())
        self.assertIn("product-queue", path.name)
        self.assertTrue(path.is_relative_to(QUEUE.PREP))

    def test_receipt_status_rejects_wrong_case_even_when_completed(self) -> None:
        case = "UF_F1_MDBC_DP010_H060"
        attempt = "m4-enrichment-001"
        with tempfile.TemporaryDirectory(prefix="m4-receipt-case-") as temporary:
            run = Path(temporary) / case
            receipt_path = run / attempt / "execution-receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps({
                "schema": "ds02.execution-receipt.v1",
                "status": "completed",
                "returncode": 0,
                "request": {"case_id": "UF_F1_MDBC_DP010_H052", "attempt_id": attempt},
            }), encoding="utf-8")
            status, actual_path, detail = QUEUE._receipt_status(run, attempt, case=case)
            self.assertEqual(status, "invalid")
            self.assertEqual(actual_path, receipt_path)
            self.assertEqual(detail["validation_error"], "receipt_case_id_missing_or_mismatch")

    def test_receipt_status_rejects_completed_nonzero_return(self) -> None:
        case = "UF_F1_MDBC_DP010_H060"
        attempt = "m4-enrichment-001"
        with tempfile.TemporaryDirectory(prefix="m4-receipt-return-") as temporary:
            run = Path(temporary) / case
            receipt_path = run / attempt / "execution-receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps({
                "schema": "ds02.execution-receipt.v1",
                "status": "completed",
                "returncode": 1,
                "request": {"case_id": case, "attempt_id": attempt},
            }), encoding="utf-8")
            status, _, detail = QUEUE._receipt_status(run, attempt, case=case)
            self.assertEqual(status, "invalid")
            self.assertEqual(detail["validation_error"], "completed_returncode_not_zero")

    def test_completed_receipt_requires_exact_request_hash(self) -> None:
        case = "UF_F1_MDBC_DP010_H060"
        attempt = "m4-enrichment-001"
        with tempfile.TemporaryDirectory(prefix="m4-receipt-hash-") as temporary:
            root = Path(temporary)
            run = root / case
            receipt_path = run / attempt / "execution-receipt.json"
            request_path = root / "request.json"
            receipt_path.parent.mkdir(parents=True)
            request_path.write_text(json.dumps({
                "schema": "ds-data-02.runner.request.v1",
                "case_id": case,
                "attempt_id": attempt,
            }), encoding="utf-8")
            receipt_path.write_text(json.dumps({
                "schema": "ds02.execution-receipt.v1",
                "status": "completed",
                "returncode": 0,
                "request": {"case_id": case, "attempt_id": attempt},
            }), encoding="utf-8")
            status, _, detail = QUEUE._receipt_status(run, attempt, case=case, request_path=request_path)
            self.assertEqual(status, "invalid")
            self.assertEqual(detail["validation_error"], "missing_request_sha256")

    def test_h058_remains_fail_closed_without_solver_and_native_audits(self) -> None:
        case = "UF_F1_MDBC_DP010_H058"
        paths = QUEUE._case_paths(case)
        plan = QUEUE._build_plan(case, create_candidate=True)
        self.assertEqual(plan["status"], "blocked_actual_completed_sources")
        self.assertIsNone(plan["direct_candidate"])
        self.assertIn("missing_solver_001_receipt", plan["blockers"])
        self.assertIn("missing_native_integrity_001_receipt", plan["blockers"])
        self.assertFalse(paths["candidate"].exists())

    def test_future_h052_candidate_normalizes_audit_receipt_keys(self) -> None:
        case = "UF_F1_MDBC_DP010_H052"
        paths = QUEUE._case_paths(case)
        owner_info = QUEUE._prepare_owner(case, paths)
        evidence = QUEUE._validate_evidence(case, paths, owner_info["record"])
        actual = QUEUE._source_gates(case, paths, owner_info["record"])
        fake_report = {"path": "/tmp/mock-native-report.json", "bytes": 1, "sha256": "a" * 64, "status": "verified"}
        fake_receipt = {"path": "/tmp/mock-native-receipt.json", "bytes": 1, "sha256": "b" * 64, "status": "completed"}
        actual.update({
            "solver": {"status": "completed", "binding": {"path": "/tmp/mock-solver-receipt.json", "bytes": 1, "sha256": "c" * 64}},
            "native_integrity_receipt": {"status": "completed", "binding": fake_receipt},
            "native_frame_scan_receipt": {"status": "completed", "binding": fake_receipt},
            "native_integrity_report": fake_report,
            "native_frame_scan_report": {**fake_report, "frame_count": 241, "frame_bytes_total": 1, "frame_hash_sequence_sha256": "d" * 64},
            "status": "ready",
            "blockers": [],
        })
        with tempfile.TemporaryDirectory(prefix="m4-condition-queue-test-") as temporary:
            test_paths = dict(paths)
            test_paths["candidate"] = Path(temporary) / "UF_F1_MDBC_DP010_H052-m4-direct-conversion-001.candidate.json"
            mocked_native_files = {
                "files": [{"path": str(paths["solver_receipt"].parent / name), "bytes": 1, "role": name} for name in ("Run.csv", "Run.out", "RunPARTs.csv", "data/PartInfo.ibi4", "data/PartOut_000.obi4")],
                "required_relative_paths": ["Run.csv", "Run.out", "RunPARTs.csv", "data/PartInfo.ibi4", "data/PartOut_000.obi4"],
                "raw_frame_set": {"root": "/tmp/data", "pattern": "Part_*.bi4", "count": 241, "staged_or_copied": False},
                "hash_policy": "test mock",
            }
            with mock.patch.object(QUEUE, "_native_files", return_value=mocked_native_files):
                result = QUEUE._build_direct_candidate(case, test_paths, owner_info, evidence, actual)
            self.assertIsNotNone(result)
            candidate = result["record"]
            self.assertEqual(candidate["attempt_id"], "m4-direct-conversion-001")
            self.assertEqual(set(candidate["actual_completed_receipts"]), {"gencase", "solver", "native_integrity", "native_frame_scan"})
            self.assertIn("native_integrity_report", candidate["input_file_bindings"])
            self.assertIn("native_frame_scan_report", candidate["input_file_bindings"])
            self.assertIn(str(QUEUE.CONVERTER_V2), candidate["input_files"])


if __name__ == "__main__":
    unittest.main()

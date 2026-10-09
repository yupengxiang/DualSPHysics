from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_current_receipt_mismatch_v1 as subject


def _write(path: Path, value: object) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path, *, wrong_alias_input: bool = False) -> tuple[dict, str]:
    target = subject.TARGET_CASE_KEY
    physical = subject.TARGET_PHYSICAL_ID
    exact_row = {"case_key": target, "family_id": "F2", "physical_case_id": physical, "status": "rich"}
    alias_row = dict(exact_row)
    other_exact = {"case_key": "F1/ONE", "family_id": "F1", "physical_case_id": "ONE", "status": "rich"}
    other_alias = dict(other_exact, status="simplified")
    exact_path = root / "exact.json"
    alias_path = root / "alias.json"
    exact_sha = _write(exact_path, {"schema": "ds02.stage2.current336.v1", "cases": [exact_row, other_exact], "total_hdf5_bytes": 2, "unresolved": 0})
    alias_sha = _write(alias_path, {"schema": "ds02.stage2.current336.v1", "cases": [alias_row, other_alias], "total_hdf5_bytes": 1, "unresolved": 1})

    scan_path = root / "scan.json"
    scan_sha = _write(scan_path, {"schema": "ds02.stage2.scientific-scan.v1", "family_id": "F2", "physical_case_id": physical})
    scan_receipt_path = root / "scan-receipt.json"
    scan_request = {
        "case_id": "STAGE2_F2_S1_SCIENCE",
        "attempt_id": "scan-F2-S1-001",
        "input_sha256": {str(alias_path): alias_sha},
    }
    if wrong_alias_input:
        scan_request["input_sha256"][str(alias_path)] = "0" * 64
    scan_receipt_sha = _write(scan_receipt_path, {
        "schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0,
        "request": scan_request, "output_root": str(root / "producer"),
    })
    detail_path = root / "detail.json"
    detail_sha = _write(detail_path, {
        "schema": "ds02.stage2.scientific-scan-detail-card.v2", "case_key": target,
        "family_id": "F2", "physical_case_id": physical,
        "scan_provenance": {"path": str(scan_path), "observed_sha256": scan_sha},
        "receipt_provenance": {"path": str(scan_receipt_path), "observed_sha256": scan_receipt_sha},
    })

    report_path = root / "report.json"
    report_case = {
        "case_key": target, "family_id": "F2", "physical_case_id": physical,
        "receipt": {
            "status": "completed", "attempt_id": "scan-F2-S1-001",
            "current_binding": {
                "exact": False,
                "expected_path": str(exact_path), "expected_sha256": exact_sha,
                "observed": [{"path": str(alias_path), "sha256": alias_sha}],
            },
        },
        "scan_binding": {
            "scientific_scan": {"path": str(scan_path), "sha256": scan_sha},
            "execution_receipt": {"path": str(scan_receipt_path), "sha256": scan_receipt_sha},
            "detail_card": {"path": str(detail_path), "sha256": detail_sha},
        },
    }
    report_sha = _write(report_path, {"schema": "ds02.stage2.scientific-scan-enriched-audit.v3", "status": "done", "cases": [report_case]})
    root_receipt_path = root / "root-receipt.json"
    root_receipt_sha = _write(root_receipt_path, {
        "schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0,
        "output_root": str(root / "root-output"),
    })
    proof_path = root / "proof.json"
    proof_sha = _write(proof_path, {
        "schema": "ds02.stage2.root-actual-verification.v1",
        "report": str(report_path), "report_sha256": report_sha,
        "current_receipt_mismatch_case_keys": [target],
    })
    refs = []
    for role, path, sha in (
        ("root183_proof", proof_path, proof_sha),
        ("root183_report", report_path, report_sha),
        ("root183_execution_receipt", root_receipt_path, root_receipt_sha),
        ("current_exact", exact_path, exact_sha),
        ("current_alias", alias_path, alias_sha),
        ("target_scientific_scan", scan_path, scan_sha),
        ("target_scan_receipt", scan_receipt_path, scan_receipt_sha),
        ("target_detail_card", detail_path, detail_sha),
    ):
        refs.append({"role": role, "path": str(path), "sha256": sha})
    manifest = {
        "schema": subject.MANIFEST_SCHEMA, "status": "READY_JSON_ONLY",
        "target": {
            "case_key": target, "exact_current_path": str(exact_path), "exact_current_sha256": exact_sha,
            "alias_current_path": str(alias_path), "alias_current_sha256": alias_sha,
            "root183_output_root": str(root / "root-output"),
        },
        "source_refs": refs,
    }
    return manifest, alias_sha


class CurrentReceiptMismatchTests(unittest.TestCase):
    def test_target_row_equal_but_catalog_level_difference_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = _fixture(Path(directory))
            sidecar = subject.reconcile(manifest)
        self.assertEqual(sidecar["status"], "RECONCILED_HISTORICAL_ALIAS_MISMATCH_NO_SCIENTIFIC_CREDIT")
        catalogs = sidecar["current_catalogs"]
        self.assertTrue(catalogs["target_row_equal"])
        self.assertEqual(catalogs["different_row_count"], 1)
        self.assertFalse(catalogs["catalog_level_identity_equal"])
        self.assertEqual(sidecar["classification"]["scientific_credit"], "NONE")

    def test_wrong_alias_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = _fixture(Path(directory), wrong_alias_input=True)
            with self.assertRaises(subject.MismatchError):
                subject.reconcile(manifest)

    def test_scientific_payload_paths_are_blocked(self) -> None:
        with self.assertRaises(subject.MismatchError):
            subject._path("/tmp/trajectory.h5", "payload")

    def test_duplicate_current_case_keys_are_rejected(self) -> None:
        with self.assertRaises(subject.MismatchError):
            subject._case_map({"cases": [{"case_key": "A"}, {"case_key": "A"}]}, "fixture")

    def test_sidecar_consumer_preserves_unknown_and_no_credit_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = _fixture(Path(directory))
            sidecar = subject.reconcile(manifest)
            patch = subject.validate_sidecar(sidecar)
        self.assertEqual(patch["status"], "INDEX_MISMATCH_RECORDED_NO_SCIENTIFIC_CREDIT")
        self.assertEqual(patch["scientific_credit"], "NONE")
        self.assertEqual(patch["qualification"]["QI"], "UNKNOWN")

    def test_sidecar_consumer_rejects_scientific_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = _fixture(Path(directory))
            sidecar = subject.reconcile(manifest)
            sidecar["classification"]["physical_fate"] = "OUTFLOW"
            with self.assertRaises(subject.MismatchError):
                subject.validate_sidecar(sidecar)


if __name__ == "__main__":
    unittest.main()

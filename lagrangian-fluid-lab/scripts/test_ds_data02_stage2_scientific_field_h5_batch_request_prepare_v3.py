#!/usr/bin/env python3
"""Metadata-only tests for the 335-group V3 request preparer.

Fixtures use a non-HDF5 file with an ``.h5`` suffix to prove that deferred
inputs are stat-only.  The production preparer is separately exercised on
the frozen 335 index during source preparation; these tests never touch it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("ds_data02_stage2_scientific_field_h5_batch_request_prepare_v3.py")
SPEC = importlib.util.spec_from_file_location("h5_batch_prepare_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ScientificFieldH5BatchPrepareV3Tests(unittest.TestCase):
    def test_deferred_h5_is_stat_only_and_known_sha_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.h5"
            path.write_bytes(b"this is deliberately not an HDF5 payload")
            stat = MODULE.stat_ref(path, "fixture H5")
            row = {"physical_case_id": "FIXTURE", "trajectory_h5": {**stat, "known_sha256": "a" * 64}}
            seen = []
            original = MODULE.sha256_file

            def forbidden(value):
                seen.append(Path(value))
                raise AssertionError("deferred H5 must not be hashed")

            MODULE.sha256_file = forbidden
            try:
                result = MODULE.deferred_h5_ref(row)
            finally:
                MODULE.sha256_file = original
            self.assertEqual(seen, [])
            self.assertEqual(result["known_sha256"], "a" * 64)
            self.assertFalse(result["content_read_by_preparer"])
            self.assertTrue(result["deferred_after_parent_reservation"])

    def test_static_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-a-static.obi4"
            path.write_bytes(b"fixture")
            with self.assertRaises(MODULE.BatchPrepareError):
                MODULE.static_ref(path, "payload")

    def test_missing_case_manifest_is_explicit_source_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def ref(name, content):
                path = root / name
                path.write_text(content, encoding="utf-8")
                return MODULE.static_ref(path, name)
            h5 = root / "trajectory.h5"
            h5.write_bytes(b"deferred fixture")
            h5_stat = MODULE.stat_ref(h5, "fixture trajectory")
            master_row = {
                "physical_case_id": "F2_SINGLE_CASE",
                "family_id": "F2",
                "producer": {"status": "COMPLETED", "producer_id": "ROOT-TINY", "proof": ref("proof.json", "proof")},
                "typed_lifecycle_evidence": {
                    "case_manifest": None,
                    "case_receipt": ref("receipt.json", "receipt"),
                    "typed_summary": ref("summary.json", "summary"),
                },
                "trajectory_h5": {**h5_stat, "known_sha256": "b" * 64},
                "saved_mask_status": "ACTUAL_SAVED_MASK_COMPLETED",
                "source_join_status": "EXACT_CURRENT_AUDIT_METADATA_JOIN",
            }
            current_row = {"family_id": "F2", "frames": 2, "particles": 3, "header": {"units": dict(MODULE.UNIT_PROTOCOL), "identity_key": "(Zone,Idp)"}}
            case, refs = MODULE._case_contract(master_row, current_row)
            self.assertIsNone(case["case_manifest"])
            self.assertEqual(case["case_manifest_status"], "NOT_EXPOSED_BY_PRODUCER")
            self.assertEqual(len(refs), 3)
            self.assertEqual(case["trajectory_h5"]["known_sha256"], "b" * 64)

    def test_group_partition_rejects_duplicate_case(self):
        master = {
            "schema": MODULE.MASTER_SCHEMA,
            "status": "SOURCE_PREPARED_335_CANONICAL_METADATA_ONLY",
            "cases": [{"physical_case_id": "A", "family_id": "F1", "saved_mask_status": "ACTUAL", "source_join_status": "EXACT"}],
            "groups": [{"group_id": "g1", "family_id": "F1", "case_ids": ["A", "A"], "declared_source_bytes": 1}],
        }
        with self.assertRaises(MODULE.BatchPrepareError):
            MODULE._validate_master(master, require_full=False)


if __name__ == "__main__":
    unittest.main()

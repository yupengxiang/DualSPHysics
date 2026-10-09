#!/usr/bin/env python3
"""Manufactured and source-shape tests for the additive V6 mass adapter."""
from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / "ds_data02_stage2_build_native_typed_mass_impact_v6.py"
spec = importlib.util.spec_from_file_location("stage2_mass_v6", SCRIPT)
assert spec is not None and spec.loader is not None
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


class MassV6Tests(unittest.TestCase):
    def test_native_row_normalizer_accepts_singleton_and_joined_report_shapes(self) -> None:
        old = {
            "schema": "old",
            "rows": [{"zone": 0, "idp": 10, "native_first_missing_frame": 4, "native_first_missing_bracket_s": [0.3, 0.4], "typed_first_disappeared_time_s": 0.4}],
        }
        self.assertEqual(MODULE._native_rows(old, "old")[0]["identity_key"], [0, 10])
        f4 = {
            "exact_join": {"rows": [{"zone": 0, "idp": 11, "first_disappeared_frame": 5, "first_disappeared_time_s": 0.5, "first_disappeared_bracket_s": [0.4, 0.5], "native_motive_code": 2, "initial_mass_kg": 0.001}]},
            "native": {"rows": [{"zone": 0, "idp": 11, "motive_code": 2}]},
        }
        row = MODULE._native_rows(f4, "f4")[0]
        self.assertEqual((row["frame"], row["motive_code"]), (5, 2))
        self.assertAlmostEqual(row["initial_mass_kg"], 0.001)

    def test_records_contract_normalizes_top_level_and_typed_edges_without_opening_jsonl(self) -> None:
        records = {"path": "/deferred/case.jsonl", "bytes": 10, "rows": 2, "sha256": "a" * 64, "pre_stat": {"bytes": 10, "mtime_ns": 1, "ctime_ns": 2, "st_dev": 3, "st_ino": 4}}
        result = MODULE._records_contract({}, {"records": records}, "case")
        self.assertTrue(result["read_after_parent_reservation"])
        self.assertEqual(result["st_ino"], 4)
        typed = {"path": "/deferred/typed.jsonl", "bytes": 11, "rows": 3, "sha256": "b" * 64, "pre_stat": {"bytes": 11, "mtime_ns": 1, "ctime_ns": 2, "st_dev": 3, "st_ino": 5}}
        result2 = MODULE._records_contract({}, {"typed": typed}, "typed")
        self.assertEqual(result2["path"], "/deferred/typed.jsonl")

    def test_proof_rows_accept_legacy_singleton_and_full_multi_case_proof(self) -> None:
        singleton = {"schema": MODULE.join_v3.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_SINGLE", "physical_case_id": "one"}
        self.assertEqual(MODULE._proof_rows(singleton, "single"), ["one"])
        multi = {"schema": MODULE.join_v3.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_BATCH", "case_verifications": [{"physical_case_id": "a"}, {"physical_case_id": "b"}]}
        self.assertEqual(MODULE._proof_rows(multi, "multi"), ["a", "b"])

    def test_audit_case_keeps_missing_mass_null_and_requires_fluid_type3(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            records = root / "records.jsonl"
            rows = [
                {"schema": MODULE.v4.v3.RECORD_SCHEMA, "status": "COMPLETED_TYPED_LIFECYCLE_RECORDS_NO_PHYSICAL_CREDIT", "family_id": "F6", "physical_case_id": "case", "record_fields": MODULE.v4.v3.RECORD_FIELDS},
                {"zone": 0, "idp": 10, "initial_role": "fluid", "initial_type_code": 3, "initial_mass_kg": None},
            ]
            records.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            st = records.stat()
            ref = {"path": str(records), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns, "st_dev": st.st_dev, "st_ino": st.st_ino, "rows": 1, "sha256": hashlib.sha256(records.read_bytes()).hexdigest(), "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}
            native = root / "native.json"
            write_json(native, {"rows": [{"identity_key": [0, 10], "first_missing_frame": 1, "first_missing_time_s": 0.1, "bracket_s": [0.0, 0.1], "motive_code": 1}]})
            case = {"physical_case_id": "case", "family_id": "F6", "native_report": {"path": str(native)}, "typed_records_deferred": ref, "selected_native_ids": [{"identity_key": [0, 10], "zone": 0, "idp": 10, "native_motive_code": 1, "native_first_missing_frame": 1, "native_first_missing_time_s": 0.1, "native_saved_bracket_s": [0.0, 0.1], "native_row_initial_mass_kg": None}]}
            result = MODULE._audit_case(case)
            self.assertIsNone(result["selected_typed_initial_mass_sum_kg"])
            self.assertEqual(result["selected_typed_initial_mass_status"], "UNKNOWN_AT_LEAST_ONE_SELECTED_ROW_MASS_MISSING")


if __name__ == "__main__":
    unittest.main()

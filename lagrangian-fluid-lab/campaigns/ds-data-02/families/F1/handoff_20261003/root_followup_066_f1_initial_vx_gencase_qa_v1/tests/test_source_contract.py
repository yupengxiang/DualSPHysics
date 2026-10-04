#!/usr/bin/env python3
"""Regression checks for the source-only fresh066 handoff.

The test reads metadata and source files only.  It never invokes GenCase,
PartVTK, a solver, or an output/array reader.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
VALIDATION = HERE / "metadata" / "static-validation.json"
EXPECTED_PARENTS = {
    "F1_STAGE1_ECC_H110_DP010",
    "F1_STAGE1_ECC_H130_DP010",
    "F1_FALLBACK_ECC_COARSE",
    "F1_STAGE1_ECC_H190_DP010",
    "F1_STAGE1_DUAL_H220_DP020",
    "F1_STAGE1_DUAL_H260_DP020",
    "F1_FALLBACK_DUAL_COARSE",
    "F1_STAGE1_DUAL_H340_DP020",
}


class SourceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(VALIDATION.read_text(encoding="utf-8"))

    def test_validation_is_source_only_and_disabled(self) -> None:
        self.assertEqual(self.data["schema"], "ds02.f1.initial-vx-gencase-qa-source-validation.v1")
        for key in (
            "source_only",
            "launch_allowed",
            "execution_allowed",
            "gencase_launched",
            "initial_qa_launched",
            "solver_launched",
            "raw_arrays_read",
            "raw_arrays_hashed",
            "shared_index_or_ledger_modified",
        ):
            self.assertEqual(self.data[key], key == "source_only", key)
        self.assertEqual(self.data["independent_case_count_increment"], 0)

    def test_all_parents_and_velocity_values_are_independent(self) -> None:
        cases = self.data["cases"]
        self.assertEqual(len(cases), 16)
        self.assertEqual({case["parent_case_id"] for case in cases}, EXPECTED_PARENTS)
        self.assertEqual({tuple(case["velocity_m_per_s"]) for case in cases}, {(0.1, 0.0, 0.0), (0.2, 0.0, 0.0)})
        self.assertEqual(len({case["physical_condition_sha256"] for case in cases}), 16)
        for case in cases:
            self.assertEqual(case["future_receipt_sha256"], None)
            self.assertEqual(case["future_output_sha256"], None)
            self.assertFalse(case["launch_allowed"])
            self.assertGreater(case["parent_total_particles"], 0)
            self.assertGreater(case["parent_fluid_particles"], 0)
            self.assertTrue(case["parent_actual_3d"])

    def test_request_scope_contains_only_gencase_and_initial_qa(self) -> None:
        requests = HERE / "requests"
        self.assertEqual(len(list(requests.glob("*.gencase.request.json"))), 16)
        self.assertEqual(len(list(requests.glob("*.initial-qa.request.json"))), 16)
        self.assertEqual(list(requests.glob("*.native.request.json")), [])
        for path in requests.glob("*.json"):
            request = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(request["launch_allowed"], path.name)
            self.assertFalse(request["execution_allowed"], path.name)
            self.assertTrue(request["source_only"], path.name)
            self.assertIsNone(request.get("future_input_sha256"), path.name)
            self.assertNotIn("root_followup_064", json.dumps(request), path.name)
            self.assertNotIn("-064", json.dumps(request), path.name)
            for raw_path in request["input_files"]:
                self.assertNotIn(Path(raw_path).suffix.lower(), {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz"})


if __name__ == "__main__":
    unittest.main()

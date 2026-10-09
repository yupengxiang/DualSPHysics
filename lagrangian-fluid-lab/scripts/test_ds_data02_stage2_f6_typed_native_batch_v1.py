#!/usr/bin/env python3
"""Manufactured and source-shape tests for the ROOT220 batch builder."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("ds_data02_stage2_f6_typed_native_batch_v1.py")
spec = importlib.util.spec_from_file_location("root220_batch", SCRIPT)
assert spec is not None and spec.loader is not None
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class Root220BatchTests(unittest.TestCase):
    def test_exact_nonoverlap_case_set(self) -> None:
        self.assertEqual(len(batch.ROOT220_CASES), 8)
        self.assertEqual(len(set(batch.ROOT220_CASES)), 8)
        self.assertNotIn(batch.ROOT216_CASE, batch.ROOT220_CASES)
        self.assertNotIn(batch.ROOT219_CASE, batch.ROOT220_CASES)

    def test_duplicate_case_ids_rejected_before_source_access(self) -> None:
        with self.assertRaises(batch.BatchError):
            batch._build_case_contracts([batch.ROOT220_CASES[0], batch.ROOT220_CASES[0]])

    def test_forbidden_single_case_overlap_rejected_before_source_access(self) -> None:
        with self.assertRaises(batch.BatchError):
            batch._build_case_contracts([batch.ROOT216_CASE])

    def test_batch_size_rejected_before_source_access(self) -> None:
        with self.assertRaises(batch.BatchError):
            batch._build_case_contracts([f"synthetic-{i}" for i in range(9)])

    def test_target_rows_must_be_nonempty_unique_and_case_scoped(self) -> None:
        native = {"excluded_particles": [{"zone": 0, "idp": 7}, {"zone": 0, "idp": 8}]}
        self.assertEqual(batch._target_keys(native, "case-a"), {(0, 7), (0, 8)})
        with self.assertRaises(batch.BatchError):
            batch._target_keys({"excluded_particles": []}, "case-empty")
        with self.assertRaises(batch.BatchError):
            batch._target_keys({"excluded_particles": [{"zone": 0, "idp": 7}, {"zone": 0, "idp": 7}]}, "case-dup")

    def test_aggregate_count_cannot_replace_id_level_target_set(self) -> None:
        summary = {"role_ledgers": {"fluid": {"initial_count": 327680, "first_disappearance_count": 3, "active_count_by_frame": [327680, 327677]}}}
        with self.assertRaises(batch.BatchError):
            batch._validate_fluid_target_count(summary, 0, "case-empty")
        with self.assertRaises(batch.BatchError):
            batch._validate_fluid_target_count(summary, 2, "case-count-mismatch")
        # A non-empty exact count is accepted only as an input contract; this
        # test does not award a scientific cause or fate claim.
        batch._validate_fluid_target_count(summary, 3, "case-exact")

    def test_proof_case_requires_completed_saved_mask_and_unknown_physics(self) -> None:
        proof = {
            "schema": "ds02.stage2.root-actual-verification.v1",
            "status": "VERIFIED_ACTUAL_F6_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT",
            "counts": {"completed": 7, "failed": 0},
            "case_verifications": [{
                "physical_case_id": "case-a",
                "family_id": "F6",
                "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
                "source_H5_prepost_known_SHA_and_current_stat_equal": True,
                "native_cause_fate_legal_flux_dynamics": "UNKNOWN",
            }],
        }
        self.assertEqual(batch._proof_case(proof, "case-a")["status"], "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY")
        proof["case_verifications"][0]["native_cause_fate_legal_flux_dynamics"] = "POSITION"
        with self.assertRaises(batch.BatchError):
            batch._proof_case(proof, "case-a")

    def test_real_cli_help_is_wired_to_subcommands(self) -> None:
        completed = subprocess.run([str(batch.VENV), str(SCRIPT), "--help"], check=True, capture_output=True, text=True)
        self.assertIn("prepare", completed.stdout)
        self.assertIn("audit", completed.stdout)

    def test_batch_preserves_independent_case_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = []
            for index, case_id in enumerate(batch.ROOT220_CASES):
                contract = root / f"case-{index}.json"
                contract.write_text(json.dumps({"physical_case_id": case_id}), encoding="utf-8")
                entries.append({"physical_case_id": case_id, "contract_path": str(contract), "contract_sha256": batch._hash_file(contract, "fixture contract")})
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema": batch.BATCH_SCHEMA, "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED", "case_contracts": entries}), encoding="utf-8")
            original = batch._audit_one
            def fake_audit(_base, contract_path, output_path):
                case = json.loads(Path(contract_path).read_text(encoding="utf-8"))["physical_case_id"]
                if case == batch.ROOT220_CASES[2]:
                    raise batch.BatchError("manufactured per-case native CSV mismatch")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("{}\n", encoding="utf-8")
                return {"status": "COMPLETED"}
            batch._audit_one = fake_audit
            try:
                result = batch.audit_batch(type("Args", (), {"manifest": manifest, "output": root / "batch.json"})())
            finally:
                batch._audit_one = original
            self.assertEqual(result["completed"], 7)
            self.assertEqual(result["failed"], 1)
            report = json.loads((root / "batch.json").read_text(encoding="utf-8"))
            failed = [row for row in report["case_results"] if row["status"] == "FAILED"]
            self.assertEqual(len(failed), 1)
            self.assertFalse(failed[0]["saved_mask_credit"])

    def test_generated_source_request_is_nonlaunch_and_payload_deferred(self) -> None:
        # This checks the checked-in source-prepared artifact shape.  It does
        # not open any deferred JSONL/H5/BI4 content.
        request = SCRIPT.parents[1] / "campaigns/ds-data-02/stage2/requests/f6-typed-native-batch-root-forward-220-003.json"
        if not request.exists():
            self.skipTest("source-prepared ROOT220 request is not present in this checkout")
        value = json.loads(request.read_text(encoding="utf-8"))
        self.assertFalse(value["launch_allowed"])
        self.assertEqual(value["deferred_input_policy"], "ONE_SEQUENTIAL_PASS_PER_CASE_AFTER_PARENT_RESERVATION")
        self.assertFalse(any(str(path).endswith((".h5", ".hdf5", ".bi4", ".obi4", ".jsonl")) for path in value["input_files"]))
        self.assertIn("native_bi4_solver_payload", {row["role"] for row in value["source_payload_declarations"]})


if __name__ == "__main__":
    unittest.main()

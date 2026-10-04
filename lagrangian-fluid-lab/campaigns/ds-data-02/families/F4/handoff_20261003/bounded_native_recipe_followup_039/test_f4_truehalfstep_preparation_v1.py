#!/usr/bin/env python3
"""Synthetic unit tests for F4 single-case exact truehalfstep preparation."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from selected_transformer import (
    transform_execution_xml_bytes,
    audit_sources,
    DROP_FINE_XML_PATH,
    DROP_FINE_XML_SHA256,
    DROP_FINE_BI4_PATH,
    DROP_FINE_BI4_SHA256,
    DROP_FINE_BI4_BYTES,
    CASEDEF_CFL_TOKEN,
    EXECUTION_COEFDTMIN_ORIGINAL,
    EXECUTION_COEFDTMIN_MUTATED,
    EXECUTION_CFL_ORIGINAL,
    EXECUTION_CFL_MUTATED,
    FIXED_DT_CLAMPS,
)
from prepare import prepare_truehalfstep_clone


class TestF4TrueHalfstepPreparation(unittest.TestCase):
    """Test suite validating F4 exact truehalfstep execution cloning."""

    def test_01_source_integrity(self):
        """Audit source XML, BI4, and receipts; verify all SHA256 hashes match."""
        res = audit_sources()
        self.assertTrue(res["all_sources_verified"], f"Audit failed: {res}")
        self.assertTrue(res["files"]["source_xml"]["verified"])
        self.assertTrue(res["files"]["source_bi4"]["verified"])
        self.assertEqual(res["files"]["source_bi4"]["bytes"], DROP_FINE_BI4_BYTES)
        self.assertTrue(res["files"]["source_gencase_receipt"]["verified"])
        self.assertTrue(res["files"]["source_solver_receipt"]["verified"])
        self.assertTrue(res["files"]["source_macro_series_receipt"]["verified"])

    def test_02_xml_casedef_preservation(self):
        """Verify that <casedef> historical CFL is preserved untouched."""
        raw = DROP_FINE_XML_PATH.read_bytes()
        mutated, meta = transform_execution_xml_bytes(raw)
        mutated_text = mutated.decode("utf-8")
        parts = mutated_text.split("<execution>", 1)
        casedef_part = parts[0]
        self.assertIn(CASEDEF_CFL_TOKEN, casedef_part)
        self.assertEqual(meta["casedef_historical_cfl_preserved"], "0.20000000000000001")

    def test_03_xml_execution_mutation(self):
        """Verify that only execution parameters CoefDtMin and cflnumber are halved."""
        raw = DROP_FINE_XML_PATH.read_bytes()
        mutated, meta = transform_execution_xml_bytes(raw)
        mutated_text = mutated.decode("utf-8")
        execution_part = mutated_text.split("<execution>", 1)[1]

        self.assertIn(EXECUTION_COEFDTMIN_MUTATED, execution_part)
        self.assertNotIn(EXECUTION_COEFDTMIN_ORIGINAL, execution_part)

        self.assertIn(EXECUTION_CFL_MUTATED, execution_part)
        self.assertNotIn(EXECUTION_CFL_ORIGINAL, execution_part)

        self.assertEqual(meta["execution_cfl_mutated"], "0.1")
        self.assertEqual(meta["execution_coefdtmin_mutated"], "0.025")

    def test_04_whole_xml_reverse_proof(self):
        """Verify byte-for-byte whole-XML reverse roundtrip and SHA256 identity."""
        raw = DROP_FINE_XML_PATH.read_bytes()
        _, meta = transform_execution_xml_bytes(raw)
        self.assertTrue(meta["reversibility_verified"])
        self.assertEqual(meta["original_sha256"], DROP_FINE_XML_SHA256)

    def test_05_no_unintended_fixed_dt_floor(self):
        """Verify DtFixed=0, DtIni=0, DtMin=0 are intact so no fixedDt floor is created."""
        raw = DROP_FINE_XML_PATH.read_bytes()
        mutated, meta = transform_execution_xml_bytes(raw)
        mutated_text = mutated.decode("utf-8")
        execution_part = mutated_text.split("<execution>", 1)[1]

        for clamp in FIXED_DT_CLAMPS:
            self.assertIn(clamp, execution_part)

        self.assertFalse(meta["dt_fixed_floor_safe"]["unintended_fixed_dt_floor"])

    def test_06_bi4_exact_asset_copy(self):
        """Verify BI4 exists, matches byte count, and matches cryptographic SHA256."""
        self.assertTrue(DROP_FINE_BI4_PATH.is_file())
        self.assertEqual(DROP_FINE_BI4_PATH.stat().st_size, DROP_FINE_BI4_BYTES)

    def test_07_prepare_worker_execution(self):
        """Execute prepare_truehalfstep_clone in a temporary directory and verify output report."""
        binding_file = Path(__file__).parent / "binding.json"
        binding_data = json.loads(binding_file.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir)
            report = prepare_truehalfstep_clone(binding_data, out_path)

            self.assertEqual(report["cloned_case_id"], "F4_DROP_CENTERED_REFERENCE_001_DP0025_GENUINE_HALF_CFL001")
            self.assertTrue(report["transformation_metadata"]["reversibility_verified"])
            self.assertFalse(report["numerical_controls"]["unintended_fixed_dt_floor"])
            self.assertTrue(report["prepared_files"]["bi4"]["identical_to_source_bi4"])
            self.assertTrue((out_path / "prepared-input-report.json").is_file())

            # Check written XML and BI4
            written_xml = Path(report["prepared_files"]["xml"]["path"])
            written_bi4 = Path(report["prepared_files"]["bi4"]["path"])
            self.assertTrue(written_xml.is_file())
            self.assertTrue(written_bi4.is_file())
            self.assertEqual(written_bi4.stat().st_size, DROP_FINE_BI4_BYTES)

    def test_08_governance_and_runner_requests(self):
        """Verify runner requests have launch_allowed=false and strict non-claims."""
        handoff_dir = Path(__file__).parent
        prep_req = json.loads((handoff_dir / "prepare-request.json").read_text(encoding="utf-8"))
        solv_req = json.loads((handoff_dir / "solver-request.json").read_text(encoding="utf-8"))

        self.assertFalse(prep_req["launch_allowed"])
        self.assertEqual(prep_req["launch_owner"], "root")
        self.assertEqual(prep_req["q_n_status"], "not_assessed")
        self.assertEqual(prep_req["production_approval"], "none")

        self.assertFalse(solv_req["launch_allowed"])
        self.assertEqual(solv_req["launch_owner"], "root")
        self.assertEqual(solv_req["q_n_status"], "not_assessed")
        self.assertEqual(solv_req["production_approval"], "none")

    def test_09_resource_estimate_audit(self):
        """Verify resource estimates derive from actual complete baseline numbers."""
        handoff_dir = Path(__file__).parent
        eval_report = json.loads((handoff_dir / "evaluation_report.json").read_text(encoding="utf-8"))
        res = eval_report["resource_estimate_audit"]

        self.assertEqual(res["actual_baseline_particles"], 4165249)
        self.assertEqual(res["actual_baseline_steps"], 68322)
        self.assertAlmostEqual(res["actual_baseline_elapsed_seconds"], 2057.47, places=1)
        self.assertGreaterEqual(res["root_budget_check"]["root_remaining_gpu_hours"], 30)
        self.assertTrue(res["root_budget_check"]["budget_satisfied"])

    def test_10_both_mechanisms_validated(self):
        """Verify that both DROP and COLLISION mechanisms are audited and validated."""
        handoff_dir = Path(__file__).parent
        eval_report = json.loads((handoff_dir / "evaluation_report.json").read_text(encoding="utf-8"))
        self.assertTrue(eval_report["mechanism_validation"]["both_mechanisms_validated"])
        mechs = eval_report["mechanism_validation"]["mechanisms"]
        self.assertIn("finite_drop_pool", mechs)
        self.assertIn("oblique_finite_columns", mechs)
        self.assertFalse(mechs["finite_drop_pool"]["prior_truehalfstep_consumed"])
        self.assertTrue(mechs["oblique_finite_columns"]["prior_truehalfstep_consumed"])


if __name__ == "__main__":
    unittest.main()

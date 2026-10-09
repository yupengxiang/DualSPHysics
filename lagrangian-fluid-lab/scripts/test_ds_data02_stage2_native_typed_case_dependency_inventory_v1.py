from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_native_typed_case_dependency_inventory_v1 as subject


def synthetic_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for family, count in (("F2", 48), ("F4", 22), ("F6", 48)):
        for index in range(count):
            rows.append({
                "physical_case_id": f"{family}_CASE_{index:03d}",
                "family_id": family,
                "typed_source": {"declared_bytes": 3_000_000_000 + index},
            })
    return rows


class NativeTypedDependencyInventoryTests(unittest.TestCase):
    def test_case_count_does_not_expand_from_typed_identity_count(self) -> None:
        rows = synthetic_rows()
        completed = {"F2_CASE_000"}
        groups = subject._build_groups(rows, completed)
        selected = [case_id for group in groups for case_id in group["case_ids"]]
        self.assertEqual(len(selected), 117)
        self.assertNotIn("F2_CASE_000", selected)
        self.assertEqual(sum(group["case_count"] for group in groups), 117)
        self.assertTrue(all(group["case_count"] <= 8 for group in groups))
        self.assertTrue(all(group["within_source_bounds"] for group in groups))

    def test_large_source_cap_splits_before_eight_cases(self) -> None:
        rows = [{
            "physical_case_id": f"F6_CASE_{index}",
            "family_id": "F6",
            "typed_source": {"declared_bytes": 3_100_000_000},
        } for index in range(8)]
        groups = subject._build_groups(rows, set())
        self.assertEqual([group["case_count"] for group in groups], [6, 2])
        self.assertTrue(all(group["declared_typed_h5_bytes"] <= subject.MAX_GROUP_BYTES for group in groups))

    def test_stat_only_does_not_read_deferred_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.h5"
            path.write_bytes(b"this is a fixture payload")
            stat = subject._stat_only(path, "fixture trajectory")
            self.assertEqual(stat["status"], "PRESENT_STAT_ONLY")
            self.assertFalse(stat["content_opened"])
            self.assertFalse(stat["content_hashed"])

    def test_crosscheck_identity_count_is_a_field_of_one_case_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof_path = root / "proof.json"
            proof = {
                "status": "VERIFIED_ACTUAL_F2_TYPED_NATIVE_118_FIRST_MISSING_SAVED_FRAME_JOIN_NO_PHYSICAL_CREDIT",
                "guarded_receipt_status": "completed",
                "parent_reservation_released": True,
                "physical_case_id": "F2H10V2_OFFSET_V1",
                "comparison_counts": {"exact_native_identity_join_count": 118, "saved_frame_mismatches": 0, "saved_frame_unknown": 0},
                "whole_typed_record_count": 421566,
                "non_target_typed_record_count": 421448,
                "source_H5_prepost_known_SHA_and_current_stat_equal": True,
            }
            proof_path.write_text(json.dumps(proof), encoding="utf-8")
            attempt = subject._single_attempt(proof, proof_path, "ROOT205_TYPED_NATIVE_FIRST_MISSING", {})
            self.assertEqual(attempt["physical_case_id"], "F2H10V2_OFFSET_V1")
            self.assertEqual(attempt["typed_identity_count"], 118)
            self.assertNotEqual(attempt["typed_identity_count"], 118 * 118)
            self.assertTrue(attempt["native_first_missing_semantics_verified"])

    def test_native_report_and_physical_fate_are_separate(self) -> None:
        status, join = subject._case_status([], True)
        self.assertEqual(status, "NATIVE_REPORT_STAT_ONLY_TYPED_LIFECYCLE_NOT_RUN")
        self.assertEqual(join, "NATIVE_SOURCE_PRESENT_TYPED_CONTENT_NOT_AUDITED")

    def test_bounded_native_report_preserves_numeric_cause_without_fate_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "omission-forensics.json"
            report = {
                "schema": "ds02.stage2.omission-forensics.v2",
                "status": "CAUSES_RECONCILED",
                "family_id": "F2",
                "physical_case_id": "F2_FIXTURE",
                "typed_identity": {"missing_fluid_count": 2, "missing_fluid_initial_mass_kg": 0.002},
                "excluded_particles": [
                    {"first_missing_frame": 4, "first_missing_bracket_s": [0.3, 0.4], "native_exit_cause": "NUMERICAL_POSITION_EXCLUSION", "native_motive": "position", "native_motive_code": 1},
                    {"first_missing_frame": 7, "first_missing_bracket_s": [0.7, 0.8], "native_exit_cause": "NUMERICAL_POSITION_EXCLUSION", "native_motive": "position", "native_motive_code": 1},
                ],
                "native_decode": {
                    "runparts_row_count": 8,
                    "runparts_totals": {"NpOut": 2, "NpOutPos": 2, "NpOutRho": 0, "NpOutMov": 0},
                    "max_saved_time_delta_s": 0.0,
                    "partout": {"path": "PartOut.csv", "sha256": "a" * 64, "bytes": 12},
                    "runparts": {"path": "RunPARTs.csv", "sha256": "b" * 64, "bytes": 34},
                },
                "physical_fate": "UNKNOWN; numerical exclusion is not proof of spill",
                "dynamical_impact": "NOT_ASSESSED",
            }
            raw = json.dumps(report, sort_keys=True).encode("utf-8")
            report_path.write_bytes(raw)
            semantics = subject._native_report_content({"path": str(report_path), "declared_sha256": hashlib.sha256(raw).hexdigest()}, physical_case_id="F2_FIXTURE")
            self.assertEqual(semantics["semantic_status"], "SOURCE_BOUND_NATIVE_REPORT_CONTENT_VERIFIED_SMALL_JSON")
            self.assertEqual(semantics["native_exit_cause_counts"], {"NUMERICAL_POSITION_EXCLUSION": 2})
            self.assertEqual(semantics["native_motive_code_counts"], {"1": 2})
            self.assertEqual(semantics["runparts_totals"]["NpOutPos"], 2)
            self.assertEqual(semantics["physical_fate_legal_flux_dynamics"], "UNKNOWN")
            self.assertNotIn("idp", semantics)

            mismatched = subject._native_report_content({"path": str(report_path), "declared_sha256": "0" * 64}, physical_case_id="F2_FIXTURE")
            self.assertEqual(mismatched["semantic_status"], "MISMATCH_REJECTED")

    def test_legacy_f2_reconciliation_shape_is_source_bound_but_stays_unknown_fate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "native-reconciliation.json"
            report = {
                "schema": "ds02.stage2.native-exclusion-reconciliation.v1",
                "status": "CAUSES_RECONCILED",
                "family_id": "F2",
                "physical_case_id": "F2_S1_FIXTURE",
                "typed_unique_missing": 3,
                "joined_count": 3,
                "joined_initial_mass_kg": 0.003,
                "native_saved_time_max_delta_s": 0.0,
                "native_motive_counts": {"position": 3, "density": 0, "movement": 0},
                "runparts_totals": {"NpOut": 3, "NpOutPos": 3, "NpOutRho": 0, "NpOutMov": 0},
                "missing_fluid_ids": [
                    {"first_missing_frame": 154, "first_missing_bracket_s": [1.5, 1.6], "native_exit_cause": "NUMERICAL_POSITION_EXCLUSION", "native_record": {"motive": "position", "motive_code": 1}},
                    {"first_missing_frame": 207, "first_missing_bracket_s": [2.0, 2.1], "native_exit_cause": "NUMERICAL_POSITION_EXCLUSION", "native_record": {"motive": "position", "motive_code": 1}},
                    {"first_missing_frame": 207, "first_missing_bracket_s": [2.0, 2.1], "native_exit_cause": "NUMERICAL_POSITION_EXCLUSION", "native_record": {"motive": "position", "motive_code": 1}},
                ],
                "physical_fate": "UNKNOWN",
                "dynamical_impact": "NOT_ASSESSED",
            }
            raw = json.dumps(report, sort_keys=True).encode("utf-8")
            report_path.write_bytes(raw)
            semantics = subject._native_report_content({"path": str(report_path), "declared_sha256": hashlib.sha256(raw).hexdigest()}, physical_case_id="F2_S1_FIXTURE")
            self.assertEqual(semantics["semantic_status"], "SOURCE_BOUND_NATIVE_REPORT_CONTENT_VERIFIED_SMALL_JSON")
            self.assertEqual(semantics["report_format"], "NATIVE_RECONCILIATION_V1")
            self.assertEqual(semantics["excluded_particle_count"], 3)
            self.assertEqual(semantics["native_exit_cause_counts"], {"NUMERICAL_POSITION_EXCLUSION": 3})
            self.assertEqual(semantics["runparts_totals"]["NpOutPos"], 3)
            self.assertEqual(semantics["physical_fate_legal_flux_dynamics"], "UNKNOWN")

    def test_cli_self_test_is_source_only(self) -> None:
        import subprocess

        result = subprocess.run([sys.executable, str(subject.SCRIPT), "self-test"], check=True, capture_output=True, text=True)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "PASS")
        self.assertFalse(value["launch_allowed"])
        self.assertFalse(value["h5_opened"])
        self.assertFalse(value["native_opened"])


if __name__ == "__main__":
    unittest.main()

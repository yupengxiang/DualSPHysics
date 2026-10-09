from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_native_typed_case_dependency_inventory_v2 as subject


def case_row(*, case_id: str = "F2_FIXTURE", excluded: int | None = 2, typed: int | None = 2, category: bool = True) -> dict:
    return {
        "physical_case_id": case_id,
        "family_id": "F2",
        "native_source": {"report_semantics": {
            "semantic_status": "SOURCE_BOUND_NATIVE_REPORT_CONTENT_VERIFIED_SMALL_JSON",
            "excluded_particle_count": excluded,
            "typed_identity_missing_fluid_count": typed,
            "native_exit_cause_counts": {"NUMERICAL_POSITION_EXCLUSION": excluded} if category and excluded else {},
            "runparts_totals": {"NpOut": excluded or 0, "NpOutPos": excluded or 0} if category else {},
        }},
        "evidence_layers": {"typed_native_first_missing_saved_frame_join": "NOT_PROVEN_FOR_THIS_CASE"},
    }


def old_row(*, history_cause: str = "UNKNOWN", joined: int | None = None, ids_match: bool = False, scanned: bool = True) -> dict:
    return {
        "physical_case_id": "F2_FIXTURE",
        "family_id": "F2",
        "cause": {"history_cause": history_cause, "joined_count": joined, "ids_match_scan": ids_match},
        "current_scan": {"scan_status": "SCANNED" if scanned else "INCOMPLETE"},
    }


class NativeTypedScopeV2Tests(unittest.TestCase):
    def test_per_fluid_credit_requires_historical_id_join_and_matching_counts(self) -> None:
        row = case_row(excluded=2, typed=2)
        old = old_row(history_cause="NATIVE_NUMERICAL_EXCLUSION_RECONCILED", joined=2, ids_match=True)
        result = subject.classify_case(row, old)
        self.assertEqual(result["classification"], "NATIVE_CAUSE_BOUND_PER_FLUID_ID")
        self.assertEqual(result["reported_native_category_scope"], "PER_FLUID_ID_NATIVE_NUMERICAL_CAUSE")

    def test_family_report_category_does_not_promote_unlocated_case(self) -> None:
        row = case_row(excluded=4, typed=4, category=True)
        old = old_row(history_cause="UNKNOWN", joined=None, ids_match=False, scanned=True)
        result = subject.classify_case(row, old)
        self.assertEqual(result["classification"], "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN")
        self.assertEqual(result["reported_native_category_scope"], "NATIVE_REPORT_CATEGORY_OR_RUNPARTS_STAT_ONLY_UNRESOLVED")
        self.assertFalse(result["historical_ids_match_scan"])

    def test_empty_report_is_not_a_zero_loss_cause_credit(self) -> None:
        row = case_row(excluded=0, typed=0, category=False)
        old = old_row(scanned=True)
        result = subject.classify_case(row, old)
        self.assertEqual(result["classification"], "SCAN_COMPLETED_NO_NATIVE_TARGETS")
        self.assertEqual(result["reported_native_category_scope"], "NO_NATIVE_TARGETS_OBSERVED")
        self.assertEqual(result["physical_fate_legal_flux_dynamics"], "UNKNOWN")

    def test_solid_only_or_non_target_rows_remain_stat_only(self) -> None:
        row = case_row(excluded=3, typed=0, category=True)
        old = old_row(scanned=True)
        result = subject.classify_case(row, old)
        self.assertEqual(result["classification"], "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN")
        self.assertEqual(result["reported_native_category_scope"], "NATIVE_REPORT_CATEGORY_OR_RUNPARTS_STAT_ONLY_UNRESOLVED")

    def test_missing_report_or_scan_is_unknown(self) -> None:
        row = case_row(excluded=3, typed=3, category=True)
        row["native_source"]["report_semantics"]["semantic_status"] = "UNKNOWN_REPORT_CONTENT"
        old = old_row(scanned=False)
        result = subject.classify_case(row, old)
        self.assertEqual(result["classification"], "UNKNOWN_SOURCE_OR_IDENTITY")

    def test_cli_self_test_is_source_only(self) -> None:
        result = subprocess.run([sys.executable, str(subject.SCRIPT), "self-test"], check=True, capture_output=True, text=True)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "PASS")
        self.assertFalse(value["launch_allowed"])
        self.assertFalse(value["payload_opened"])


if __name__ == "__main__":
    unittest.main()

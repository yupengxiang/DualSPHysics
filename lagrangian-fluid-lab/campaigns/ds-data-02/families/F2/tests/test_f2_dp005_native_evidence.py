"""Read-only regression checks for the DP005 native exclusion evidence.

These tests intentionally bind the diagnostic code to the actual completed
solver artifacts.  They check the two facts that are easy to lose when the
large raw exports are summarized: separator-aware RunPARTs accounting and a
measured negative result for RV4 mother equivalence.  They do not launch
PartVTKOut, a solver, or a conversion.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


F2_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DP005_ROOT = DATA_ROOT / "families/F2/F2_COMM4_DP005_REPAIR01_NATIVE_EXCLUSION_DIAGNOSTIC"
SUMMARY = DP005_ROOT / "diagnostic-f2-dp005-repair01-native-summary-v4/dp005-native-summary.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIAGNOSTIC = _load(
    "f2_dp005_native_diagnostic_test_module",
    F2_ROOT / "f2_handoff_20261002_dp005_native_diagnostic_v1.py",
)
SUMMARY_V4 = _load(
    "f2_dp005_native_summary_v4_test_module",
    F2_ROOT / "f2_handoff_20261002_dp005_native_summary_v4.py",
)


def _runparts(background: str) -> Path:
    case = f"F2_COMM4_{background.upper()}_V1_DP005_REPAIR01_MACRO_SAVE010"
    short = background.lower()
    return (
        DATA_ROOT
        / f"families/F2/{case}/qualification-f2_comm4_{short}_v1_dp005_repair01_macro_save010-native-fullstate-v1/solver_output/RunPARTs.csv"
    )


def _xml(background: str) -> Path:
    case = f"F2_COMM4_{background.upper()}_V1_DP005"
    return DATA_ROOT / f"families/F2/{case}/gencase-f2-f2-comm4-{background.lower()}-v1-dp005-gridaligned-v2/{case}.xml"


def _motion(background: str) -> Path:
    xml = _xml(background)
    return xml.with_name(xml.stem + "_motion.dat")


class F2DP005NativeEvidenceTests(unittest.TestCase):
    def test_separator_aware_runparts_keeps_all_exclusion_counts(self):
        center = DIAGNOSTIC.runparts(_runparts("CENTER"))
        offset = DIAGNOSTIC.runparts(_runparts("OFFSET"))
        self.assertEqual(len(center), 401)
        self.assertEqual(len(offset), 401)
        self.assertEqual(sum(row["NpOutPos"] for row in center), 128348)
        self.assertEqual(sum(row["NpOutPos"] for row in offset), 135964)
        self.assertEqual(sum(row["NpOutRho"] for row in center), 0)
        self.assertEqual(sum(row["NpOutMov"] for row in offset), 0)

    def test_dp005_is_measured_as_a_non_equivalent_mother(self):
        rv4_xml = INTEGRATION_ROOT / (
            "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/"
            "handoff_20261002/root_rv4_launch_001/staged_inputs/"
            "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001/"
            "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001.xml"
        )
        dp_signature = DIAGNOSTIC.geometry_signature(_xml("CENTER"))
        rv4_signature = DIAGNOSTIC.geometry_signature(rv4_xml)
        dp_motion = DIAGNOSTIC.motion_values(_motion("CENTER"))
        rv4_motion = DIAGNOSTIC.motion_values(
            rv4_xml.with_name("F2H10V2_CENTER_V1_MEDIUM_motion.dat")
        )
        self.assertNotEqual(
            dp_signature["boundary_canonical_sha256"],
            rv4_signature["boundary_canonical_sha256"],
        )
        difference = DIAGNOSTIC.motion_difference(dp_motion, rv4_motion)
        self.assertFalse(difference["same_values_exact"])
        self.assertGreater(difference["max_angle_difference_deg"], 50.0)

    def test_detailed_ranges_preserve_three_fluid_source_mks(self):
        ranges = SUMMARY_V4.detailed_ranges(_xml("CENTER"))
        fluid = [item for item in ranges if item["source"] == "fluid"]
        self.assertEqual(len(fluid), 3)
        self.assertEqual({item["mk_values"][0] for item in fluid}, {1, 2, 3})
        for item in fluid:
            resolved = DIAGNOSTIC.typed_identity(item["low"], ranges)
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["type"], 3)
            self.assertEqual(resolved["mk"], item["mk_values"][0])

    def test_summary_retains_unknown_semantics_and_actual_counts(self):
        report = json.loads(SUMMARY.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "diagnostic_complete_pending_scientific_review")
        self.assertEqual(report["qualification_claim"], "none")
        self.assertEqual(report["production_claim"], "none")
        self.assertEqual(len(report["cases"]), 2)
        for case in report["cases"]:
            export = case["partvtkout_export"]
            self.assertTrue(export["all_motive_rows_remain_numerical_unknown"])
            self.assertEqual(export["typed_type_totals"], {"3": export["row_count"]})
            self.assertFalse(case["strict_mother_equivalence"]["comparisons"]["measured_strict_mother_equivalence"])
            self.assertEqual(
                case["strict_mother_equivalence"]["comparisons"]["classification"],
                "non_equivalent_geometry_or_control_requires_new_scope",
            )


if __name__ == "__main__":
    unittest.main()

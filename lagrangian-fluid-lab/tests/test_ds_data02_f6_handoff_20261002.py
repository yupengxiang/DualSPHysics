#!/usr/bin/env python3
"""Pure tests for the additive F6 handoff_20261002 mother definitions."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_handoff_20261002.py"
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HandoffMotherTests(unittest.TestCase):
    def test_three_dp_ladder_exactly_tiles_frozen_fluid_box(self) -> None:
        self.assertAlmostEqual(MODULE.continuous_fluid_volume(), 5.12)
        self.assertEqual(MODULE.initial_submerged_body_volume(), 0.0)
        self.assertEqual([MODULE.expected_fluid_particles(dp) for _, dp in MODULE.DP_LADDER], [10000, 40960, 80000])
        self.assertTrue(all(MODULE.FLUID["size"][axis] / dp % 1 == 0 for _, dp in MODULE.DP_LADDER for axis in range(3)))

    def test_body_contract_separates_aggregate_mass_and_inertia(self) -> None:
        self.assertEqual(MODULE.BODY["mass_kg"], 128.0)
        self.assertAlmostEqual(MODULE.body_volume(), 0.256)
        inertia = MODULE.body_inertia()
        self.assertAlmostEqual(inertia[0][0], 8.533333333333334)
        self.assertAlmostEqual(inertia[1][1], 8.533333333333334)
        self.assertAlmostEqual(inertia[2][2], 13.653333333333334)
        self.assertTrue(all(inertia[i][j] == 0 for i in range(3) for j in range(3) if i != j))

    def test_definition_contains_finite_walls_native_body_and_wave_motion(self) -> None:
        for mechanism, _ in MODULE.MECHANISMS.items():
            xml = MODULE._definition_xml(mechanism, "medium", 0.05)
            self.assertIn("bottom | left | right | front | back", xml)
            self.assertIn('massbody value="128"', xml)
            self.assertIn('RigidAlgorithm" value="1"', xml)
            self.assertNotIn("<chrono", xml.lower())
            if mechanism == "wave_no_contact":
                self.assertIn('<objreal ref="10">', xml)
                self.assertIn('<mkbound value="10" />', xml)

    def test_materialized_manifest_is_additive_and_cpu_only(self) -> None:
        manifest_path = MODULE.FAMILY_ROOT / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["cases"]), 6)
        self.assertTrue(manifest["cpu_only_until_root_review"])
        self.assertFalse(manifest["history_boundary"]["old_fallback_02_reused"])
        self.assertTrue(all(case["request"]["kind"] == "cpu" for case in manifest["cases"]))
        self.assertTrue(all(case["request"]["cpu_task_kind"] == "gencase" for case in manifest["cases"]))


if __name__ == "__main__":
    unittest.main()

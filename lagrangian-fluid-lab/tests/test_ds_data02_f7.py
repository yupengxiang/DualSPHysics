#!/usr/bin/env python3
"""Focused contract tests for the F7 input generator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f7.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f7", SCRIPT)
assert SPEC and SPEC.loader
F7 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = F7
SPEC.loader.exec_module(F7)


class F7GeneratorTest(unittest.TestCase):
    def test_registry_is_two_mechanisms_three_resolutions_and_nested_stages(self) -> None:
        specs = F7.case_specs()
        self.assertEqual(len(specs), 48)
        self.assertEqual(sum(s.mechanism == "pump_recirculation" for s in specs), 24)
        self.assertEqual(sum(s.mechanism == "moving_obstacle_exchange" for s in specs), 24)
        self.assertEqual({s.resolution for s in specs}, {"coarse", "medium", "fine"})
        self.assertEqual({stage: sum(F7.stage_for_case(s) == stage for s in specs)
                          for stage in ("stage8", "stage24", "stage48")},
                         {"stage8": 8, "stage24": 16, "stage48": 24})

    def test_pump_schedule_has_stop_and_reverse(self) -> None:
        spec = next(s for s in F7.case_specs() if s.mechanism == "pump_recirculation")
        rows = F7._pump_control_rows(spec)
        states = {row["state"] for row in rows}
        self.assertTrue({"forward_constant", "neutral_wait", "reverse_constant"} <= states)
        self.assertLess(min(row["angular_velocity_deg_s"] for row in rows), 0.0)
        self.assertGreater(max(row["angular_velocity_deg_s"] for row in rows), 0.0)
        self.assertAlmostEqual(rows[0]["angle_deg"], rows[250]["angle_deg"], places=8)
        self.assertAlmostEqual(rows[0]["angle_deg"], rows[500]["angle_deg"], places=8)

    def test_materialized_inputs_are_native_three_dimensional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            family = Path(directory) / "F7"
            result = F7.materialize(family)
            self.assertEqual(result["case_count"], 48)
            pump = family / "definitions/F7_PUMP_COARSE_V080_F090_O00_Def.xml"
            obstacle = family / "definitions/F7_OBSTACLE_COARSE_V080_F090_O00_Def.xml"
            for path in (pump, obstacle):
                root = ET.parse(path).getroot()
                definition = root.find("./casedef/geometry/definition")
                self.assertIsNotNone(definition)
                pointmin = definition.find("./pointmin")
                pointmax = definition.find("./pointmax")
                self.assertIsNotNone(pointmin)
                self.assertIsNotNone(pointmax)
                self.assertNotEqual(pointmin.get("z"), pointmax.get("z"))
                motion = root.find("./casedef/motion/objreal")
                self.assertIsNotNone(motion)
                self.assertEqual(motion.get("ref"), "2")
                self.assertTrue(root.findall("./casedef/geometry/commands/mainlist/setmkfluid"))
                self.assertNotIn("MovingSquare", path.read_text())
            self.assertIn("mvrotace", pump.read_text())
            self.assertIn("mvrotsinu", obstacle.read_text())

    def test_request_bounds_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            family = Path(directory) / "F7"
            requests = F7.emit_requests(family, "matrix", 1)
            self.assertEqual(len(requests), 6)
            for request_path in requests:
                request = __import__("json").loads(request_path.read_text())
                self.assertEqual(request["max_wall_seconds"], 300)
                self.assertEqual(request["cpu_threads"], 4)
                self.assertLessEqual(request["estimated_storage_bytes"], 256 * 1024 * 1024)
                self.assertTrue(request["input_files"])
                self.assertIn("{attempt_root}", " ".join(request["command"]))


if __name__ == "__main__":
    unittest.main()

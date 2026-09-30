#!/usr/bin/env python3
"""Contract tests for F7 physical-parent and reference registries."""

from __future__ import annotations

import importlib.util
import json
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
    def test_physical_parent_count_and_nested_stages(self) -> None:
        specs = F7.production_specs()
        self.assertEqual(len(specs), 48)
        self.assertEqual(sum(s.mechanism == "pump_recirculation" for s in specs), 24)
        self.assertEqual(sum(s.mechanism == "moving_obstacle_exchange" for s in specs), 24)
        self.assertEqual({s.resolution for s in specs}, {"fine"})
        self.assertEqual(len({s.physical_parent_id for s in specs}), 48)
        for mechanism in ("pump_recirculation", "moving_obstacle_exchange"):
            rows = [s for s in specs if s.mechanism == mechanism]
            self.assertEqual({s.split for s in rows}, {"train", "validation", "test"})
            self.assertEqual({key: sum(s.split == key for s in rows)
                              for key in ("train", "validation", "test")},
                             {"train": 8, "validation": 8, "test": 8})
        self.assertEqual({stage: sum(F7.stage_for_case(s) == stage for s in specs)
                          for stage in ("stage8", "stage24", "stage48")},
                         {"stage8": 8, "stage24": 16, "stage48": 24})

    def test_reference_matrix_has_one_parent_per_mechanism(self) -> None:
        refs = F7.reference_specs()
        self.assertEqual(len(refs), 6)
        for mechanism in ("pump_recirculation", "moving_obstacle_exchange"):
            rows = [s for s in refs if s.mechanism == mechanism]
            self.assertEqual(len(rows), 3)
            self.assertEqual(len({s.physical_parent_id for s in rows}), 1)
            self.assertEqual({s.resolution for s in rows}, {"coarse", "medium", "fine"})
            self.assertEqual({s.split for s in rows}, {"reference"})

    def test_pump_schedule_and_physical_axis(self) -> None:
        specs = F7.production_specs()
        first = next(s for s in specs if s.mechanism == "pump_recirculation" and s.variant == 0)
        second = next(s for s in specs if s.mechanism == "pump_recirculation" and s.variant == 1)
        rows = F7._pump_control_rows(first)
        states = {row["state"] for row in rows}
        self.assertTrue({"forward_constant", "neutral_wait", "reverse_constant"} <= states)
        self.assertLess(min(row["angular_velocity_deg_s"] for row in rows), 0.0)
        self.assertGreater(max(row["angular_velocity_deg_s"] for row in rows), 0.0)
        first_motion = ET.Element("objreal")
        second_motion = ET.Element("objreal")
        F7._pump_motion(first_motion, first)
        F7._pump_motion(second_motion, second)
        self.assertNotEqual(ET.tostring(first_motion), ET.tostring(second_motion))

    def test_materialize_archives_old_bytes_and_corrects_obstacle_seed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            family = Path(directory) / "F7"
            old_definition = family / "definitions/F7_PUMP_COARSE_V080_F090_O00_Def.xml"
            old_control = family / "controls/F7_PUMP_COARSE_V080_F090_O00_motion.csv"
            old_manifest = family / "case_manifests/F7_PUMP_COARSE_V080_F090_O00.json"
            old_definition.parent.mkdir(parents=True)
            old_control.parent.mkdir(parents=True)
            old_manifest.parent.mkdir(parents=True)
            old_definition.write_text("legacy-definition\n")
            old_control.write_text("legacy-control\n")
            old_manifest.write_text("{\"legacy\":true}\n")
            old_bytes = {path: path.read_bytes() for path in (old_definition, old_control, old_manifest)}
            result = F7.materialize(family)
            self.assertEqual(result["production_case_count"], 48)
            self.assertEqual(result["reference_case_count"], 6)
            archive = family / "archive/legacy_views"
            for source, relative in ((old_definition, "definitions/F7_PUMP_COARSE_V080_F090_O00_Def.xml"),
                                     (old_control, "controls/F7_PUMP_COARSE_V080_F090_O00_motion.csv"),
                                     (old_manifest, "case_manifests/F7_PUMP_COARSE_V080_F090_O00.json")):
                self.assertEqual((archive / relative).read_bytes(), old_bytes[source])
                self.assertEqual(source.read_bytes(), old_bytes[source])
            obstacle = family / "reference/definitions/F7_OBSTACLE_REFERENCE_BASE_COARSE_Def.xml"
            root = ET.parse(obstacle).getroot()
            fill = root.find("./casedef/geometry/commands/mainlist/fillbox")
            blade = root.findall("./casedef/geometry/commands/mainlist/drawbox")[1]
            self.assertIsNotNone(fill)
            self.assertLess(float(fill.get("x")), float(blade.find("./point").get("x")))
            self.assertEqual(len(list((family / "production/case_manifests").glob("*.json"))), 48)
            self.assertEqual(len(list((family / "reference/case_manifests").glob("*.json"))), 6)

    def test_reference_requests_are_bounded_and_provenanced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            family = Path(directory) / "F7"
            requests = F7.emit_requests(family, "reference", 4)
            self.assertEqual(len(requests), 6)
            for request_path in requests:
                request = json.loads(request_path.read_text())
                self.assertEqual(request["max_wall_seconds"], 300)
                self.assertEqual(request["cpu_threads"], 4)
                self.assertLessEqual(request["estimated_storage_bytes"], 256 * 1024 * 1024)
                self.assertTrue(request["input_files"])
                self.assertIn("{attempt_root}", " ".join(request["command"]))
                self.assertEqual(request["registry_kind"], "reference")
                self.assertIn("physical_parent_id", request)


if __name__ == "__main__":
    unittest.main()

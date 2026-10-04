#!/usr/bin/env python3
"""Regression fixture for the genuine semicolon FloatingInfo header shape."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCOPE = Path(__file__).resolve().parents[1]
WORKER = SCOPE / "workers" / "audit_frame0_omega_csv_alias_fix.py"
OLD_WORKER = (
    SCOPE.parent
    / "root_followup_059_stage1_frame0_omega_csv_decoder_audit_v1"
    / "workers"
    / "audit_frame0_omega_csv.py"
).resolve()


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UnitBearingAliasTest(unittest.TestCase):
    def test_actual_header_and_zero_positive_rows_decode(self) -> None:
        header = (
            "part;time [s];fvel.x [m/s];fvel.y [m/s];fvel.z [m/s];"
            "fomega.x [rad/s];fomega.y [rad/s];fomega.z [rad/s];"
            "center.x [m];center.y [m];center.z [m]"
        )
        rows = (
            "0;0.0;0;0;0;0;0;0;2.4;1.2;1.08\n"
            "1;0.05006182597552;0.000424042467;-0.000387029024;-0.397236562485;"
            "0.029855592235;0.037821214564;0.059935286653;2.4;1.2;1.08\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "FloatingInfo_mk60.synthetic.csv"
            path.write_text(header + "\n" + rows, encoding="utf-8")
            successor = load(WORKER, "f6_alias_successor_061")
            previous = load(OLD_WORKER, "f6_immutable_decoder_059")
            fixed = successor._floatinginfo_summary(path, 4)
            old = previous._floatinginfo_summary(path, 4)

        self.assertEqual(fixed["delimiter"], ";")
        self.assertEqual(fixed["normalized_headers"][2], "fvelxms")
        self.assertEqual(fixed["normalized_headers"][5], "fomegaxrads")
        self.assertEqual(fixed["normalized_headers"][8], "centerxm")
        self.assertEqual(fixed["status"], "ok")
        self.assertEqual(fixed["selected_rows"]["frame_zero"]["omega_rad_s"], [0.0, 0.0, 0.0])
        self.assertEqual(fixed["selected_rows"]["frame_zero"]["linear_velocity_m_per_s"], [0.0, 0.0, 0.0])
        self.assertEqual(fixed["selected_rows"]["first_positive_saved"]["omega_rad_s"][0], 0.029855592235)
        self.assertEqual(fixed["selected_rows"]["first_positive_saved"]["center_m"], [2.4, 1.2, 1.08])
        self.assertEqual(old["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()

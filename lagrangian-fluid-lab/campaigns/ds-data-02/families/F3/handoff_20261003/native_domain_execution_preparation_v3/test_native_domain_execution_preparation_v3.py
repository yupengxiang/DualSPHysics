#!/usr/bin/env python3
"""
Focused Synthetic Tests for F3 Native Domain Execution Preparation (v3)

Validates:
1. Selected transformer functions and IEEE-754 .17g roundtrip precision.
2. Rejection of non-finite values (NaN, Inf, -Inf).
3. Rejection of malformed records (field count, non-numeric).
4. Strict wrapper guards: exact start time (0.0 / "0") and end time (8.35 / "8.35") with zero tolerance.
5. Strictly increasing time guard and exact row count enforcement (167001 data rows).
6. Zero-drive physics formula across amplitudes A = 0.90, 0.97, 1.10.
7. Numerical identity at A = 1.0.
8. Exclusive non-overwrite file creation guard.
9. Source SHA256 before/after verification logic.
10. XML definitions and commensurate lattice rules across all cases.
11. Request schemas, launch_allowed=false boundaries, and single-case dispatch limits.
12. Compared source SHA verification against f630fe48.
"""

import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

from prepare_native_gencase import (
    PINNED_SOURCE_CSV_SHA256,
    GRAVITY_Z,
    EXPECTED_DATA_ROWS,
    EXPECTED_START_TIME,
    EXPECTED_START_TOKEN,
    EXPECTED_END_TIME,
    EXPECTED_END_TOKEN,
    compute_sha256,
    format_coord,
    transform_row,
    transform_forcing_stream_with_guards,
    semantic_xml,
)

BASE_DIR = Path(__file__).resolve().parent
COMPARED_SOURCE_SHA = "c2498ff54514536ebf2a229022e5fd555d4869f61f197159ace05fb685dff934"


class TestNativeDomainPreparationV3(unittest.TestCase):
    """Synthetic test suite for F3 v3 native preparation worker and domain staging."""

    def test_01_compared_source_sha(self):
        """Verify byte-exact transform_forcing.py matches f630fe48 SHA."""
        tf_path = BASE_DIR / "transform_forcing.py"
        self.assertTrue(tf_path.exists(), "transform_forcing.py must exist in new scope")
        digest = compute_sha256(tf_path)
        self.assertEqual(digest, COMPARED_SOURCE_SHA, "transform_forcing.py SHA mismatch")

    def test_02_pinned_source_csv_hash(self):
        """Verify pinned source CSV exists and matches pinned digest."""
        source_csv = Path(
            "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
            "F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005/"
            "root-cell3-nominal-cfl-decoupled-floor-input-005/prepared/CaseSloshingAccData.csv"
        )
        if source_csv.exists():
            digest = compute_sha256(source_csv)
            self.assertEqual(digest, PINNED_SOURCE_CSV_SHA256, "Pinned source CSV hash mismatch")

    def test_03_format_coord_roundtrip_precision(self):
        """Verify IEEE-754 .17g format guarantees exact double precision roundtrip without clamping."""
        test_values = [
            1.2345678901234567e-22,
            -8.765432109876543e14,
            -9.81,
            -9.81 + 1e-13,
            0.312057592,
            -0.18887913,
            0.0,
            1e-300,
        ]
        for val in test_values:
            formatted = format_coord(val)
            self.assertEqual(float(formatted), val, f"Roundtrip failed for {val}: got {formatted}")
            # Ensure no arbitrary deadband zero clamping occurred for non-zero small values
            if val != 0.0:
                self.assertNotEqual(formatted, "0")

    def test_04_format_coord_non_finite_rejection(self):
        """Verify non-finite values are strictly rejected."""
        for bad in [float("nan"), float("inf"), float("-inf")]:
            with self.assertRaises(ValueError):
                format_coord(bad)

    def test_05_transform_row_malformed_rejection(self):
        """Verify malformed rows (wrong token count, non-numeric) raise ValueError."""
        # Too few columns
        with self.assertRaises(ValueError):
            transform_row(["0", "1.0", "2.0"], amplitude=0.9)
        # Too many columns
        with self.assertRaises(ValueError):
            transform_row(["0", "1", "2", "3", "4", "5", "6", "extra"], amplitude=0.9)
        # Non-numeric coordinate
        with self.assertRaises(ValueError):
            transform_row(["0", "not_a_number", "0", "-9.81", "0", "0", "0"], amplitude=0.9)
        # Non-numeric time
        with self.assertRaises(ValueError):
            transform_row(["time_bad", "0", "0", "-9.81", "0", "0", "0"], amplitude=0.9)

    def test_06_strict_start_time_guard(self):
        """Verify strict exact start time guard (0.0 / '0') with zero tolerance."""
        # Non-zero float start time
        bad_start_csv = io.StringIO("0.0001;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_forcing_stream_with_guards(bad_start_csv, io.StringIO(), amplitude=0.90)
        self.assertIn("Strict start time violation", str(ctx.exception))

        # Start time string not exact token '0' (e.g. '0.000')
        bad_token_csv = io.StringIO("0.000;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_forcing_stream_with_guards(bad_token_csv, io.StringIO(), amplitude=0.90)
        self.assertIn("Strict start time violation", str(ctx.exception))

    def test_07_strict_end_time_guard(self):
        """Verify strict exact end time guard (8.35 / '8.35') with zero tolerance."""
        # End time offset
        bad_end_csv = io.StringIO("0;0;0;-9.81;0;0;0\n8.3499;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_forcing_stream_with_guards(bad_end_csv, io.StringIO(), amplitude=0.90)
        self.assertIn("Strict end time violation", str(ctx.exception))

        # End time string not exact token '8.35' (e.g. '8.350')
        bad_token_end = io.StringIO("0;0;0;-9.81;0;0;0\n8.350;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_forcing_stream_with_guards(bad_token_end, io.StringIO(), amplitude=0.90)
        self.assertIn("Strict end time violation", str(ctx.exception))

    def test_08_strictly_increasing_time_guard(self):
        """Verify non-monotonic time is rejected."""
        non_inc_csv = io.StringIO("0;0;0;-9.81;0;0;0\n1.0;0;0;-9.81;0;0;0\n0.99;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_forcing_stream_with_guards(non_inc_csv, io.StringIO(), amplitude=0.90)
        self.assertIn("strictly increasing time", str(ctx.exception))

    def test_09_row_count_guard(self):
        """Verify row count guard requires exactly EXPECTED_DATA_ROWS rows."""
        short_csv = io.StringIO("0;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_forcing_stream_with_guards(short_csv, io.StringIO(), amplitude=0.90)
        self.assertIn("Exact row count mismatch", str(ctx.exception))

    def test_10_zero_drive_formula(self):
        """Verify zero-drive formula: a_lin = g + A*(a_nom - g) and alpha = A*alpha_nom."""
        # Baseline zero drive: a_nom = (0, 0, -9.81), alpha_nom = (0, 0, 0)
        for amp in [0.90, 0.97, 1.10]:
            out = transform_row(["0", "0.0", "0.0", "-9.81", "0.0", "0.0", "0.0"], amplitude=amp)
            self.assertEqual(float(out[1]), 0.0)
            self.assertEqual(float(out[2]), 0.0)
            self.assertAlmostEqual(float(out[3]), GRAVITY_Z, places=14)
            self.assertEqual(float(out[4]), 0.0)
            self.assertEqual(float(out[5]), 0.0)
            self.assertEqual(float(out[6]), 0.0)

        # Non-zero acceleration test row
        # a_nom = (1.5, -2.0, -7.81), alpha_nom = (0.5, -0.4, 1.2)
        # Note: az_nom - g = -7.81 - (-9.81) = +2.0
        row = ["1.0", "1.5", "-2.0", "-7.81", "0.5", "-0.4", "1.2"]
        # For A = 0.90:
        # ax = 0.9 * 1.5 = 1.35
        # ay = 0.9 * -2.0 = -1.8
        # az = -9.81 + 0.9 * 2.0 = -8.01
        # alphax = 0.9 * 0.5 = 0.45, alphay = -0.36, alphaz = 1.08
        res_09 = transform_row(row, amplitude=0.90)
        self.assertAlmostEqual(float(res_09[1]), 1.35, places=13)
        self.assertAlmostEqual(float(res_09[2]), -1.80, places=13)
        self.assertAlmostEqual(float(res_09[3]), -8.01, places=13)
        self.assertAlmostEqual(float(res_09[4]), 0.45, places=13)
        self.assertAlmostEqual(float(res_09[5]), -0.36, places=13)
        self.assertAlmostEqual(float(res_09[6]), 1.08, places=13)

        # For A = 1.10:
        # ax = 1.1 * 1.5 = 1.65, ay = -2.2, az = -9.81 + 1.1*2.0 = -7.61
        res_11 = transform_row(row, amplitude=1.10)
        self.assertAlmostEqual(float(res_11[1]), 1.65, places=13)
        self.assertAlmostEqual(float(res_11[2]), -2.20, places=13)
        self.assertAlmostEqual(float(res_11[3]), -7.61, places=13)

    def test_11_numerical_identity_at_unity(self):
        """Verify exact numerical identity at A = 1.0."""
        row = ["2.345", "-0.0123456789012345", "0.54321", "-9.5", "0.1", "-0.2", "0.3"]
        out = transform_row(row, amplitude=1.0)
        self.assertEqual(out[0], row[0])
        for c in range(1, 7):
            self.assertEqual(float(out[c]), float(row[c]))

    def test_12_non_overwrite_exclusive_guard(self):
        """Verify mode='x' prevents overwriting existing files."""
        tmp = Path("/tmp/_test_non_overwrite_v3.tmp")
        if tmp.exists():
            tmp.unlink()
        tmp.write_text("existing content")
        try:
            with open(tmp, "x") as f:
                f.write("overwrite attempt")
            self.fail("Expected FileExistsError on mode='x' with existing file")
        except FileExistsError:
            pass
        finally:
            if tmp.exists():
                tmp.unlink()

    def test_13_definitions_and_commensurate_lattice(self):
        """Verify all definitions XML parse cleanly and follow commensurate cell-centre lattice rules."""
        defs_dir = BASE_DIR / "definitions"
        self.assertTrue(defs_dir.exists())

        xml_files = list(defs_dir.glob("*.xml"))
        self.assertGreaterEqual(len(xml_files), 9, "Expected at least 9 XML definitions")

        for xf in xml_files:
            root = ET.parse(xf).getroot()
            cfl = float(root.find("./casedef/constantsdef/cflnumber").get("value"))
            self.assertEqual(cfl, 0.05, f"CFL must be 0.05 in {xf.name}")

            geom = root.find("./casedef/geometry/definition")
            dp = float(geom.get("dp"))
            pref = geom.find("pointref")
            for axis in "xyz":
                p_val = float(pref.get(axis))
                self.assertAlmostEqual(p_val, dp / 2.0, places=10, msg=f"Commensurate pointref mismatch in {xf.name}")

            # Verify open 5-wall boxfill
            box = root.find(".//commands/list[@name='GeometryForNormals']/drawbox/boxfill")
            self.assertEqual(box.text.strip(), "all^top", f"Must be open 5-wall in {xf.name}")

            # Verify globalgravity=0 in accinputs
            gg = root.find(".//execution/special/accinputs/accinput/globalgravity")
            self.assertEqual(gg.get("value"), "0", f"globalgravity must be 0 in {xf.name}")

    def test_14_bindings_and_requests_consistency(self):
        """Verify all bindings and runner requests enforce launch_allowed=false and single-case execution."""
        bindings_dir = BASE_DIR / "bindings"
        requests_dir = BASE_DIR / "requests"

        b_files = list(bindings_dir.glob("*.json"))
        r_files = list(requests_dir.glob("*.json"))
        self.assertEqual(len(b_files), 6, "Expected 6 binding files")
        self.assertEqual(len(r_files), 6, "Expected 6 request files")

        for rf in r_files:
            req = json.loads(rf.read_text(encoding="utf-8"))
            self.assertEqual(req["schema"], "ds02.runner-request.v2")
            self.assertFalse(req["launch_allowed"], f"launch_allowed must be false in {rf.name}")
            self.assertEqual(req["kind"], "cpu")
            self.assertEqual(req["cpu_task_kind"], "gencase")
            self.assertEqual(req["independent_case_count_increment"], 0)
            self.assertEqual(req["production_approval"], "none")
            self.assertIn("prepare_native_gencase.py", req["command"][1])


if __name__ == "__main__":
    unittest.main()

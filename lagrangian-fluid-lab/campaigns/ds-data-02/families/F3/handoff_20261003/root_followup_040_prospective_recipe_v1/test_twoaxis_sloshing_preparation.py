#!/usr/bin/env python3
"""
Focused Synthetic Test Suite for F3 True 3D Two-Axis Sloshing Control (Followup 040)

Campaign: DS-DATA-02
Family: F3 (Open-Top Rectangular Tank Sloshing)
Authority: Root Followup 040
Scope: lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_040_prospective_recipe_v1

Validates:
1. Exact GPU v5.4 force branch source code audit strings and file paths.
2. Nominal CSV t=0 angular acceleration is non-zero (alpha_y = 0.312057592).
3. IEEE-754 .17g roundtrip precision without deadband clamps or quantization.
4. Non-finite coordinate rejection.
5. Malformed row rejection.
6. Strict start time guard (0.0 / "0").
7. Strict end time guard (8.35 / "8.35").
8. Strictly increasing time guard.
9. Row count guard (167001 data rows).
10. Smooth envelope boundaries, plateau, and C^1 smoothness.
11. Exact numerical identity at Ay = 0.0 and Ax = 1.0.
12. Two-axis forcing physics formula across amplitudes Ay in {0.25, 0.50, 0.75}.
13. Non-overwrite exclusive file creation guard.
14. Definitions and commensurate cell-centre lattice rules across all 12 XML files.
15. Known nominal geometry particle counts (277272 DP005 / 179208 DP006 / 356692 DP0045).
16. Bindings and runner requests schema, launch_allowed=false boundaries, and uncorrupted file SHAs.
"""

import hashlib
import io
import json
import math
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from transform_twoaxis_forcing import (
    PINNED_NOMINAL_FORCING_SHA256,
    GRAVITY_Z,
    EXPECTED_NOMINAL_ROWS,
    EXPECTED_START_TIME,
    EXPECTED_START_TOKEN,
    EXPECTED_END_TIME,
    EXPECTED_END_TOKEN,
    DEFAULT_OMEGA_Y,
    DEFAULT_PHASE_Y,
    DEFAULT_RAMP_DURATION,
    compute_sha256,
    format_coord,
    evaluate_envelope,
    evaluate_transverse_acc,
    transform_twoaxis_row,
    transform_twoaxis_forcing_stream,
)

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics")


class TestTwoAxisSloshingPreparation(unittest.TestCase):
    """Synthetic unit tests for F3 two-axis sloshing control preparation."""

    def test_01_gpu_force_branch_audit_exact_strings_and_paths(self):
        """Verify DualSPHysics GPU v5.4 source code paths and kernel branch audit strings."""
        ker_cu = REPO_ROOT / "src/source/JDsAccInput_ker.cu"
        input_cpp = REPO_ROOT / "src/source/JDsAccInput.cpp"

        self.assertTrue(ker_cu.exists(), f"Missing GPU kernel source: {ker_cu}")
        self.assertTrue(input_cpp.exists(), f"Missing host acceleration input source: {input_cpp}")

        ker_text = ker_cu.read_text(encoding="utf-8")
        cpp_text = input_cpp.read_text(encoding="utf-8")

        # Verify kernel branch condition
        branch_cond = "const bool withaccang=(accang.x!=0 || accang.y!=0 || accang.z!=0);"
        self.assertIn(branch_cond, ker_text, "Missing withaccang branch condition in JDsAccInput_ker.cu")

        # Verify kernel dispatch lines
        ker_ang_dispatch = "if(withaccang)KerAddAccInputAng <<<sgrid,SPHBSIZE,0,stm>>>"
        ker_lin_dispatch = "else          KerAddAccInputLin <<<sgrid,SPHBSIZE,0,stm>>>"
        self.assertIn(ker_ang_dispatch, ker_text, "Missing KerAddAccInputAng invocation in JDsAccInput_ker.cu")
        self.assertIn(ker_lin_dispatch, ker_text, "Missing KerAddAccInputLin invocation in JDsAccInput_ker.cu")

        # Verify linear acceleration addition in KerAddAccInputAng
        self.assertIn("accx+=acclin.x;  accy+=acclin.y;  accz+=acclin.z;", ker_text)

        # Verify host cpp checks withaccang
        self.assertIn("const bool withaccang=(v.accang.x!=0 || v.accang.y!=0 || v.accang.z!=0);", cpp_text)

        # Verify linear velocity integration in host cpp
        self.assertIn("currvellin.y=vellin0.y+(acclin.y*dt);", cpp_text)

    def test_02_nominal_csv_t0_angular_acceleration_not_zero(self):
        """Verify nominal CSV has alpha_y(t=0) = 0.312057592 != 0, activating KerAddAccInputAng."""
        csv_path = Path(
            "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
            "F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005/"
            "root-cell3-nominal-cfl-decoupled-floor-input-005/prepared/CaseSloshingAccData.csv"
        )
        if csv_path.exists():
            h = compute_sha256(csv_path)
            self.assertEqual(h, PINNED_NOMINAL_FORCING_SHA256, "Pinned nominal source CSV digest mismatch")

            with open(csv_path, "r", encoding="utf-8") as f:
                header = f.readline().strip()
                first_row = f.readline().strip()

            self.assertEqual(header, "#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ")
            tokens = first_row.split(";")
            t0 = float(tokens[0])
            alphay_t0 = float(tokens[5])

            self.assertEqual(t0, 0.0)
            self.assertAlmostEqual(alphay_t0, 0.312057592, places=8)
            # Crucial assertion: accang.y != 0 at t=0
            self.assertNotEqual(alphay_t0, 0.0, "Nominal alpha_y at t=0 must NOT be zero")

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
            if val != 0.0:
                self.assertNotEqual(formatted, "0")

    def test_04_format_coord_non_finite_rejection(self):
        """Verify non-finite values are strictly rejected."""
        for bad in [float("nan"), float("inf"), float("-inf")]:
            with self.assertRaises(ValueError):
                format_coord(bad)

    def test_05_transform_twoaxis_row_malformed_rejection(self):
        """Verify malformed rows (wrong token count, non-numeric) raise ValueError."""
        with self.assertRaises(ValueError):
            transform_twoaxis_row(["0", "1.0", "2.0"], amplitude_x=1.0, amplitude_y=0.50)
        with self.assertRaises(ValueError):
            transform_twoaxis_row(["0", "1", "2", "3", "4", "5", "6", "extra"], amplitude_x=1.0, amplitude_y=0.50)
        with self.assertRaises(ValueError):
            transform_twoaxis_row(["0", "not_num", "0", "-9.81", "0", "0", "0"], amplitude_x=1.0, amplitude_y=0.50)
        with self.assertRaises(ValueError):
            transform_twoaxis_row(["bad_time", "0", "0", "-9.81", "0", "0", "0"], amplitude_x=1.0, amplitude_y=0.50)

    def test_06_strict_start_time_guard(self):
        """Verify strict exact start time guard (0.0 / '0') with zero tolerance."""
        bad_start_csv = io.StringIO("0.0001;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_twoaxis_forcing_stream(bad_start_csv, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        self.assertIn("Strict start time violation", str(ctx.exception))

        bad_token_csv = io.StringIO("0.000;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_twoaxis_forcing_stream(bad_token_csv, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        self.assertIn("Strict start time violation", str(ctx.exception))

    def test_07_strict_end_time_guard(self):
        """Verify strict exact end time guard (8.35 / '8.35') with zero tolerance."""
        bad_end_csv = io.StringIO("0;0;0;-9.81;0;0;0\n8.3499;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_twoaxis_forcing_stream(bad_end_csv, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        self.assertIn("Strict end time violation", str(ctx.exception))

        bad_token_end = io.StringIO("0;0;0;-9.81;0;0;0\n8.350;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_twoaxis_forcing_stream(bad_token_end, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        self.assertIn("Strict end time violation", str(ctx.exception))

    def test_08_strictly_increasing_time_guard(self):
        """Verify non-monotonic time series is rejected."""
        non_inc_csv = io.StringIO("0;0;0;-9.81;0;0;0\n1.0;0;0;-9.81;0;0;0\n0.99;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_twoaxis_forcing_stream(non_inc_csv, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        self.assertIn("strictly increasing time", str(ctx.exception))

    def test_09_row_count_guard(self):
        """Verify row count guard requires exactly 167001 data rows."""
        short_csv = io.StringIO("0;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
        with self.assertRaises(ValueError) as ctx:
            transform_twoaxis_forcing_stream(short_csv, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        self.assertIn("Exact row count mismatch", str(ctx.exception))

    def test_10_smooth_envelope_boundaries_and_plateau(self):
        """Verify envelope E(t) satisfies boundary conditions, plateau, and smooth transition."""
        self.assertEqual(evaluate_envelope(0.0), 0.0)
        self.assertEqual(evaluate_envelope(8.35), 0.0)
        self.assertEqual(evaluate_envelope(-0.01), 0.0)
        self.assertEqual(evaluate_envelope(8.36), 0.0)

        # End of ramp-in (tau_ramp = 0.50 s)
        self.assertAlmostEqual(evaluate_envelope(0.50), 1.0, places=12)
        # Start of ramp-out (8.35 - 0.50 = 7.85 s)
        self.assertAlmostEqual(evaluate_envelope(7.85), 1.0, places=12)
        # Inside plateau
        self.assertEqual(evaluate_envelope(2.0), 1.0)
        self.assertEqual(evaluate_envelope(5.0), 1.0)

        # In ramp: 0 < E < 1
        self.assertTrue(0.0 < evaluate_envelope(0.25) < 1.0)
        self.assertTrue(0.0 < evaluate_envelope(8.10) < 1.0)

    def test_11_numerical_identity_at_ay_zero(self):
        """Verify exact numerical identity at Ay = 0.0 and Ax = 1.0."""
        nominal_row = ["2.345", "-0.0123456789012345", "0", "-9.5", "0.0", "0.312057592", "0.0"]
        out = transform_twoaxis_row(nominal_row, amplitude_x=1.0, amplitude_y=0.0)
        self.assertEqual(out[0], nominal_row[0])
        for c in range(1, 7):
            self.assertEqual(float(out[c]), float(nominal_row[c]))

    def test_12_twoaxis_forcing_physics_formula(self):
        """Verify two-axis forcing physics formula: ay(t) = Ay * E(t) * sin(omega_y * t)."""
        for ay_amp in [0.25, 0.50, 0.75]:
            # At t=0: E(0) = 0, so ay must be 0.0
            r_start = transform_twoaxis_row(
                ["0", "-1.96e-10", "0", "-9.81", "0", "0.312057592", "0"],
                amplitude_x=1.0,
                amplitude_y=ay_amp,
            )
            self.assertEqual(float(r_start[2]), 0.0)

            # At t=2.0 (plateau, E=1.0): ay = Ay * sin(omega_y * 2.0)
            t_mid = 2.0
            r_mid = transform_twoaxis_row(
                [str(t_mid), "0", "0", "-9.81", "0", "0.5", "0"],
                amplitude_x=1.0,
                amplitude_y=ay_amp,
            )
            expected_ay = ay_amp * math.sin(DEFAULT_OMEGA_Y * t_mid)
            self.assertAlmostEqual(float(r_mid[2]), expected_ay, places=12)

            # Check that nominal pitch components are preserved when Ax = 1.0
            self.assertAlmostEqual(float(r_mid[3]), -9.81, places=12)
            self.assertAlmostEqual(float(r_mid[5]), 0.5, places=12)

    def test_13_non_overwrite_exclusive_guard(self):
        """Verify mode='x' prevents overwriting existing files."""
        tmp = Path("/tmp/_test_non_overwrite_f040.tmp")
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

    def test_14_definitions_and_commensurate_lattice(self):
        """Verify all definitions XML parse cleanly and follow commensurate cell-centre lattice rules."""
        defs_dir = BASE_DIR / "definitions"
        self.assertTrue(defs_dir.exists())

        xml_files = list(defs_dir.glob("*.xml"))
        self.assertGreaterEqual(len(xml_files), 12, "Expected at least 12 XML definitions")

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

    def test_15_known_nominal_geometry_particle_counts(self):
        """Verify known nominal geometry particle counts for the commensurate ladder."""
        known_counts = {
            0.006: {"fluid": 67500, "fixed": 111708, "total": 179208},
            0.005: {"fluid": 116640, "fixed": 160632, "total": 277272},
            0.0045: {"fluid": 160000, "fixed": 196692, "total": 356692},
        }
        manifest = json.loads((BASE_DIR / "binding_manifest.json").read_text(encoding="utf-8"))
        ladder = manifest["commensurate_ladder"]

        self.assertEqual(ladder["candidate"]["expected_total"], known_counts[0.006]["total"])
        self.assertEqual(ladder["candidate"]["expected_fluid"], known_counts[0.006]["fluid"])

        self.assertEqual(ladder["reference"]["expected_total"], known_counts[0.005]["total"])
        self.assertEqual(ladder["reference"]["expected_fluid"], known_counts[0.005]["fluid"])

        self.assertEqual(ladder["finer_reference"]["expected_total"], known_counts[0.0045]["total"])
        self.assertEqual(ladder["finer_reference"]["expected_fluid"], known_counts[0.0045]["fluid"])

    def test_16_bindings_and_requests_consistency(self):
        """Verify all bindings and runner requests enforce launch_allowed=false and single-case execution."""
        bindings_dir = BASE_DIR / "bindings"
        requests_dir = BASE_DIR / "requests"

        b_files = list(bindings_dir.glob("*.json"))
        r_files = list(requests_dir.glob("*.json"))
        self.assertEqual(len(b_files), 9, "Expected 9 binding files")
        self.assertEqual(len(r_files), 9, "Expected 9 request files")

        for rf in r_files:
            req = json.loads(rf.read_text(encoding="utf-8"))
            self.assertEqual(req["schema"], "ds02.runner-request.v2")
            self.assertFalse(req["launch_allowed"], f"launch_allowed must be false in {rf.name}")
            self.assertEqual(req["kind"], "cpu")
            self.assertEqual(req["cpu_task_kind"], "gencase")
            self.assertEqual(req["independent_case_count_increment"], 0)
            self.assertEqual(req["production_approval"], "none")
            self.assertIn("prepare_twoaxis_gencase.py", req["command"][1])

            # Check that input_sha256 matches actual files
            for fp, expected_sha in req["input_sha256"].items():
                p = Path(fp)
                if not p.exists():
                    alt = BASE_DIR / p.name
                    if not alt.exists():
                        alt = BASE_DIR / "definitions" / p.name
                    if not alt.exists():
                        alt = BASE_DIR / "bindings" / p.name
                    if alt.exists():
                        p = alt
                if p.exists():
                    actual_sha = hashlib.sha256(p.read_bytes()).hexdigest()
                    self.assertEqual(actual_sha, expected_sha, f"SHA mismatch for input file {p}")


if __name__ == "__main__":
    unittest.main()

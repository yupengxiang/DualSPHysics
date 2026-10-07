#!/usr/bin/env python3
"""Comprehensive unit test suite for Family F6 Stage 8 production scripts.

Tests:
1. Quaternion conversion and motion CSV parsing in ds_data02_f6_stage8_convert.
2. Static event definitions and label configs compliance with ds_data02_native_labels.
3. Q-I integrity physics and bound auditing in ds_data02_f6_stage8_audit.
4. Model-free P5 evaluation standards and failure mode detection in ds_data02_f6_evaluator.
5. End-to-end synthetic trajectory conversion, label materialization, and evaluation.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_f6_stage8_convert import (
    quaternion_from_euler_deg,
    parse_floating_motion_csv,
)
from ds_data02_f6_stage8_audit import (
    audit_f6_trajectory_physics,
    TANK_BOUNDS,
)
from ds_data02_f6_evaluator import (
    evaluate_f6,
    quaternion_distance_rad,
)
from ds_data02_native_labels import validate_config, materialize


def create_synthetic_f6_trajectory(
    path: Path,
    nframes: int = 5,
    nparticles: int = 100,
    mechanism: str = "simple_free_response",
    *,
    inject_nan: bool = False,
    inject_loss: bool = False,
    inject_oob_fluid: bool = False,
    inject_oob_body: bool = False,
    inject_contact: bool = False,
    inject_quat_error: bool = False,
) -> Path:
    """Create a synthetically conforming F6 trajectory.h5 for testing."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    dt = 0.05
    times = np.arange(nframes) * dt
    pids = np.arange(nparticles, dtype=np.uint32)
    zones = np.zeros(nparticles, dtype=np.int16)

    # 20 fixed (0), 20 moving/floating (2), 60 fluid (3)
    types = np.zeros((nframes, nparticles), dtype=np.int8)
    types[:, :20] = 0
    types[:, 20:40] = 2
    types[:, 40:] = 3

    mks = np.zeros((nframes, nparticles), dtype=np.int16)
    mks[:, :20] = 1
    mks[:, 20:40] = 60
    mks[:, 40:] = 30

    masses = np.ones((nframes, nparticles), dtype=np.float32) * 0.064
    valid = np.ones((nframes, nparticles), dtype=bool)

    if inject_loss and nframes > 1:
        valid[-1, 40:45] = False  # Lose 5 fluid particles

    positions = np.zeros((nframes, nparticles, 3), dtype=np.float32)
    velocities = np.zeros((nframes, nparticles, 3), dtype=np.float32)
    densities = np.ones((nframes, nparticles), dtype=np.float32) * 1000.0
    pressures = np.zeros((nframes, nparticles), dtype=np.float32)

    # Place particles safely inside tank [0, 4.0] x [0, 2.0] x [0, 1.4]
    for i in range(nparticles):
        positions[:, i, 0] = 0.5 + (i % 10) * 0.3
        positions[:, i, 1] = 0.3 + ((i // 10) % 5) * 0.3
        positions[:, i, 2] = 0.1 + (i // 50) * 0.3

    if inject_oob_fluid and nframes > 1:
        positions[-1, 50, 2] = 1.60  # Escapes above open top (1.4m)

    if inject_nan and nframes > 1:
        positions[-1, 45, 0] = np.nan

    # Rigid body state
    rb_pos = np.zeros((nframes, 3), dtype=np.float64)
    rb_pos[:, 0] = 2.0
    rb_pos[:, 1] = 1.0
    rb_pos[:, 2] = 0.72 + 0.05 * np.sin(times)

    if inject_oob_body:
        rb_pos[-1, 0] = 5.5  # Outside tank length 4.0m

    rb_lin_vel = np.zeros((nframes, 3), dtype=np.float64)
    rb_lin_vel[:, 2] = 0.05 * np.cos(times)

    rb_ang_vel = np.zeros((nframes, 3), dtype=np.float64)
    rb_euler_deg = np.zeros((nframes, 3), dtype=np.float64)
    rb_euler_deg[:, 1] = 2.0 * np.sin(times)  # Pitch oscillation
    rb_euler_rad = np.radians(rb_euler_deg)

    rb_quats = np.zeros((nframes, 4), dtype=np.float64)
    for ti in range(nframes):
        rb_quats[ti] = quaternion_from_euler_deg(rb_euler_deg[ti, 0], rb_euler_deg[ti, 1], rb_euler_deg[ti, 2])

    if inject_quat_error:
        rb_quats[-1, :] = [2.0, 2.0, 2.0, 2.0]  # Non-unit norm

    rb_displacements = np.zeros((nframes, 3), dtype=np.float64)
    rb_displacements[:, 2] = rb_pos[:, 2] - rb_pos[0, 2]

    rb_lin_acc = np.zeros((nframes, 3), dtype=np.float64)
    rb_ang_acc = np.zeros((nframes, 3), dtype=np.float64)
    rb_force = np.zeros((nframes, 3), dtype=np.float64)
    rb_torque = np.zeros((nframes, 3), dtype=np.float64)
    rb_contact = np.zeros(nframes, dtype=bool)

    if inject_contact:
        rb_contact[-1] = True

    with h5py.File(path, "w") as h5:
        h5.attrs["schema"] = "ds-data-02.hdf5-schema.v1"
        h5.attrs["family_id"] = "F6"
        h5.attrs["case_id"] = f"F6_SYNTHETIC_{mechanism.upper()}"
        h5.attrs["time_units"] = "s"
        h5.attrs["position_units"] = "m"
        h5.attrs["velocity_units"] = "m/s"
        h5.attrs["density_units"] = "kg/m^3"
        h5.attrs["mass_units"] = "kg"
        h5.attrs["pressure_units"] = "Pa"
        h5.attrs["coordinate_frame"] = "world_tank_and_tank_attached_observations" if "wave" in mechanism else "tank_attached_inertial"
        h5.attrs["geometry_sha256"] = "0" * 64
        h5.attrs["control_sha256"] = "1" * 64
        h5.attrs["conversion_complete"] = True
        h5.attrs["conversion_complete_frames"] = nframes
        h5.attrs["floating_massbody_kg"] = 72.0
        h5.attrs["floating_masspart_kg"] = 0.064
        h5.attrs["floating_inertia_kg_m2"] = "[[2.38, 0, 0], [0, 3.21, 0], [0, 0, 4.06]]"
        h5.attrs["orientation_semantics"] = "FloatingInfo roll/pitch/yaw Euler deg and intrinsic XYZ unit quaternion [x,y,z,w]"

        h5.create_dataset("time", data=times, dtype="f8")
        h5.create_dataset("particle_id", data=pids, dtype="u4")
        h5.create_dataset("particle_zone", data=zones, dtype="i2")
        h5.create_dataset("valid", data=valid, dtype="bool")
        h5.create_dataset("type", data=types, dtype="i1")
        h5.create_dataset("mk", data=mks, dtype="i2")
        h5.create_dataset("position", data=positions, dtype="f4")
        h5.create_dataset("velocity", data=velocities, dtype="f4")
        h5.create_dataset("density", data=densities, dtype="f4")
        h5.create_dataset("mass", data=masses, dtype="f4")
        h5.create_dataset("pressure", data=pressures, dtype="f4")

        h5.create_dataset("initial_type", data=types[0], dtype="i1")
        h5.create_dataset("initial_mk", data=mks[0], dtype="i2")
        h5.create_dataset("initial_mass", data=masses[0], dtype="f4")

        rb = h5.create_group("rigid_body")
        rb.attrs["schema"] = "ds-data-02.f6.rigid-body-state.v1"
        rb.attrs["body_name"] = "floating_box"
        rb.attrs["mass_kg"] = 72.0
        rb.attrs["quaternion_convention"] = "xyzw"

        rb.create_dataset("position", data=rb_pos, dtype="f8")
        rb.create_dataset("linear_velocity", data=rb_lin_vel, dtype="f8")
        rb.create_dataset("angular_velocity", data=rb_ang_vel, dtype="f8")
        rb.create_dataset("orientation_quaternion", data=rb_quats, dtype="f8")
        rb.create_dataset("body_quaternion_xyzw", data=rb_quats, dtype="f8")
        rb.create_dataset("orientation_euler_deg", data=rb_euler_deg, dtype="f8")
        rb.create_dataset("orientation_euler_rad", data=rb_euler_rad, dtype="f8")
        rb.create_dataset("surge_sway_heave_m", data=rb_displacements, dtype="f8")
        rb.create_dataset("linear_acceleration", data=rb_lin_acc, dtype="f8")
        rb.create_dataset("angular_acceleration", data=rb_ang_acc, dtype="f8")
        rb.create_dataset("fluid_force", data=rb_force, dtype="f8")
        rb.create_dataset("fluid_torque", data=rb_torque, dtype="f8")
        rb.create_dataset("contact_event_flag", data=rb_contact, dtype="bool")

        # Softlink rigid_state
        rs = h5.create_group("rigid_state")
        for k in rb.keys():
            rs[k] = h5py.SoftLink(f"/rigid_body/{k}")

    return path


class TestF6Stage8(unittest.TestCase):
    """Test suite for F6 conversion, audit, label configs, and evaluator."""

    def test_quaternion_conversion(self):
        """Test conversion from Euler angles (roll, pitch, yaw) to unit quaternion."""
        # 1. Identity rotation
        q0 = quaternion_from_euler_deg(0.0, 0.0, 0.0)
        self.assertAlmostEqual(q0[0], 0.0, places=6)
        self.assertAlmostEqual(q0[1], 0.0, places=6)
        self.assertAlmostEqual(q0[2], 0.0, places=6)
        self.assertAlmostEqual(q0[3], 1.0, places=6)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in q0)), 1.0, places=6)

        # 2. 90 degree pitch
        qp = quaternion_from_euler_deg(0.0, 90.0, 0.0)
        norm_p = math.sqrt(sum(x * x for x in qp))
        self.assertAlmostEqual(norm_p, 1.0, places=6)
        self.assertAlmostEqual(qp[1], 1.0 / math.sqrt(2.0), places=6)
        self.assertAlmostEqual(qp[3], 1.0 / math.sqrt(2.0), places=6)

        # 3. Arbitrary angles unit norm check
        for r, p, y in [(12.5, -5.2, 3.1), (-25.0, 15.0, -10.0), (0.0, 45.0, 0.0)]:
            q = quaternion_from_euler_deg(r, p, y)
            self.assertAlmostEqual(math.sqrt(sum(x * x for x in q)), 1.0, places=6)

    def test_parse_floating_motion_csv(self):
        """Test parsing FloatingMotion and Floating_Actual CSV formats."""
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "FloatingMotion_test.csv"
            csv_content = (
                "time [s];fvel.x [m/s];fvel.y [m/s];fvel.z [m/s];fomega.x [rad/s];fomega.y [rad/s];fomega.z [rad/s];"
                "center.x [m];center.y [m];center.z [m];surge [m];sway [m];heave [m];roll [deg];pitch [deg];yaw [deg];"
                "face.x [m/s^2];face.y [m/s^2];face.z [m/s^2];faceomega.x [rad/s^2];faceomega.y [rad/s^2];faceomega.z [rad/s^2];"
                "fluidforcelin.x [N];fluidforcelin.y [N];fluidforcelin.z [N];fluidforceang.x [Nm];fluidforceang.y [Nm];fluidforceang.z [Nm]\n"
                "0.0;0.0;0.0;0.0;0.0;0.0;0.0;2.0;1.0;0.72;0.0;0.0;0.0;0.0;5.0;0.0;0.0;0.0;0.0;0.0;0.0;0.0;0.0;0.0;700.0;0.0;10.0;0.0\n"
                "0.05;0.0;0.0;-0.01;0.0;0.05;0.0;2.0;1.0;0.719;0.0;0.0;-0.001;0.0;4.8;0.0;0.0;0.0;-0.2;0.0;-0.1;0.0;0.0;0.0;720.0;0.0;8.0;0.0\n"
            )
            csv_path.write_text(csv_content, encoding="utf-8")
            data = parse_floating_motion_csv(csv_path)

            self.assertEqual(len(data["time"]), 2)
            self.assertEqual(data["position"].shape, (2, 3))
            self.assertEqual(data["orientation_quaternion"].shape, (2, 4))
            self.assertEqual(data["body_quaternion_xyzw"].shape, (2, 4))
            self.assertAlmostEqual(data["position"][0, 2], 0.72)
            self.assertAlmostEqual(data["orientation_euler_deg"][0, 1], 5.0)

            # Quaternions must be unit normalized
            for qi in range(2):
                qnorm = np.linalg.norm(data["orientation_quaternion"][qi])
                self.assertAlmostEqual(qnorm, 1.0, places=6)

    def test_static_event_configs_validity(self):
        """Test that F6 static event configurations are fully valid according to ds_data02_native_labels."""
        cfg_simple = json.loads((REPO / "campaigns/ds-data-02/families/F6/labels/simple_free_response_event_config.json").read_text(encoding="utf-8"))
        validate_config(cfg_simple)

        cfg_wave = json.loads((REPO / "campaigns/ds-data-02/families/F6/labels/wave_no_contact_event_config.json").read_text(encoding="utf-8"))
        validate_config(cfg_wave)

        # Also verify event_definitions.json parses cleanly
        ev_defs = json.loads((REPO / "campaigns/ds-data-02/families/F6/event_definitions.json").read_text(encoding="utf-8"))
        self.assertEqual(ev_defs["family_id"], "F6")
        self.assertEqual(len(ev_defs["mechanisms"]), 2)

    def test_audit_physics_on_conforming_trajectory(self):
        """Test that Q-I physics audit passes on a valid conforming trajectory."""
        with tempfile.TemporaryDirectory() as td:
            traj_path = Path(td) / "trajectory.h5"
            create_synthetic_f6_trajectory(traj_path, nframes=4, nparticles=80)
            res = audit_f6_trajectory_physics(traj_path)

            self.assertEqual(res["status"], "pass")
            self.assertEqual(len(res["failures"]), 0)
            self.assertTrue(res["checks"]["global_nan_inf_free"])
            self.assertEqual(res["checks"]["mass_conservation"]["status"], "pass")
            self.assertEqual(res["checks"]["spatial_bounds"]["status"], "pass")
            self.assertEqual(res["checks"]["rigid_body_audit"]["status"], "pass")

    def test_audit_physics_detects_failures(self):
        """Test that Q-I physics audit catches NaN, particle loss, boundary exit, and contact violations."""
        with tempfile.TemporaryDirectory() as td:
            # 1. NaN injection
            p_nan = Path(td) / "traj_nan.h5"
            create_synthetic_f6_trajectory(p_nan, inject_nan=True)
            res_nan = audit_f6_trajectory_physics(p_nan)
            self.assertEqual(res_nan["status"], "fail")
            self.assertFalse(res_nan["checks"]["global_nan_inf_free"])

            # 2. Particle loss injection
            p_loss = Path(td) / "traj_loss.h5"
            create_synthetic_f6_trajectory(p_loss, inject_loss=True)
            res_loss = audit_f6_trajectory_physics(p_loss)
            self.assertEqual(res_loss["status"], "fail")
            self.assertEqual(res_loss["checks"]["mass_conservation"]["particle_loss"], 5)

            # 3. Open top containment exit injection
            p_oob = Path(td) / "traj_oob.h5"
            create_synthetic_f6_trajectory(p_oob, inject_oob_fluid=True)
            res_oob = audit_f6_trajectory_physics(p_oob)
            self.assertEqual(res_oob["status"], "fail")
            self.assertGreater(res_oob["checks"]["spatial_bounds"]["open_top_violations"], 0)

            # 4. Rigid body out of bounds
            p_rb_oob = Path(td) / "traj_rb_oob.h5"
            create_synthetic_f6_trajectory(p_rb_oob, inject_oob_body=True)
            res_rb_oob = audit_f6_trajectory_physics(p_rb_oob)
            self.assertEqual(res_rb_oob["status"], "fail")
            self.assertIn("rigid_body_translation_out_of_bounds", res_rb_oob["failures"])

            # 5. Contact violation
            p_contact = Path(td) / "traj_contact.h5"
            create_synthetic_f6_trajectory(p_contact, inject_contact=True)
            res_contact = audit_f6_trajectory_physics(p_contact)
            self.assertEqual(res_contact["status"], "fail")
            self.assertEqual(res_contact["checks"]["rigid_body_audit"]["contact_events"], 1)

    def test_evaluator_self_comparison(self):
        """Test P5 exact self-comparison: reference vs reference must yield valid=True, 0 errors, no failures."""
        with tempfile.TemporaryDirectory() as td:
            traj_path = Path(td) / "trajectory.h5"
            create_synthetic_f6_trajectory(traj_path, nframes=4, nparticles=80)
            res = evaluate_f6(traj_path, traj_path, mechanism="simple_free_response")

            self.assertTrue(res["valid"])
            self.assertEqual(len(res["failures"]), 0)
            self.assertEqual(res["mean_position_error"], 0.0)
            self.assertEqual(res["mean_velocity_error"], 0.0)
            self.assertEqual(res["rigid_body_evaluation"]["mean_position_error_relative"], 0.0)
            self.assertEqual(res["rigid_body_evaluation"]["mean_linear_velocity_error_relative"], 0.0)
            self.assertEqual(res["rigid_body_evaluation"]["mean_quaternion_error_rad"], 0.0)
            self.assertEqual(res["finite_wall_crossing_count"], 0)
            self.assertEqual(res["open_top_exit_count"], 0)
            self.assertFalse(res["model_invoked"])

    def test_evaluator_detects_time_mismatch(self):
        """Test that evaluator detects saved time mismatch."""
        with tempfile.TemporaryDirectory() as td:
            ref_path = Path(td) / "ref.h5"
            cand_path = Path(td) / "cand.h5"
            create_synthetic_f6_trajectory(ref_path, nframes=4)
            create_synthetic_f6_trajectory(cand_path, nframes=5)

            res = evaluate_f6(ref_path, cand_path)
            self.assertFalse(res["valid"])
            self.assertIn("saved_time_mismatch", res["failures"])

    def test_evaluator_detects_rigid_violations(self):
        """Test that evaluator detects candidate rigid body violations (contact and boundary escape)."""
        with tempfile.TemporaryDirectory() as td:
            ref_path = Path(td) / "ref.h5"
            cand_contact = Path(td) / "cand_contact.h5"
            create_synthetic_f6_trajectory(ref_path, nframes=4)
            create_synthetic_f6_trajectory(cand_contact, nframes=4, inject_contact=True)

            res_c = evaluate_f6(ref_path, cand_contact)
            self.assertFalse(res_c["valid"])
            self.assertTrue(any("contact_violation" in f for f in res_c["failures"]))

            cand_oob = Path(td) / "cand_oob.h5"
            create_synthetic_f6_trajectory(cand_oob, nframes=4, inject_oob_body=True)
            res_oob = evaluate_f6(ref_path, cand_oob)
            self.assertFalse(res_oob["valid"])
            self.assertIn("rigid_body_boundary_violation", res_oob["failures"])

    def test_native_labels_materialize_on_synthetic(self):
        """Test native transport label materialization on synthetic F6 trajectory."""
        with tempfile.TemporaryDirectory() as td:
            traj_path = Path(td) / "trajectory.h5"
            labels_h5 = Path(td) / "native-labels.h5"
            create_synthetic_f6_trajectory(traj_path, nframes=3, nparticles=60)

            cfg = json.loads((REPO / "campaigns/ds-data-02/families/F6/labels/simple_free_response_event_config.json").read_text(encoding="utf-8"))
            res = materialize(traj_path, labels_h5, cfg, particle_chunk=65536)

            self.assertTrue(labels_h5.is_file())
            self.assertIn("sha256", res)
            self.assertEqual(res["frames"], 3)
            self.assertEqual(res["identities"], 60)

            # Inspect generated labels HDF5
            with h5py.File(labels_h5, "r") as lh5:
                self.assertIn("source_label", lh5)
                self.assertIn("destination_time_series", lh5)
                self.assertIn("first_passage_interval", lh5)
                self.assertEqual(lh5["source_label"].shape, (60,))
                self.assertEqual(lh5["destination_time_series"].shape, (3, 60))


if __name__ == "__main__":
    unittest.main()

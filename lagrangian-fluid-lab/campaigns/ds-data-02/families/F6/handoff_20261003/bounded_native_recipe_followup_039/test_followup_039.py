#!/usr/bin/env python3
"""DS-DATA-02 F6 Followup 039 Test Suite.

Comprehensive synthetic tests covering:
1. Source and resource bindings integrity.
2. Exact initial rigid geometry, mass, inertia, center, native EOS, and driver validation.
3. WholeXML undo proof (byte-for-byte and tree-for-tree roundtrip invariance).
4. Concrete clone worker dry-run execution.
5. Independent guard audit on baseline RunPARTs timestep counters and DTsMin clamps.
6. Kabsch proper SO(3) SVD rigid pose fitting and SLERP interpolation on synthetic bodies.
7. Runner requests compliance (launch_allowed=false, valid schemas, hash consistency).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from clone_transformer import (
    ORIGINAL_BI4_SHA256,
    ORIGINAL_GENCASE_RECEIPT_SHA256,
    ORIGINAL_XML_SHA256,
    compute_bytes_sha256,
    compute_sha256,
    transform_execution_xml_bytes,
    verify_exact_initial_physics_and_geometry,
)
from clone_worker import audit_source_inputs, execute_clone
from independent_guard_audit import audit_baseline, parse_runparts_csv
from kabsch_evaluation_pipeline import evaluate_trajectories
import owner_geometry_v1 as owner

DIR_PATH = Path(__file__).parent
BINDING_PATH = DIR_PATH / "source_and_resource_binding.json"
PREREG_PATH = DIR_PATH / "preregistration.json"
REQUESTS_DIR = DIR_PATH / "requests"


class TestF6Followup039(unittest.TestCase):
    """Synthetic tests for F6 Followup 039."""

    def setUp(self) -> None:
        self.binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))

    def test_01_source_and_resource_binding(self) -> None:
        """Verify that source bindings exist, hashes match, and resource budgets are valid."""
        orig = self.binding["original_actual_full_run"]
        self.assertEqual(orig["case_id"], "F6_ANGULAR_RELEASE_DP0125")
        self.assertEqual(orig["nominal_dp_m"], 0.0125)
        self.assertEqual(orig["floating_nodes_expected_count"], 131072)
        self.assertEqual(orig["particle_summary"]["total_particles"], 3045508)
        self.assertEqual(orig["particle_summary"]["fixed_boundary_particles"], 292996)
        self.assertEqual(orig["particle_summary"]["floating_boundary_particles"], 131072)
        self.assertEqual(orig["particle_summary"]["fluid_particles"], 2621440)

        # File hash checks
        audit = audit_source_inputs(self.binding)
        self.assertTrue(audit["all_sources_verified"], f"Source verification failed: {audit}")

        # Budget checks
        res = self.binding["parent_campaign_resources"]
        self.assertEqual(res["root_remaining_gpu_hours"], 32)
        self.assertEqual(res["root_remaining_qualification_attempts"], 56)
        self.assertGreaterEqual(res["home_storage_remaining_gib"], 500)

    def test_02_exact_initial_physics_and_geometry(self) -> None:
        """Verify exact initial rigid geometry, mass, inertia, center, EOS, and driver in XML."""
        xml_path = Path(self.binding["original_actual_full_run"]["source_xml_path"])
        xml_bytes = xml_path.read_bytes()
        meta = verify_exact_initial_physics_and_geometry(xml_bytes)

        self.assertTrue(meta["verified"])
        self.assertEqual(meta["rigid_mass_kg"], 128.0)
        self.assertEqual(meta["rigid_center_m"], [2.4, 1.2, 1.08])
        self.assertAlmostEqual(meta["rigid_inertia_kg_m2"][0], 8.53333333333, places=4)
        self.assertAlmostEqual(meta["rigid_inertia_kg_m2"][1], 8.53333333333, places=4)
        self.assertAlmostEqual(meta["rigid_inertia_kg_m2"][2], 13.6533333333, places=4)
        self.assertEqual(meta["initial_angular_vel_rad_s"], [0.08, 0.12, 0.06])
        self.assertEqual(meta["floating_nodes"], 131072)
        self.assertEqual(meta["total_particles"], 3045508)
        self.assertEqual(meta["eos_rhop0"], 1000.0)
        self.assertEqual(meta["dt_fixed"], 0.0)

    def test_03_whole_xml_undo_proof(self) -> None:
        """Verify wholeXML undo proof: reversion is 100% byte-for-byte and tree-for-tree identical."""
        xml_path = Path(self.binding["original_actual_full_run"]["source_xml_path"])
        orig_bytes = xml_path.read_bytes()

        mutated_bytes, meta = transform_execution_xml_bytes(orig_bytes)
        self.assertTrue(meta["whole_xml_undo_proof_verified"])
        self.assertEqual(meta["casedef_cfl_preserved"], "0.2")
        self.assertEqual(meta["execution_cfl_mutated"], "0.1")
        self.assertEqual(meta["execution_coefdtmin_mutated"], "0.025")

        # Mutated bytes must not equal original bytes, but differ only in execution cfl and CoefDtMin
        self.assertNotEqual(mutated_bytes, orig_bytes)
        self.assertIn(b'<cflnumber value="0.1" />', mutated_bytes)
        self.assertIn(b'<parameter key="CoefDtMin" value="0.025" />', mutated_bytes)

        # Historical casedef must retain 0.2
        casedef_chunk = mutated_bytes.split(b"<execution>")[0]
        self.assertIn(b'<cflnumber value="0.2" />', casedef_chunk)
        self.assertNotIn(b'<cflnumber value="0.1" />', casedef_chunk)

    def test_04_clone_worker_dry_run(self) -> None:
        """Verify clone worker dry-run execution."""
        result = execute_clone(BINDING_PATH, output_dir=None, dry_run=True)
        self.assertEqual(result["mode"], "dry_run")
        self.assertTrue(result["audit"]["all_sources_verified"])
        self.assertFalse(result["new_gencase_generation"])
        self.assertEqual(result["whole_xml_undo_proof"], "PASSED (reversion byte-for-byte and tree-for-tree verified)")

    def test_05_independent_guard_audit_baseline(self) -> None:
        """Verify independent guard audit on baseline RunPARTs timestep counters and clamps."""
        audit = audit_baseline(BINDING_PATH)
        self.assertTrue(audit["all_checks_passed"])

        parsed = audit["baseline_runparts_audit"]
        self.assertEqual(parsed["frame_count"], 241)
        self.assertEqual(parsed["part_start"], 0)
        self.assertEqual(parsed["part_end"], 240)
        self.assertEqual(parsed["time_start_s"], 0.0)
        self.assertGreaterEqual(parsed["time_final_s"], 12.0)
        self.assertTrue(parsed["is_monotonic"])
        self.assertEqual(parsed["total_solver_steps"], 163707)
        self.assertEqual(parsed["total_dtsmin_clamps"], 273)

        # Verify clamps are strictly confined to parts 7 and 8
        self.assertEqual(set(parsed["dtsmin_clamp_distribution"].keys()), {"part_7", "part_8"})
        self.assertEqual(parsed["dtsmin_clamp_distribution"]["part_7"]["dtsmin_clamps"], 229)
        self.assertEqual(parsed["dtsmin_clamp_distribution"]["part_8"]["dtsmin_clamps"], 44)

        # Verify DtFixed ruling
        ruling = audit["timestep_control_ruling"]
        self.assertEqual(ruling["dt_fixed_value"], 0.0)
        self.assertIn("variable time-stepping", ruling["ruling"])

    def test_06_kabsch_so3_math_and_slerp(self) -> None:
        """Verify Kabsch proper SO(3) SVD mathematics and SLERP trajectory interpolation."""
        # Create a synthetic 3D rigid box of 1000 points
        np.random.seed(42)
        P_ref = np.random.uniform(-0.4, 0.4, size=(1000, 3)) + np.array([2.4, 1.2, 1.08])

        # Test case A: Pure translation by [0.03, 0.02, -0.01] m (within generic 5% budget 0.04m)
        t_shift = np.array([0.03, 0.02, -0.01])
        P_trans = P_ref + t_shift
        fit_trans = owner.compute_kabsch_svd(P_ref, P_trans)

        self.assertTrue(fit_trans["is_rank_3"])
        self.assertAlmostEqual(fit_trans["det_R"], 1.0, places=6)
        self.assertAlmostEqual(np.linalg.norm(fit_trans["target_centroid_m"] - (np.mean(P_ref, axis=0) + t_shift)), 0.0, places=6)
        self.assertAlmostEqual(fit_trans["rigidity_rms_m"], 0.0, places=6)
        d_R_trans = owner.compute_so3_geodesic_distance(np.eye(3), fit_trans["rotation_matrix"])
        self.assertAlmostEqual(d_R_trans, 0.0, places=6)

        # Test case B: 90 deg rotation around Z-axis
        theta = np.pi / 2.0
        R_z = np.array([
            [np.cos(theta), -np.sin(theta), 0.0],
            [np.sin(theta), np.cos(theta), 0.0],
            [0.0, 0.0, 1.0]
        ])
        c_ref = np.mean(P_ref, axis=0)
        P_rot = (P_ref - c_ref) @ R_z.T + c_ref
        fit_rot = owner.compute_kabsch_svd(P_ref, P_rot)

        self.assertTrue(fit_rot["is_rank_3"])
        self.assertAlmostEqual(fit_rot["det_R"], 1.0, places=6)
        self.assertAlmostEqual(fit_rot["rigidity_rms_m"], 0.0, places=6)
        d_R_rot = owner.compute_so3_geodesic_distance(np.eye(3), fit_rot["rotation_matrix"])
        self.assertAlmostEqual(d_R_rot, theta, places=5)

        # Test case C: Trajectory comparison structure
        grid_times = np.array([0.0, 0.05, 0.10])
        traj_a = {
            "times": grid_times,
            "centroids": np.array([c_ref, c_ref, c_ref]),
            "quaternions": np.array([[1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]]),
        }
        traj_b = {
            "times": grid_times,
            "centroids": np.array([c_ref + t_shift, c_ref + t_shift, c_ref + t_shift]),
            "quaternions": np.array([fit_rot["quaternion_wxyz"], fit_rot["quaternion_wxyz"], fit_rot["quaternion_wxyz"]]),
        }
        eval_result = evaluate_trajectories(traj_a, traj_b, grid_times)
        self.assertEqual(eval_result["grid_frames"], 3)
        self.assertIsNone(eval_result["claim_boundary"]["orientation_budget"])
        self.assertEqual(eval_result["claim_boundary"]["q_n"], "not_granted")
        self.assertEqual(eval_result["claim_boundary"]["production_approval"], "none")

    def test_07_runner_requests_compliance(self) -> None:
        """Verify runner requests compliance: launch_allowed=false, schema, and files."""
        request_files = list(REQUESTS_DIR.glob("*.json"))
        self.assertGreaterEqual(len(request_files), 4)

        for req_path in request_files:
            data = json.loads(req_path.read_text(encoding="utf-8"))
            self.assertEqual(data.get("schema"), "ds02.runner-request.v2", f"Invalid schema in {req_path.name}")
            self.assertEqual(data.get("family_id"), "F6", f"Invalid family_id in {req_path.name}")
            self.assertFalse(data.get("launch_allowed"), f"CRITICAL: launch_allowed must be FALSE in {req_path.name}")
            self.assertEqual(data.get("launch_owner"), "root", f"launch_owner must be root in {req_path.name}")

            # Verify input_files exist and match sha256 if declared
            input_files = data.get("input_files", [])
            input_sha256 = data.get("input_sha256", {})
            for fpath_str in input_files:
                fpath = Path(fpath_str)
                self.assertTrue(fpath.is_file(), f"Input file {fpath_str} referenced in {req_path.name} does not exist!")
                if fpath_str in input_sha256:
                    actual_hash = compute_sha256(fpath)
                    self.assertEqual(actual_hash, input_sha256[fpath_str], f"SHA256 mismatch for {fpath_str} in {req_path.name}")


if __name__ == "__main__":
    unittest.main()

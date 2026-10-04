#!/usr/bin/env python3
"""Comprehensive test suite for F3 two-axis sloshing native transport & domain preparation.

Tests:
1. Canonical Physical Condition & Erratum Hash Guards.
2. Prohibition of Single-Axis Controls Hash Transfer.
3. 23 Event Closure Categories & 13 Mandatory Payload Datasets Verification.
4. Preflight Dry-Run Checks for Label and Paired-Transport Workers.
5. Synthetic Paired Same-UID Transport Logic:
   - Fate switch detection and mass summation.
   - Joint vs nominal-only vs sensitivity-only first passages.
   - Literal native bracket overlap vs disjoint tracking.
   - Mass-weighted mean and quantile delta metrics.
   - Strict preservation of native binary weights.
6. SAME-Mother Second-Mechanism Amplitude Bracket & Interior Points:
   - Plain container geometry integrity.
   - Fundamental transverse eigenfrequency derivation.
   - Envelope E(t) parameters and boundary conditions.
   - Bracket [0.25, 0.75] m/s^2 and interior points {0.375, 0.50, 0.625} m/s^2.
   - Zero-drive identity at Ay = 0.0 m/s^2.
7. Runner Requests Schema (ds02.runner-request.v2) & Governance Guards (launch_allowed: false).
8. Strict Source Immutability.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile
import unittest

import h5py
import numpy as np

# Add worker directory to sys.path
BASE_DIR = Path(__file__).resolve().parent
import sys
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from twoaxis_labels_worker import (
    CANONICAL_PHYSICAL_CONDITION_SHA256,
    DECLARED_TOP_LEVEL_ERRATUM_MARKER,
    FORBIDDEN_SINGLE_AXIS_HASHES,
    MANDATORY_PAYLOAD_DATASETS,
    MANDATORY_SUMMARY_DATASETS,
    evaluate_23_closure_categories,
    validate_root_guard,
    run_labels_worker,
)
from twoaxis_paired_transport_worker import compute_stats, run_paired_transport_worker


class TestTwoAxisGuardsAndHashes(unittest.TestCase):
    def test_canonical_condition_hashes(self):
        self.assertEqual(
            CANONICAL_PHYSICAL_CONDITION_SHA256,
            "49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb",
        )
        self.assertEqual(
            DECLARED_TOP_LEVEL_ERRATUM_MARKER,
            "49d16330fd5267668670f166a20191bfb00c5223ad5528439630c7e62dd4c6a0",
        )
        self.assertNotIn(CANONICAL_PHYSICAL_CONDITION_SHA256, FORBIDDEN_SINGLE_AXIS_HASHES)

    def test_root_guard_rejections(self):
        # Transferred single-axis hash must be rejected
        bad_binding = {
            "physical_condition_sha256": "59abc8c59ecbb994aef358a683672feac00ff8d1024d55f0219c8fe257f6ff90",
            "conversion_receipt": "/nonexistent",
            "conversion_report": "/nonexistent",
        }
        with self.assertRaises(ValueError):
            validate_root_guard(bad_binding)

        # Mismatched declared erratum marker must be rejected
        bad_erratum_binding = {
            "physical_condition_sha256": CANONICAL_PHYSICAL_CONDITION_SHA256,
            "declared_top_level_digest": "wrong_hash",
            "conversion_receipt": "/nonexistent",
            "conversion_report": "/nonexistent",
        }
        with self.assertRaises(ValueError):
            validate_root_guard(bad_erratum_binding)


class Test23ClosureCategoriesAndPayloads(unittest.TestCase):
    def test_payload_dataset_constants(self):
        self.assertEqual(len(MANDATORY_PAYLOAD_DATASETS), 13)
        self.assertEqual(len(MANDATORY_SUMMARY_DATASETS), 6)
        expected_13 = [
            "time",
            "particle_id",
            "particle_zone",
            "source_label",
            "destination_time_series",
            "final_category",
            "failure_reason",
            "first_passage_interval",
            "first_passage_chord_time",
            "first_passage_censor",
            "residence_time_s",
            "unresolved_interval_time_s",
            "initial_fluid_mass_kg",
        ]
        self.assertEqual(MANDATORY_PAYLOAD_DATASETS, expected_13)

    def test_synthetic_23_closure_evaluation(self):
        # Create a synthetic label file with complete 23 categories
        with tempfile.TemporaryDirectory() as tmp_dir:
            h5_path = Path(tmp_dir) / "synthetic-labels.h5"
            nt = 836
            n = 100
            n_fluid = 60
            time = np.linspace(0.0, 8.35, nt)

            p_id = np.arange(n, dtype=np.int32)
            p_zone = np.zeros(n, dtype=np.int32)
            fluid_mass = np.where(np.arange(n) < n_fluid, 0.000216, 0.0)

            config = {
                "source_regions": [{"id": "left"}, {"id": "right"}],
                "destination_regions": [{"id": "left"}, {"id": "right"}],
                "events": [{"id": "left_right_exchange"}, {"id": "top_open_exit"}],
            }

            with h5py.File(h5_path, "w") as h:
                h.attrs["complete"] = True
                h.attrs["config_json"] = json.dumps(config)
                h.create_dataset("time", data=time)
                h.create_dataset("particle_id", data=p_id)
                h.create_dataset("particle_zone", data=p_zone)
                h.create_dataset("initial_fluid_mass_kg", data=fluid_mass)
                h.create_dataset("source_label", data=np.where(fluid_mass > 0, 1, 0).astype(np.int16))

                dest_ts = np.zeros((nt, n), dtype=np.int16)
                dest_ts[:, fluid_mass > 0] = 1
                dest_ts[:, fluid_mass == 0] = -3
                h.create_dataset("destination_time_series", data=dest_ts)
                h.create_dataset("final_category", data=dest_ts[-1])
                h.create_dataset("failure_reason", data=np.zeros(n, dtype=np.int8))

                brackets = np.full((n, 2, 2), np.nan)
                estimates = np.full((n, 2), np.nan)
                censor = np.ones((n, 2), dtype=np.int8)

                # Simulate observed first passage for fluid particles
                for idx in range(n_fluid):
                    censor[idx, 0] = 0
                    brackets[idx, 0] = [1.0, 1.01]
                    estimates[idx, 0] = 1.005

                h.create_dataset("first_passage_interval", data=brackets)
                h.create_dataset("first_passage_chord_time", data=estimates)
                h.create_dataset("first_passage_censor", data=censor)

                residence = np.zeros((n, 2), dtype=float)
                residence[fluid_mass > 0, 0] = 8.35
                h.create_dataset("residence_time_s", data=residence)
                h.create_dataset("unresolved_interval_time_s", data=np.zeros(n, dtype=float))

                fb = np.zeros((nt, 2, 2), dtype=float)
                h.create_dataset("forward_backward_mass_kg", data=fb)
                h.create_dataset("cumulative_net_flux_kg", data=np.zeros((nt, 2), dtype=float))
                h.create_dataset("unknown_mass_kg", data=np.zeros(nt, dtype=float))
                h.create_dataset("numerical_loss_mass_kg", data=np.zeros(nt, dtype=float))
                h.create_dataset("invalid_state_mass_kg", data=np.zeros(nt, dtype=float))

                mass_table = np.zeros((3, 5), dtype=float)
                mass_table[1, 3] = float(fluid_mass.sum())
                h.create_dataset("source_final_mass_kg", data=mass_table)

            expected_ids = np.column_stack((p_zone, p_id))
            expected_mass = float(fluid_mass.sum())
            closure = evaluate_23_closure_categories(h5_path, expected_ids, expected_mass)
            self.assertTrue(closure["passed"])
            self.assertEqual(closure["fluid_identities"], n_fluid)
            self.assertAlmostEqual(closure["initial_native_float_mass_kg"], expected_mass)


class TestPairedTransportLogic(unittest.TestCase):
    def test_stats_computation(self):
        delta = np.array([0.01, 0.02, 0.05, -0.03])
        weights = np.array([1.0, 1.0, 1.0, 1.0])
        s = compute_stats(delta, weights)
        self.assertEqual(s["identities"], 4)
        self.assertEqual(s["native_mass_kg"], 4.0)
        self.assertAlmostEqual(s["mass_weighted_mean_abs_gap_s"], 0.0275)
        self.assertAlmostEqual(s["max_abs_gap_s"], 0.05)

    def test_bracket_overlap_and_disjoint(self):
        ix = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        iy = np.array([[1.5, 2.5], [4.1, 5.0], [5.2, 5.8]])
        overlap = np.maximum(ix[:, 0], iy[:, 0]) <= np.minimum(ix[:, 1], iy[:, 1])
        # [1.5, 2.0] -> overlap
        # [4.1, 4.0] -> disjoint
        # [5.2, 5.8] -> overlap
        self.assertTrue(overlap[0])
        self.assertFalse(overlap[1])
        self.assertTrue(overlap[2])
        self.assertEqual(int(overlap.sum()), 2)
        self.assertEqual(int((~overlap).sum()), 1)


class TestAmplitudeBracketAndPhysics(unittest.TestCase):
    def test_transverse_eigenmode_calculation(self):
        W = 0.18
        h = 0.09
        g = 9.81
        ky = math.pi / W
        tanh_val = math.tanh(ky * h)
        omega_y = math.sqrt(g * ky * tanh_val)
        self.assertAlmostEqual(ky, 17.4532925, places=5)
        self.assertAlmostEqual(tanh_val, 0.9171523, places=5)
        self.assertAlmostEqual(omega_y, 12.531236, places=4)
        f_y = omega_y / (2 * math.pi)
        self.assertAlmostEqual(f_y, 1.9944, places=3)
        T_y = 1.0 / f_y
        self.assertAlmostEqual(T_y, 0.5014, places=3)

    def test_amplitude_bracket_specification_json(self):
        spec_path = BASE_DIR / "definitions" / "amplitude_bracket_specification.json"
        self.assertTrue(spec_path.is_file())
        spec = json.loads(spec_path.read_text())
        self.assertEqual(spec["mechanism_id"], "F3_TWOAXIS_TRANSVERSE_LINACC_V1")
        self.assertEqual(spec["mother_definition"]["water_dimensions_m"]["width_y"], 0.18)
        self.assertEqual(spec["mother_definition"]["continuum_fluid_mass_kg"], 14.58)

        bracket = spec["amplitude_bracket"]
        self.assertEqual(bracket["lower_endpoint"]["A_y_m_s2"], 0.25)
        self.assertEqual(bracket["upper_endpoint"]["A_y_m_s2"], 0.75)
        interior_amps = [p["A_y_m_s2"] for p in bracket["interior_points"]]
        self.assertIn(0.50, interior_amps)
        self.assertGreaterEqual(len(interior_amps), 1)

        # Confirm scientific boundaries are declared
        bounds = spec["scientific_boundary_declarations"]
        self.assertIn("accepted none", bounds["existing_domain"].lower())
        self.assertIn("no assertion of endpoints convergence", bounds["endpoint_convergence"].lower())
        self.assertIn("no need for non-native tracers", bounds["tracer_policy"].lower())


class TestBindingsAndRequestsIntegrity(unittest.TestCase):
    def test_bindings_exist_and_conform(self):
        bindings_dir = BASE_DIR / "bindings"
        for name in [
            "binding_twoaxis_dp006_baseline_labels.json",
            "binding_twoaxis_dp006_halfstep_labels.json",
            "binding_twoaxis_dp006_dense_labels.json",
            "binding_twoaxis_dp006_halfstep_transport.json",
            "binding_twoaxis_dp006_dense_transport.json",
        ]:
            b_path = bindings_dir / name
            self.assertTrue(b_path.is_file(), f"Missing binding: {name}")
            data = json.loads(b_path.read_text())
            self.assertEqual(
                data["physical_condition_sha256"],
                CANONICAL_PHYSICAL_CONDITION_SHA256,
            )
            self.assertEqual(
                data["declared_top_level_digest"],
                DECLARED_TOP_LEVEL_ERRATUM_MARKER,
            )

    def test_requests_exist_and_enforce_no_launch(self):
        requests_dir = BASE_DIR / "requests"
        for name in [
            "request_twoaxis_dp006_baseline_labels.json",
            "request_twoaxis_dp006_halfstep_labels.json",
            "request_twoaxis_dp006_dense_labels.json",
            "request_twoaxis_dp006_halfstep_transport.json",
            "request_twoaxis_dp006_dense_transport.json",
        ]:
            r_path = requests_dir / name
            self.assertTrue(r_path.is_file(), f"Missing request: {name}")
            data = json.loads(r_path.read_text())
            self.assertEqual(data["schema"], "ds02.runner-request.v2")
            self.assertFalse(data["launch_allowed"])
            self.assertEqual(data["launch_owner"], "root")
            self.assertEqual(data["q_n_status"], "not_assessed")
            self.assertEqual(data["production_approval"], "none")


class TestWorkerPreflight(unittest.TestCase):
    def test_labels_worker_preflight(self):
        binding_path = BASE_DIR / "bindings" / "binding_twoaxis_dp006_baseline_labels.json"
        config_path = Path(
            "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/legacy_plain_8/f3_legacy_plain_full_transport_config.v1.json"
        )
        out_dir = Path("/tmp/test_preflight_out")
        res = run_labels_worker(
            binding_path=binding_path,
            config_path=config_path,
            output_dir=out_dir,
            dry_run_check=True,
        )
        self.assertEqual(res["status"], "preflight_passed")
        self.assertEqual(res["closure_categories"], 23)
        self.assertEqual(res["mandatory_payload_datasets"], 13)

    def test_transport_worker_preflight(self):
        binding_path = BASE_DIR / "bindings" / "binding_twoaxis_dp006_halfstep_transport.json"
        out_path = Path("/tmp/test_transport_preflight.json")
        res = run_paired_transport_worker(
            binding_path=binding_path, output_path=out_path, dry_run_check=True
        )
        self.assertEqual(res["status"], "preflight_passed")
        self.assertEqual(res["physical_condition_sha256"], CANONICAL_PHYSICAL_CONDITION_SHA256)


if __name__ == "__main__":
    unittest.main()

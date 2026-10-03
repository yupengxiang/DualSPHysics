"""Synthetic unit test for F7 paired transport comparison v2."""
import json
from pathlib import Path
import tempfile
import unittest

import h5py
import numpy as np

from scripts.ds_data02_f7_native_transport_compare_v2 import compare, digest, compute_unconditional_cdf


class TestF7TransportCompareSynthetic(unittest.TestCase):
    def test_unconditional_cdf_computation(self):
        # 4 synthetic particles with weights [1, 2, 3, 4] -> total mass 10
        times = np.array([1.0, 5.0, 8.0, 10.0])
        censored = np.array([False, False, True, False])  # particle 2 is censored
        weights = np.array([1.0, 2.0, 3.0, 4.0])
        grid = np.array([0.0, 2.0, 6.0, 9.0, 12.0])

        cdf, deciles = compute_unconditional_cdf(times, censored, weights, grid)
        # At t=0: 0/10 = 0.0
        # At t=2: particle 0 (w=1) -> 1/10 = 0.1
        # At t=6: particle 0 (w=1) + particle 1 (w=2) -> 3/10 = 0.3
        # At t=9: particle 2 is censored (>12), so only part 0, 1 -> 3/10 = 0.3
        # At t=12: particle 3 (w=4) passed at 10.0 -> (1+2+4)/10 = 0.7
        self.assertAlmostEqual(cdf[0], 0.0)
        self.assertAlmostEqual(cdf[1], 0.1)
        self.assertAlmostEqual(cdf[2], 0.3)
        self.assertAlmostEqual(cdf[3], 0.3)
        self.assertAlmostEqual(cdf[4], 0.7)

    def test_compare_synthetic_fixtures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            n_particles = 10
            n_frames = 11
            n_events = 3

            # Common identity data
            time_arr = np.linspace(0.0, 12.0, n_frames)
            p_id = np.arange(100, 100 + n_particles, dtype=np.uint32)
            p_zone = np.ones(n_particles, dtype=np.int64)
            source_lbl = np.zeros(n_particles, dtype=np.int16)
            mass_arr = np.full(n_particles, 0.5, dtype=np.float64)

            # Create synthetic baseline H5
            base_h5 = tmp / "base_labels.h5"
            with h5py.File(base_h5, "w") as h:
                h.attrs["complete"] = True
                h.attrs["initial_fluid_mass_kg"] = 5.0
                h.create_dataset("time", data=time_arr)
                h.create_dataset("particle_id", data=p_id)
                h.create_dataset("particle_zone", data=p_zone)
                h.create_dataset("source_label", data=source_lbl)
                h.create_dataset("initial_fluid_mass_kg", data=mass_arr)

                censor = np.zeros((n_particles, n_events), dtype=np.int8)
                censor[8:, :] = 1  # 8, 9 censored
                h.create_dataset("first_passage_censor", data=censor)

                chord = np.ones((n_particles, n_events), dtype=np.float64) * 2.0
                chord[8:, :] = np.nan
                h.create_dataset("first_passage_chord_time", data=chord)

                interval = np.zeros((n_particles, n_events, 2), dtype=np.float64)
                interval[:, :, 0] = 1.9
                interval[:, :, 1] = 2.1
                h.create_dataset("first_passage_interval", data=interval)

            # Create synthetic variant H5 (slightly shifted chord times, particle 7 censored in variant)
            var_h5 = tmp / "var_labels.h5"
            with h5py.File(var_h5, "w") as h:
                h.attrs["complete"] = True
                h.attrs["initial_fluid_mass_kg"] = 5.0
                h.create_dataset("time", data=time_arr)
                h.create_dataset("particle_id", data=p_id)
                h.create_dataset("particle_zone", data=p_zone)
                h.create_dataset("source_label", data=source_lbl)
                h.create_dataset("initial_fluid_mass_kg", data=mass_arr)

                censor = np.zeros((n_particles, n_events), dtype=np.int8)
                censor[7:, :] = 1  # 7, 8, 9 censored
                censor[8, 0] = 0  # particle 8 observed only in variant for event 0
                h.create_dataset("first_passage_censor", data=censor)

                chord = np.ones((n_particles, n_events), dtype=np.float64) * 2.05
                chord[7:, :] = np.nan
                chord[8, 0] = 3.0
                h.create_dataset("first_passage_chord_time", data=chord)

                interval = np.zeros((n_particles, n_events, 2), dtype=np.float64)
                interval[:, :, 0] = 2.0
                interval[:, :, 1] = 2.2
                interval[8, 0, 0] = 2.9
                interval[8, 0, 1] = 3.1
                h.create_dataset("first_passage_interval", data=interval)

            # Reports
            base_report_path = tmp / "base_report.json"
            base_report = {
                "frames": n_frames,
                "identities": n_particles,
                "all_observed_crossing_rows": 50,
                "event_ids": ["obstacle_subdomain_crossing", "lateral_slosh_exchange", "top_open_exit"],
                "event_crossing_counts": [20, 20, 10],
                "maximum_all_event_half_bracket_s": [0.001, 0.001, 0.001],
                "final_native_exclusion_mass_kg": 0.41,
                "final_unknown_region_mass_kg": 0.0,
                "sha256": digest(base_h5),
            }
            base_report_path.write_text(json.dumps(base_report))

            var_report_path = tmp / "var_report.json"
            var_report = {
                "frames": n_frames,
                "identities": n_particles,
                "all_observed_crossing_rows": 55,
                "event_ids": ["obstacle_subdomain_crossing", "lateral_slosh_exchange", "top_open_exit"],
                "event_crossing_counts": [22, 22, 11],
                "maximum_all_event_half_bracket_s": [0.001, 0.001, 0.001],
                "final_native_exclusion_mass_kg": 0.423,
                "final_unknown_region_mass_kg": 0.0,
                "sha256": digest(var_h5),
            }
            var_report_path.write_text(json.dumps(var_report))

            # Budget
            budget_path = tmp / "budget.json"
            budget = {
                "physical_scale": {
                    "event_absolute_budget_s": 0.006624,
                    "save_or_integration_event_budget_s": 0.001325,
                }
            }
            budget_path.write_text(json.dumps(budget))

            # Event config
            config_path = tmp / "config.json"
            config = {
                "events": [
                    {"id": "obstacle_subdomain_crossing"},
                    {"id": "lateral_slosh_exchange"},
                    {"id": "top_open_exit"},
                ]
            }
            config_path.write_text(json.dumps(config))

            out_json = tmp / "out.json"
            res = compare(
                base_h5, var_h5, budget_path, config_path,
                base_report_path, var_report_path, out_json,
                cdf_grid_points=25,
            )

            self.assertEqual(res["schema"], "ds02.f7.full-native-transport-comparison.v2")
            self.assertEqual(len(res["events"]), 3)
            # Event 0: joint particles (0..6) = 7 particles
            # Baseline-only (7) = 1 particle
            # Variant-only (8) = 1 particle
            # Joint-censored (9) = 1 particle
            cb0 = res["events"][0]["cohort_breakdown"]
            self.assertEqual(cb0["joint_observed"]["count"], 7)
            self.assertEqual(cb0["baseline_only"]["count"], 1)
            self.assertEqual(cb0["variant_only"]["count"], 1)
            self.assertEqual(cb0["joint_censored"]["count"], 1)
            self.assertEqual(cb0["switching_identities"]["count"], 2)

            deltas0 = res["events"][0]["per_identity_chord_deltas"]
            self.assertAlmostEqual(deltas0["mean_signed_delta_s"], 0.05)
            self.assertAlmostEqual(deltas0["mean_absolute_delta_s"], 0.05)

            # Check exclusion mass
            self.assertAlmostEqual(res["native_exclusion_mass"]["delta_kg"], 0.423 - 0.41)


if __name__ == "__main__":
    unittest.main()

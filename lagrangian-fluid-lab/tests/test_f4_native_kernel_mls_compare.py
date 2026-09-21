import json

import h5py
import numpy as np

from scripts.f4_native_kernel_mls_compare import compare_traces


def _write_trace(path, *, substeps, unknown_count, contact_count, endpoint_offset):
    n = 512
    frames = 2
    position = np.zeros((frames, n, 3), dtype=np.float64)
    position[:, :, 2] = 0.4 + endpoint_offset
    reliable = np.ones((frames, n), dtype=bool)
    permanent_unknown = np.zeros((frames, n), dtype=bool)
    permanent_unknown[1, :unknown_count] = True
    reliable[1] = ~permanent_unknown[1]
    destination = np.zeros((frames, n), dtype=bool)
    destination[1, :contact_count] = True
    contact = np.zeros((frames, n), dtype=bool)
    contact[1, :contact_count] = True
    contact_time = np.full((frames, n), np.nan, dtype=np.float64)
    contact_time[1, :contact_count] = 0.08
    residence = np.zeros((frames, n), dtype=np.float64)
    residence[1, :contact_count] = 0.02
    return_time = np.full((frames, n), np.nan, dtype=np.float64)
    returned = np.zeros((frames, n), dtype=bool)
    event_status = np.zeros((frames, n), dtype=np.int8)
    event_status[1, :contact_count] = 1
    mass_closure = np.zeros(frames, dtype=np.float64)
    residual = np.full((frames, n), 0.01, dtype=np.float64)
    path_budget = np.full((frames, n), 0.001, dtype=np.float64)
    binding = {
        "schema": "core.material.f4.native_kernel_mls.trace.v1",
        "backend": "f4_native_kernel_mls_causal_current_volume_rk4_v1",
        "source_sha256": "source-sha",
        "h_m": 0.011941277883,
        "query_count": n,
        "q": 0.5,
        "fluid_type": 3,
        "event_definition": {"interface_plane_z_m": 0.18},
    }
    with h5py.File(path, "w") as handle:
        handle.attrs["schema"] = binding["schema"]
        handle.attrs["binding"] = json.dumps(binding, sort_keys=True)
        handle.attrs["binding_sha256"] = "binding"
        handle.attrs["seed_hash"] = "seed"
        handle.attrs["committed"] = 1
        handle.attrs["material_reliability"] = "not_assessed"
        handle["time"] = [0.0, 0.1]
        handle["initial_position"] = position[0]
        handle["query_mass"] = np.full(n, 1.0 / n)
        handle["source_label"] = np.asarray(["drop_q0.5"] * n, dtype=h5py.string_dtype())
        handle["position"] = position
        handle["reliable"] = reliable
        handle["permanent_unknown"] = permanent_unknown
        handle["destination_member"] = destination
        handle["contact_time"] = contact_time
        handle["upward_time"] = np.full((frames, n), np.nan)
        handle["return_time"] = return_time
        handle["residence_s"] = residence
        handle["contacted"] = contact
        handle["upward"] = np.zeros((frames, n), dtype=bool)
        handle["returned"] = returned
        handle["event_status"] = event_status
        handle["mass_closure_error"] = mass_closure
        handle["residual_estimate_mps"] = residual
        handle["path_error_budget_m"] = path_budget


def test_compare_reports_cdf_unknown_and_common_path(tmp_path):
    s2 = tmp_path / "s2.h5"
    s4 = tmp_path / "s4.h5"
    _write_trace(s2, substeps=2, unknown_count=8, contact_count=32, endpoint_offset=0.0)
    _write_trace(s4, substeps=4, unknown_count=16, contact_count=24, endpoint_offset=0.001)
    result = compare_traces(s2, s4, tmp_path / "comparison.json")
    assert result["comparison_status"] == "diagnostic_only"
    assert result["t2_status"] == "not_evaluated"
    row = result["source_comparison"]["drop_q0.5"]
    assert row["s2"]["unknown_fraction"] == 8 / 512
    assert row["s4"]["unknown_fraction"] == 16 / 512
    assert row["s2"]["first_contact_cdf"]["event_mass_fraction"] == 32 / 512
    assert row["s4"]["first_contact_cdf"]["event_mass_fraction"] == 24 / 512
    assert row["s2"]["residence_mean_s_all_seeds"] == 32 * 0.02 / 512
    assert row["s2"]["residence_zero_mass_fraction_lower"] == 480 / 512
    assert row["s2"]["residence_cdf"]["lower_mass_fraction"][-1] == 1.0
    assert result["common_reliable_path"]["common_seed_count"] == 496
    assert result["mass_closure"]["s2_max_abs_error"] == 0.0
    saved = json.loads((tmp_path / "comparison.json").read_text())
    assert saved["material_reliability_status"].startswith("uncalibrated")


def _write_midrun_unknown_trace(path):
    """Unknown seeds lose support before a later possible contact.

    Seeds 0..3 are unknown at frame 2 and never have an observed contact;
    seeds 4..15 contact and accumulate residence.  The all-source residence
    CDF must retain the 496 exact zero seeds and bound the four unknown seeds.
    """
    n = 512
    frames = 3
    position = np.zeros((frames, n, 3), dtype=np.float64)
    position[:, :, 2] = 0.4
    reliable = np.ones((frames, n), dtype=bool)
    permanent_unknown = np.zeros((frames, n), dtype=bool)
    permanent_unknown[2, :4] = True
    reliable[2] = ~permanent_unknown[2]
    destination = np.zeros((frames, n), dtype=bool)
    destination[:, 4:16] = True
    contact = np.zeros((frames, n), dtype=bool)
    contact[:, 4:16] = True
    contact_time = np.full((frames, n), np.nan, dtype=np.float64)
    contact_time[:, 4:16] = 0.08
    residence = np.zeros((frames, n), dtype=np.float64)
    residence[:, 4:16] = 0.01
    return_time = np.full((frames, n), np.nan, dtype=np.float64)
    returned = np.zeros((frames, n), dtype=bool)
    event_status = np.zeros((frames, n), dtype=np.int8)
    event_status[:, 4:16] = 1
    mass_closure = np.zeros(frames, dtype=np.float64)
    residual = np.full((frames, n), 0.01, dtype=np.float64)
    path_budget = np.full((frames, n), 0.001, dtype=np.float64)
    binding = {
        "schema": "core.material.f4.native_kernel_mls.trace.v1",
        "backend": "f4_native_kernel_mls_causal_current_volume_rk4_v1",
        "source_sha256": "source-sha",
        "h_m": 0.011941277883,
        "query_count": n,
        "q": 0.5,
        "fluid_type": 3,
        "event_definition": {"interface_plane_z_m": 0.18},
    }
    with h5py.File(path, "w") as handle:
        handle.attrs["schema"] = binding["schema"]
        handle.attrs["binding"] = json.dumps(binding, sort_keys=True)
        handle.attrs["binding_sha256"] = "binding"
        handle.attrs["seed_hash"] = "seed"
        handle.attrs["committed"] = 2
        handle.attrs["material_reliability"] = "not_assessed"
        handle["time"] = [0.0, 0.1, 0.2]
        handle["initial_position"] = position[0]
        handle["query_mass"] = np.full(n, 1.0 / n)
        handle["source_label"] = np.asarray(["drop_q0.5"] * n, dtype=h5py.string_dtype())
        handle["position"] = position
        handle["reliable"] = reliable
        handle["permanent_unknown"] = permanent_unknown
        handle["destination_member"] = destination
        handle["contact_time"] = contact_time
        handle["upward_time"] = np.full((frames, n), np.nan)
        handle["return_time"] = return_time
        handle["residence_s"] = residence
        handle["contacted"] = contact
        handle["upward"] = np.zeros((frames, n), dtype=bool)
        handle["returned"] = returned
        handle["event_status"] = event_status
        handle["mass_closure_error"] = mass_closure
        handle["residual_estimate_mps"] = residual
        handle["path_error_budget_m"] = path_budget


def test_residence_uses_all_source_mass_and_bounds_midrun_unknown(tmp_path):
    s2 = tmp_path / "s2.h5"
    s4 = tmp_path / "s4.h5"
    _write_midrun_unknown_trace(s2)
    _write_midrun_unknown_trace(s4)
    result = compare_traces(s2, s4, tmp_path / "comparison.json")
    row = result["source_comparison"]["drop_q0.5"]["s2"]

    # The 496 no-contact seeds remain exact zero residence in the full source
    # denominator; the four unknown seeds are intervals, not point values.
    assert row["residence_zero_mass_fraction_lower"] == 496 / 512
    assert row["residence_zero_mass_fraction_upper"] == 500 / 512
    assert row["residence_bounds_s"]["unknown_interval_mass_fraction"] == 4 / 512
    assert row["residence_mean_s_all_seeds"] == 12 * 0.01 / 512
    assert row["residence_mean_s_all_seeds_upper_bound"] == (12 * 0.01 + 4 * 0.1) / 512
    cdf = row["residence_cdf"]
    value_index = cdf["value_s"].index(0.0)
    assert cdf["lower_mass_fraction"][value_index] == 496 / 512
    assert cdf["upper_mass_fraction"][value_index] == 500 / 512

    # The unknown no-contact seeds can first contact after the last reliable
    # frame, so they widen the contact CDF upper bound at t=0.1 s.
    contact = row["first_contact_cdf"]
    time_index = contact["time_s"].index(0.1)
    assert contact["lower_mass_fraction"][time_index] == 12 / 512
    assert contact["upper_mass_fraction"][time_index] == 16 / 512
    assert contact["unknown_unresolved_mass_fraction"] == 4 / 512

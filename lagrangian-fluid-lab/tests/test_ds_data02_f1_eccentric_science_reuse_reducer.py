import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f1_eccentric_science_reuse_reducer.py"
SPEC = importlib.util.spec_from_file_location("f1_eccentric_science_reuse_reducer", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_no_hdf5_is_allowed_as_a_reducer_input(tmp_path):
    path = tmp_path / "trajectory.h5"
    path.write_bytes(b"not read")
    try:
        MODULE.load_json(str(path))
    except ValueError as exc:
        assert "HDF5" in str(exc)
    else:
        raise AssertionError("HDF5 input must be rejected")


def test_event_budget_summary_is_explicit():
    comparison = {
        "baseline_saved_frames": 161,
        "reference_saved_frames": 1601,
        "max_actual_timestamp_alignment_difference_s": 0.0,
        "events": [
            {
                "event_id": "a",
                "chord_time_max_absolute_difference_s": 0.004,
                "chord_time_mass_weighted_mean_absolute_difference_s": 0.001,
                "saved_interval_worst_possible_max_difference_s": 0.01,
                "cumulative_forward_backward_max_difference_kg": 0.1,
                "timestamp_bracket_forward_backward_max_difference_bound_kg": 0.2,
                "jointly_censored_mass_kg": 1.0,
            }
        ],
        "residence": [{"destination_id": "a", "max_absolute_difference_s": 0.003, "mass_weighted_mean_absolute_difference_s": 0.001}],
        "final_destination_disagreement_mass_kg": 0.0,
        "final_destination_disagreement_mass_fraction": 0.0,
        "temporal_diagnostics": {"unknown_mass_kg": 0.0},
        "q_n_status": "not_granted",
        "limitations": [],
    }
    config = {"events": [{"id": "a"}], "limitations": ["x", "first passage"]}
    result = MODULE.summarize_dense_events(comparison, config, 0.0035)
    assert result["observed_chord_within_event_budget"] is False
    assert result["worst_saved_bracket_within_event_budget"] is False


def test_time_step_factor_summary_is_preserved_without_case_measurement():
    result = MODULE.summarize_steps(
        {
            "DENSE_SAVE": {
                "status": "completed",
                "measurement": {
                    "native_minimum_dt_s": 1.0,
                    "native_maximum_dt_s": 2.0,
                    "internal_step_count": 3,
                    "final_time_s": 4.0,
                    "saved_frame_count": 5,
                    "source": "run.csv",
                    "source_sha256": "abc",
                },
            },
            "separate_factor_evidence": {
                "actual_fixed_max_dt_below_half_baseline_min": True,
                "dense_saved_frame_count": 5,
            },
        }
    )
    assert result["DENSE_SAVE"]["saved_frame_count"] == 5
    assert result["separate_factor_evidence"]["dense_saved_frame_count"] == 5

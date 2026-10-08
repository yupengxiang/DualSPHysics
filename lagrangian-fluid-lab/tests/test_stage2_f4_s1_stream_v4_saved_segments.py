from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f4_s1_stream_v4_saved_segments.py"
SPEC = importlib.util.spec_from_file_location("stage2_f4_s1_stream_v4_saved_segments", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_identity_mass_separates_first_later_direction_and_net():
    value = {
        "total_saved_crossings": 2,
        "first_saved_crossings": 1,
        "later_saved_crossings": 1,
        "positive_saved_crossings": 1,
        "negative_saved_crossings": 1,
        "saved_initial_mass_kg": 2.0,
        "first_direction": "positive_x",
        "first_bracket_s": [0.0, 0.5],
        "later_brackets_s": [[0.5, 1.0]],
    }
    result = MODULE._identity_mass_record("7:42", value)
    assert result["initial_mass_kg_reconstructed"] == 1.0
    assert result["event_weighted_mass_kg"] == 2.0
    assert result["unique_first_mass_kg"] == 1.0
    assert result["later_recross_mass_kg"] == 1.0
    assert result["unique_first_net_transport_mass_kg"] == 1.0
    assert result["later_net_transport_mass_kg"] == -1.0
    assert result["event_weighted_net_transport_mass_kg"] == 0.0
    assert result["hidden_recrossings"] == "unknown"


def test_occupancy_and_residence_use_saved_right_endpoint_and_trapezoid(tmp_path):
    path = tmp_path / "saved.csv"
    path.write_text(
        "time_s,pool_finite_aperture_mass_kg,pool_finite_aperture_particles\n"
        "0.0,0.0,0\n"
        "1.0,2.0,1\n"
        "2.0,4.0,1\n",
        encoding="utf-8",
    )
    rows = MODULE.read_csv(path)
    result = MODULE._occupancy_summary("pool", rows, path)
    assert result["saved_interval_occupancy_seconds"] == 2.0
    assert result["saved_right_hold_residence_mass_time_kg_s"] == 6.0
    assert result["saved_trapezoid_residence_mass_time_kg_s"] == 4.0
    assert result["continuous_residence"] == "unknown_between_saved_frames"


def test_source_amount_is_reported_without_transport_error_gate():
    source = MODULE._source_summary(
        "pool",
        {
            "candidate_plane_crossings": 2,
            "outside_aperture_crossings": 0,
            "accepted_saved_crossings": 2,
            "first_saved_crossings": 1,
            "later_saved_crossings": 1,
            "positive_saved_crossings": 1,
            "negative_saved_crossings": 1,
            "accepted_saved_initial_mass_kg": 2.0,
            "per_typed_identity": {
                "7:42": {
                    "total_saved_crossings": 2,
                    "first_saved_crossings": 1,
                    "later_saved_crossings": 1,
                    "positive_saved_crossings": 1,
                    "negative_saved_crossings": 1,
                    "saved_initial_mass_kg": 2.0,
                    "first_direction": "positive_x",
                    "first_bracket_s": [0.0, 0.5],
                    "later_brackets_s": [[0.5, 1.0]],
                }
            },
        },
        source_initial_mass=10.0,
        whole_mass=10.0,
    )
    assert source["event_weighted_mass_fraction_whole_initial"] == 0.2
    # The V4 schema has no pass/fail status for this amount: it is a repeated
    # saved crossing observation, not an error bound or physical flux.
    assert "diagnostic_status" not in source

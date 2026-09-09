from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import r5_f1_solver_gate as gate


def test_records_are_exactly_the_preflighted_nine_cells():
    records = gate.records()
    assert len(records) == 9
    assert {item["background_id"] for item in records} == {
        "plain_dam_break", "center_obstacle", "twin_obstacle_split_remerge"
    }
    assert {item["resolution"] for item in records} == {"coarse", "medium", "fine"}
    assert {item["dp_m"] for item in records} == {0.035, 0.024, 0.014}


def test_smoke_case_is_first_and_physical_wall_spec_has_open_top_only():
    assert gate.SMOKE_CASE_ID == "R4_F1_plain_dam_break_medium"
    plain = next(item for item in gate.records() if item["background_id"] == "plain_dam_break")
    assert plain["wall_spec"]["open_faces"] == ["top"]
    assert plain["wall_spec"]["obstacles"] == []


def test_input_fingerprint_binds_candidate_and_generated_inputs():
    record = gate.records()[0]
    fingerprint = gate.input_fingerprint(record)
    assert fingerprint["record_hash"]
    assert len(fingerprint["files"]) == 5
    assert all(item["exists"] for item in fingerprint["files"])


def test_wall_penetration_does_not_treat_open_top_as_a_wall():
    record = next(item for item in gate.records() if item["background_id"] == "plain_dam_break")
    points = np.asarray([
        [0.5, 0.2, 0.1],
        [0.5, 0.2, 0.8],
        [-0.1, 0.2, 0.1],
    ])
    mass = np.ones(3)
    result = gate._wall_penetration(points, mass, record["wall_spec"], 1e-6)
    assert result["outside_closed_container_count"] == 1
    assert result["obstacle_penetration_count"] == 0


def test_finite_wall_segment_events_distinguish_rim_motion_and_side_crossing():
    record = next(item for item in gate.records() if item["background_id"] == "plain_dam_break")
    spec = record["wall_spec"]
    tolerance = 1e-6
    above_rim = gate._wall_segment_crossings(
        np.asarray([[0.5, 0.38, 0.70]]), np.asarray([[0.5, 0.42, 0.70]]), spec, tolerance
    )
    side_crossing = gate._wall_segment_crossings(
        np.asarray([[0.5, 0.38, 0.30]]), np.asarray([[0.5, 0.42, 0.30]]), spec, tolerance
    )
    leaves_top_before_side = gate._wall_segment_crossings(
        np.asarray([[0.5, 0.38, 0.55]]), np.asarray([[0.5, 0.42, 0.75]]), spec, tolerance
    )
    assert above_rim == []
    assert len(side_crossing) == 1
    assert side_crossing[0]["face"] == "back"
    assert side_crossing[0]["fraction"] == pytest.approx(0.5)
    assert leaves_top_before_side == []


def test_swept_obstacle_event_is_finite_and_separate_from_container_wall():
    record = next(item for item in gate.records() if item["background_id"] == "center_obstacle")
    events = gate._wall_segment_crossings(
        np.asarray([[0.60, 0.20, 0.20]]), np.asarray([[0.90, 0.20, 0.20]]), record["wall_spec"], 1e-6
    )
    assert len(events) == 1
    assert events[0]["kind"] == "obstacle"
    assert events[0]["obstacle_id"] == "center_obstacle"


def test_audit_records_saved_frame_interval_for_swept_crossing(tmp_path: Path):
    record = next(item for item in gate.records() if item["background_id"] == "plain_dam_break")
    h5_path = tmp_path / "swept.h5"
    with h5py.File(h5_path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 0.5, 1.0])
        h5.create_dataset("particle_id", data=[1])
        h5.create_dataset("particle_zone", data=[0])
        h5.create_dataset("valid", data=[[True], [True], [True]])
        h5.create_dataset("position", data=np.asarray([
            [[0.5, 0.38, 0.30]],
            [[0.5, 0.42, 0.30]],
            [[0.5, 0.38, 0.30]],
        ], dtype=np.float32))
        h5.create_dataset("velocity", data=np.zeros((3, 1, 3), dtype=np.float32))
        for name, value in (("density", 1000.0), ("mass", 1.0), ("pressure", 0.0)):
            h5.create_dataset(name, data=np.full((3, 1), value, dtype=np.float32))
        h5.create_dataset("type", data=np.full((3, 1), 3, dtype=np.int8))
        h5.create_dataset("mk", data=np.zeros((3, 1), dtype=np.int16))
    result = gate.audit_hdf5(record, h5_path, None)
    assert result["penetration"]["frames_with_swept_crossing"] == 1
    assert result["penetration"]["swept_crossings_by_face"]["back"] == 1
    assert result["penetration"]["first_swept_crossing"]["time_interval_s"] == [0.0, 0.5]
    assert result["penetration"]["first_swept_crossing"]["time_semantics"] == "saved_frame_interval_linear_chord_locator"
    assert "swept_finite_wall_or_obstacle_crossing" in result["issues"]


def test_audit_hdf5_detects_reappearing_identity_and_keeps_missing_log_unknown(tmp_path: Path):
    record = next(item for item in gate.records() if item["background_id"] == "plain_dam_break")
    h5_path = tmp_path / "synthetic.h5"
    with h5py.File(h5_path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 0.5, 1.0])
        h5.create_dataset("particle_id", data=[1, 2])
        h5.create_dataset("particle_zone", data=[0, 0])
        h5.create_dataset("valid", data=[[True, True], [True, False], [True, True]])
        position = np.asarray([
            [[0.1, 0.1, 0.1], [0.2, 0.1, 0.1]],
            [[0.2, 0.1, 0.1], [np.nan, np.nan, np.nan]],
            [[0.4, 0.1, 0.1], [0.3, 0.1, 0.1]],
        ], dtype=np.float32)
        velocity = np.zeros_like(position)
        h5.create_dataset("position", data=position)
        h5.create_dataset("velocity", data=velocity)
        for name, value in (("density", 1000.0), ("mass", 1.0), ("pressure", 0.0)):
            h5.create_dataset(name, data=np.full((3, 2), value, dtype=np.float32))
        h5.create_dataset("type", data=np.full((3, 2), 3, dtype=np.int8))
        h5.create_dataset("mk", data=np.zeros((3, 2), dtype=np.int16))
    result = gate.audit_hdf5(record, h5_path, None)
    assert result["identities_reappeared_after_gap"] == 1
    assert result["excluded_particles_from_solver_log"] is None
    assert "excluded_particle_evidence_unknown" in result["unknowns"]

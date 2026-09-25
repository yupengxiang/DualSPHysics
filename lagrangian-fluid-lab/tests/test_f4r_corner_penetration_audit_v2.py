from __future__ import annotations

import hashlib

import h5py
import numpy as np
import pytest

from scripts import f4r_corner_penetration_audit_v2 as audit


def test_saved_chord_can_cross_finite_face_before_endpoint_leaves_corner_aabb():
    times = np.asarray([0.16, 0.18])
    positions = np.asarray([[[0.01, 0.388, 0.01]], [[-0.01, 0.41, 0.01]]])
    velocities = np.zeros_like(positions)
    valid = np.ones((2, 1), dtype=bool)

    result = audit.analyze_selected_tracks(times, positions, velocities, valid, [67069])
    track = result["tracks"][0]

    assert track["finite_face_endpoint_violation_frame_count"] == 0
    assert track["outside_tank_aabb_frame_count"] == 1
    assert track["outside_tank_aabb_frames_without_finite_wall_endpoint"] == [1]
    assert len(result["finite_wall_saved_chord_outward_crossings"]) == 1
    event = result["finite_wall_saved_chord_outward_crossings"][0]
    assert (event["face"], event["from_frame"], event["to_frame"]) == ("left", 0, 1)
    assert event["crossing_position_m"][1] < audit.WALL_BOUNDS["ymax"]
    assert result["saved_chord_is_exact_solver_substep_path"] is False


def test_open_top_is_in_tank_aabb_but_not_a_closed_wall_endpoint():
    times = np.asarray([0.0, 1.0])
    positions = np.asarray([[[0.6, 0.2, 0.59]], [[0.6, 0.2, 0.61]]])
    velocities = np.zeros_like(positions)
    valid = np.ones((2, 1), dtype=bool)

    result = audit.analyze_selected_tracks(times, positions, velocities, valid, [67069])
    track = result["tracks"][0]

    assert track["finite_face_endpoint_violation_frame_count"] == 0
    assert track["outside_tank_aabb_frame_count"] == 1
    assert track["outside_tank_aabb_frames_without_finite_wall_endpoint"] == [1]
    assert result["finite_wall_saved_chord_outward_crossings"] == []


def test_mass_summary_keeps_six_cell_denominator_and_no_rescaling():
    cells = []
    for background in ("center", "offset"):
        for dp in (0.00818181818181818, 0.0075, 0.006):
            cells.append({
                "case_id": f"F4R_{background}_dp{dp}",
                "dp_m": dp,
                "discrete_source_mass_kg": list(audit.CONTINUOUS_SOURCE_MASS_KG),
                "continuous_source_mass_kg": list(audit.CONTINUOUS_SOURCE_MASS_KG),
                "source_mass_relative_errors": [0.0, 0.0],
            })
    result = audit._mass_summary(cells)
    assert len(result["cells"]) == 6
    assert result["mass_rescaling_applied"] is False
    assert result["all_six_total_mass_span"]["spread_fraction_of_max"] == 0.0


def test_hash_mismatch_fails_before_hdf5_open(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("particle_id", data=np.asarray([1], dtype=np.uint32))
    monkeypatch.setattr(audit.h5py, "File", lambda *_args, **_kwargs: pytest.fail("HDF5 opened before hash check"))

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        audit.scan_hdf5_case(
            path,
            expected_sha256="0" * 64,
            expected_frames=2,
            expected_particles=1,
            expected_initial=[],
            relative_path="synthetic.h5",
        )


def test_synthetic_hdf5_scan_uses_expected_id_and_fd_hash(tmp_path):
    path = tmp_path / "synthetic.h5"
    ids = np.asarray(audit.EXPECTED_PARTICLE_IDS, dtype=np.uint32)
    times = np.asarray([0.0, 1.0], dtype=np.float64)
    positions = np.zeros((2, len(ids), 3), dtype=np.float32)
    positions[0, :, :] = np.asarray([0.1, 0.2, 0.2])
    positions[1, :, :] = np.asarray([0.2, 0.2, 0.2])
    with h5py.File(path, "w") as h5:
        h5.create_dataset("particle_id", data=ids)
        h5.create_dataset("time", data=times)
        h5.create_dataset("position", data=positions)
        h5.create_dataset("velocity", data=np.zeros_like(positions))
        h5.create_dataset("valid", data=np.ones((2, len(ids)), dtype=np.uint8))
        h5.create_dataset("mk", data=np.ones((2, len(ids)), dtype=np.uint8))
    expected_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    expected_initial = [
        {"id": int(particle_id), "position": positions[0, column].tolist(), "source_mk": 1}
        for column, particle_id in enumerate(ids)
    ]
    result = audit.scan_hdf5_case(
        path,
        expected_sha256=expected_sha,
        expected_frames=2,
        expected_particles=len(ids),
        expected_initial=expected_initial,
        relative_path="synthetic.h5",
    )
    assert result["fd_identity_stable"] is True
    assert result["source"]["sha256"] == expected_sha
    assert result["initial_corner_particles"][0]["particle_id"] == audit.EXPECTED_PARTICLE_IDS[0]
    assert result["track_summary"]["tracks"][0]["valid_frame_count"] == 2


def test_output_directory_is_published_atomically_and_never_replaced(tmp_path):
    masses = {
        "cells": [],
        "continuous_total_mass_kg": 52.416,
        "cross_resolution_spread_by_background": {
            "center": {"spread_fraction_of_max": 0.0},
            "offset": {"spread_fraction_of_max": 0.0},
        },
        "all_six_total_mass_span": {"spread_fraction_of_max": 0.0},
    }
    receipt = {
        "scope": {"float32_initial_geometry_comparison_tolerance_m": audit.INITIAL_GEOMETRY_TOLERANCE_M},
        "mass_summary_from_bound_six_cell_forensics": masses,
        "resource_policy_and_observation": {"hdf5_bytes_hashed": 0},
    }
    output_dir = tmp_path / "published"

    receipt_path, report_path = audit.write_outputs(receipt, output_dir=output_dir)

    assert receipt_path.is_file()
    assert report_path.is_file()
    assert sorted(path.name for path in output_dir.iterdir()) == ["receipt.json", "report.zh-CN.md"]
    with pytest.raises(FileExistsError):
        audit.write_outputs(receipt, output_dir=output_dir)

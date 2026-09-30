from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts.ds_data02_f3_surface_audit import audit_surfaces


def _write_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    operators = tmp_path / "operators.json"
    operators.write_text(json.dumps({"schema": "ds02.f3.weak-dual-operators.v1"}))
    event_definitions = tmp_path / "event-definitions.json"
    event_definitions.write_text(json.dumps({
        "schema": "ds-data-02.f3.event_definitions.v1",
        "finite_surfaces": [
            {"event_id": "left_right_exchange", "surface": "x=0", "normal_in_tank_frame": [1, 0, 0]},
            {"event_id": "front_back_exchange", "surface": "y=0", "normal_in_tank_frame": [0, 1, 0]},
            {"event_id": "top_open_exit", "surface": "z=0.51", "normal_in_tank_frame": [0, 0, 1]},
        ],
    }))
    owner = tmp_path / "owner.json"
    owner.write_text(json.dumps({
        "physical_case_id": "F3_DUAL_AXIS_WEAK_006G_004G",
        "physical_binding": {
            "schema": "ds-data-02.physical-binding.v1",
            "geometry": {
                "top_open": True,
                "tank": {"low_m": [-0.45, -0.09, 0.0], "size_m": [0.9, 0.18, 0.51]},
            },
        },
    }))
    return operators, event_definitions, owner


def _write_trajectory(path: Path) -> None:
    # p0 crosses x=0 twice; p1 crosses y=0; p2 leaves through the legal top;
    # p3 crosses x=0 outside the finite y aperture and must be rejected.
    positions = np.asarray([
        [[-0.10, 0.00, 0.04], [0.20, -0.05, 0.04], [0.10, 0.01, 0.49], [-0.60, 0.20, 0.04]],
        [[ 0.10, 0.00, 0.04], [0.20,  0.05, 0.04], [0.10, 0.01, 0.52], [ 0.60, 0.20, 0.04]],
        [[-0.10, 0.00, 0.04], [0.20,  0.05, 0.04], [0.10, 0.01, 0.52], [ 0.60, 0.20, 0.04]],
    ], dtype="f4")
    frames, particles = positions.shape[:2]
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=np.asarray([0.0, 1.0, 2.0], dtype="f8"))
        h5.create_dataset("particle_id", data=np.asarray([10, 11, 12, 13], dtype="u4"))
        h5.create_dataset("particle_zone", data=np.zeros(particles, dtype="i2"))
        h5.create_dataset("initial_type", data=np.full(particles, 3, dtype="i1"))
        h5.create_dataset("initial_mk", data=np.ones(particles, dtype="i2"))
        h5.create_dataset("initial_mass", data=np.ones(particles, dtype="f4"))
        h5.create_dataset("valid", data=np.ones((frames, particles), dtype=bool))
        h5.create_dataset("position", data=positions)
        h5.create_dataset("mass", data=np.ones((frames, particles), dtype="f4"))


def test_surface_audit_separates_exchange_from_top_exit_and_rejects_outside_support(tmp_path: Path) -> None:
    operators, event_definitions, owner = _write_sources(tmp_path)
    trajectory = tmp_path / "trajectory.h5"
    report_path = tmp_path / "surface-audit.json"
    _write_trajectory(trajectory)

    report = audit_surfaces(
        h5_path=trajectory,
        output_path=report_path,
        operators_path=operators,
        event_definitions_path=event_definitions,
        owner_metadata_path=owner,
        sample_limit=8,
    )

    left_right = report["surfaces"]["left_right_exchange"]
    front_back = report["surfaces"]["front_back_exchange"]
    top = report["surfaces"]["top_open_exit"]
    assert left_right["accepted_crossings"] == 2
    assert left_right["positive_crossings"] == 1
    assert left_right["negative_crossings"] == 1
    assert left_right["aperture_rejected_crossings"] == 1
    assert left_right["repeat_crossings"] == 1
    assert front_back["accepted_crossings"] == 1
    assert top["accepted_crossings"] == 1
    assert top["classification"] == "legal_open_exit_diagnostic"
    assert left_right["classification"] == "in_domain_transport_interface"
    assert left_right["sample_events_with_neighboring_states"][0]["idp"] == 10
    assert left_right["sample_events_with_neighboring_states"][0]["crossing_time_s"] == 0.5
    assert report["trajectory"]["final_category_counts"]["above_open_top"] == 1
    assert report_path.is_file()


def test_surface_audit_does_not_hash_h5_when_hash_is_only_declared(tmp_path: Path) -> None:
    operators, event_definitions, owner = _write_sources(tmp_path)
    trajectory = tmp_path / "trajectory.h5"
    _write_trajectory(trajectory)
    report = audit_surfaces(
        h5_path=trajectory,
        output_path=tmp_path / "report.json",
        operators_path=operators,
        event_definitions_path=event_definitions,
        owner_metadata_path=owner,
        expected_h5_sha256="declared-source-hash",
        sample_limit=0,
    )
    assert report["source"]["binding"]["h5_sha256_status"] == "declared_only_not_rehashed"
    assert report["source"]["hdf5_modified"] is False

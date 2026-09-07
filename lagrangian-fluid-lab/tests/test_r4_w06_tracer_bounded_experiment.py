"""Contract tests for the bounded W06 wall-aware tracer experiment."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts" / "r4_w06_tracer_bounded_experiment.py"
SPEC = importlib.util.spec_from_file_location("r4_w06_tracer_bounded", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_experiment_matrix_and_candidate_semantics_are_explicit():
    assert MODULE.CASE_ID == "W06_standard_slow_center"
    assert MODULE.SEED_COUNTS == (32, 64)
    assert MODULE.SUBSTEPS == (1, 4)
    assert MODULE.DESTINATION_SPEC["lifecycle_model"] == "closed"
    assert MODULE.DESTINATION_SPEC["destination_frame"] == {"kind": "world"}
    assert MODULE.DESTINATION_SPEC["sources"] == {"mode": "mk"}
    assert MODULE.BOUNDARY_POLICY["formal_wall_aware_admission"] is False
    assert set(MODULE.BOUNDARY_POLICY["component_roles"]) == {"17", "18", "19"}


def test_input_summary_binds_release_hdf5_sidecar_and_time_axis():
    record = MODULE._load_manifest_record()
    summary = MODULE._input_summary(record)
    assert summary["case_id"] == MODULE.CASE_ID
    assert summary["frames"] == 251
    assert summary["initial_fluid_particles"] == 1764
    assert summary["sidecar_audit"]["all_frames_finite"] is True
    assert summary["sidecar_audit"]["all_frames_nondegenerate"] is True
    assert set(summary["sidecar_components"]) == {"17", "18", "19"}


def test_mass_ledger_keeps_destination_complement_and_failure_mass_closed():
    trace = {
        "position": np.asarray([
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            [[0.5, 0.0, 0.1], [0.0, 0.0, 0.0]],
        ]),
        "reliability_history": np.asarray([[True, True], [True, False]]),
        "wall_crossing": np.asarray([[False, True]]),
        "support_gate_pass": np.asarray([[True, True]]),
        "nearest_support_distance": np.asarray([[0.01, 0.01]]),
        "effective_sample_size": np.asarray([[2.0, 2.0]]),
        "support_geometry_rank": np.asarray([[3, 3]]),
        "support_anisotropy": np.asarray([[1.0, 1.0]]),
        "interpolation_reconstruction_error_mps": np.asarray([[0.0, 0.0]]),
    }
    rows = MODULE._mass_row(
        0.1,
        1,
        trace,
        np.asarray([1, 2]),
        np.asarray([2.0, 3.0]),
        {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
        {"name": "inside_receiver", "type": "aabb", "min": [0.25, -0.25, 0.0], "max": [0.75, 0.25, 0.5]},
    )
    by_source = {row["source_mk"]: row for row in rows}
    assert by_source[1]["mass_inside_receiver_kg"] == 2.0
    assert by_source[2]["mass_wall_crossing_kg"] == 3.0
    assert sum(value for key, value in by_source[1].items() if key.startswith("mass_")) == 2.0
    assert sum(value for key, value in by_source[2].items() if key.startswith("mass_")) == 3.0

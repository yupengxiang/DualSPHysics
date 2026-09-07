"""CPU-only contract and evaluator tests for the R5 F1 material task."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

import h5py
import numpy as np
import pytest


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts" / "r5_f1_material_task.py"
SPEC = importlib.util.spec_from_file_location("r5_f1_material_task", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Create a tiny real HDF5/finite-sidecar pair, not a mocked evaluator."""
    hdf5_path = tmp_path / "R5_F1_single_obstacle_fixture.h5"
    sidecar_path = tmp_path / "R5_F1_single_obstacle_fixture_sidecar.h5"
    time = np.asarray([0.0, 0.5, 1.0], dtype=np.float64)
    # 3 x 2 x 3 regular fluid lattice: exactly six particles in each of the
    # three initial-depth strata.  Every particle translates uniformly into
    # the frozen downstream target by t=1.
    initial = np.asarray([
        [0.10, 0.10, 0.10], [0.20, 0.10, 0.10], [0.30, 0.10, 0.10],
        [0.10, 0.30, 0.10], [0.20, 0.30, 0.10], [0.30, 0.30, 0.10],
        [0.10, 0.10, 0.30], [0.20, 0.10, 0.30], [0.30, 0.10, 0.30],
        [0.10, 0.30, 0.30], [0.20, 0.30, 0.30], [0.30, 0.30, 0.30],
        [0.10, 0.10, 0.50], [0.20, 0.10, 0.50], [0.30, 0.10, 0.50],
        [0.10, 0.30, 0.50], [0.20, 0.30, 0.50], [0.30, 0.30, 0.50],
    ], dtype=np.float64)
    velocity = np.tile(np.asarray([0.80, 0.0, 0.0]), (len(initial), 1))
    position = np.asarray([initial + frame * 0.5 * velocity for frame in range(len(time))])
    shape = (len(time), len(initial))
    with h5py.File(hdf5_path, "w") as h5:
        h5.attrs["case_id"] = "R5_F1_single_obstacle_fixture"
        h5.attrs["schema_version"] = 3
        h5.attrs["particle_spacing_m"] = 0.1
        h5.create_dataset("time", data=time)
        h5.create_dataset("particle_id", data=np.arange(100, 100 + len(initial), dtype=np.int64))
        h5.create_dataset("particle_zone", data=np.zeros(len(initial), dtype=np.int16))
        h5.create_dataset("valid", data=np.ones(shape, dtype=bool))
        h5.create_dataset("position", data=position)
        h5.create_dataset("velocity", data=np.broadcast_to(velocity, (len(time), *velocity.shape)))
        h5.create_dataset("mass", data=np.ones(shape, dtype=np.float64))
        h5.create_dataset("type", data=np.full(shape, 3, dtype=np.int8))
        h5.create_dataset("mk", data=np.zeros(shape, dtype=np.int16))

    # Two static finite triangles.  They are deliberately outside the fluid
    # path, while their labels exercise the frozen tank/obstacle component
    # registry (17/18) and the sidecar-backed real advector path.
    triangles = np.asarray([
        [[2.0, 2.0, 0.0], [2.0, 2.5, 0.0], [2.0, 2.0, 0.5]],
        [[-2.0, -2.0, 0.0], [-2.0, -2.5, 0.0], [-2.0, -2.0, 0.5]],
    ], dtype=np.float64)
    with h5py.File(sidecar_path, "w") as sidecar:
        sidecar.attrs["case_id"] = "R5_F1_single_obstacle_fixture"
        sidecar.attrs["schema_version"] = "boundary-sidecar-v1"
        sidecar.attrs["coordinate_frame"] = "world"
        sidecar.create_dataset("time", data=time)
        sidecar.create_dataset("triangles_world", data=np.repeat(triangles[None], len(time), axis=0))
        sidecar.create_dataset("triangle_mk", data=np.asarray([17, 18], dtype=np.int64))
        sidecar.create_dataset("triangle_type", data=np.zeros(2, dtype=np.int8))
    return hdf5_path, sidecar_path


def _snapshot_and_seeds(tmp_path: Path, count: int = 6):
    hdf5_path, sidecar_path = _write_fixture(tmp_path)
    spec = MODULE.load_transport_spec()
    snapshot = MODULE.load_input_snapshot(hdf5_path, sidecar_path, spec)
    resolved = MODULE._resolved_spec(spec, 0.1, 0.5, snapshot.case_id)
    seeds = MODULE.select_weighted_seeds(snapshot, count, "fixture_config")
    return hdf5_path, sidecar_path, snapshot, resolved, seeds


def _trace(snapshot, seeds, *, valid=None, wall=None, final_position=None):
    count = len(seeds["mass_weight"])
    frames = len(snapshot.time)
    position = np.repeat(seeds["initial_position"][None, :, :], frames, axis=0)
    if final_position is None:
        final_position = np.tile(np.asarray([1.0, 0.2, 0.2]), (count, 1))
    position[-1] = final_position
    if valid is None:
        valid = np.ones((frames, count), dtype=bool)
    trace = {
        "time": snapshot.time.copy(),
        "position": position,
        "valid": np.asarray(valid, dtype=bool),
        "particle_spacing_m": 0.1,
        "maximum_support_distance": 0.175,
        "wall_crossing": np.zeros((frames - 1, count), dtype=bool),
        "support_gate_pass": np.ones((frames - 1, count), dtype=bool),
        "nearest_support_distance": np.full((frames - 1, count), 0.01),
        "effective_sample_size": np.full((frames - 1, count), 2.0),
        "support_geometry_rank": np.full((frames - 1, count), 3),
        "support_anisotropy": np.ones((frames - 1, count)),
        "interpolation_reconstruction_error_mps": np.zeros((frames - 1, count)),
    }
    if wall is not None:
        trace["wall_crossing"] = np.asarray(wall, dtype=bool)
    return trace


def test_versioned_contract_is_explicit_and_measure_only():
    spec = MODULE.load_transport_spec()
    assert spec["version"] == "r5.1.0"
    assert spec["sources"]["layer_order"] == ["lower", "middle", "upper"]
    assert spec["sources"]["measure_only"] is True
    assert spec["sources"]["labels_are_not_material_identity"] is True
    assert spec["wall"]["component_roles"]["17"]["open_faces"] == ["top"]
    assert spec["wall"]["component_roles"]["18"]["open_faces"] == ["bottom"]
    assert spec["wall"]["rim_policy"] == "finite_generated_triangles_only"
    assert set(spec["terminal_categories"]) == set(MODULE.TERMINAL_CATEGORIES)


def test_real_cpu_run_writes_four_bounded_trace_bundles(tmp_path):
    hdf5_path, sidecar_path = _write_fixture(tmp_path)
    report = MODULE.run_bounded(
        hdf5_path,
        sidecar_path,
        output_dir=tmp_path / "outputs",
        seed_counts=(6, 8),
        substeps=(1, 2),
    )
    assert report["execution_status"] == "completed"
    assert report["acceptance_status"] == "candidate_only_not_physical_acceptance"
    assert len(report["configurations"]) == 4
    assert report["controls"]["solver_rerun"] is False
    assert report["controls"]["gencase_rerun"] is False
    assert report["controls"]["gpu_used"] is False
    assert report["hashes"]["input_hdf5_sha256"]
    assert report["hashes"]["input_sidecar_sha256"]
    assert report["mass_accounting"]["initial_mass_kg"] == pytest.approx(18.0)
    assert set(report["mass_accounting"]["categories"]) == set(MODULE.TERMINAL_CATEGORIES)
    assert set(report["checks"]) >= {
        "identity_unique", "destination_disjoint", "mass_closed",
        "wall_policy_explicit", "tracer_failure_is_censored",
    }
    for config in report["configurations"]:
        assert config["mass_accounting"]["closure_error_kg"] == pytest.approx(0.0)
        assert config["mass_accounting"]["categories_kg"]["target"] == pytest.approx(18.0)
        bundle = LAB / config["trajectory_bundle"]
        # The bundle is under tmp_path, so resolve the report's relative path
        # directly from the recorded output path instead of relying on LAB.
        bundle = tmp_path / "outputs" / Path(config["trajectory_bundle"]).name
        with h5py.File(bundle, "r") as h5:
            assert h5.attrs["schema_version"] == MODULE.OUTPUT_SCHEMA_VERSION
            assert bool(h5.attrs["source_label_measure_only"])
            assert set(h5["source_label"].asstr()[:]) == set(MODULE.SOURCE_LABELS)
            assert h5["position"].shape[1] == config["seed_count"]
            assert h5["failure/reason"].shape == (2, config["seed_count"])
            assert h5["destination/first_passage_status"].asstr()[0] == "observed"


def test_initial_depth_labels_and_weights_close_by_layer(tmp_path):
    _hdf5, _sidecar, snapshot, _resolved, seeds = _snapshot_and_seeds(tmp_path, 6)
    assert dict(zip(MODULE.SOURCE_LABELS, [int(np.sum(snapshot.initial_source_labels == label)) for label in MODULE.SOURCE_LABELS])) == {
        "lower": 6,
        "middle": 6,
        "upper": 6,
    }
    assert set(seeds["source_label"]) == set(MODULE.SOURCE_LABELS)
    assert np.sum(seeds["mass_weight"]) == pytest.approx(snapshot.input_summary["initial_fluid_mass_kg"])
    for label in MODULE.SOURCE_LABELS:
        assert np.sum(seeds["mass_weight"][seeds["source_label"] == label]) == pytest.approx(6.0)


def test_identity_mismatch_is_rejected(tmp_path):
    _hdf5, _sidecar, snapshot, resolved, seeds = _snapshot_and_seeds(tmp_path)
    bad = dict(seeds)
    bad["reference_particle_id"] = seeds["reference_particle_id"].copy()
    bad["reference_particle_id"][0] += 1000
    trace = _trace(snapshot, seeds)
    with pytest.raises(ValueError, match="identity"):
        MODULE._classify_trace(trace, bad, snapshot, resolved, "fixture_config", 6, 1)


def test_duplicate_target_assignment_is_rejected(tmp_path):
    _hdf5, _sidecar, snapshot, resolved, seeds = _snapshot_and_seeds(tmp_path)
    bad_spec = deepcopy(resolved)
    duplicate = deepcopy(bad_spec["destinations"][0])
    duplicate["name"] = "duplicate_target"
    bad_spec["destinations"].append(duplicate)
    with pytest.raises(ValueError, match="duplicate target"):
        MODULE._classify_trace(_trace(snapshot, seeds), seeds, snapshot, bad_spec, "fixture_config", 6, 1)


def test_mass_leak_is_rejected_against_initial_denominator(tmp_path):
    _hdf5, _sidecar, snapshot, resolved, seeds = _snapshot_and_seeds(tmp_path)
    bad = dict(seeds)
    bad["mass_weight"] = seeds["mass_weight"].copy()
    bad["mass_weight"][0] *= 0.5
    with pytest.raises(ValueError, match="mass leak"):
        MODULE._classify_trace(_trace(snapshot, seeds), bad, snapshot, resolved, "fixture_config", 6, 1)


def test_wall_crossing_is_failure_and_censors_first_passage(tmp_path):
    _hdf5, _sidecar, snapshot, resolved, seeds = _snapshot_and_seeds(tmp_path)
    wall = np.zeros((2, len(seeds["mass_weight"])), dtype=bool)
    wall[0, 0] = True
    result = MODULE._classify_trace(
        _trace(snapshot, seeds, wall=wall),
        seeds, snapshot, resolved, "fixture_config", 6, 1,
    )
    assert result["first_failure_reason"][0] == "wall_crossing"
    assert not result["valid"][1:, 0].any()
    assert result["first_passage_frame"][0] == -1
    assert result["first_passage_status"][0] == "censored_by_tracer_failure"
    assert result["terminal_category"][0] == "tracer_unknown"
    assert result["summary"]["mass_accounting"]["categories_kg"]["tracer_unknown"] == pytest.approx(3.0)


def test_solver_identity_loss_is_reported_separately_from_tracer_unknown(tmp_path):
    _hdf5, _sidecar, snapshot, resolved, seeds = _snapshot_and_seeds(tmp_path)
    snapshot.solver_valid[1, seeds["reference_index"][0]] = False
    result = MODULE._classify_trace(
        _trace(snapshot, seeds), seeds, snapshot, resolved, "fixture_config", 6, 1,
    )
    assert result["first_failure_reason"][0] == "solver_identity_missing"
    assert result["first_passage_status"][0] == "censored_by_numerical_loss"
    assert result["terminal_category"][0] == "numerical_loss"
    assert result["summary"]["mass_accounting"]["categories_kg"]["numerical_loss"] == pytest.approx(3.0)


def test_tracer_failure_is_not_encoded_as_no_event(tmp_path):
    _hdf5, _sidecar, snapshot, resolved, seeds = _snapshot_and_seeds(tmp_path)
    valid = np.ones((3, len(seeds["mass_weight"])), dtype=bool)
    valid[1:, 0] = False
    # The stale post-failure coordinates are inside the target.  They must be
    # ignored because valid is false; otherwise the evaluator would invent a
    # first passage after the tracer had already failed.
    positions = np.repeat(seeds["initial_position"][None, :, :], 3, axis=0)
    positions[1:, 0] = [1.0, 0.2, 0.2]
    trace = _trace(snapshot, seeds, valid=valid)
    trace["position"] = positions
    result = MODULE._classify_trace(trace, seeds, snapshot, resolved, "fixture_config", 6, 1)
    assert result["first_passage_frame"][0] == -1
    assert result["first_passage_status"][0] == "censored_by_tracer_failure"
    assert result["first_passage_censored"][0] is np.True_ or bool(result["first_passage_censored"][0])
    assert result["terminal_category"][0] == "tracer_unknown"
    assert result["summary"]["mass_accounting"]["categories_kg"]["target"] < 18.0


def test_bounded_configuration_limit_is_enforced(tmp_path):
    hdf5_path, sidecar_path = _write_fixture(tmp_path)
    with pytest.raises(ValueError, match="bounded material run"):
        MODULE.run_bounded(
            hdf5_path,
            sidecar_path,
            output_dir=tmp_path / "outputs",
            seed_counts=(3, 4, 5),
            substeps=(1, 2, 3),
        )

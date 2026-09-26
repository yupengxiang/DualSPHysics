"""Synthetic-only tests for the streaming/recovery F3 material evaluator."""
from __future__ import annotations

import hashlib
import copy
from collections import Counter

import h5py
import numpy as np
import pytest

from scripts.f3_native_volume_mls_model_material import (
    MODEL_ROLE,
    run_material_trace as run_v1,
)
from scripts import f3_native_volume_mls_model_material_v2 as material_v2
from scripts.f3_native_volume_mls_model_material_v2 import (
    _advance_rk4_with_first_failure,
    _row_values,
    run_material_trace as run_v2,
)
from scripts.f3_native_volume_mls_temporal_v3 import MLSResult, _new_state


def _synthetic_source(path, *, frames=3):
    axis = np.asarray([-0.015, 0.0, 0.015], dtype=np.float64)
    points = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1).reshape(-1, 3)
    velocity = np.column_stack((
        np.full(len(points), -0.10),
        0.2 * points[:, 1],
        -0.1 * points[:, 2],
    ))
    times = np.arange(frames, dtype=np.float64) * 0.01
    with h5py.File(path, "w") as handle:
        handle.attrs.update(
            schema_version=1,
            state_schema="core.state.native_velocity.v1",
            velocity_semantics="native saved numerical velocity",
            future_state_inputs=False,
            autonomous_prediction=True,
            identity_semantics="particle_zone,particle_id",
        )
        handle["time"] = times
        handle["position"] = np.stack([points + i * 0.0001 * velocity for i in range(frames)])
        handle["velocity"] = np.stack([velocity for _ in range(frames)])
        handle["particle_id"] = np.arange(len(points), dtype=np.int64)
        handle["particle_zone"] = np.zeros(len(points), dtype=np.int64)
        handle["mass"] = np.full(len(points), 1.0e-6)
        handle["valid"] = np.ones((frames, len(points)), dtype=bool)


def _inputs(source, output, **overrides):
    values = {
        "source": source,
        "output": output,
        "role": MODEL_ROLE,
        "rho0_kgm3": 1000.0,
        "dp_m": 0.015,
        "seeds": np.asarray([
            [-0.001, 0.0, 0.0], [-0.0005, 0.001, 0.001],
            [0.0005, -0.001, -0.001], [0.001, 0.0, 0.0],
        ], dtype=np.float64),
        "intervals": 2,
        "substeps": 2,
        "walls": np.empty((0, 3, 3), dtype=np.float64),
    }
    values.update(overrides)
    return values


def _dataset_value(dataset):
    if h5py.check_string_dtype(dataset.dtype) is not None:
        return np.asarray(dataset.asstr())
    return np.asarray(dataset)


def _assert_trace_datasets_equal(left, right):
    with h5py.File(left, "r") as lhs, h5py.File(right, "r") as rhs:
        assert set(lhs) == set(rhs)
        for name in lhs:
            if isinstance(lhs[name], h5py.Group):
                assert set(lhs[name]) == set(rhs[name])
                for child in lhs[name]:
                    np.testing.assert_array_equal(
                        _dataset_value(lhs[name][child]), _dataset_value(rhs[name][child]),
                        err_msg=f"dataset mismatch: {name}/{child}",
                    )
            else:
                np.testing.assert_array_equal(
                    _dataset_value(lhs[name]), _dataset_value(rhs[name]),
                    err_msg=f"dataset mismatch: {name}",
                )
        assert int(lhs.attrs["committed_rows"]) == int(rhs.attrs["committed_rows"])
        assert lhs.attrs["binding_json"] == rhs.attrs["binding_json"]
        assert lhs.attrs["qualification_claim"] == rhs.attrs["qualification_claim"] == "none"


def _assert_scientific_summary_equal(v1_report, v2_report):
    assert v2_report["qualification_claim"] == "none"
    assert v2_report["material_reliability"] == "not_established"
    assert v1_report["source_rows"] == v2_report["source_rows"]
    assert v1_report["unknown_fraction_max"] == v2_report["unknown_fraction_max"]
    assert v1_report["unknown_fraction_final"] == v2_report["unknown_fraction_final"]
    assert v1_report["unknown_fraction_by_frame"] == v2_report["unknown_fraction_by_frame"]
    assert v1_report["common_reliable_path_fraction"] == v2_report["common_reliable_path_fraction"]
    assert v1_report["mass_closure"] == v2_report["mass_closure"]
    assert v1_report["diagnostics"]["stage_failure_counts"] == v2_report["diagnostics"]["stage_failure_counts"]


def test_streaming_synthetic_summary_and_trace_match_v1(tmp_path):
    source = tmp_path / "synthetic-model.h5"
    _synthetic_source(source)
    v1_output = tmp_path / "v1-trace.h5"
    v2_output = tmp_path / "v2-trace.h5"
    args1 = _inputs(source, v1_output)
    args2 = _inputs(source, v2_output)

    report1 = run_v1(**args1)
    report2 = run_v2(**args2)

    _assert_scientific_summary_equal(report1, report2)
    actual_hash = hashlib.sha256(v2_output.read_bytes()).hexdigest()
    assert report2["trace_h5_sha256"] == actual_hash
    with h5py.File(v1_output, "r") as old, h5py.File(v2_output, "r") as new:
        for name in old:
            np.testing.assert_array_equal(
                _dataset_value(old[name]), _dataset_value(new[name]), err_msg=name,
            )
        assert new["position"].maxshape[0] is None
        assert new.attrs["qualification_claim"] == "none"


def test_interruption_resume_matches_uninterrupted_trace_exactly(tmp_path):
    source = tmp_path / "synthetic-model.h5"
    _synthetic_source(source)
    continuous = tmp_path / "continuous.h5"
    resumed = tmp_path / "resumed.h5"

    full_report = run_v2(**_inputs(source, continuous))
    stopped = run_v2(**_inputs(source, resumed, stop_after_steps=1))
    assert stopped["status"] == "interrupted"
    assert stopped["completed_substeps"] == 1
    with h5py.File(resumed, "r") as handle:
        assert int(handle.attrs["committed_rows"]) == 2
        assert len(handle["_journal/commit_log"]) == 2

    resumed_report = run_v2(**_inputs(source, resumed, resume=True))
    assert resumed_report["status"] == "completed"
    _assert_trace_datasets_equal(continuous, resumed)
    _assert_scientific_summary_equal(full_report, resumed_report)


def test_resume_rejects_changed_source_bytes_and_parameters(tmp_path):
    source = tmp_path / "synthetic-model.h5"
    _synthetic_source(source)
    trace = tmp_path / "resume.h5"
    args = _inputs(source, trace, stop_after_steps=1)
    assert run_v2(**args)["status"] == "interrupted"

    changed_parameters = _inputs(source, trace, resume=True, rho0_kgm3=1001.0)
    with pytest.raises(ValueError, match="binding mismatch"):
        run_v2(**changed_parameters)

    with h5py.File(source, "r+") as handle:
        handle.attrs["synthetic_mutation"] = "changes source bytes"
    with pytest.raises(ValueError, match="binding mismatch"):
        run_v2(**_inputs(source, trace, resume=True))


def test_resume_rejects_changed_transitive_implementation_dependency(tmp_path, monkeypatch):
    source = tmp_path / "synthetic-model.h5"
    _synthetic_source(source)
    trace = tmp_path / "dependency-change.h5"
    assert run_v2(**_inputs(source, trace, stop_after_steps=1))["status"] == "interrupted"

    original_binding = material_v2._implementation_binding
    changed_binding = copy.deepcopy(original_binding())
    changed_binding["local_execution_dependencies"]["core_material.py"]["sha256"] = "0" * 64
    monkeypatch.setattr(material_v2, "_implementation_binding", lambda: changed_binding)
    with pytest.raises(ValueError, match="binding mismatch"):
        run_v2(**_inputs(source, trace, resume=True))


def test_resume_truncates_only_uncommitted_hdf5_tail(tmp_path):
    source = tmp_path / "synthetic-model.h5"
    _synthetic_source(source)
    continuous = tmp_path / "continuous.h5"
    resumed = tmp_path / "tail.h5"
    run_v2(**_inputs(source, continuous))
    assert run_v2(**_inputs(source, resumed, stop_after_steps=1))["status"] == "interrupted"

    # Simulate a row payload that was extended but never entered in the commit log.
    with h5py.File(resumed, "r+") as handle:
        dataset = handle["time"]
        dataset.resize((len(dataset) + 1,))
        dataset[-1] = 12345.0
        assert int(handle.attrs["committed_rows"]) == 2

    report = run_v2(**_inputs(source, resumed, resume=True))
    assert report["status"] == "completed"
    _assert_trace_datasets_equal(continuous, resumed)


def test_resume_fails_closed_on_committed_prefix_corruption(tmp_path):
    source = tmp_path / "synthetic-model.h5"
    _synthetic_source(source)
    trace = tmp_path / "corrupt.h5"
    run_v2(**_inputs(source, trace, stop_after_steps=1))
    with h5py.File(trace, "r+") as handle:
        handle["position"][0, 0, 0] += 1.0e-8
    with pytest.raises(ValueError, match="integrity|commit-log"):
        run_v2(**_inputs(source, trace, resume=True))


def test_output_is_not_silently_overwritten(tmp_path):
    source = tmp_path / "synthetic-model.h5"
    _synthetic_source(source)
    trace = tmp_path / "once.h5"
    run_v2(**_inputs(source, trace, stop_after_steps=0))
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        run_v2(**_inputs(source, trace))


class _StageSequenceTracer:
    def __init__(self, stage_results):
        self.stage_results = stage_results
        self.calls = 0

    def reconstruct(self, query, _frame, _walls):
        result = self.stage_results[self.calls]
        self.calls += 1
        return result


class _DummyProvider:
    def field_at(self, _interval, time_s):
        return time_s


def _stage_result(*, reliable, reason, velocity=(0.0, 0.0, 0.0)):
    return MLSResult(
        np.asarray([velocity], dtype=np.float64),
        np.asarray([8], dtype=np.int64), np.asarray([8], dtype=np.int64),
        np.asarray([0], dtype=np.int64), np.asarray([8.0]), np.asarray([4]),
        np.asarray([1.0]), np.asarray([0.5]), np.asarray([0.0]),
        np.asarray([reliable]), np.asarray([reliable]), np.asarray([reliable]),
        np.asarray([reason], dtype=object),
    )


def test_rk4_records_first_unreliable_stage_even_when_k4_recovers():
    initial = np.asarray([[0.1, 0.0, 0.0]], dtype=np.float64)
    state = _new_state(initial, np.asarray([1], dtype=np.int8))
    state["reliable"][:] = True
    state["permanent_unknown"][:] = False
    state["failure_reason"] = np.asarray(["reliable"], dtype=object)
    tracer = _StageSequenceTracer([
        _stage_result(reliable=False, reason="k1_wall_occluded"),
        _stage_result(reliable=True, reason="reliable"),
        _stage_result(reliable=True, reason="reliable"),
        _stage_result(reliable=True, reason="reliable"),
    ])

    result = _advance_rk4_with_first_failure(
        state, tracer, _DummyProvider(), np.empty((0, 3, 3)), 0, 0.0, 0.1,
        {"stage_failure_counts": Counter()},
    )

    assert tracer.calls == 4
    assert not state["reliable"][0]
    assert state["permanent_unknown"][0]
    assert state["failure_reason"][0] == "k1_wall_occluded"
    np.testing.assert_array_equal(state["position"], initial)
    assert _row_values(state, result, 0.1)["failure_reason"].tolist() == ["k1_wall_occluded"]


def test_trace_persists_first_failed_stage_reason(tmp_path, monkeypatch):
    source = tmp_path / "synthetic-model.h5"
    _synthetic_source(source)
    output = tmp_path / "first-stage-failure.h5"
    results = iter([
        _stage_result(reliable=True, reason="reliable"),  # initial state
        _stage_result(reliable=False, reason="k1_wall_occluded"),
        _stage_result(reliable=True, reason="reliable"),
        _stage_result(reliable=True, reason="reliable"),
        _stage_result(reliable=True, reason="reliable"),
        _stage_result(reliable=True, reason="reliable"),  # later interval cannot revive it
        _stage_result(reliable=True, reason="reliable"),
        _stage_result(reliable=True, reason="reliable"),
        _stage_result(reliable=True, reason="reliable"),
    ])
    monkeypatch.setattr(
        material_v2.F3NativeVolumeMLS,
        "reconstruct",
        lambda _self, *_args: next(results),
    )

    report = run_v2(**_inputs(
        source, output, seeds=np.asarray([[0.001, 0.0, 0.0]]),
        intervals=2, substeps=1, walls=np.empty((0, 3, 3)),
    ))

    assert report["status"] == "completed"
    assert report["unknown_fraction_final"] == 1.0
    assert report["unknown_fraction_by_frame"]["fraction"] == [0.0, 1.0, 1.0]
    with h5py.File(output, "r") as handle:
        assert handle["failure_reason"].asstr()[1].tolist() == ["k1_wall_occluded"]
        assert bool(handle["permanent_unknown"][1, 0])
        np.testing.assert_array_equal(handle["position"][1], [[0.001, 0.0, 0.0]])
        assert bool(handle["permanent_unknown"][2, 0])
        assert handle["failure_reason"].asstr()[2].tolist() == ["k1_wall_occluded"]
        np.testing.assert_array_equal(handle["position"][2], handle["position"][1])


def test_rk4_records_earliest_failed_stage_and_preserves_previous_failure():
    initial = np.asarray([[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]], dtype=np.float64)
    state = _new_state(initial, np.asarray([1, 0], dtype=np.int8))
    state["reliable"][:] = [True, False]
    state["permanent_unknown"][:] = [False, True]
    state["failure_reason"] = np.asarray(["reliable", "prior_failure"], dtype=object)
    stage_results = [_stage_result(reliable=False, reason="placeholder") for _ in range(4)]
    # The active seed has distinct per-stage reasons; the inactive seed is
    # already unknown and must retain its original first failure.
    for result, active_reason, inactive_reason in zip(
        stage_results,
        ("k1_ok", "k2_failure", "k3_failure", "k4_ok"),
        ("later_k1", "later_k2", "later_k3", "later_k4"),
    ):
        result.failure_reason = np.asarray([active_reason, inactive_reason], dtype=object)
        result.reliable = np.asarray([active_reason.endswith("_ok"), False])
        result.velocity = np.zeros((2, 3), dtype=np.float64)
        result.support_count = np.full(2, 8, dtype=np.int64)
        result.candidate_count = np.full(2, 8, dtype=np.int64)
        result.wall_rejected_count = np.zeros(2, dtype=np.int64)
        result.effective_sample_size = np.full(2, 8.0)
        result.geometry_rank = np.full(2, 4, dtype=np.int8)
        result.condition_number = np.ones(2)
        result.anisotropy = np.full(2, 0.5)
        result.reconstruction_error_mps = np.zeros(2)
        result.old_gate_pass = np.zeros(2, dtype=bool)
        result.candidate_support_pass = np.zeros(2, dtype=bool)

    _advance_rk4_with_first_failure(
        state, _StageSequenceTracer(stage_results), _DummyProvider(),
        np.empty((0, 3, 3)), 0, 0.0, 0.1,
        {"stage_failure_counts": Counter()},
    )

    assert state["failure_reason"].tolist() == ["k2_failure", "prior_failure"]

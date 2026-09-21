"""Tests for fixed-denominator F3 trace comparison and censoring bounds."""

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.f3_native_volume_mls_compare import _cdf_sup_difference, compare_traces


def _write_trace(path: Path, times: np.ndarray, unknown_frame: int, *,
                 n: int = 512, source_sha256: str = "source-sha",
                 seed_hash: str = "seed-sha", trace_backend: str = "test",
                 walls_sha256: str | None = None, event_definition: dict | None = None,
                 trace_schema: str = "core.material.f3.native_volume_mls.trace.v2") -> None:
    frames = len(times)
    labels = np.r_[np.zeros(n // 2, dtype=np.int8), np.ones(n // 2, dtype=np.int8)]
    initial = np.zeros((n, 3), dtype=np.float64)
    initial[:, 0] = np.linspace(-0.2, 0.2, n)
    positions = np.zeros((frames, n, 3), dtype=np.float64)
    positions[-1, :, 0] = 1.0e-3
    reliable = np.ones((frames, n), dtype=bool)
    reliable[unknown_frame:, 0] = False
    unknown = ~reliable
    first = np.full(n, np.nan, dtype=np.float64)
    first[2] = 0.1
    returned = np.zeros(n, dtype=bool)
    returned[2] = True
    return_time = np.full(n, np.nan, dtype=np.float64)
    return_time[2] = 0.15
    residence = np.full(n, 0.02, dtype=np.float64)
    residence[1] = 0.0  # reliable no-contact seed must remain in residence CDF
    residence[0] = 0.01  # observed lower bound before support loss
    binding = {
        "source_sha256": source_sha256,
        "query_count": n,
        "seed_hash": seed_hash,
        "source_definition": {"kind": "continuous_halfspace", "boundary_m": 0.0},
        "event_definition": event_definition or {
            "first_passage": "crossing", "return": "crossing_back",
        },
        "frame_selection": {"selection_mode": "test-direct-native", "interpolation": False},
    }
    if walls_sha256 is not None:
        binding["walls_sha256"] = walls_sha256
    with h5py.File(path, "w") as handle:
        handle.attrs["schema"] = trace_schema
        handle.attrs["trace_backend"] = trace_backend
        handle.attrs["binding"] = json.dumps(binding, sort_keys=True)
        handle.attrs["committed"] = frames - 1
        handle.attrs["material_reliability"] = "not_established"
        handle.create_dataset("time", data=times)
        handle.create_dataset("initial_position", data=initial)
        handle.create_dataset("source_label", data=labels)
        handle.create_dataset("position", data=positions)
        handle.create_dataset("reliable", data=reliable)
        handle.create_dataset("permanent_unknown", data=unknown)
        for name, value in (("first_passage", first), ("return_time", return_time),
                            ("residence_opposite", residence), ("returned", returned)):
            handle.create_dataset(name, data=np.repeat(value[None, ...], frames, axis=0))
        handle.create_dataset("seed_mass_closure_error", data=np.zeros(frames))


def test_compare_keeps_unknown_and_zero_residence_in_source_denominator(tmp_path):
    left = tmp_path / "left.h5"
    right = tmp_path / "right.h5"
    _write_trace(left, np.array([0.0, 0.1, 0.2]), unknown_frame=1)
    _write_trace(right, np.array([0.0, 0.05, 0.1, 0.15, 0.2]), unknown_frame=2)
    output = tmp_path / "comparison.json"
    result = compare_traces(left, right, output)
    assert output.exists()
    source0 = result["source_comparison"]["0"]
    assert source0["left"]["seed_count"] == 256
    assert source0["left"]["final_unknown_fraction"] == 1.0 / 256.0
    assert source0["left"]["first_passage_event_fraction_bounds"]["upper"] > \
        source0["left"]["first_passage_event_fraction_bounds"]["lower"]
    assert source0["cdf_sup_difference_bounds"]["first_passage"][
        "sup_abs_difference_bound"
    ] > 0.0
    assert source0["left"]["residence_zero_mass_fraction_bounds"]["lower"] > 0.0
    assert result["common_reliable_path"]["common_full_path_fraction"] < 1.0
    assert result["denominator_policy"]["seed_count"] == 512


def test_cross_scope_requires_registered_provenance_and_reports_time_alignment(tmp_path):
    left = tmp_path / "left.h5"
    right = tmp_path / "right.h5"
    _write_trace(left, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
                 source_sha256="coarse-source")
    _write_trace(right, np.array([0.0, 0.1, 0.20002]), unknown_frame=1,
                 source_sha256="fine-source")
    with pytest.raises(ValueError, match="requires explicit registered comparison provenance"):
        compare_traces(left, right, comparison_mode="cross_scope_same_seed_axis")
    unauthorized = {
        "comparison_mode": "cross_scope_same_seed_axis",
        "allow_source_sha_mismatch": False,
        "endpoint_time_tolerance_s": 3.0e-5,
        "expected_trace_source_sha256": {
            "left": "coarse-source", "right": "fine-source",
        },
    }
    with pytest.raises(ValueError, match="does not explicitly allow source_sha256 mismatch"):
        compare_traces(
            left, right, comparison_mode="cross_scope_same_seed_axis",
            provenance=unauthorized,
        )
    provenance = {
        "comparison_mode": "cross_scope_same_seed_axis",
        "comparison_id": "test-registered-cross-scope-v1",
        "allow_source_sha_mismatch": True,
        "endpoint_time_tolerance_s": 3.0e-5,
        "expected_trace_source_sha256": {
            "left": "coarse-source", "right": "fine-source",
        },
    }
    result = compare_traces(
        left, right, comparison_mode="cross_scope_same_seed_axis",
        provenance=provenance,
    )
    assert result["common_binding"]["source_hash_policy"] == \
        "explicitly_registered_mismatch_allowed"
    assert result["common_binding"]["endpoint_time_tolerance_s"] == 3.0e-5
    assert result["common_reliable_path"]["alignment"]["strategy"] == \
        "union_of_saved_times_right_continuous_hold"

    bad_tolerance = dict(provenance, endpoint_time_tolerance_s=float("nan"))
    with pytest.raises(ValueError, match="endpoint_time_tolerance_s"):
        compare_traces(
            left, right, comparison_mode="cross_scope_same_seed_axis",
            provenance=bad_tolerance,
        )
    too_small_tolerance = dict(provenance, endpoint_time_tolerance_s=1.0e-8)
    with pytest.raises(ValueError, match="physical observation end differs"):
        compare_traces(
            left, right, comparison_mode="cross_scope_same_seed_axis",
            provenance=too_small_tolerance,
        )


def _v3_cross_scope_provenance(left_source: str, right_source: str, *, wall: str = "finite-wall-sha",
                               expected_seed_count: int = 512,
                               expected_seed_hash: str = "v3-seed-sha"):
    return {
        "comparison_mode": "cross_scope_same_seed_axis",
        "comparison_id": "test-v3-spatial-scope-v1",
        "allow_source_sha_mismatch": True,
        "expected_trace_source_sha256": {
            "left": left_source, "right": right_source,
        },
        "expected_trace_backend": (
            "f3_native_volume_mls_temporal_linear_current_interval_rk4_v3"
        ),
        "expected_backend_family": "temporal_linear_v3",
        "expected_source_definition": {
            "kind": "continuous_halfspace", "boundary_m": 0.0,
        },
        "expected_event_definition": TEMPORAL_EVENTS,
        "expected_trace_seed_hash": expected_seed_hash,
        "expected_seed_count": expected_seed_count,
        "require_finite_wall_match": True,
        "expected_walls_sha256": wall,
        "endpoint_time_tolerance_s": 3.0e-5,
    }


def test_cross_scope_explicitly_accepts_same_v3_backend_with_registered_geometry(tmp_path):
    left = tmp_path / "v3-coarse.h5"
    right = tmp_path / "v3-fine.h5"
    _write_trace(
        left, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        source_sha256="coarse-source", seed_hash="v3-seed-sha",
        trace_backend="f3_native_volume_mls_temporal_linear_current_interval_rk4_v3",
        walls_sha256="finite-wall-sha", event_definition=TEMPORAL_EVENTS,
    )
    _write_trace(
        right, np.array([0.0, 0.1, 0.20002]), unknown_frame=1,
        source_sha256="fine-source", seed_hash="v3-seed-sha",
        trace_backend="f3_native_volume_mls_temporal_linear_current_interval_rk4_v3",
        walls_sha256="finite-wall-sha", event_definition=TEMPORAL_EVENTS,
    )
    result = compare_traces(
        left, right, comparison_mode="cross_scope_same_seed_axis",
        provenance=_v3_cross_scope_provenance("coarse-source", "fine-source"),
    )
    assert result["comparison_mode"] == "cross_scope_same_seed_axis"
    assert result["common_binding"]["left_backend_family"] == "temporal_linear_v3"
    assert result["common_binding"]["right_backend_family"] == "temporal_linear_v3"
    assert result["qualification_claim"] == "none"


def test_cross_scope_accepts_only_explicitly_registered_4096_seed_axis(tmp_path):
    left = tmp_path / "v3-production-4096.h5"
    right = tmp_path / "v3-fine-4096.h5"
    backend = "f3_native_volume_mls_temporal_linear_current_interval_rk4_v3"
    _write_trace(
        left, np.array([0.0, 0.1, 0.2]), unknown_frame=1, n=4096,
        source_sha256="production-source", seed_hash="v3-4096-seed-sha",
        trace_backend=backend, walls_sha256="finite-wall-sha",
        event_definition=TEMPORAL_EVENTS,
    )
    _write_trace(
        right, np.array([0.0, 0.1, 0.20002]), unknown_frame=1, n=4096,
        source_sha256="fine-source", seed_hash="v3-4096-seed-sha",
        trace_backend=backend, walls_sha256="finite-wall-sha",
        event_definition=TEMPORAL_EVENTS,
    )
    with pytest.raises(ValueError, match="provenance-registered seed axis of 512"):
        compare_traces(
            left, right, comparison_mode="cross_scope_same_seed_axis",
            provenance=_v3_cross_scope_provenance("production-source", "fine-source"),
        )
    result = compare_traces(
        left, right, comparison_mode="cross_scope_same_seed_axis",
        provenance=_v3_cross_scope_provenance(
            "production-source", "fine-source", expected_seed_count=4096,
            expected_seed_hash="v3-4096-seed-sha",
        ),
    )
    assert result["common_binding"]["expected_seed_count"] == 4096
    assert result["denominator_policy"]["left_seed_count"] == 4096


def test_cross_scope_v3_rejects_backend_drift_even_when_seed_and_wall_match(tmp_path):
    left = tmp_path / "v3-left.h5"
    right = tmp_path / "v1-right.h5"
    _write_trace(
        left, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        source_sha256="left-source", seed_hash="v3-seed-sha",
        trace_backend="f3_native_volume_mls_temporal_linear_current_interval_rk4_v3",
        walls_sha256="finite-wall-sha", event_definition=TEMPORAL_EVENTS,
    )
    _write_trace(
        right, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        source_sha256="right-source", seed_hash="v3-seed-sha",
        trace_backend="f3_native_volume_mls_current_frame_rk4_v1",
        walls_sha256="finite-wall-sha", event_definition=TEMPORAL_EVENTS,
    )
    with pytest.raises(ValueError, match="expected_trace_backend"):
        compare_traces(
            left, right, comparison_mode="cross_scope_same_seed_axis",
            provenance=_v3_cross_scope_provenance("left-source", "right-source"),
        )


def test_cross_scope_v3_rejects_wall_mismatch_or_missing_wall_binding(tmp_path):
    left = tmp_path / "v3-left.h5"
    right = tmp_path / "v3-right.h5"
    backend = "f3_native_volume_mls_temporal_linear_current_interval_rk4_v3"
    _write_trace(
        left, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        source_sha256="left-source", seed_hash="v3-seed-sha", trace_backend=backend,
        walls_sha256="finite-wall-sha", event_definition=TEMPORAL_EVENTS,
    )
    _write_trace(
        right, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        source_sha256="right-source", seed_hash="v3-seed-sha", trace_backend=backend,
        walls_sha256="other-wall", event_definition=TEMPORAL_EVENTS,
    )
    with pytest.raises(ValueError, match="matching walls_sha256|expected_walls_sha256"):
        compare_traces(
            left, right, comparison_mode="cross_scope_same_seed_axis",
            provenance=_v3_cross_scope_provenance("left-source", "right-source"),
        )

    right.unlink()
    _write_trace(
        right, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        source_sha256="right-source", seed_hash="v3-seed-sha", trace_backend=backend,
        event_definition=TEMPORAL_EVENTS,
    )
    with pytest.raises(ValueError, match="finite-wall walls_sha256"):
        compare_traces(
            left, right, comparison_mode="cross_scope_same_seed_axis",
            provenance=_v3_cross_scope_provenance("left-source", "right-source"),
        )


def test_cross_scope_v3_rejects_identical_but_unregistered_event_definition(tmp_path):
    left = tmp_path / "v3-left.h5"
    right = tmp_path / "v3-right.h5"
    backend = "f3_native_volume_mls_temporal_linear_current_interval_rk4_v3"
    wrong_event = dict(TEMPORAL_EVENTS, residence="wrong event semantics")
    for path, source in ((left, "left-source"), (right, "right-source")):
        _write_trace(
            path, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
            source_sha256=source, seed_hash="v3-seed-sha", trace_backend=backend,
            walls_sha256="finite-wall-sha", event_definition=wrong_event,
        )
    with pytest.raises(ValueError, match="expected_event_definition"):
        compare_traces(
            left, right, comparison_mode="cross_scope_same_seed_axis",
            provenance=_v3_cross_scope_provenance("left-source", "right-source"),
        )


def test_cdf_sup_bound_handles_intersecting_and_disjoint_intervals():
    identical = {
        "time_s": [0.0, 1.0],
        "lower_mass_fraction": [0.2, 0.5],
        "upper_mass_fraction": [0.4, 0.7],
    }
    # Overlapping censoring intervals still have a nonzero worst-case
    # difference equal to the interval width; only point intervals collapse
    # the bound to zero.
    assert _cdf_sup_difference(identical, identical)[
        "sup_abs_difference_bound"
    ] == pytest.approx(0.2)
    disjoint_left = {
        "time_s": [0.0],
        "lower_mass_fraction": [0.2],
        "upper_mass_fraction": [0.2],
    }
    disjoint_right = {
        "time_s": [0.0],
        "lower_mass_fraction": [0.8],
        "upper_mass_fraction": [0.8],
    }
    assert _cdf_sup_difference(disjoint_left, disjoint_right)[
        "sup_abs_difference_bound"
    ] == pytest.approx(0.6)


def test_independent_seed_axes_do_not_pair_endpoints(tmp_path):
    left = tmp_path / "left512.h5"
    right = tmp_path / "right256.h5"
    _write_trace(left, np.array([0.0, 0.1, 0.2]), unknown_frame=1, n=512)
    _write_trace(right, np.array([0.0, 0.1, 0.2]), unknown_frame=1, n=256,
                 seed_hash="seed-sha-256")
    provenance = {
        "comparison_mode": "independent_seed_axes",
        "comparison_id": "test-independent-axis-v1",
        "allow_seed_axis_difference": True,
        "endpoint_time_tolerance_s": 1.0e-8,
    }
    result = compare_traces(
        left, right, comparison_mode="independent_seed_axes",
        provenance=provenance,
    )
    assert result["common_reliable_path"]["status"] == \
        "not_applicable_independent_seed_axes"
    assert result["common_binding"]["seed_axis_policy"] == \
        "independent_no_seed_pairing"
    assert result["denominator_policy"]["left_seed_count"] == 512
    assert result["denominator_policy"]["right_seed_count"] == 256
    assert result["denominator_policy"]["seed_count"] is None
    assert result["source_comparison"]["0"]["right"]["denominator_policy"] == \
        "all independent geometric seeds in this source; uniform per-trace weight=1/256"


TEMPORAL_EVENTS = {
    "first_passage": "continuous crossing of x=0 into opposite source half on accepted linear RK segment",
    "return": "first later crossing back to the seed's origin half",
    "residence": "accepted segment time in the opposite source half",
}


def _temporal_provenance(*, left_source="source-sha", right_source="source-sha",
                         wall="finite-wall-sha", event=None):
    return {
        "comparison_mode": "temporal_method_comparison",
        "comparison_id": "test-temporal-method-v1",
        "allow_temporal_method_difference": True,
        "expected_backend_families": ["temporal_linear_v3", "current_frame_hold"],
        "expected_trace_source_sha256": {"left": left_source, "right": right_source},
        "expected_walls_sha256": wall,
        "expected_event_definition": TEMPORAL_EVENTS if event is None else event,
        "endpoint_time_tolerance_s": 1.0e-8,
    }


@pytest.mark.parametrize("current_backend", [
    "f3_native_volume_mls_current_frame_rk4_v1",
    "f3_native_volume_mls_current_frame_rk4_v2",
])
def test_temporal_method_mode_requires_explicit_same_source_and_reports_method_only(
        tmp_path, current_backend):
    left = tmp_path / "temporal-v3.h5"
    right = tmp_path / "current-frame.h5"
    _write_trace(
        left, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        trace_backend="f3_native_volume_mls_temporal_linear_current_interval_rk4_v3",
        trace_schema="core.material.f3.native_volume_mls.trace.temporal.v3",
        walls_sha256="finite-wall-sha", event_definition=TEMPORAL_EVENTS,
    )
    _write_trace(
        right, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        trace_backend=current_backend, walls_sha256="finite-wall-sha",
        event_definition=TEMPORAL_EVENTS,
    )
    result = compare_traces(
        left, right, comparison_mode="temporal_method_comparison",
        provenance=_temporal_provenance(),
    )
    assert result["qualification_claim"] == "none"
    assert result["common_binding"]["source_hash_policy"] == \
        "explicitly_registered_same_source_method_difference"
    assert result["common_binding"]["left_backend_family"] == "temporal_linear_v3"
    assert result["common_binding"]["right_backend_family"] == "current_frame_hold"
    assert result["common_binding"]["method_comparison"]["qualification_effect"] == \
        "none; comparison remains diagnostic-only"
    assert result["common_reliable_path"]["common_full_path_fraction"] < 1.0


def test_different_backend_is_rejected_without_temporal_method_provenance(tmp_path):
    left = tmp_path / "temporal-v3.h5"
    right = tmp_path / "current-frame.h5"
    _write_trace(
        left, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        trace_backend="f3_native_volume_mls_temporal_linear_current_interval_rk4_v3",
        trace_schema="core.material.f3.native_volume_mls.trace.temporal.v3",
    )
    _write_trace(
        right, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        trace_backend="f3_native_volume_mls_current_frame_rk4_v2",
    )
    with pytest.raises(ValueError, match="trace backend differs"):
        compare_traces(left, right)


def test_temporal_mode_binds_explicit_seed_hash_representation_difference(tmp_path):
    left = tmp_path / "temporal-v3.h5"
    right = tmp_path / "current-frame.h5"
    _write_trace(
        left, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        seed_hash="v3-seed-representation",
        trace_backend="f3_native_volume_mls_temporal_linear_current_interval_rk4_v3",
        trace_schema="core.material.f3.native_volume_mls.trace.temporal.v3",
        walls_sha256="finite-wall-sha", event_definition=TEMPORAL_EVENTS,
    )
    _write_trace(
        right, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        seed_hash="v2-seed-representation",
        trace_backend="f3_native_volume_mls_current_frame_rk4_v2",
        walls_sha256="finite-wall-sha", event_definition=TEMPORAL_EVENTS,
    )
    provenance = _temporal_provenance()
    provenance.update({
        "allow_seed_hash_representation_difference": True,
        "expected_trace_seed_hash": {
            "left": "v3-seed-representation",
            "right": "v2-seed-representation",
        },
    })
    result = compare_traces(
        left, right, comparison_mode="temporal_method_comparison",
        provenance=provenance,
    )
    assert result["common_binding"]["seed_axis_policy"] == "paired_same_seed_axis"


@pytest.mark.parametrize("change", ["source", "seed", "wall", "event"])
def test_temporal_method_mode_rejects_source_seed_wall_or_event_mismatch(tmp_path, change):
    left = tmp_path / "temporal-v3.h5"
    right = tmp_path / "current-frame.h5"
    _write_trace(
        left, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        trace_backend="f3_native_volume_mls_temporal_linear_current_interval_rk4_v3",
        trace_schema="core.material.f3.native_volume_mls.trace.temporal.v3",
        source_sha256="source-sha", seed_hash="seed-sha",
        walls_sha256="finite-wall-sha", event_definition=TEMPORAL_EVENTS,
    )
    right_kwargs = {
        "source_sha256": "source-sha",
        "seed_hash": "seed-sha",
        "walls_sha256": "finite-wall-sha",
        "event_definition": TEMPORAL_EVENTS,
    }
    if change == "source":
        right_kwargs["source_sha256"] = "other-source"
    elif change == "seed":
        right_kwargs["seed_hash"] = "other-seed"
    elif change == "wall":
        right_kwargs["walls_sha256"] = "other-wall"
    else:
        right_kwargs["event_definition"] = dict(TEMPORAL_EVENTS, residence="different")
    _write_trace(
        right, np.array([0.0, 0.1, 0.2]), unknown_frame=1,
        trace_backend="f3_native_volume_mls_current_frame_rk4_v2",
        **right_kwargs,
    )
    with pytest.raises(ValueError):
        compare_traces(
            left, right, comparison_mode="temporal_method_comparison",
            provenance=_temporal_provenance(
                right_source=right_kwargs["source_sha256"],
            ),
        )

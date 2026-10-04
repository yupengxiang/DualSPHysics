from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "nativefluid_bed_support_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("f5_nativefluid_bed_support", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_source_only_synthetic_api_check() -> None:
    MODULE._synthetic_check()


def test_piecewise_profile_keeps_outside_domain_undefined() -> None:
    result = MODULE.bed_profile_z(np.asarray([-0.2, 2.5, 4.8, 4.9]))
    assert np.allclose(result[:3], [0.0, 0.14, 0.05])
    assert np.isnan(result[3])


def test_frame_metrics_retains_outside_and_nonfinite_type3_rows() -> None:
    metrics = MODULE.frame_metrics(
        frame_index=400,
        time_s=8.0,
        positions=np.asarray(
            [
                [0.0, 0.0, 0.01],
                [3.0, 0.0, 0.20],
                [4.9, 0.0, 0.0],
                [0.0, 0.0, np.nan],
                [0.0, 0.0, 0.0],
            ],
            dtype=np.float64,
        ),
        valid=np.asarray([1, 1, 1, 1, 0], dtype=np.uint8),
        particle_type=np.asarray([3, 3, 3, 3, 3], dtype=np.int8),
        mass=np.asarray([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64),
        particle_ids=np.asarray([10, 11, 12, 13, 14], dtype=np.uint32),
    )
    assert metrics["valid_type3_native_count"] == 4
    assert metrics["finite_position_count_valid_type3"] == 3
    assert metrics["x_outside_actual_bed_domain_count_finite_type3"] == 1
    assert metrics["distance_unevaluable_count"] == 2
    assert metrics["denominator_policy"]["no_mask_or_drop"] is True
    assert metrics["uid_digest_sorted_uint64le_sha256"] == MODULE.uid_digest([10, 11, 12, 13])


def test_initial_plane_occupancy_is_bound_to_all_bed_nodes() -> None:
    result = MODULE.initial_plane_occupancy(
        positions=np.asarray([[0.0, 0.0, 0.01], [2.0, 0.0, 0.01]], dtype=np.float64),
        valid=np.asarray([1, 1], dtype=np.uint8),
        particle_type=np.asarray([3, 3], dtype=np.int8),
        mass=np.asarray([1.0, 1.0], dtype=np.float64),
        particle_ids=np.asarray([1, 2], dtype=np.uint32),
    )
    assert len(result["planes"]) == 7
    assert result["planes"][0]["occupancy_count_valid_type3"] == 0
    assert result["planes"][1]["occupancy_count_valid_type3"] == 1

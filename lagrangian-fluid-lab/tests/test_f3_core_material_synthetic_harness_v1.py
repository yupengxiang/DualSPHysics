"""Synthetic-only tests for the bounded F3 core-material harness."""
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.f3_core_material_synthetic_harness_v1 import (
    K16_DIAGNOSTIC_NEIGHBOURS,
    canonical_json,
    run_harness,
)


@pytest.fixture(scope="module")
def report():
    return run_harness()


def test_receipt_is_explicitly_diagnostic_and_bounded(report):
    assert report["schema"] == "core.material.f3.synthetic_harness.v1"
    assert report["diagnostic_only"] is True
    assert report["qualification_credit"] == 0
    assert report["qualified_T2_macro"] is False
    assert report["production_artifacts_touched"] is False
    assert report["input_contract"]["source_path_accepted"] is False
    assert report["input_contract"]["source_path_opened"] is False
    assert report["execution"]["device"] == "cpu"
    assert report["execution"]["workers"] == 1
    assert report["execution"]["gpu_started"] is False
    assert report["execution"]["solver_started"] is False
    assert report["execution"]["worker_started"] is False
    assert report["execution"]["queue_mutated"] is False
    assert report["workload_bound"]["max_native_frames"] == 5
    assert report["workload_bound"]["max_particle_count"] == 15**3
    assert report["workload_bound"]["max_seed_count"] == 4
    assert report["denominator_policy"]["unknown_kept_in_full_seed_denominator"] is True
    assert report["denominator_policy"]["gate_relaxed"] is False


def test_affine_quadratic_and_unregistered_k16_report_support_metrics(report):
    affine = report["support_cases"]["affine_shear"]
    quadratic = report["support_cases"]["quadratic"]
    k16 = report["support_cases"]["synthetic_k16_candidate"]
    assert affine["all_passed"] is True
    assert quadratic["all_passed"] is True
    assert k16["neighbours"] == K16_DIAGNOSTIC_NEIGHBOURS
    assert k16["registration_status"] == "not_registered"
    assert k16["formal_variant"] is False
    assert k16["qualification_credit"] == 0
    for case in (affine, quadratic, k16):
        assert len(case["per_query"]) == 3
        for row in case["per_query"]:
            assert row["geometry_rank"] == 3
            assert row["effective_sample_size"] >= 4.0
            assert row["anisotropy"] >= 0.005
            assert row["interpolation_reconstruction_error_mps"] <= report[
                "fixed_gate"
            ]["maximum_reconstruction_error_mps"]
            assert row["failure_reasons"] == []
            assert np.isfinite(row["truth_velocity_error_mps"])


def test_invalid_and_degenerate_support_fail_closed(report):
    degenerate = report["support_cases"]["degenerate_planar_support"]
    invalid = report["support_cases"]["all_samples_invalid"]
    nonfinite = report["support_cases"]["nonfinite_query"]
    assert degenerate["all_passed"] is False
    assert degenerate["per_query"][0]["geometry_rank"] < 3
    assert "geometry_rank" in degenerate["per_query"][0]["failure_reasons"]
    assert np.isfinite(degenerate["per_query"][0]["anisotropy"])
    assert invalid["valid_sample_count"] == 0
    assert invalid["all_passed"] is False
    assert "no_visible_support" in invalid["failure_reason_counts"]
    assert nonfinite["all_passed"] is False
    assert "nonfinite_query" in nonfinite["failure_reason_counts"]


def test_rk2_substep_comparison_and_censor_keep_full_denominator(report):
    temporal = report["temporal_cases"]
    substeps2 = temporal["substeps_2"]
    substeps4 = temporal["substeps_4"]
    censor = temporal["censor_probe"]
    assert substeps2["status"] == "completed"
    assert substeps4["status"] == "completed"
    assert substeps2["unknown_gate_pass"] is True
    assert substeps4["unknown_gate_pass"] is True
    assert substeps2["first_unreliable_step_overall"] is None
    assert substeps4["first_unreliable_step_overall"] is None
    assert temporal["comparison"]["substeps_4_rmse_not_greater_than_substeps_2"] is True
    assert substeps4["final_position_rmse_m"] < substeps2["final_position_rmse_m"]

    assert censor["unknown_full_denominator"] is True
    assert censor["unknown_gate_pass"] is False
    assert censor["first_unreliable_step_overall"] == 2
    assert censor["first_unreliable_step_expected"] == 2
    assert censor["support_failure_reason"] == "frame_2_all_support_samples_invalid"
    assert all(row["unknown_fraction_max"] == 1.0 for row in censor["by_source"])
    assert censor["qualification_claim"] == "none"
    assert censor["qualified_T2_macro"] is False


def test_report_serializes_canonically_and_rejects_non_temporary_output(report, tmp_path):
    encoded = canonical_json(report)
    assert json.loads(encoded)["schema"] == report["schema"]
    assert "NaN" not in encoded
    assert "Infinity" not in encoded
    from scripts.f3_core_material_synthetic_harness_v1 import _safe_output

    with pytest.raises(ValueError, match="system temporary directory"):
        _safe_output(Path.cwd() / "outside-the-system-temp-dir.json")

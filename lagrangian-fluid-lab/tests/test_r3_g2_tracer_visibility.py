from __future__ import annotations

import numpy as np

from diagnostics.r3_g2_tracer_visibility.probe import (
    _narrow_gap_case,
    _partition_case,
    _separated_blob_case,
    build_report,
    component_label_guard,
    minimum_visible_support_guard,
    summarize_interpolant,
)


def test_partition_legacy_mixes_and_existing_wall_aware_filters():
    case = _partition_case()
    legacy = summarize_interpolant(case, barriers=None)
    wall_aware = summarize_interpolant(case, barriers=case["barriers"])
    assert legacy["wrong_tangential_direction_fraction"] == 1.0
    assert wall_aware["wrong_tangential_direction_fraction"] == 0.0
    assert legacy["contaminant_weight_fraction"]["mean"] > 0.5
    assert wall_aware["contaminant_weight_fraction"]["max"] == 0.0
    assert wall_aware["eligible_visible_count"]["max"] == 8


def test_narrow_gap_blocks_wall_samples_but_keeps_real_opening():
    case = _narrow_gap_case()
    legacy = summarize_interpolant(case, barriers=None)
    wall_aware = summarize_interpolant(case, barriers=case["barriers"])
    visibility = np.asarray(
        # Reuse the report-level rows only for stable count assertions.
        [row["eligible_visible_count"] for row in wall_aware["query_rows"]]
    )
    assert legacy["contaminant_weight_fraction"]["mean"] > 0.5
    assert wall_aware["contaminant_weight_fraction"]["max"] == 0.0
    assert np.all(visibility == 23)
    guard = minimum_visible_support_guard(case)
    assert guard["accepted_query_fraction"] == 0.0
    assert guard["status"] == "candidate_only_rejected"


def test_geometry_only_wall_aware_cannot_separate_liquid_blobs():
    case = _separated_blob_case()
    legacy = summarize_interpolant(case, barriers=None)
    wall_aware = summarize_interpolant(case, barriers=case["barriers"])
    assert wall_aware["wrong_tangential_direction_fraction"] == legacy[
        "wrong_tangential_direction_fraction"
    ]
    assert wall_aware["contaminant_weight_fraction"] == legacy[
        "contaminant_weight_fraction"
    ]
    gate = component_label_guard(case)
    assert gate["wrong_tangential_direction_fraction"] == 0.0
    assert gate["status"] == "candidate_only_rejected"


def test_report_is_cpu_only_and_keeps_candidate_rejection():
    report = build_report()
    assert report["compute"]["gpu_used"] is False
    assert report["compute"]["cfd_solver_run"] is False
    assert report["acceptance_status"] == "candidate_only_rejected"
    assert report["implementation_audit"]["requested_script_present"] is False
    assert set(report["cases"]) == {
        "partition_tangential_flow",
        "narrow_gap_visibility",
        "separated_liquid_blob",
    }

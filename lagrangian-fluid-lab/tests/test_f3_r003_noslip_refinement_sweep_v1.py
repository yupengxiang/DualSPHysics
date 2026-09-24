"""Pure helper checks for the read-only R003 refinement diagnostics."""

import numpy as np

from scripts.f3_r003_noslip_refinement_sweep_v1 import (
    BOUNDARY_OFFSETS_H,
    TIME_REFINEMENT_FACTORS,
    _time_summary,
)


def test_refinement_design_is_nested_and_stays_inside_bounded_probe_grid():
    assert TIME_REFINEMENT_FACTORS == (1, 2, 4, 8, 16)
    assert BOUNDARY_OFFSETS_H == (0.25, 0.5, 1.0, 1.5, 1.9)
    assert max(BOUNDARY_OFFSETS_H) < 2.0


def test_time_summary_compares_only_completed_endpoint_pairs():
    records = [
        {
            "seed": 1,
            "time_refinement": [
                {"refinement_factor": 1, "status": "completed", "state": [1.0, 0.0, 0.0],
                 "residual_gate_failed": False, "residual_gate_exceedances": 0,
                 "constrained_outward_evaluations": 0,
                 "maximum_constrained_fit_residual_mps": 0.01, "accepted_steps": 2},
                {"refinement_factor": 2, "status": "completed", "state": [1.5, 0.0, 0.0],
                 "residual_gate_failed": True, "residual_gate_exceedances": 1,
                 "constrained_outward_evaluations": 1,
                 "maximum_constrained_fit_residual_mps": 0.06, "accepted_steps": 3},
                {"refinement_factor": 4, "status": "fail_closed", "state": [2.0, 0.0, 0.0],
                 "residual_gate_failed": False, "residual_gate_exceedances": 0,
                 "constrained_outward_evaluations": 0,
                 "maximum_constrained_fit_residual_mps": None, "accepted_steps": 1},
                {"refinement_factor": 8, "status": "completed", "state": [1.9, 0.0, 0.0],
                 "residual_gate_failed": False, "residual_gate_exceedances": 0,
                 "constrained_outward_evaluations": 0,
                 "maximum_constrained_fit_residual_mps": 0.03, "accepted_steps": 5},
                {"refinement_factor": 16, "status": "completed", "state": [2.0, 0.0, 0.0],
                 "residual_gate_failed": False, "residual_gate_exceedances": 0,
                 "constrained_outward_evaluations": 0,
                 "maximum_constrained_fit_residual_mps": 0.02, "accepted_steps": 8},
            ],
        },
    ]
    summary = _time_summary(records)
    assert summary["by_refinement_factor"]["2"]["seeds_with_residual_gate_failure"] == 1
    assert summary["endpoint_difference_vs_factor_16"]["1"]["compared_seed_count"] == 1
    assert summary["endpoint_difference_vs_factor_16"]["1"][
        "max_distance_to_factor_16_endpoint_m"
    ] == 1.0
    assert summary["endpoint_difference_vs_factor_16"]["4"]["compared_seed_count"] == 0

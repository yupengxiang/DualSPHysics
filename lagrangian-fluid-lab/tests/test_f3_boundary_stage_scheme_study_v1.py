"""Manufactured-flow tests for the offline F3 boundary-stage design review."""

from scripts.f3_boundary_stage_scheme_study_v1 import (
    integrate_stage_safe,
    no_slip_exact_x,
    no_slip_field,
    outward_field,
    rk4_trial,
    study,
)


def test_smooth_no_slip_stage_retry_recovers_convergent_in_domain_trace():
    initial = (0.9, 0.0)
    exact_x = no_slip_exact_x(0.5)
    raw, stages = rk4_trial(initial, 0.5, no_slip_field)
    assert max(stages) > 1.0
    assert raw[0] < 1.0

    coarse_safe = integrate_stage_safe(initial, 0.5, 0.5, no_slip_field)
    fine_safe = integrate_stage_safe(initial, 0.5, 0.125, no_slip_field)
    assert coarse_safe["status"] == "completed"
    assert fine_safe["status"] == "completed"
    assert 0.0 <= coarse_safe["state"][0] <= 1.0
    assert 0.0 <= fine_safe["state"][0] <= 1.0
    assert abs(fine_safe["state"][0] - exact_x) < abs(coarse_safe["state"][0] - exact_x)


def test_query_clamp_does_not_resolve_persistent_outward_velocity():
    clamped, _ = rk4_trial((0.9, 0.0), 0.5, outward_field, clamp_query=True)
    assert clamped[0] > 1.0

    adaptive = integrate_stage_safe((0.9, 0.0), 0.5, 0.5, outward_field)
    assert adaptive["status"] == "stalled_at_boundary_fail_closed"
    assert adaptive["state"][0] <= 1.0
    assert adaptive["state"][0] > 0.99
    assert adaptive["elapsed_s"] < 0.5


def test_study_records_clamping_projection_and_stall_as_distinct_semantics():
    result = study()
    assert result["production_code_modified"] is False
    outward = result["constant_outward_reconstruction"]
    assert outward["unconstrained_rk4"]["leaks"] is True
    assert outward["query_clamp_only"]["leaks"] is True
    assert outward["tangent_projection_and_endpoint_clamp"]["remains_in_domain"] is True
    assert outward["tangent_projection_and_endpoint_clamp"]["continues_after_boundary"] is True
    assert outward["stage_safe_substepping"]["status"] == "stalled_at_boundary_fail_closed"

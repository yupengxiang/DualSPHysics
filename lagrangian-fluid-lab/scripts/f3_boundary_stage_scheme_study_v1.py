"""Offline manufactured-flow study for F3 RK stage boundary handling.

This module is diagnostic only. It does not change the registered F3
integrator, scientific gates, or any campaign artifacts.
"""

from __future__ import annotations

import json
import math
from typing import Callable


State = tuple[float, float]
Velocity = tuple[float, float]
Field = Callable[[float], Velocity]


def no_slip_field(x: float) -> Velocity:
    """Smooth wall-compatible field on x in [0, 1], with dy/dx = 0.2."""
    speed = math.sin(math.pi * x)
    return speed, 0.2 * speed


def outward_field(_x: float) -> Velocity:
    """Deliberately wall-incompatible constant outward reconstruction."""
    return 1.0, 0.0


def no_slip_exact_x(time_s: float, initial_x: float = 0.9) -> float:
    """Exact x(t) for dx/dt=sin(pi*x), away from the asymptotic walls."""
    transformed = math.tan(math.pi * initial_x / 2.0) * math.exp(math.pi * time_s)
    return 2.0 / math.pi * math.atan(transformed)


def _evaluate(
    x: float,
    field: Field,
    *,
    clamp_query: bool,
    project_outward_normal: bool,
) -> Velocity:
    query_x = min(1.0, max(0.0, x)) if clamp_query else x
    vx, vy = field(query_x)
    if project_outward_normal and (
        (query_x <= 0.0 and vx < 0.0) or (query_x >= 1.0 and vx > 0.0)
    ):
        vx = 0.0
    return vx, vy


def rk4_trial(
    state: State,
    step_s: float,
    field: Field,
    *,
    clamp_query: bool = False,
    project_outward_normal: bool = False,
    clamp_endpoint: bool = False,
) -> tuple[State, tuple[float, float, float]]:
    """Take one 2-D RK4 step; return endpoint and three intermediate x queries."""
    x, y = state
    k1 = _evaluate(x, field, clamp_query=clamp_query,
                   project_outward_normal=project_outward_normal)
    q2 = (x + 0.5 * step_s * k1[0], y + 0.5 * step_s * k1[1])
    k2 = _evaluate(q2[0], field, clamp_query=clamp_query,
                   project_outward_normal=project_outward_normal)
    q3 = (x + 0.5 * step_s * k2[0], y + 0.5 * step_s * k2[1])
    k3 = _evaluate(q3[0], field, clamp_query=clamp_query,
                   project_outward_normal=project_outward_normal)
    q4 = (x + step_s * k3[0], y + step_s * k3[1])
    k4 = _evaluate(q4[0], field, clamp_query=clamp_query,
                   project_outward_normal=project_outward_normal)
    candidate = (
        x + step_s * (k1[0] + 2.0 * k2[0] + 2.0 * k3[0] + k4[0]) / 6.0,
        y + step_s * (k1[1] + 2.0 * k2[1] + 2.0 * k3[1] + k4[1]) / 6.0,
    )
    if clamp_endpoint:
        candidate = (min(1.0, max(0.0, candidate[0])), candidate[1])
    return candidate, (q2[0], q3[0], q4[0])


def integrate_stage_safe(
    initial: State,
    duration_s: float,
    base_step_s: float,
    field: Field,
    *,
    max_halvings: int = 20,
) -> dict:
    """Retry out-of-domain RK trials with smaller steps; fail closed on stall."""
    if duration_s <= 0.0 or base_step_s <= 0.0:
        raise ValueError("duration_s and base_step_s must be positive")
    state = initial
    elapsed = 0.0
    accepted = 0
    rejected = 0
    status = "completed"
    time_tolerance = 1e-14
    while elapsed < duration_s - time_tolerance:
        step_s = min(base_step_s, duration_s - elapsed)
        for _ in range(max_halvings + 1):
            candidate, stages = rk4_trial(state, step_s, field)
            abscissae = (*stages, candidate[0])
            if all(0.0 <= x <= 1.0 for x in abscissae):
                state = candidate
                elapsed += step_s
                accepted += 1
                break
            rejected += 1
            step_s *= 0.5
        else:
            status = "stalled_at_boundary_fail_closed"
            break
    return {
        "status": status,
        "state": state,
        "elapsed_s": elapsed,
        "accepted_steps": accepted,
        "rejected_trials": rejected,
    }


def _stage_outside(stages: tuple[float, float, float]) -> bool:
    return any(x < 0.0 or x > 1.0 for x in stages)


def study() -> dict:
    """Compare query clamping, tangent projection, and stage-safe retries."""
    initial = (0.9, 0.0)
    duration_s = 0.5
    base_step_s = 0.5

    raw_smooth, raw_stages = rk4_trial(initial, base_step_s, no_slip_field)
    clamped_smooth, clamped_stages = rk4_trial(
        initial, base_step_s, no_slip_field, clamp_query=True
    )
    adaptive_smooth = integrate_stage_safe(
        initial, duration_s, base_step_s, no_slip_field
    )
    exact_x = no_slip_exact_x(duration_s)

    raw_outward, raw_outward_stages = rk4_trial(
        initial, duration_s, outward_field
    )
    clamped_outward, _ = rk4_trial(
        initial, duration_s, outward_field, clamp_query=True
    )
    projected_outward, _ = rk4_trial(
        initial, duration_s, outward_field,
        clamp_query=True, project_outward_normal=True, clamp_endpoint=True,
    )
    adaptive_outward = integrate_stage_safe(
        initial, duration_s, base_step_s, outward_field
    )

    return {
        "schema": "f3_boundary_stage_scheme_study_v1",
        "production_code_modified": False,
        "gates_or_campaign_state_modified": False,
        "domain_x": [0.0, 1.0],
        "smooth_no_slip": {
            "duration_s": duration_s,
            "base_step_s": base_step_s,
            "exact_x": exact_x,
            "raw_rk4": {
                "x": raw_smooth[0],
                "max_stage_x": max(raw_stages),
                "stage_outside": _stage_outside(raw_stages),
                "endpoint_error": abs(raw_smooth[0] - exact_x),
            },
            "query_clamp_only": {
                "x": clamped_smooth[0],
                "max_unprojected_stage_x": max(clamped_stages),
                "stage_outside_before_query_clamp": _stage_outside(clamped_stages),
                "endpoint_error": abs(clamped_smooth[0] - exact_x),
            },
            "stage_safe_substepping": {
                **adaptive_smooth,
                "x": adaptive_smooth["state"][0],
                "endpoint_error": abs(adaptive_smooth["state"][0] - exact_x),
            },
        },
        "constant_outward_reconstruction": {
            "duration_s": duration_s,
            "base_step_s": base_step_s,
            "unconstrained_rk4": {
                "x": raw_outward[0],
                "max_stage_x": max(raw_outward_stages),
                "leaks": raw_outward[0] > 1.0,
            },
            "query_clamp_only": {
                "x": clamped_outward[0],
                "leaks": clamped_outward[0] > 1.0,
            },
            "tangent_projection_and_endpoint_clamp": {
                "x": projected_outward[0],
                "remains_in_domain": 0.0 <= projected_outward[0] <= 1.0,
                "continues_after_boundary": True,
            },
            "stage_safe_substepping": {
                **adaptive_outward,
                "x": adaptive_outward["state"][0],
                "remains_in_domain": 0.0 <= adaptive_outward["state"][0] <= 1.0,
            },
        },
    }


def main() -> None:
    print(json.dumps(study(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

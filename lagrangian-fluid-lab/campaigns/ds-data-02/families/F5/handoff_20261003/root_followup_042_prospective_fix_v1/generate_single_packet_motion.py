#!/usr/bin/env python3
"""Finite single-wave packet paddle motion generator for F5 fallback cases.

Constructs smooth, compact wavemaker forcing that isolates incident shoaling,
runup, and overtopping while parking the paddle during return flow to eliminate
wavemaker reflections and standing-wave resonances.

Actual scientific file output is executed under Rootguard dispatch.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Dict, List, Tuple

# Physical Motion Parameters
TOTAL_WINDOW_S: float = 16.00
MOTION_DT_S: float = 0.025  # 40 Hz sampling, matching standard piston format
PACKET_DURATION_S: float = 7.50
MAX_STROKE_LIMIT_M: float = 0.030  # Physical stroke ceiling of wavemaker flume
NOMINAL_PACKET_AMPLITUDE_M: float = 0.028  # Target excursion: 2.80 cm


def evaluate_motion_profile(
    t: float,
    t_gen: float = PACKET_DURATION_S,
    amplitude: float = NOMINAL_PACKET_AMPLITUDE_M,
    n_cycles: float = 2.5,
) -> float:
    """Evaluate paddle displacement x(t) [m] at time t [s].

    Uses a smooth Hann envelope modulated by an oscillatory carrier to produce
    a finite, self-contained wave group:
      x(t) = amplitude * sin^2(pi * t / t_gen) * sin(2 * pi * n_cycles * t / t_gen)
    for t in [0, t_gen], and exactly 0.0 for t >= t_gen.

    Properties:
      - x(0) = 0.0, x'(0) = 0.0
      - x(t_gen) = 0.0, x'(t_gen) = 0.0
      - Strictly 0.0 for all t in [t_gen, TOTAL_WINDOW_S]
    """
    if t < 0.0 or t >= t_gen:
        return 0.0

    # Hann tapering window
    window = math.sin(math.pi * t / t_gen) ** 2
    # Harmonic carrier
    carrier = math.sin(2.0 * math.pi * n_cycles * t / t_gen)

    return amplitude * window * carrier


def generate_motion_table(
    total_time: float = TOTAL_WINDOW_S,
    dt: float = MOTION_DT_S,
    t_gen: float = PACKET_DURATION_S,
    amplitude: float = NOMINAL_PACKET_AMPLITUDE_M,
) -> List[Tuple[float, float]]:
    """Compute time-displacement table over [0, total_time] with step dt."""
    n_steps = int(round(total_time / dt)) + 1
    table: List[Tuple[float, float]] = []
    for i in range(n_steps):
        t = i * dt
        x = evaluate_motion_profile(t, t_gen=t_gen, amplitude=amplitude)
        table.append((t, x))
    return table


def format_motion_dat(table: List[Tuple[float, float]]) -> str:
    """Format motion table into DualSPHysics 2-column piston dat format."""
    lines: List[str] = []
    for t, x in table:
        lines.append(f"{t:.5f} {x:.8f}")
    return "\n".join(lines) + "\n"


def validate_motion_series(
    table: List[Tuple[float, float]],
    t_gen: float = PACKET_DURATION_S,
    max_stroke: float = MAX_STROKE_LIMIT_M,
) -> Dict[str, object]:
    """Validate physical and numerical properties of the motion series."""
    times = [pt[0] for pt in table]
    disps = [pt[1] for pt in table]

    # Initial condition
    assert abs(disps[0]) < 1e-12, f"Initial displacement non-zero: {disps[0]}"

    # Amplitude bound
    peak_excursion = max(abs(x) for x in disps)
    assert peak_excursion <= max_stroke, (
        f"Excursion {peak_excursion:.5f} m exceeds limit {max_stroke:.5f} m"
    )

    # Quiescent tail
    tail_disps = [x for t, x in table if t >= t_gen]
    max_tail_err = max(abs(x) for x in tail_disps) if tail_disps else 0.0
    assert max_tail_err < 1e-12, f"Tail not strictly quiescent: {max_tail_err}"

    # Approximate velocity and acceleration bounds
    dt = times[1] - times[0]
    velocities = [(disps[i + 1] - disps[i]) / dt for i in range(len(disps) - 1)]
    max_vel = max(abs(v) for v in velocities)
    assert max_vel < 0.20, f"Max paddle velocity excessive: {max_vel:.4f} m/s"

    return {
        "samples_count": len(table),
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "dt_s": dt,
        "peak_stroke_m": peak_excursion,
        "max_velocity_m_s": max_vel,
        "active_duration_s": t_gen,
        "quiescent_tail_s": [t_gen, times[-1]],
        "is_quiescent_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finite single-wave packet motion generator."
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run physical validation without writing files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output .dat file destination (Rootguard execution only).",
    )
    args = parser.parse_args()

    table = generate_motion_table()
    report = validate_motion_series(table)

    if args.validate_only or not args.output:
        print("Motion validation report:")
        for k, v in report.items():
            print(f"  {k}: {v}")

    if args.output:
        # Note: writing actual scientific assets is governed under Rootguard
        dat_content = format_motion_dat(table)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(dat_content, encoding="utf-8")
        print(f"Wrote motion file to {args.output} ({len(table)} lines)")


if __name__ == "__main__":
    main()

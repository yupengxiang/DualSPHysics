#!/usr/bin/env python3
"""Finite single-wave packet paddle motion generator for F5 compact fallback cases.

Constructs smooth, compact wavemaker forcing that isolates incident shoaling,
runup, and candidate weir overtopping while parking the paddle during return flow
to eliminate wavemaker reflections and continuous standing-wave pumping.

Preserves the full 16.0-second event window with a strictly quiescent tail.
Actual scientific file output is executed strictly under Rootguard dispatch.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Dict, List, Tuple

# Physical Motion Parameters
TOTAL_WINDOW_S: float = 16.00
MOTION_DT_S: float = 0.025  # 40 Hz sampling, matching standard DualSPHysics piston format
PACKET_DURATION_S: float = 5.00  # Finite event generation duration
MAX_STROKE_LIMIT_M: float = 0.030  # Physical stroke ceiling of wavemaker flume
NOMINAL_PACKET_AMPLITUDE_M: float = 0.028  # Target excursion: 2.80 cm


def evaluate_motion_profile(
    t: float,
    t_gen: float = PACKET_DURATION_S,
    amplitude: float = NOMINAL_PACKET_AMPLITUDE_M,
    n_cycles: float = 2.0,
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

    return {
        "rows_count": len(table),
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "peak_excursion_m": peak_excursion,
        "packet_duration_s": t_gen,
        "tail_duration_s": times[-1] - t_gen,
        "max_tail_residual_m": max_tail_err,
        "is_valid": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="F5 compact packet motion generator and validator."
    )
    parser.add_argument(
        "--validate-motion",
        action="store_true",
        help="Run physical and numerical checks on the finite motion series.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Target output dat file path (Rootguard execution only).",
    )
    args = parser.parse_args()

    table = generate_motion_table()

    if args.validate_motion:
        report = validate_motion_series(table)
        print("Compact packet motion validation passed:")
        for k, v in report.items():
            print(f"  {k}: {v}")

    if args.output:
        dat_text = format_motion_dat(table)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(dat_text, encoding="utf-8")
        print(f"Wrote motion table ({len(table)} rows) to {args.output}")


if __name__ == "__main__":
    main()

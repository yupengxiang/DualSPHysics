#!/usr/bin/env python3
"""Finite single-wave packet paddle motion generator for F5 compact equilibrium fallback cases.

Constructs a smooth, compact wavemaker forcing time-series formatted to full IEEE double
precision (17g) and written exclusively (O_EXCL) to prevent silent overwrite.

PHYSICAL BOUNDARY REFLECTION BEHAVIOR & WAVE DYNAMICS:
  - An analytic finite wave envelope does NOT eliminate wavemaker reflections or chaos.
  - When the wavemaker packet generation finishes at t_gen = 5.0 s, the paddle returns
    to x = 0.0 m and remains stationary for the remainder of the 16.0-second window.
  - The stationary paddle at x = 0.0 m constitutes a rigid, reflective vertical boundary.
  - Waves reflecting from the continuous sloping beach, breaking region, or weir propagate
    back upstream into the basin and will reflect off the stationary paddle face.
  - The 2-cycle Hann packet is therefore treated strictly as a candidate incident wave group.
    Whether wave reflections, standing waves, or nonlinear sloshing occur in the return flow
    cannot be eliminated analytically and must be demonstrated by actual native simulation data.

FORMAT & EXCLUSIVE IO:
  - Formatted strictly with ':.17g' for both time and displacement columns.
  - File output adheres to exclusive creation semantics (O_EXCL), refusing silent overwrite.
  - Actual scientific file staging is executed strictly under Rootguard dispatch.
"""

from __future__ import annotations

import argparse
import math
import os
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
    a candidate incident wave group:
      x(t) = amplitude * sin^2(pi * t / t_gen) * sin(2 * pi * n_cycles * t / t_gen)
    for t in [0, t_gen], and exactly 0.0 for t >= t_gen.

    Boundary properties:
      - x(0) = 0.0, x'(0) = 0.0
      - x(t_gen) = 0.0, x'(t_gen) = 0.0
      - Strictly 0.0 for all t in [t_gen, TOTAL_WINDOW_S]
      - NOTE: The stationary paddle at x = 0.0 for t >= t_gen reflects incident returning waves.
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


def format_motion_dat_17g(table: List[Tuple[float, float]]) -> str:
    """Format motion table into DualSPHysics 2-column piston dat format using 17g precision."""
    lines: List[str] = []
    for t, x in table:
        lines.append(f"{t:.17g} {x:.17g}")
    return "\n".join(lines) + "\n"


def write_exclusive_text(target_path: Path, content: str) -> None:
    """Write text to target_path exclusively (O_CREAT | O_EXCL), refusing silent overwrite."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(target_path), flags, 0o644)
    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)


def validate_motion_series(
    table: List[Tuple[float, float]],
    t_gen: float = PACKET_DURATION_S,
    max_stroke: float = MAX_STROKE_LIMIT_M,
) -> Dict[str, object]:
    """Validate physical and numerical properties of the candidate motion series."""
    times = [pt[0] for pt in table]
    disps = [pt[1] for pt in table]

    # Initial condition
    assert abs(disps[0]) < 1e-15, f"Initial displacement non-zero: {disps[0]}"

    # Amplitude bound
    peak_excursion = max(abs(x) for x in disps)
    assert peak_excursion <= max_stroke, (
        f"Excursion {peak_excursion:.17g} m exceeds limit {max_stroke:.17g} m"
    )

    # Quiescent paddle at x = 0 (reflective boundary)
    tail_disps = [x for t, x in table if t >= t_gen]
    max_tail_err = max(abs(x) for x in tail_disps) if tail_disps else 0.0
    assert max_tail_err < 1e-15, f"Parked paddle position non-zero: {max_tail_err}"

    return {
        "rows_count": len(table),
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "peak_excursion_m": peak_excursion,
        "packet_duration_s": t_gen,
        "parked_duration_s": times[-1] - t_gen,
        "max_tail_residual_m": max_tail_err,
        "precision_format": "17g",
        "paddle_reflectivity_note": "Stationary paddle at x=0 for t >= 5s reflects returning waves",
        "is_valid": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="F5 compact packet motion generator with 17g precision and exclusive IO."
    )
    parser.add_argument(
        "--validate-motion",
        action="store_true",
        help="Run physical and numerical checks on the candidate motion series.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Target output dat file path (Rootguard exclusive write only).",
    )
    args = parser.parse_args()

    table = generate_motion_table()

    if args.validate_motion:
        report = validate_motion_series(table)
        print("Compact packet motion validation passed:")
        for k, v in report.items():
            print(f"  {k}: {v}")

    if args.output:
        dat_text = format_motion_dat_17g(table)
        write_exclusive_text(args.output, dat_text)
        print(f"Wrote motion table ({len(table)} rows, 17g precision) exclusively to {args.output}")


if __name__ == "__main__":
    main()

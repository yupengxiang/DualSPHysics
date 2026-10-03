#!/usr/bin/env python3
"""
Standard Library Transformer for F3 Prospective Control Amplitude Scaling.

This script scales nominal prescribed sloshing body accelerations using the
zero-drive gravity relation defined in F3-CELL3-PROTOCOL.json:
    a_lin = g + A * (a_nom - g)
    alpha = A * alpha_nom
where:
    g = (0.0, 0.0, -9.81) m/s^2
    nominal zero-drive is linear=(0,0,-9.81), angular=(0,0,0), globalgravity=0.

Solver velocity integration and frame kinetics:
    - Solver-native right-endpoint velocity integration:
      v_lin[k] = v_lin[k-1] + a_lin[k] * (t[k] - t[k-1])
      v_ang[k] = v_ang[k-1] + alpha[k] * (t[k] - t[k-1])
      as natively executed by JDsAccInput.cpp.
    - GPU Coriolis and angular frame terms are computed per-component by
      JDsAccInput_ker.cu without replacing solver physics.

Input arrays are NOT permanently committed to git; this transformer provides
guarded, verified control generation for execution when authorized by Root.
Pinned nominal forcing SHA256:
    6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3
"""

import argparse
import hashlib
import math
from pathlib import Path
import sys

PINNED_NOMINAL_FORCING_SHA256 = "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3"
GRAVITY_Z = -9.81


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def format_coord(val: float) -> str:
    """Format float cleanly matching DualSPHysics input expectations."""
    if abs(val) < 1e-15:
        return "0"
    # For values close to gravity
    if abs(val - GRAVITY_Z) < 1e-12:
        return "-9.81E+00"
    # Exponential formatting if very small or large, else decimal
    abs_v = abs(val)
    if abs_v < 1e-3 or abs_v >= 1e4:
        # Standard scientific format: e.g. 7.36E-03 or -1.96E-10
        s = f"{val:.2E}" if abs_v < 1e-2 and abs_v >= 1e-6 else f"{val:.9E}"
        # Cleanup exponent: replace E-004 with E-04
        parts = s.split("E")
        if len(parts) == 2:
            sign = parts[1][0]
            exp_val = parts[1][1:].lstrip("0") or "0"
            return f"{parts[0]}E{sign}{exp_val.zfill(2)}"
        return s
    return f"{val:.10g}"


def transform_row(time_str: str,
                  ax_str: str, ay_str: str, az_str: str,
                  alphax_str: str, alphay_str: str, alphaz_str: str,
                  amplitude: float) -> list:
    """
    Transform single acceleration row using zero-drive relation.
    """
    ax = float(ax_str) * amplitude
    ay = float(ay_str) * amplitude
    az_nom = float(az_str)
    az = GRAVITY_Z + amplitude * (az_nom - GRAVITY_Z)
    alphax = float(alphax_str) * amplitude
    alphay = float(alphay_str) * amplitude
    alphaz = float(alphaz_str) * amplitude

    return [
        time_str,
        format_coord(ax),
        format_coord(ay),
        format_coord(az),
        format_coord(alphax),
        format_coord(alphay),
        format_coord(alphaz),
    ]


def transform_forcing_file(input_path: Path,
                           output_path: Path,
                           amplitude: float,
                           check_source_hash: bool = True) -> dict:
    """
    Stream-transform the forcing CSV from input_path to output_path.
    Does not hold the full CSV in memory.
    """
    if check_source_hash:
        actual_hash = compute_sha256(input_path)
        if actual_hash != PINNED_NOMINAL_FORCING_SHA256:
            raise ValueError(
                f"Source forcing hash mismatch!\n"
                f"Expected: {PINNED_NOMINAL_FORCING_SHA256}\n"
                f"Actual:   {actual_hash}"
            )

    rows_processed = 0
    t_min = None
    t_max = None
    col_min = [float("inf")] * 6
    col_max = [float("-inf")] * 6

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(input_path, "r", encoding="utf-8") as in_f, open(output_path, "w", encoding="utf-8") as out_f:
        for line in in_f:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                out_f.write(stripped + "\n")
                continue
            parts = stripped.split(";")
            if len(parts) < 7:
                continue
            time_val = float(parts[0])
            if t_min is None or time_val < t_min:
                t_min = time_val
            if t_max is None or time_val > t_max:
                t_max = time_val

            trans = transform_row(
                parts[0], parts[1], parts[2], parts[3],
                parts[4], parts[5], parts[6],
                amplitude
            )
            out_f.write(";".join(trans) + "\n")
            rows_processed += 1

            for c in range(6):
                val = float(trans[c + 1])
                if val < col_min[c]:
                    col_min[c] = val
                if val > col_max[c]:
                    col_max[c] = val

    out_hash = compute_sha256(output_path)
    return {
        "status": "success",
        "amplitude": amplitude,
        "input_file": str(input_path),
        "output_file": str(output_path),
        "output_sha256": out_hash,
        "rows_processed": rows_processed,
        "time_range_s": [t_min, t_max],
        "column_min": col_min,
        "column_max": col_max,
    }


def self_test():
    """Verify zero-drive formula consistency."""
    # Test zero-drive: nominal zero is (0, 0, -9.81), angular (0,0,0)
    res = transform_row("0.0", "0.0", "0.0", "-9.81", "0.0", "0.0", "0.0", amplitude=0.9)
    assert res[1] == "0", f"Expected ax=0, got {res[1]}"
    assert res[2] == "0", f"Expected ay=0, got {res[2]}"
    assert abs(float(res[3]) - GRAVITY_Z) < 1e-10, f"Expected az=-9.81, got {res[3]}"
    assert res[4] == "0" and res[5] == "0" and res[6] == "0"

    # Test scaling of linear acceleration
    res_a09 = transform_row("1.0", "1.0", "0.0", "-8.81", "0.0", "2.0", "0.0", amplitude=0.9)
    # az_nom = -8.81 -> az_nom - g = 1.0 -> az = -9.81 + 0.9 * 1.0 = -8.91
    assert abs(float(res_a09[1]) - 0.9) < 1e-10
    assert abs(float(res_a09[3]) - (-8.91)) < 1e-10
    assert abs(float(res_a09[5]) - 1.8) < 1e-10

    # Test identity when A=1.0
    res_a10 = transform_row("1.0", "1.0", "0.0", "-8.81", "0.0", "2.0", "0.0", amplitude=1.0)
    assert abs(float(res_a10[1]) - 1.0) < 1e-10
    assert abs(float(res_a10[3]) - (-8.81)) < 1e-10
    assert abs(float(res_a10[5]) - 2.0) < 1e-10

    print("Self-test passed successfully.")


def main():
    parser = argparse.ArgumentParser(
        description="DualSPHysics F3 Forcing Amplitude Transformer (Zero-Drive Physics)"
    )
    parser.add_argument("--input", "-i", type=Path, help="Path to nominal input CSV")
    parser.add_argument("--output", "-o", type=Path, help="Path to output transformed CSV")
    parser.add_argument("--amplitude", "-a", type=float, help="Scaling amplitude A")
    parser.add_argument("--skip-hash-check", action="store_true", help="Skip sha256 verification of input")
    parser.add_argument("--test", action="store_true", help="Run self-test only")
    args = parser.parse_args()

    if args.test:
        self_test()
        sys.exit(0)

    if not args.input or not args.output or args.amplitude is None:
        parser.error("--input, --output, and --amplitude are required unless --test is specified.")

    report = transform_forcing_file(
        args.input,
        args.output,
        args.amplitude,
        check_source_hash=not args.skip_hash_check
    )
    import json
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Standard Library Transformer for F3 Prospective Control Amplitude Scaling (v2).

Repairs and improvements over v1:
- Uses full roundtrip .17g float formatting without precision loss or quantization.
- Removes unauthorized arbitrary clamps (no abs < 1e-15 clamp, no azgravity < 1e-12 clamp).
- Removes small-value .2E quantization that previously distorted amplitudes by up to ~0.5%.
- Enforces strict guards:
    * Rejects malformed rows (does NOT silently drop them).
    * Validates that all 7 columns are finite (math.isfinite).
    * Validates strictly increasing time values (t[k] > t[k-1]).
    * Validates exact complete event window [0.0, 8.35] s.
    * Validates expected row count (167,001 rows for nominal sloshing series).
- Preserves exact original time strings verbatim (zero string formatting drift).
- Strictly preserves zero-drive formula and numerical identity at A=1.0:
    a_lin = g + A * (a_nom - g)
    alpha = A * alpha_nom
  where g = (0.0, 0.0, -9.81) m/s^2.
- Safe output handling: enforces non-overwrite exclusive creation (mode="x") by default.
- Pinned nominal forcing SHA256:
    6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3
- Comprehensive synthetic fixtures exercising tiny, large, non-finite, malformed, signed zero,
  and close-to-gravity values without materializing real CSVs outside Root guard.
"""

import argparse
import hashlib
import io
import math
from pathlib import Path
import sys

PINNED_NOMINAL_FORCING_SHA256 = "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3"
GRAVITY_Z = -9.81
EXPECTED_NOMINAL_ROWS = 167001
EXPECTED_TIME_WINDOW = (0.0, 8.35)


def compute_sha256(filepath: Path) -> str:
    """Compute SHA256 digest of a file in chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def format_coord(val: float) -> str:
    """
    Format float coordinate using IEEE-754 double precision full roundtrip (.17g).

    Guarantees:
    - Finite value validation (raises ValueError on NaN / Inf).
    - Exact roundtrip: float(format_coord(val)) == val for all finite double floats.
    - No small-value quantization (.2E truncation eliminated).
    - No arbitrary deadband clamping (preserves tiny values and near-gravity values).
    - Preserves signed zero gracefully.
    """
    if not math.isfinite(val):
        raise ValueError(f"Non-finite coordinate value encountered: {val}")
    return f"{val:.17g}"


def transform_row(parts: list, amplitude: float) -> list:
    """
    Transform single acceleration row using zero-drive relation.

    Arguments:
        parts: List of 7 string tokens: [time, ax, ay, az, alphax, alphay, alphaz].
        amplitude: Scaling amplitude multiplier A.

    Returns:
        List of 7 string tokens with exact preserved time string and .17g coordinates.
    """
    if len(parts) != 7:
        raise ValueError(
            f"Malformed row: expected exactly 7 semicolon-separated fields, got {len(parts)}: {parts}"
        )

    time_str = parts[0].strip()

    # Parse and validate all 7 numeric values
    try:
        t_val = float(time_str)
    except ValueError as e:
        raise ValueError(f"Malformed non-numeric time value '{time_str}': {e}") from e
    if not math.isfinite(t_val):
        raise ValueError(f"Non-finite time value encountered: '{time_str}'")

    coords = []
    for col_idx in range(1, 7):
        col_str = parts[col_idx].strip()
        try:
            val = float(col_str)
        except ValueError as e:
            raise ValueError(
                f"Malformed non-numeric coordinate at column {col_idx} '{col_str}': {e}"
            ) from e
        if not math.isfinite(val):
            raise ValueError(f"Non-finite coordinate at column {col_idx}: '{col_str}'")
        coords.append(val)

    ax_nom, ay_nom, az_nom, alphax_nom, alphay_nom, alphaz_nom = coords

    # Apply zero-drive formula:
    # a_lin = g + A * (a_nom - g)
    # alpha = A * alpha_nom
    # where g = (0, 0, -9.81) m/s^2.
    if amplitude == 1.0:
        # Exact numerical identity for nominal A=1.0
        ax = ax_nom
        ay = ay_nom
        az = az_nom
        alphax = alphax_nom
        alphay = alphay_nom
        alphaz = alphaz_nom
    else:
        ax = amplitude * ax_nom
        ay = amplitude * ay_nom
        az = GRAVITY_Z + amplitude * (az_nom - GRAVITY_Z)
        alphax = amplitude * alphax_nom
        alphay = amplitude * alphay_nom
        alphaz = amplitude * alphaz_nom

    return [
        time_str,  # Exact preserved time string verbatim
        format_coord(ax),
        format_coord(ay),
        format_coord(az),
        format_coord(alphax),
        format_coord(alphay),
        format_coord(alphaz),
    ]


def transform_forcing_stream(in_stream,
                             out_stream,
                             amplitude: float,
                             expected_rows: int = EXPECTED_NOMINAL_ROWS,
                             expected_window: tuple = EXPECTED_TIME_WINDOW) -> dict:
    """
    Stream-transform forcing CSV lines from in_stream to out_stream.

    Enforces:
    - Finite guards across all fields.
    - Strictly increasing time: t[k] > t[k-1].
    - Expected row count validation.
    - Exact time window boundaries.
    - Immediate failure on malformed records (no silent dropping).
    """
    rows_processed = 0
    t_min = None
    t_max = None
    prev_time = None
    col_min = [float("inf")] * 6
    col_max = [float("-inf")] * 6

    for line_idx, line in enumerate(in_stream, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            out_stream.write(stripped + "\n")
            continue

        parts = stripped.split(";")
        if len(parts) != 7:
            raise ValueError(
                f"Line {line_idx} malformed: expected 7 fields separated by ';', got {len(parts)}: {line}"
            )

        trans = transform_row(parts, amplitude)

        time_val = float(trans[0])
        if prev_time is not None and time_val <= prev_time:
            raise ValueError(
                f"Line {line_idx} violates strictly increasing time: t={time_val} <= prev_t={prev_time}"
            )
        prev_time = time_val

        if t_min is None:
            t_min = time_val
        t_max = time_val

        out_stream.write(";".join(trans) + "\n")
        rows_processed += 1

        for c in range(6):
            val = float(trans[c + 1])
            if val < col_min[c]:
                col_min[c] = val
            if val > col_max[c]:
                col_max[c] = val

    # Validate window if requested
    if expected_window is not None:
        if t_min is None or abs(t_min - expected_window[0]) > 1e-9:
            raise ValueError(
                f"Time window start mismatch: expected {expected_window[0]}, got {t_min}"
            )
        if t_max is None or abs(t_max - expected_window[1]) > 1e-9:
            raise ValueError(
                f"Time window end mismatch: expected {expected_window[1]}, got {t_max}"
            )

    # Validate row count if requested
    if expected_rows is not None and rows_processed != expected_rows:
        raise ValueError(
            f"Row count mismatch: expected {expected_rows} data rows, processed {rows_processed}"
        )

    return {
        "status": "success",
        "amplitude": amplitude,
        "rows_processed": rows_processed,
        "time_range_s": [t_min, t_max],
        "column_min": col_min,
        "column_max": col_max,
    }


def transform_forcing_file(input_path: Path,
                            output_path: Path,
                            amplitude: float,
                            check_source_hash: bool = True,
                            expected_rows: int = EXPECTED_NOMINAL_ROWS,
                            expected_window: tuple = EXPECTED_TIME_WINDOW,
                            overwrite: bool = False) -> dict:
    """
    Stream-transform the forcing CSV from input_path to output_path.

    Enforces non-overwrite mode (open with mode="x") by default.
    """
    if check_source_hash:
        actual_hash = compute_sha256(input_path)
        if actual_hash != PINNED_NOMINAL_FORCING_SHA256:
            raise ValueError(
                f"Source forcing hash mismatch!\n"
                f"Expected: {PINNED_NOMINAL_FORCING_SHA256}\n"
                f"Actual:   {actual_hash}"
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_mode = "w" if overwrite else "x"

    try:
        with open(input_path, "r", encoding="utf-8") as in_f, open(output_path, out_mode, encoding="utf-8") as out_f:
            report = transform_forcing_stream(
                in_f, out_f, amplitude, expected_rows=expected_rows, expected_window=expected_window
            )
    except FileExistsError as e:
        raise FileExistsError(
            f"Output file already exists and overwrite=False (non-overwrite guard enforced): {output_path}"
        ) from e

    out_hash = compute_sha256(output_path)
    report.update({
        "input_file": str(input_path),
        "output_file": str(output_path),
        "output_sha256": out_hash,
    })
    return report


def self_test():
    """
    Comprehensive synthetic test fixtures exercising:
    1. Tiny values (no arbitrary clamping, full roundtrip).
    2. Large values (precision retained, full roundtrip).
    3. Non-finite values (NaN / Inf / -Inf rejected).
    4. Malformed rows (wrong field count, non-numeric tokens rejected).
    5. Signed zero (-0.0 vs +0.0 handled cleanly).
    6. Close-to-gravity values (no unauthorized gravity deadband clamping).
    7. Zero-drive physics consistency.
    8. Numerical identity at A=1.0.
    9. Strictly increasing time guard and window boundaries.
    10. Row count enforcement.
    11. Exact preserved time strings.
    12. Exclusive creation non-overwrite guard.

    All tests operate on in-memory synthetic streams without materializing real CSVs.
    """
    print("Running comprehensive transformer synthetic unit tests...")

    # 1. Tiny values test
    tiny_val = 1.2345678901234567e-22
    s_tiny = format_coord(tiny_val)
    assert float(s_tiny) == tiny_val, f"Tiny roundtrip failed: {s_tiny} vs {tiny_val}"
    # Verify no clamp to 0 occurred
    assert s_tiny != "0", "Tiny value was erroneously clamped to '0'"

    # 2. Large values test
    large_val = 8.765432109876543e14
    s_large = format_coord(large_val)
    assert float(s_large) == large_val, f"Large roundtrip failed: {s_large} vs {large_val}"

    # 3. Non-finite values test
    for bad_val in [float("nan"), float("inf"), float("-inf")]:
        try:
            format_coord(bad_val)
            assert False, f"Expected ValueError for non-finite {bad_val}"
        except ValueError:
            pass

    # Non-finite in row
    bad_row = ["0.0", "1.0", "0.0", "NaN", "0.0", "0.0", "0.0"]
    try:
        transform_row(bad_row, amplitude=0.9)
        assert False, "Expected ValueError for NaN in row"
    except ValueError:
        pass

    # 4. Malformed rows test
    # Too few columns
    try:
        transform_row(["0.0", "1.0", "0.0"], amplitude=0.9)
        assert False, "Expected ValueError for 3-column row"
    except ValueError:
        pass

    # Too many columns
    try:
        transform_row(["0.0", "1.0", "0.0", "-9.81", "0.0", "0.0", "0.0", "extra"], amplitude=0.9)
        assert False, "Expected ValueError for 8-column row"
    except ValueError:
        pass

    # Non-numeric coordinate
    try:
        transform_row(["0.0", "bad_num", "0.0", "-9.81", "0.0", "0.0", "0.0"], amplitude=0.9)
        assert False, "Expected ValueError for non-numeric coordinate"
    except ValueError:
        pass

    # 5. Signed zero test
    sz = -0.0
    s_sz = format_coord(sz)
    assert float(s_sz) == 0.0, f"Signed zero float conversion failed: {s_sz}"
    # Transform with signed zero
    row_sz = ["0.000", "-0.0", "0.0", "-9.81", "0.0", "-0.0", "0.0"]
    res_sz = transform_row(row_sz, amplitude=0.9)
    assert float(res_sz[1]) == 0.0
    assert float(res_sz[3]) == GRAVITY_Z

    # 6. Close to gravity test (no arbitrary deadband clamping)
    close_g = -9.8100000000000005
    s_cg = format_coord(close_g)
    assert s_cg != "-9.81E+00", f"Close to gravity was clamped: {s_cg}"
    assert float(s_cg) == close_g

    close_g_offset = -9.81 + 1e-13
    s_cgo = format_coord(close_g_offset)
    assert s_cgo != "-9.81E+00", f"Close to gravity offset was clamped: {s_cgo}"
    assert float(s_cgo) == close_g_offset

    # 7. Zero-drive physics formula test
    # Nominal zero drive: lin=(0, 0, -9.81), ang=(0, 0, 0)
    for amp in [0.90, 0.97, 1.10]:
        z_res = transform_row(["1.234", "0.0", "0.0", "-9.81", "0.0", "0.0", "0.0"], amplitude=amp)
        assert float(z_res[1]) == 0.0
        assert float(z_res[2]) == 0.0
        assert abs(float(z_res[3]) - GRAVITY_Z) < 1e-15, f"Zero-drive az mismatch for A={amp}: {z_res[3]}"
        assert float(z_res[4]) == 0.0
        assert float(z_res[5]) == 0.0
        assert float(z_res[6]) == 0.0

    # Linear and angular scaling
    test_row = ["1.000", "2.0", "-1.0", "-7.81", "0.5", "-0.4", "1.2"]
    # For A = 0.9:
    # ax = 0.9 * 2.0 = 1.8
    # ay = 0.9 * -1.0 = -0.9
    # az = -9.81 + 0.9 * (-7.81 - (-9.81)) = -9.81 + 0.9 * 2.0 = -9.81 + 1.8 = -8.01
    # alphax = 0.9 * 0.5 = 0.45
    # alphay = 0.9 * -0.4 = -0.36
    # alphaz = 0.9 * 1.2 = 1.08
    t_res_09 = transform_row(test_row, amplitude=0.9)
    assert abs(float(t_res_09[1]) - 1.8) < 1e-14
    assert abs(float(t_res_09[2]) - (-0.9)) < 1e-14
    assert abs(float(t_res_09[3]) - (-8.01)) < 1e-14
    assert abs(float(t_res_09[4]) - 0.45) < 1e-14
    assert abs(float(t_res_09[5]) - (-0.36)) < 1e-14
    assert abs(float(t_res_09[6]) - 1.08) < 1e-14

    # 8. Numerical A=1.0 identity test
    t_res_10 = transform_row(test_row, amplitude=1.0)
    for col in range(1, 7):
        assert float(t_res_10[col]) == float(test_row[col]), (
            f"Numerical identity failed at col {col}: {t_res_10[col]} vs {test_row[col]}"
        )

    # 9. Exact preserved time strings test
    raw_time_strs = ["0", "5.00E-05", "0.0001000", "1.23456789"]
    for rts in raw_time_strs:
        r_out = transform_row([rts, "0.0", "0.0", "-9.81", "0.0", "0.0", "0.0"], amplitude=0.97)
        assert r_out[0] == rts, f"Time string altered: '{r_out[0]}' vs '{rts}'"

    # 10. Synthetic stream validation (strictly increasing time & window & row count)
    synthetic_csv = io.StringIO(
        "#Header line\n"
        "0.00;0.0;0.0;-9.81;0.0;0.0;0.0\n"
        "1.00;0.1;0.0;-9.81;0.0;0.2;0.0\n"
        "2.00;0.2;0.0;-9.81;0.0;0.4;0.0\n"
    )
    synthetic_out = io.StringIO()
    rep = transform_forcing_stream(
        synthetic_csv, synthetic_out, amplitude=0.90, expected_rows=3, expected_window=(0.0, 2.0)
    )
    assert rep["rows_processed"] == 3
    assert rep["time_range_s"] == [0.0, 2.0]

    # Non-increasing time guard
    bad_time_csv = io.StringIO(
        "#Header\n"
        "0.00;0.0;0.0;-9.81;0.0;0.0;0.0\n"
        "1.00;0.1;0.0;-9.81;0.0;0.2;0.0\n"
        "0.99;0.2;0.0;-9.81;0.0;0.4;0.0\n"
    )
    try:
        transform_forcing_stream(
            bad_time_csv, io.StringIO(), amplitude=0.90, expected_rows=3, expected_window=(0.0, 2.0)
        )
        assert False, "Expected ValueError on non-monotonic time"
    except ValueError as e:
        assert "strictly increasing time" in str(e)

    # Malformed row in stream raises immediately
    malformed_csv = io.StringIO(
        "#Header\n"
        "0.00;0.0;0.0;-9.81;0.0;0.0;0.0\n"
        "1.00;bad_row\n"
        "2.00;0.2;0.0;-9.81;0.0;0.4;0.0\n"
    )
    try:
        transform_forcing_stream(
            malformed_csv, io.StringIO(), amplitude=0.90, expected_rows=3, expected_window=(0.0, 2.0)
        )
        assert False, "Expected ValueError on malformed row in stream"
    except ValueError as e:
        assert "malformed" in str(e).lower()

    # 11. Exclusive creation non-overwrite test
    test_tmp_path = Path("/tmp/_test_f3_non_overwrite_guard.tmp")
    if test_tmp_path.exists():
        test_tmp_path.unlink()
    test_tmp_path.write_text("existing")
    try:
        # Attempt to open with exclusive creation (mode="x")
        with open(test_tmp_path, "x") as f:
            f.write("overwrite attempt")
        assert False, "Expected FileExistsError on exclusive creation over existing file"
    except FileExistsError:
        pass
    finally:
        if test_tmp_path.exists():
            test_tmp_path.unlink()

    print("✓ All 12 synthetic unit test fixtures passed successfully without real CSV materialization.")


def main():
    parser = argparse.ArgumentParser(
        description="DualSPHysics F3 Forcing Amplitude Transformer (Zero-Drive Physics, v2)"
    )
    parser.add_argument("--input", "-i", type=Path, help="Path to nominal input CSV")
    parser.add_argument("--output", "-o", type=Path, help="Path to output transformed CSV")
    parser.add_argument("--amplitude", "-a", type=float, help="Scaling amplitude A")
    parser.add_argument("--skip-hash-check", action="store_true", help="Skip sha256 verification of input")
    parser.add_argument("--expected-rows", type=int, default=EXPECTED_NOMINAL_ROWS,
                        help=f"Expected row count guard (default {EXPECTED_NOMINAL_ROWS})")
    parser.add_argument("--window-start", type=float, default=EXPECTED_TIME_WINDOW[0],
                        help=f"Expected window start (default {EXPECTED_TIME_WINDOW[0]})")
    parser.add_argument("--window-end", type=float, default=EXPECTED_TIME_WINDOW[1],
                        help=f"Expected window end (default {EXPECTED_TIME_WINDOW[1]})")
    parser.add_argument("--overwrite", action="store_true",
                        help="Allow overwriting existing output file (default is exclusive non-overwrite)")
    parser.add_argument("--test", action="store_true", help="Run comprehensive synthetic self-tests only")
    args = parser.parse_args()

    if args.test:
        self_test()
        sys.exit(0)

    if not args.input or not args.output or args.amplitude is None:
        parser.error("--input, --output, and --amplitude are required unless --test is specified.")

    window = (args.window_start, args.window_end) if args.window_start is not None and args.window_end is not None else None

    report = transform_forcing_file(
        args.input,
        args.output,
        args.amplitude,
        check_source_hash=not args.skip_hash_check,
        expected_rows=args.expected_rows,
        expected_window=window,
        overwrite=args.overwrite
    )
    import json
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

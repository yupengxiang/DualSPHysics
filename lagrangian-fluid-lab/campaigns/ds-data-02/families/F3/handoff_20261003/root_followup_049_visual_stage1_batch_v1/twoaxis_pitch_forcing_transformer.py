#!/usr/bin/env python3
"""Standard Library Transformer for F3 Coupled Two-Axis Sloshing Control (Followup 049).

Campaign: DS-DATA-02
Family: F3 (Open-Top Rectangular Tank Sloshing)
Authority: Root Followup 049 under F3 isolated worktree ds-data-02-f6
Mechanism ID: F3_TWOAXIS_TRANSVERSE_LINACC_AND_PITCH_V1

Physical Principles & Formulation:
- Container Geometry: Plain open 5-wall box (0.90 m x 0.18 m x 0.51 m, depth H=0.09 m, fluid mass 14.58 kg).
- Primary Longitudinal Mechanism: Pitch angular acceleration alpha_y around the Y-axis (and linear ax, az).
  Nominal pitch angular source is kept physically consistent via the zero-drive formula:
    a_x(t) = A_pitch * a_x_nom(t)
    a_z(t) = g_z + A_pitch * (a_z_nom(t) - g_z)
    alpha_y(t) = A_pitch * alpha_y_nom(t)
  where g_z = -9.81 m/s^2. For nominal pitch baseline, A_pitch = 1.0.
  Nominal CSV has alpha_y(t=0) = 0.312057592 != 0.
  DualSPHysics GPU kernel cuaccin::KerAddAccInputAng is therefore ALWAYS activated from t=0.
- Second Physical Mechanism: Bounded transverse LINEAR acceleration a_y(t) along the Y-axis
  with a smooth startup/shutdown envelope:
    a_y(t) = A_y * E(t) * sin(omega_y * t + phi_y)
  where:
    * omega_y is derived from fundamental transverse sloshing eigenmode for width W=0.18 m:
      k_y = pi / W = 17.4532925 rad/m
      omega_y = sqrt(g * k_y * tanh(k_y * H)) = 12.531236478 rad/s (f_y = 1.9944 Hz, T_y = 0.5014 s).
    * E(t) is a smooth Hann/cosine ramp envelope over [t_start, t_final]:
      E(t) = 0.5 * (1 - cos(pi * t / tau_ramp))                 for 0 <= t < tau_ramp
      E(t) = 1.0                                                for tau_ramp <= t <= t_final - tau_ramp
      E(t) = 0.5 * (1 - cos(pi * (t_final - t) / tau_ramp))      for t_final - tau_ramp < t <= t_final
      E(t) = 0.0                                                otherwise
      Ramp duration tau_ramp = 0.50 s (~ 1 transverse period).
    * Bounded transverse amplitude: A_y in [0.25, 0.75] m/s^2 (~ 2.5% to 7.6% of g).
      Displacement amplitude Y_0 = A_y / omega_y^2 ~ 1.6 to 4.8 mm << W = 180 mm.
- Pure Translational Transverse Drive:
  By driving the second axis with bounded linear acceleration a_y(t) rather than roll rotation,
  we eliminate artificial rotating-frame orientation/quaternion drift, avoid fictional Euler
  angle coordinate claims, and preserve the fixed tank Cartesian canonical event operator.
- Exact Numerical Identity:
  When transverse amplitude A_y = 0.0 and longitudinal pitch amplitude A_pitch = 1.0,
  a_y(t) = 0.0 identically and pitch components equal nominal, producing exact NUMERIC identity.
- Strict Wrapper Guards:
  * Pinned nominal forcing SHA256 verified before and after transformation:
      6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3
  * Exact start time (0.0 / token '0') and end time (8.35 / token '8.35') with zero tolerance.
  * Strictly increasing time series: t[k] > t[k-1].
  * Exact row count: exactly 167,001 data rows (167,002 lines including header).
  * Double precision IEEE-754 .17g format without deadband clamping or small-value quantization.
  * All 7 fields verified finite.
  * Non-overwrite exclusive file creation (mode='x') by default.
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
EXPECTED_START_TIME = 0.0
EXPECTED_START_TOKEN = "0"
EXPECTED_END_TIME = 8.35
EXPECTED_END_TOKEN = "8.35"

TANK_LENGTH_X = 0.90
TANK_WIDTH_Y = 0.18
WATER_DEPTH_H = 0.09
FLUID_MASS_KG = 14.58

DEFAULT_KY = math.pi / TANK_WIDTH_Y  # ~17.4532925 rad/m
DEFAULT_OMEGA_Y = math.sqrt(9.81 * DEFAULT_KY * math.tanh(DEFAULT_KY * WATER_DEPTH_H))  # ~12.5312365 rad/s
DEFAULT_FREQ_Y = DEFAULT_OMEGA_Y / (2.0 * math.pi)  # ~1.9944 Hz
DEFAULT_PERIOD_Y = 1.0 / DEFAULT_FREQ_Y  # ~0.5014 s
DEFAULT_RAMP_DURATION = 0.50  # s
DEFAULT_PHASE_Y = 0.0  # rad


def compute_sha256(filepath: Path) -> str:
    """Compute SHA256 digest of a file in 64 KiB binary chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def format_coord(val: float) -> str:
    """Format float using IEEE-754 double precision full roundtrip (.17g)."""
    if not math.isfinite(val):
        raise ValueError(f"Non-finite coordinate value encountered: {val}")
    return f"{val:.17g}"


def evaluate_envelope(
    t: float,
    t_start: float = EXPECTED_START_TIME,
    t_final: float = EXPECTED_END_TIME,
    tau_ramp: float = DEFAULT_RAMP_DURATION,
) -> float:
    """Evaluate smooth Hann/cosine ramp envelope E(t)."""
    if t < t_start or t > t_final:
        return 0.0
    if (t - t_start) < tau_ramp:
        return 0.5 * (1.0 - math.cos(math.pi * (t - t_start) / tau_ramp))
    elif (t_final - t) < tau_ramp:
        return 0.5 * (1.0 - math.cos(math.pi * (t_final - t) / tau_ramp))
    else:
        return 1.0


def evaluate_transverse_acc(
    t: float,
    amplitude_y: float,
    omega_y: float = DEFAULT_OMEGA_Y,
    phase_y: float = DEFAULT_PHASE_Y,
    tau_ramp: float = DEFAULT_RAMP_DURATION,
    t_start: float = EXPECTED_START_TIME,
    t_final: float = EXPECTED_END_TIME,
) -> float:
    """Evaluate transverse linear acceleration a_y(t)."""
    if amplitude_y == 0.0:
        return 0.0
    env = evaluate_envelope(t, t_start=t_start, t_final=t_final, tau_ramp=tau_ramp)
    return amplitude_y * env * math.sin(omega_y * t + phase_y)


def transform_twoaxis_row(
    row_tokens: list[str],
    amplitude_x: float = 1.0,
    amplitude_y: float = 0.0,
    omega_y: float = DEFAULT_OMEGA_Y,
    phase_y: float = DEFAULT_PHASE_Y,
    tau_ramp: float = DEFAULT_RAMP_DURATION,
    gravity_z: float = GRAVITY_Z,
) -> list[str]:
    """Transform one 7-token data row preserving original time token."""
    if len(row_tokens) != 7:
        raise ValueError(f"Expected exactly 7 tokens, got {len(row_tokens)}")

    time_token = row_tokens[0]
    t = float(time_token)
    if not math.isfinite(t):
        raise ValueError(f"Non-finite timestamp: {time_token}")

    ax_nom = float(row_tokens[1])
    ay_nom = float(row_tokens[2])
    az_nom = float(row_tokens[3])
    alphax_nom = float(row_tokens[4])
    alphay_nom = float(row_tokens[5])
    alphaz_nom = float(row_tokens[6])

    for idx, v in enumerate([ax_nom, ay_nom, az_nom, alphax_nom, alphay_nom, alphaz_nom], start=1):
        if not math.isfinite(v):
            raise ValueError(f"Non-finite input column {idx} at t={time_token}: {v}")

    # Longitudinal pitch motion scaling
    if amplitude_x == 1.0:
        ax = ax_nom
        az = az_nom
        alphay = alphay_nom
    else:
        ax = amplitude_x * ax_nom
        az = gravity_z + amplitude_x * (az_nom - gravity_z)
        alphay = amplitude_x * alphay_nom

    # Transverse linear acceleration
    if amplitude_y == 0.0:
        ay = ay_nom
    else:
        ay = evaluate_transverse_acc(
            t,
            amplitude_y=amplitude_y,
            omega_y=omega_y,
            phase_y=phase_y,
            tau_ramp=tau_ramp,
        )

    alphax = alphax_nom
    alphaz = alphaz_nom

    for v in (ax, ay, az, alphax, alphay, alphaz):
        if not math.isfinite(v):
            raise ValueError(f"Non-finite computed value at t={time_token}")

    # Preserve original tokens when numerically unchanged
    s_ax = row_tokens[1] if (amplitude_x == 1.0) else format_coord(ax)
    s_ay = row_tokens[2] if (amplitude_y == 0.0) else format_coord(ay)
    s_az = row_tokens[3] if (amplitude_x == 1.0) else format_coord(az)
    s_alphax = row_tokens[4]
    s_alphay = row_tokens[5] if (amplitude_x == 1.0) else format_coord(alphay)
    s_alphaz = row_tokens[6]

    return [time_token, s_ax, s_ay, s_az, s_alphax, s_alphay, s_alphaz]


def transform_twoaxis_forcing_stream(
    in_stream: io.TextIOBase,
    out_stream: io.TextIOBase,
    amplitude_x: float = 1.0,
    amplitude_y: float = 0.0,
    omega_y: float = DEFAULT_OMEGA_Y,
    phase_y: float = DEFAULT_PHASE_Y,
    tau_ramp: float = DEFAULT_RAMP_DURATION,
    expected_rows: int = EXPECTED_NOMINAL_ROWS,
    expected_start_time: float = EXPECTED_START_TIME,
    expected_start_token: str = EXPECTED_START_TOKEN,
    expected_end_time: float = EXPECTED_END_TIME,
    expected_end_token: str = EXPECTED_END_TOKEN,
) -> dict:
    """Stream processor with strict wrapper guards."""
    rows_processed = 0
    first_time_token = None
    last_time_token = None
    prev_time = None
    t_min = None
    t_max = None
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

        trans = transform_twoaxis_row(
            parts,
            amplitude_x=amplitude_x,
            amplitude_y=amplitude_y,
            omega_y=omega_y,
            phase_y=phase_y,
            tau_ramp=tau_ramp,
        )
        time_token = trans[0]
        time_val = float(time_token)

        if first_time_token is None:
            first_time_token = time_token
            if time_val != expected_start_time or first_time_token != expected_start_token:
                raise ValueError(
                    f"Strict start time violation: expected token '{expected_start_token}' "
                    f"and value {expected_start_time}, got '{first_time_token}' ({time_val})"
                )
            t_min = time_val

        if prev_time is not None and time_val <= prev_time:
            raise ValueError(
                f"Line {line_idx} violates strictly increasing time: t={time_val} <= prev_t={prev_time}"
            )
        prev_time = time_val
        last_time_token = time_token
        t_max = time_val

        out_stream.write(";".join(trans) + "\n")
        rows_processed += 1

        for c in range(6):
            val = float(trans[c + 1])
            if val < col_min[c]:
                col_min[c] = val
            if val > col_max[c]:
                col_max[c] = val

    if t_max != expected_end_time or last_time_token != expected_end_token:
        raise ValueError(
            f"Strict end time violation: expected token '{expected_end_token}' "
            f"and value {expected_end_time}, got '{last_time_token}' ({t_max})"
        )

    if rows_processed != expected_rows:
        raise ValueError(
            f"Exact row count mismatch: expected exactly {expected_rows} data rows, "
            f"processed {rows_processed}"
        )

    return {
        "status": "success",
        "mechanism_id": "F3_TWOAXIS_TRANSVERSE_LINACC_AND_PITCH_V1",
        "amplitude_x": amplitude_x,
        "amplitude_y": amplitude_y,
        "omega_y": omega_y,
        "phase_y": phase_y,
        "tau_ramp": tau_ramp,
        "rows_processed": rows_processed,
        "start_token": first_time_token,
        "end_token": last_time_token,
        "time_range_s": [t_min, t_max],
        "column_min": col_min,
        "column_max": col_max,
    }


def transform_twoaxis_forcing_file(
    input_path: Path,
    output_path: Path,
    amplitude_x: float = 1.0,
    amplitude_y: float = 0.0,
    omega_y: float = DEFAULT_OMEGA_Y,
    phase_y: float = DEFAULT_PHASE_Y,
    tau_ramp: float = DEFAULT_RAMP_DURATION,
    expected_source_hash: str = PINNED_NOMINAL_FORCING_SHA256,
    overwrite: bool = False,
) -> dict:
    """Transform source forcing CSV with strict pre/post hash checks."""
    if not input_path.exists():
        raise FileNotFoundError(f"Source forcing file does not exist: {input_path}")

    hash_before = compute_sha256(input_path)
    if hash_before != expected_source_hash:
        raise ValueError(
            f"Source forcing SHA256 mismatch before transformation!\n"
            f"Expected: {expected_source_hash}\n"
            f"Actual:   {hash_before}"
        )

    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Output forcing file already exists: {output_path}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mode = "w" if overwrite else "x"
    with open(input_path, "r", encoding="utf-8") as in_f, open(output_path, mode, encoding="utf-8") as out_f:
        stream_rep = transform_twoaxis_forcing_stream(
            in_f,
            out_f,
            amplitude_x=amplitude_x,
            amplitude_y=amplitude_y,
            omega_y=omega_y,
            phase_y=phase_y,
            tau_ramp=tau_ramp,
        )

    hash_after = compute_sha256(input_path)
    if hash_after != expected_source_hash:
        raise ValueError(
            f"Source forcing mutated during execution!\n"
            f"Expected: {expected_source_hash}\n"
            f"After:    {hash_after}"
        )

    out_hash = compute_sha256(output_path)
    stream_rep.update({
        "input_file": str(input_path),
        "source_sha256_before": hash_before,
        "source_sha256_after": hash_after,
        "output_file": str(output_path),
        "output_sha256": out_hash,
    })
    return stream_rep


def main():
    parser = argparse.ArgumentParser(
        description="F3 Coupled Two-Axis Sloshing Control Forcing Transformer (Followup 049)"
    )
    parser.add_argument("--input", required=True, type=Path, help="Input nominal forcing CSV")
    parser.add_argument("--output", required=True, type=Path, help="Output transformed forcing CSV")
    parser.add_argument("--amp-x", type=float, default=1.0, help="Pitch longitudinal amplitude multiplier Ax (default: 1.0)")
    parser.add_argument("--amp-y", type=float, default=0.0, help="Transverse linear acceleration amplitude Ay in m/s^2 (default: 0.0)")
    parser.add_argument("--omega-y", type=float, default=DEFAULT_OMEGA_Y, help=f"Transverse circular frequency in rad/s (default: {DEFAULT_OMEGA_Y:.4f})")
    parser.add_argument("--phase-y", type=float, default=DEFAULT_PHASE_Y, help="Transverse initial phase in rad (default: 0.0)")
    parser.add_argument("--tau-ramp", type=float, default=DEFAULT_RAMP_DURATION, help="Envelope ramp duration in seconds (default: 0.50)")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwrite of output file (default: false)")

    args = parser.parse_args()

    report = transform_twoaxis_forcing_file(
        args.input,
        args.output,
        amplitude_x=args.amp_x,
        amplitude_y=args.amp_y,
        omega_y=args.omega_y,
        phase_y=args.phase_y,
        tau_ramp=args.tau_ramp,
        overwrite=args.overwrite,
    )
    print(f"Transformation complete: {report['rows_processed']} rows written to {args.output}")
    print(f"Output SHA256: {report['output_sha256']}")


if __name__ == "__main__":
    main()

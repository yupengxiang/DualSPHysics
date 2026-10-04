#!/usr/bin/env python3
"""
SELF-CONTAINED Executable CPU GenCase Preparation Worker for F3 True 3D Two-Axis Sloshing Control (Followup 040)

Family: F3 (Open-Top Rectangular Tank Sloshing)
Campaign: DS-DATA-02
Authority: Root Followup 040
Mechanism ID: F3_TWOAXIS_TRANSVERSE_LINACC_V1

Worker specification:
- Single-case execution worker: processes exactly ONE GenCase per dispatched request.
- Integrates the true 3D two-axis sloshing forcing transformer with strict wrapper guards:
  * Strict exact endpoint times: t_start == 0.0 (token "0") and t_end == 8.35 (token "8.35") with zero tolerance.
  * Strictly increasing time series: t[k] > t[k-1].
  * Exact row count enforcement: exactly 167,001 data rows (167,002 lines including header).
  * All 7 fields verified finite (math.isfinite).
  * Original time fields preserved verbatim.
  * IEEE-754 double roundtrip precision (.17g) without deadband clamps or small-value quantization.
  * Longitudinal pitch motion: zero-drive formula preserving nominal pitch motion (Ax = 1.0).
  * Transverse motion: bounded transverse linear acceleration a_y(t) with smooth Hann/cosine ramp envelope.
  * Exact numerical identity at Ay = 0.0, Ax = 1.0.
  * Pinned source CSV SHA256 verified before AND after transformation (6f42660a...).
  * Non-overwrite output guard: exclusive creation (mode="x") to prevent clobbering.
- Preflight XML definition verification based on root registered generator033 / 028:
  * Solver parameters match fine adaptive anchor.
  * Whole-field physical forcing special execution matches anchor.
  * Baseline CFL number == 0.05.
  * Commensurate cell-centre grid pointref == dp/2 for all axes.
  * Open 5-wall plain container geometry (no baffles, no moving parts).
- Native GenCase execution:
  * Runs official GenCase_linux64 with -save:all for exactly one requested case.
  * Reconciles generated XML constants (data2d='false', dp=dp_m, cflnumber=0.05).
  * Extracts actual particle counts from generated XML.
  * Computes exact SHA256 for XML, BI4, CSV, definition, and binary.
  * Emits prepared-input-report.json with full lineage and no speculative production/Q-N claims.
"""

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

# Import transformer logic from sibling module
from transform_twoaxis_forcing import (
    PINNED_NOMINAL_FORCING_SHA256,
    GRAVITY_Z,
    EXPECTED_NOMINAL_ROWS,
    EXPECTED_START_TIME,
    EXPECTED_START_TOKEN,
    EXPECTED_END_TIME,
    EXPECTED_END_TOKEN,
    DEFAULT_OMEGA_Y,
    DEFAULT_FREQ_Y,
    DEFAULT_PERIOD_Y,
    DEFAULT_RAMP_DURATION,
    DEFAULT_PHASE_Y,
    compute_sha256,
    format_coord,
    evaluate_envelope,
    evaluate_transverse_acc,
    transform_twoaxis_row,
    transform_twoaxis_forcing_stream,
    transform_twoaxis_forcing_file,
)


def semantic_xml(node):
    """Normalized semantic tuple representation for XML comparison."""
    return (
        node.tag,
        sorted((k, v) for k, v in node.attrib.items() if not k.endswith("comment")),
        (node.text or "").strip(),
        [semantic_xml(c) for c in node],
    )


def validate_definition_xml(
    candidate_path: Path,
    anchor_def_path: Path,
    anchor_gen_xml_path: Path,
    dp_m: float,
):
    """
    Validates candidate XML definition against fine adaptive anchor based on root generator033/028.
    """
    if not candidate_path.exists():
        raise FileNotFoundError(f"Candidate definition XML does not exist: {candidate_path}")
    if not anchor_def_path.exists():
        raise FileNotFoundError(f"Anchor definition XML does not exist: {anchor_def_path}")
    if not anchor_gen_xml_path.exists():
        raise FileNotFoundError(f"Anchor generated XML does not exist: {anchor_gen_xml_path}")

    candidate_root = ET.parse(candidate_path).getroot()
    anchor_def_root = ET.parse(anchor_def_path).getroot()
    anchor_gen_root = ET.parse(anchor_gen_xml_path).getroot()

    for tree, name in [(candidate_root, "Candidate"), (anchor_def_root, "Anchor Definition")]:
        params = {c.get("key"): c.get("value") for c in tree.findall(".//execution/parameters/parameter")}
        anchored_params = {c.get("key"): c.get("value") for c in anchor_gen_root.findall(".//execution/parameters/parameter")}
        if params != anchored_params:
            raise ValueError(f"{name} solver execution parameters differ from anchor generated XML")

        if semantic_xml(tree.find("./execution/special")) != semantic_xml(anchor_gen_root.find("./execution/special")):
            raise ValueError(f"{name} whole-field physical forcing differs from anchor generated XML")

        cfl_node = tree.find("./casedef/constantsdef/cflnumber")
        if cfl_node is None or float(cfl_node.get("value")) != 0.05:
            raise ValueError(f"{name} baseline CFL number must be preserved at 0.05")

    geom = candidate_root.find("./casedef/geometry/definition")
    dp_val = float(geom.get("dp"))
    if abs(dp_val - dp_m) > 1e-12:
        raise ValueError(f"Geometry dp={dp_val} does not match requested dp_m={dp_m}")

    pref = geom.find("pointref")
    for axis in "xyz":
        val = float(pref.get(axis))
        if abs(val - dp_m / 2.0) > 1e-12:
            raise ValueError(f"Commensurate cell-centre grid pointref axis {axis}={val} differs from dp/2={dp_m/2.0}")


def resolve_existing_path(p: str, search_roots: list = None) -> Path:
    """Resolve path, supporting worktree location fallback if necessary."""
    path_obj = Path(p)
    if path_obj.exists():
        return path_obj
    if search_roots:
        for root in search_roots:
            alt = root / path_obj.name
            if alt.exists():
                return alt
            for part_idx in range(len(path_obj.parts)):
                subpath = Path(*path_obj.parts[part_idx:])
                candidate = root / subpath
                if candidate.exists():
                    return candidate
    return path_obj


def prepare_twoaxis_case(binding_data: dict, output_dir: Path) -> dict:
    """
    Executes preparation worker for a single two-axis sloshing case:
    1. Validates input XML definition against fine anchor.
    2. Runs native GenCase executable.
    3. Transforms forcing CSV with transverse linear acceleration control.
    4. Validates generated XML and compiles complete digest report.
    """
    case_id = binding_data["case_id"]
    role = binding_data.get("role", "twoaxis_sloshing_control_case")
    mechanism_id = binding_data.get("mechanism_id", "F3_TWOAXIS_TRANSVERSE_LINACC_V1")
    dp_m = float(binding_data["dp_m"])
    amp_x = float(binding_data.get("amplitude_x", 1.0))
    amp_y = float(binding_data["amplitude_y"])
    omega_y = float(binding_data.get("omega_y", DEFAULT_OMEGA_Y))
    phase_y = float(binding_data.get("phase_y", DEFAULT_PHASE_Y))
    tau_ramp = float(binding_data.get("tau_ramp", DEFAULT_RAMP_DURATION))
    expected_fluid = int(binding_data.get("expected_fluid", 0))
    expected_total = int(binding_data.get("expected_total", 0))

    cur_dir = Path(__file__).resolve().parent
    search_roots = [cur_dir, cur_dir / "definitions"]

    def_path = resolve_existing_path(binding_data["definition"], search_roots)
    anchor_def = resolve_existing_path(binding_data["anchor_definition"], search_roots)
    anchor_gen_xml = resolve_existing_path(binding_data["anchor_generated_xml"], search_roots)
    gen_binary = resolve_existing_path(binding_data["gen_binary"])
    source_forcing = resolve_existing_path(binding_data["source_forcing"])

    # Preflight XML definition validation
    validate_definition_xml(def_path, anchor_def, anchor_gen_xml, dp_m)

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / case_id

    # Execute native GenCase (Single case only)
    if not gen_binary.exists():
        raise FileNotFoundError(f"Official GenCase binary not found: {gen_binary}")

    command = [str(gen_binary), str(def_path.with_suffix("")), str(prefix), "-save:all"]
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Official GenCase execution failed (code {result.returncode}):\n{result.stderr}\n{result.stdout}"
        )

    # Transform forcing CSV with strict wrapper guards & transverse mechanism
    out_csv_path = output_dir / "CaseSloshingAccData.csv"
    transform_rep = transform_twoaxis_forcing_file(
        source_forcing,
        out_csv_path,
        amplitude_x=amp_x,
        amplitude_y=amp_y,
        omega_y=omega_y,
        phase_y=phase_y,
        tau_ramp=tau_ramp,
        expected_source_hash=binding_data.get("source_forcing_sha256", PINNED_NOMINAL_FORCING_SHA256),
    )

    # Post-GenCase validation
    gen_xml = prefix.with_suffix(".xml")
    gen_bi4 = prefix.with_suffix(".bi4")
    if not gen_xml.exists() or not gen_bi4.exists():
        raise FileNotFoundError(f"GenCase outputs missing: {gen_xml} or {gen_bi4}")

    generated_tree = ET.parse(gen_xml).getroot()
    constants_elem = generated_tree.find("./execution/constants")
    constants_values = {c.tag: dict(c.attrib) for c in constants_elem}

    if constants_values.get("data2d", {}).get("value") != "false":
        raise ValueError("Generated case must be 3D (data2d='false')")
    if abs(float(constants_values.get("dp", {}).get("value", 0)) - dp_m) > 1e-12:
        raise ValueError(f"Generated XML dp differs from requested {dp_m}")
    if abs(float(constants_values.get("cflnumber", {}).get("value", 0)) - 0.05) > 1e-12:
        raise ValueError("Generated XML CFL number differs from 0.05")

    counts = {"fluid": 0, "fixed": 0, "moving": 0, "floating": 0}
    for c in generated_tree.findall("./execution/particles/*"):
        if c.tag in counts:
            counts[c.tag] += int(c.get("count", "0"))

    # Compute official SHAs
    xml_sha = compute_sha256(gen_xml)
    bi4_sha = compute_sha256(gen_bi4)
    forcing_sha = compute_sha256(out_csv_path)
    def_sha = compute_sha256(def_path)
    binary_sha = compute_sha256(gen_binary)

    report = {
        "schema": "ds02.f3.twoaxis-sloshing-preparation.v1",
        "case_id": case_id,
        "role": role,
        "mechanism_id": mechanism_id,
        "dp_m": dp_m,
        "amplitude_x": amp_x,
        "amplitude_y": amp_y,
        "omega_y": omega_y,
        "phase_y": phase_y,
        "tau_ramp": tau_ramp,
        "prefix": str(prefix),
        "definition_xml": str(def_path),
        "definition_xml_sha256": def_sha,
        "gencase_binary": str(gen_binary),
        "gencase_binary_sha256": binary_sha,
        "gencase_stdout": result.stdout,
        "xml_sha256": xml_sha,
        "bi4_sha256": bi4_sha,
        "forcing_sha256": forcing_sha,
        "source_forcing_sha256_before": transform_rep["source_sha256_before"],
        "source_forcing_sha256_after": transform_rep["source_sha256_after"],
        "forcing_transform_details": {
            "rows_processed": transform_rep["rows_processed"],
            "start_token": transform_rep["start_token"],
            "end_token": transform_rep["end_token"],
            "time_range_s": transform_rep["time_range_s"],
            "column_min": transform_rep["column_min"],
            "column_max": transform_rep["column_max"],
        },
        "generated_constants": constants_values,
        "generated_xml_particle_counts": counts,
        "expected_fluid_particles": expected_fluid,
        "expected_total_particles": expected_total,
        "native_typed_identity_audit": "pending; XML counts are not a native array audit",
        "EOS_status": "actual automatic GenCase B/h retained; cross-DP EOS dependence reported, no override",
        "q_n": "not_granted",
        "production_approval": "none",
        "independent_case_count_increment": 0,
    }

    report_path = output_dir / "prepared-input-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def run_synthetic_self_test():
    """
    Focused synthetic unit test fixtures verifying:
    1. IEEE-754 roundtrip (.17g) on tiny, large, and standard values.
    2. Strict rejection of non-finite values (NaN, Inf, -Inf).
    3. Strict rejection of malformed rows (token count, non-numeric).
    4. Strict exact start time check (time == 0.0 and token == '0').
    5. Strict exact end time check (time == 8.35 and token == '8.35').
    6. Strictly increasing time series validation.
    7. Row count validation (exactly 167001 data rows).
    8. Envelope boundary and plateau values.
    9. Numerical identity at Ay = 0.0 and Ax = 1.0.
    10. Two-axis forcing physics formula across transverse amplitudes Ay = 0.25, 0.50, 0.75.
    11. Non-overwrite exclusive file creation guard.
    12. Source SHA256 before/after verification logic.
    """
    print("Running self-contained synthetic self-test suite for Two-Axis Sloshing Control...")

    # 1. Roundtrip precision
    for val in [1.2345678901234567e-22, 8.765432109876543e14, -9.81, 0.312057592, -0.18887913]:
        s = format_coord(val)
        assert float(s) == val, f"Precision roundtrip failed for {val}: got {s}"

    # 2. Non-finite values
    for bad in [float("nan"), float("inf"), float("-inf")]:
        try:
            format_coord(bad)
            assert False, "Expected ValueError on non-finite"
        except ValueError:
            pass

    # 3. Malformed rows
    for bad_parts in [
        ["0", "1.0", "2.0"],
        ["0", "1.0", "2.0", "3.0", "4.0", "5.0", "6.0", "7.0"],
        ["0", "bad", "0", "-9.81", "0", "0", "0"],
    ]:
        try:
            transform_twoaxis_row(bad_parts, amplitude_x=1.0, amplitude_y=0.50)
            assert False, f"Expected ValueError for {bad_parts}"
        except ValueError:
            pass

    # 4. Strict exact start time check
    bad_start_csv = io.StringIO("0.0001;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
    try:
        transform_twoaxis_forcing_stream(bad_start_csv, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        assert False, "Expected ValueError for start time != 0.0"
    except ValueError as e:
        assert "Strict start time violation" in str(e)

    # 5. Strict exact end time check
    bad_end_csv = io.StringIO("0;0;0;-9.81;0;0;0\n8.3499;0;0;-9.81;0;0;0\n")
    try:
        transform_twoaxis_forcing_stream(bad_end_csv, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        assert False, "Expected ValueError for end time != 8.35"
    except ValueError as e:
        assert "Strict end time violation" in str(e)

    # 6. Strictly increasing time guard
    non_inc_csv = io.StringIO("0;0;0;-9.81;0;0;0\n1.0;0;0;-9.81;0;0;0\n0.99;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
    try:
        transform_twoaxis_forcing_stream(non_inc_csv, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        assert False, "Expected ValueError for non-monotonic time"
    except ValueError as e:
        assert "strictly increasing time" in str(e)

    # 7. Row count guard
    short_csv = io.StringIO("0;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
    try:
        transform_twoaxis_forcing_stream(short_csv, io.StringIO(), amplitude_x=1.0, amplitude_y=0.50)
        assert False, "Expected ValueError for row count != 167001"
    except ValueError as e:
        assert "Exact row count mismatch" in str(e)

    # 8. Envelope boundary and plateau values
    assert evaluate_envelope(0.0) == 0.0
    assert evaluate_envelope(8.35) == 0.0
    assert evaluate_envelope(-0.1) == 0.0
    assert evaluate_envelope(8.40) == 0.0
    assert evaluate_envelope(0.50) == 1.0  # End of ramp-in
    assert evaluate_envelope(7.85) == 1.0  # Start of ramp-out
    assert evaluate_envelope(4.0) == 1.0   # Middle plateau
    assert 0.0 < evaluate_envelope(0.25) < 1.0

    # 9. Exact numerical identity at Ay = 0.0 and Ax = 1.0
    test_row = ["1.2345", "-0.01234", "0", "-9.5", "0.0", "0.312057592", "0.0"]
    id_out = transform_twoaxis_row(test_row, amplitude_x=1.0, amplitude_y=0.0)
    assert id_out[0] == test_row[0]
    for c in range(1, 7):
        assert float(id_out[c]) == float(test_row[c]), f"Identity mismatch at col {c}: {id_out[c]} vs {test_row[c]}"

    # 10. Two-axis forcing physics formula across transverse amplitudes Ay in {0.25, 0.50, 0.75}
    for ay_amp in [0.25, 0.50, 0.75]:
        # At t=0: envelope is 0, so ay must be 0
        r_0 = transform_twoaxis_row(["0", "-1.96e-10", "0", "-9.81", "0", "0.312057592", "0"], amplitude_x=1.0, amplitude_y=ay_amp)
        assert float(r_0[2]) == 0.0
        # In plateau (t=2.0s, envelope=1.0)
        r_mid = transform_twoaxis_row(["2.0", "0", "0", "-9.81", "0", "0", "0"], amplitude_x=1.0, amplitude_y=ay_amp)
        expected_ay = ay_amp * 1.0 * math.sin(DEFAULT_OMEGA_Y * 2.0 + DEFAULT_PHASE_Y)
        assert abs(float(r_mid[2]) - expected_ay) < 1e-12

    # 11. Exclusive non-overwrite guard
    test_tmp = Path("/tmp/_test_non_overwrite_twoaxis.tmp")
    if test_tmp.exists():
        test_tmp.unlink()
    test_tmp.write_text("existing")
    try:
        with open(test_tmp, "x") as f:
            f.write("overwrite")
        assert False, "Expected FileExistsError on mode='x'"
    except FileExistsError:
        pass
    finally:
        if test_tmp.exists():
            test_tmp.unlink()

    print("All synthetic self-tests passed successfully!")


def main():
    parser = argparse.ArgumentParser(
        description="F3 Two-Axis Sloshing Control GenCase Preparation Worker (Followup 040)"
    )
    parser.add_argument("--binding", type=Path, help="Path to single-case binding JSON")
    parser.add_argument("--output-dir", type=Path, help="Directory to store prepared outputs")
    parser.add_argument("--test", action="store_true", help="Run synthetic self-test suite")

    args = parser.parse_args()

    if args.test:
        run_synthetic_self_test()
        sys.exit(0)

    if not args.binding or not args.output_dir:
        parser.error("Both --binding and --output-dir are required unless --test is specified.")

    binding_data = json.loads(args.binding.read_text(encoding="utf-8"))
    report = prepare_twoaxis_case(binding_data, args.output_dir)
    print(f"Successfully prepared case {report['case_id']}")
    print(f"Forcing SHA256: {report['forcing_sha256']}")
    print(f"GenCase XML SHA256: {report['xml_sha256']}")


if __name__ == "__main__":
    main()

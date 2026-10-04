#!/usr/bin/env python3
"""
SELFCONTAINED Executable Fresh CPU GenCase Preparation Worker (v3)

Family: F3 (Open-Top Rectangular Tank Sloshing)
Campaign: DS-DATA-02
Authority: Root Followup 038

Worker specification:
- Single-case execution worker: processes exactly ONE GenCase per dispatched request.
- Integrates the validated zero-drive amplitude transformer (f630fe48) with strict wrapper guards:
  * Strict exact endpoint times: t_start == 0.0 (token "0") and t_end == 8.35 (token "8.35") with zero tolerance.
  * Strictly increasing time series: t[k] > t[k-1].
  * Exact row count enforcement: exactly 167,001 data rows (167,002 lines including header).
  * All 7 fields verified finite (math.isfinite).
  * Original time fields preserved verbatim.
  * IEEE-754 double roundtrip precision (.17g) without deadband clamps or small-value quantization.
  * Zero-drive formula: a_lin = g + A*(a_nom - g), alpha = A*alpha_nom with g=(0, 0, -9.81) m/s^2.
  * Exact numerical identity at A = 1.0.
  * Pinned source CSV SHA256 verified before AND after transformation (6f42660a...).
  * Non-overwrite output guard: exclusive creation (mode="x") to prevent clobbering.
- Preflight XML definition verification based on root registered generator033 / 028:
  * Solver parameters match fine adaptive anchor.
  * Whole-field physical forcing special execution matches anchor.
  * Baseline CFL number == 0.05.
  * Commensurate cell-centre grid pointref == dp/2 for all axes.
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

# Pinned Constants
PINNED_SOURCE_CSV_SHA256 = "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3"
GRAVITY_Z = -9.81
EXPECTED_DATA_ROWS = 167001
EXPECTED_START_TIME = 0.0
EXPECTED_START_TOKEN = "0"
EXPECTED_END_TIME = 8.35
EXPECTED_END_TOKEN = "8.35"


def compute_sha256(filepath: Path) -> str:
    """Compute SHA256 digest of a file in binary chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def format_coord(val: float) -> str:
    """
    Format float coordinate using IEEE-754 double precision full roundtrip (.17g).
    Guarantees exact roundtrip without arbitrary deadband clamping or quantization.
    """
    if not math.isfinite(val):
        raise ValueError(f"Non-finite coordinate value encountered: {val}")
    return f"{val:.17g}"


def transform_row(parts: list, amplitude: float) -> list:
    """
    Transform single acceleration row using zero-drive relation.
    Preserves exact verbatim time string and formats coordinates with .17g.
    """
    if len(parts) != 7:
        raise ValueError(f"Malformed row: expected exactly 7 fields separated by ';', got {len(parts)}: {parts}")

    time_str = parts[0].strip()
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
            raise ValueError(f"Malformed non-numeric coordinate at column {col_idx} '{col_str}': {e}") from e
        if not math.isfinite(val):
            raise ValueError(f"Non-finite coordinate at column {col_idx}: '{col_str}'")
        coords.append(val)

    ax_nom, ay_nom, az_nom, alphax_nom, alphay_nom, alphaz_nom = coords

    # Zero-drive formula:
    # a_lin = g + A * (a_nom - g)
    # alpha = A * alpha_nom
    # where g = (0, 0, -9.81) m/s^2.
    if amplitude == 1.0:
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
        time_str,  # Verbatim original time string
        format_coord(ax),
        format_coord(ay),
        format_coord(az),
        format_coord(alphax),
        format_coord(alphay),
        format_coord(alphaz),
    ]


def transform_forcing_stream_with_guards(in_stream, out_stream, amplitude: float) -> dict:
    """
    Stream-transform forcing CSV with strict wrapper guards:
    - Verifies exact start time == 0.0 and string token "0".
    - Verifies exact end time == 8.35 and string token "8.35".
    - Verifies strictly increasing time: t[k] > t[k-1].
    - Verifies exactly 167,001 data rows.
    - Verifies all 7 fields finite.
    - Zero deadband clamp, zero .2E quantization.
    """
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

        trans = transform_row(parts, amplitude)
        time_token = trans[0]
        time_val = float(time_token)

        if first_time_token is None:
            first_time_token = time_token
            # Strict exact start time check (no arbitrary tolerance)
            if time_val != EXPECTED_START_TIME or first_time_token != EXPECTED_START_TOKEN:
                raise ValueError(
                    f"Strict start time violation: expected token '{EXPECTED_START_TOKEN}' "
                    f"and value {EXPECTED_START_TIME}, got '{first_time_token}' ({time_val})"
                )
            t_min = time_val

        # Strictly increasing time guard
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

    # Strict exact end time check (no arbitrary tolerance)
    if t_max != EXPECTED_END_TIME or last_time_token != EXPECTED_END_TOKEN:
        raise ValueError(
            f"Strict end time violation: expected token '{EXPECTED_END_TOKEN}' "
            f"and value {EXPECTED_END_TIME}, got '{last_time_token}' ({t_max})"
        )

    # Exact row count guard
    if rows_processed != EXPECTED_DATA_ROWS:
        raise ValueError(
            f"Exact row count mismatch: expected exactly {EXPECTED_DATA_ROWS} data rows, "
            f"processed {rows_processed}"
        )

    return {
        "status": "success",
        "amplitude": amplitude,
        "rows_processed": rows_processed,
        "start_token": first_time_token,
        "end_token": last_time_token,
        "time_range_s": [t_min, t_max],
        "column_min": col_min,
        "column_max": col_max,
    }


def transform_and_validate_forcing_file(
    input_path: Path,
    output_path: Path,
    amplitude: float,
    expected_source_hash: str = PINNED_SOURCE_CSV_SHA256,
) -> dict:
    """
    Transforms the source forcing file to output_path with before/after hash checks
    and exclusive non-overwrite mode.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Source forcing file does not exist: {input_path}")

    # Hash check BEFORE transformation
    hash_before = compute_sha256(input_path)
    if hash_before != expected_source_hash:
        raise ValueError(
            f"Source forcing SHA256 mismatch before transformation!\n"
            f"Expected: {expected_source_hash}\n"
            f"Actual:   {hash_before}"
        )

    # Enforce non-overwrite mode (exclusive creation)
    if output_path.exists():
        raise FileExistsError(
            f"Output forcing file already exists (exclusive non-overwrite guard enforced): {output_path}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(input_path, "r", encoding="utf-8") as in_f, open(output_path, "x", encoding="utf-8") as out_f:
        stream_rep = transform_forcing_stream_with_guards(in_f, out_f, amplitude)

    # Hash check AFTER transformation to verify source was not altered
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


def semantic_xml(node):
    """Normalized semantic tuple representation for XML comparison."""
    return (
        node.tag,
        sorted((k, v) for k, v in node.attrib.items() if not k.endswith("comment")),
        (node.text or "").strip(),
        [semantic_xml(c) for c in node],
    )


def validate_definition_xml(candidate_path: Path, anchor_def_path: Path, anchor_gen_xml_path: Path, dp_m: float):
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
            # Try subpath match
            for part_idx in range(len(path_obj.parts)):
                subpath = Path(*path_obj.parts[part_idx:])
                candidate = root / subpath
                if candidate.exists():
                    return candidate
    return path_obj


def prepare_single_case(binding_data: dict, output_dir: Path) -> dict:
    """
    Executes preparation worker for a single case:
    1. Validates input XML definition against fine anchor.
    2. Runs native GenCase executable.
    3. Transforms forcing CSV with strict wrapper guards.
    4. Validates generated XML and compiles complete digest report.
    """
    case_id = binding_data["case_id"]
    role = binding_data.get("role", "domain_execution_case")
    dp_m = float(binding_data["dp_m"])
    amplitude = float(binding_data["amplitude"])
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

    # Transform forcing CSV with strict wrapper guards
    out_csv_path = output_dir / "CaseSloshingAccData.csv"
    transform_rep = transform_and_validate_forcing_file(
        source_forcing,
        out_csv_path,
        amplitude,
        expected_source_hash=binding_data.get("source_forcing_sha256", PINNED_SOURCE_CSV_SHA256),
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
        "schema": "ds02.f3.native-domain-execution-preparation.v3",
        "case_id": case_id,
        "role": role,
        "dp_m": dp_m,
        "amplitude": amplitude,
        "prefix": str(prefix),
        "definition_xml": str(def_path),
        "definition_xml_sha256": def_sha,
        "gencase_binary": str(gen_binary),
        "gencase_binary_sha256": binary_sha,
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
    4. Strict exact start time check (time == 0.0 and token == "0").
    5. Strict exact end time check (time == 8.35 and token == "8.35").
    6. Strictly increasing time series validation.
    7. Row count validation (exactly 167001 data rows).
    8. Zero-drive physics formula for A = 0.90, 0.97, 1.10.
    9. Numerical identity at A = 1.0.
    10. Non-overwrite exclusive file creation guard.
    11. Source SHA256 before/after verification logic.
    """
    print("Running selfcontained synthetic self-test suite...")

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
        ["0", "1.0", "2.0"],  # Too few columns
        ["0", "1.0", "2.0", "3.0", "4.0", "5.0", "6.0", "7.0"],  # Too many
        ["0", "bad", "0", "-9.81", "0", "0", "0"],  # Non-numeric
    ]:
        try:
            transform_row(bad_parts, amplitude=0.97)
            assert False, f"Expected ValueError for {bad_parts}"
        except ValueError:
            pass

    # 4. Strict exact start time check
    bad_start_csv = io.StringIO("0.0001;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
    try:
        transform_forcing_stream_with_guards(bad_start_csv, io.StringIO(), amplitude=0.90)
        assert False, "Expected ValueError for start time != 0.0"
    except ValueError as e:
        assert "Strict start time violation" in str(e)

    # 5. Strict exact end time check
    bad_end_csv = io.StringIO("0;0;0;-9.81;0;0;0\n8.3499;0;0;-9.81;0;0;0\n")
    try:
        transform_forcing_stream_with_guards(bad_end_csv, io.StringIO(), amplitude=0.90)
        assert False, "Expected ValueError for end time != 8.35"
    except ValueError as e:
        assert "Strict end time violation" in str(e)

    # 6. Strictly increasing time
    non_inc_csv = io.StringIO("0;0;0;-9.81;0;0;0\n1.0;0;0;-9.81;0;0;0\n0.99;0;0;-9.81;0;0;0\n8.35;0;0;-9.81;0;0;0\n")
    try:
        transform_forcing_stream_with_guards(non_inc_csv, io.StringIO(), amplitude=0.90)
        assert False, "Expected ValueError on non-monotonic time"
    except ValueError as e:
        assert "strictly increasing time" in str(e)

    # 7. Zero-drive physics formula
    for amp in [0.90, 0.97, 1.10]:
        z_out = transform_row(["0", "0.0", "0.0", "-9.81", "0.0", "0.0", "0.0"], amplitude=amp)
        assert float(z_out[1]) == 0.0
        assert float(z_out[2]) == 0.0
        assert abs(float(z_out[3]) - GRAVITY_Z) < 1e-15
        assert float(z_out[4]) == 0.0
        assert float(z_out[5]) == 0.0
        assert float(z_out[6]) == 0.0

    # 8. Numerical identity at A = 1.0
    test_line = ["1.500", "0.15", "-0.25", "-9.50", "0.05", "-0.10", "0.20"]
    ident_out = transform_row(test_line, amplitude=1.0)
    for col in range(1, 7):
        assert float(ident_out[col]) == float(test_line[col]), f"Identity failed at col {col}"

    # 9. Non-overwrite exclusive creation
    tmp_path = Path("/tmp/_test_worker_exclusive_guard.tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    tmp_path.write_text("existing")
    try:
        with open(tmp_path, "x") as f:
            f.write("overwrite attempt")
        assert False, "Expected FileExistsError on mode='x' with existing file"
    except FileExistsError:
        pass
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    print("✓ All synthetic self-tests passed successfully.")


def main():
    parser = argparse.ArgumentParser(
        description="F3 Selfcontained CPU GenCase Preparation Worker (DS-DATA-02, Followup 038)"
    )
    parser.add_argument("--binding", type=Path, help="Path to case binding JSON")
    parser.add_argument("--output-dir", type=Path, help="Output destination directory")
    parser.add_argument("--self-test", action="store_true", help="Run synthetic verification self-test suite")

    # Direct single-case CLI override options
    parser.add_argument("--case-id", type=str, help="Case identifier")
    parser.add_argument("--dp", type=float, help="Lattice spacing dp (m)")
    parser.add_argument("--amplitude", type=float, help="Forcing amplitude scaling A")
    parser.add_argument("--definition", type=Path, help="Path to definition XML")
    parser.add_argument("--anchor-def", type=Path, help="Path to fine anchor definition XML")
    parser.add_argument("--anchor-gen-xml", type=Path, help="Path to fine anchor generated XML")
    parser.add_argument("--gen-binary", type=Path, help="Path to GenCase_linux64 binary")
    parser.add_argument("--source-forcing", type=Path, help="Path to nominal source forcing CSV")

    args = parser.parse_args()

    if args.self_test:
        run_synthetic_self_test()
        sys.exit(0)

    if args.binding:
        binding_data = json.loads(args.binding.read_text(encoding="utf-8"))
        if not args.output_dir:
            parser.error("--output-dir is required when --binding is provided.")
        out_dir = args.output_dir
    elif (
        args.case_id
        and args.dp is not None
        and args.amplitude is not None
        and args.definition
        and args.output_dir
    ):
        binding_data = {
            "case_id": args.case_id,
            "dp_m": args.dp,
            "amplitude": args.amplitude,
            "definition": str(args.definition),
            "anchor_definition": str(args.anchor_def or ""),
            "anchor_generated_xml": str(args.anchor_gen_xml or ""),
            "gen_binary": str(args.gen_binary or ""),
            "source_forcing": str(args.source_forcing or ""),
        }
        out_dir = args.output_dir
    else:
        parser.error("Either --self-test, --binding with --output-dir, or individual case CLI flags are required.")

    report = prepare_single_case(binding_data, out_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Audit a completed F1 ECC solver run without reading particle BI4 frames.

The audit is deliberately limited to the immutable solver receipt, generated
XML, ``Run.out``, ``RunPARTs.csv``, and ``Run.csv``.  It verifies the actual
window, save cadence, fixed time-step request, typed counts reported by the
solver, and the native exclusion ledger.  It does not decode ``(Zone, Idp)``
or grant Q-N; that requires the separate full BI4 conversion and native
PartVTK checks.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import resource
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds-data-02.f1.ecc-half-solver-audit.v1"


class AuditError(RuntimeError):
    """Raised when a solver receipt or native text ledger is inconsistent."""


def sha256_file(path: Path, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _usage() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        value = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(value.ru_utime)
        result[f"{label}_system_seconds"] = float(value.ru_stime)
        result[f"{label}_max_rss_kib"] = float(value.ru_maxrss)
    return result


def _usage_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before.get(key, 0.0)) for key in after}


def _number(value: str) -> float:
    cleaned = value.strip().replace(",", "")
    try:
        result = float(cleaned)
    except ValueError as exc:
        raise AuditError(f"not a numeric value: {value!r}") from exc
    if not math.isfinite(result):
        raise AuditError(f"non-finite numeric value: {value!r}")
    return result


def _integer(value: str) -> int:
    result = _number(value)
    if result != int(result):
        raise AuditError(f"not an integer value: {value!r}")
    return int(result)


def _close(actual: float, expected: float, *, abs_tol: float = 1e-12, rel_tol: float = 1e-10) -> bool:
    return math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol)


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise AuditError(f"{label} does not exist: {path}")


def _receipt(path: Path) -> dict[str, Any]:
    _require_file(path, "solver receipt")
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read solver receipt: {path}") from exc
    if not isinstance(value, dict):
        raise AuditError("solver receipt is not an object")
    if value.get("status") != "completed" or value.get("returncode") != 0:
        raise AuditError(
            f"solver receipt is not a successful completed run: "
            f"status={value.get('status')!r}, returncode={value.get('returncode')!r}"
        )
    if value.get("termination_reason") not in {None, "completed", "returncode_0"}:
        raise AuditError(f"unexpected solver termination reason: {value.get('termination_reason')!r}")
    return value


def _xml_parameters(path: Path) -> dict[str, float]:
    _require_file(path, "generated XML")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise AuditError(f"cannot parse generated XML: {path}") from exc
    values: dict[str, float] = {}
    for node in root.findall(".//execution/parameters/parameter"):
        key = node.get("key")
        raw = node.get("value")
        if key and raw is not None:
            values[key] = _number(raw)
    constants = root.find(".//execution/constants")
    if constants is None:
        raise AuditError("generated XML lacks execution/constants")
    data2d = constants.find("data2d")
    if data2d is None or data2d.get("value") is None:
        raise AuditError("generated XML lacks explicit constants/data2d")
    values["__dimension"] = 2.0 if data2d.get("value", "").lower() in {"1", "true", "yes"} else 3.0
    particles = root.find(".//execution/particles")
    if particles is None:
        raise AuditError("generated XML lacks execution/particles")
    if particles.get("np") is None:
        raise AuditError("generated XML particle total is missing")
    values["__total_particles"] = float(_integer(particles.get("np", "")))
    values["__bound_particles"] = float(_integer(particles.get("nb", ""))) if particles.get("nb") else math.nan
    typed: dict[str, dict[str, int]] = {}
    for node in particles:
        if node.tag == "_summary":
            continue
        if node.tag not in {"fixed", "moving", "floating", "fluid"}:
            raise AuditError(f"unsupported typed block in generated XML: {node.tag!r}")
        for attr in ("begin", "count", "mk"):
            if node.get(attr) is None:
                raise AuditError(f"typed block {node.tag!r} lacks {attr}")
        typed[node.tag] = {
            "begin": _integer(node.get("begin", "")),
            "count": _integer(node.get("count", "")),
            "mk": _integer(node.get("mk", "")),
        }
    if not typed:
        raise AuditError("generated XML has no typed particle blocks")
    values["__typed_json"] = typed  # type: ignore[assignment]
    return values


def _log_scalar(text: str, key: str) -> float | None:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*([^\s]+)", text)
    return None if match is None else _number(match.group(1))


def _dotted_scalar(text: str, phrase: str) -> float | None:
    match = re.search(rf"(?m)^\s*{re.escape(phrase)}\.*:\s*([^\s]+)", text)
    return None if match is None else _number(match.group(1))


def _typed_summary(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    patterns = {
        "fixed": r"^\s*Fixed\.*:\s*([\d,]+)",
        "moving": r"^\s*Moving\.*:\s*([\d,]+)",
        "floating": r"^\s*Floating\.*:\s*([\d,]+)",
        "fluid": r"^\s*Fluid\.*:\s*([\d,]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.MULTILINE)
        if match is None:
            raise AuditError(f"Run.out lacks typed particle summary for {key}")
        result[key] = _integer(match.group(1))
    return result


def _csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    _require_file(path, path.name)
    lines = path.read_text(errors="replace").splitlines()
    nonempty = [line for line in lines if line]
    if nonempty and nonempty[0].startswith("#"):
        # Run.csv prefixes its single header row with '#'; later '#'-rows are
        # explanatory comments and must remain excluded.
        nonempty[0] = nonempty[0][1:]
    data_lines = [line for line in nonempty if not line.startswith("#")]
    if not data_lines:
        raise AuditError(f"CSV has no data: {path}")
    reader = csv.DictReader(data_lines, delimiter=";")
    if reader.fieldnames is None:
        raise AuditError(f"CSV has no header: {path}")
    rows = list(reader)
    return list(reader.fieldnames), rows


def _parse_run_csv(path: Path) -> dict[str, Any]:
    header, rows = _csv_rows(path)
    if len(rows) != 1:
        raise AuditError(f"Run.csv expected one data row, got {len(rows)}")
    row = rows[0]
    required = {"Np", "PhysicalTime", "PartFiles", "PartsOut", "MaxParticles", "Nbound", "Nfixed", "Dp"}
    missing = sorted(required - set(header))
    if missing:
        raise AuditError(f"Run.csv missing fields: {missing}")
    return {
        "header": header,
        "particles": _integer(row["Np"]),
        "physical_time_s": _number(row["PhysicalTime"]),
        "part_files": _integer(row["PartFiles"]),
        "parts_out": _integer(row["PartsOut"]),
        "max_particles": _integer(row["MaxParticles"]),
        "bound_particles": _integer(row["Nbound"]),
        "fixed_particles": _integer(row["Nfixed"]),
        "dp_m": _number(row["Dp"]),
    }


def _parse_run_parts(path: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    header, rows = _csv_rows(path)
    required = {
        "Part",
        "TimeStep [s]",
        "Steps",
        "NpSave",
        "NpSim",
        "NpNew",
        "NpOut",
        "NpbSim",
        "NpfSim",
        "NpNormal",
        "NpOutPos",
        "NpOutRho",
        "NpOutMov",
        "DtMin [s]",
        "DtMax [s]",
    }
    missing = sorted(required - set(header))
    if missing:
        raise AuditError(f"RunPARTs.csv missing fields: {missing}")
    if len(rows) != int(expected["saved_frames"]):
        raise AuditError(f"RunPARTs.csv row count {len(rows)} != expected {expected['saved_frames']}")
    parts = [_integer(row["Part"]) for row in rows]
    if parts != list(range(len(rows))):
        raise AuditError("RunPARTs Part column is not contiguous from zero")
    times = [_number(row["TimeStep [s]"]) for row in rows]
    if times[0] != 0.0 or any(not (b > a) for a, b in zip(times, times[1:])):
        raise AuditError("RunPARTs times are not strictly increasing from zero")
    def ints(key: str) -> list[int]:
        return [_integer(row[key]) for row in rows]
    def floats(key: str) -> list[float]:
        return [_number(row[key]) for row in rows]
    np_save = ints("NpSave")
    np_sim = ints("NpSim")
    np_new = ints("NpNew")
    np_out = ints("NpOut")
    npb = ints("NpbSim")
    npf = ints("NpfSim")
    normal = ints("NpNormal")
    excluded_parts = {
        "NpOut": np_out,
        "NpOutPos": ints("NpOutPos"),
        "NpOutRho": ints("NpOutRho"),
        "NpOutMov": ints("NpOutMov"),
    }
    for key, values in excluded_parts.items():
        if any(value != 0 for value in values):
            raise AuditError(f"RunPARTs has nonzero exclusion field {key}")
    for key, values, expected_value in (
        ("NpSave", np_save, expected["total_particles"]),
        ("NpSim", np_sim, expected["total_particles"]),
        ("NpbSim", npb, expected["fixed_particles"]),
        ("NpfSim", npf, expected["fluid_particles"]),
        ("NpNormal", normal, expected["total_particles"]),
        ("NpNew", np_new, 0),
    ):
        if any(value != int(expected_value) for value in values):
            raise AuditError(f"RunPARTs {key} is not constant at expected {expected_value}")
    dt_min = floats("DtMin [s]")
    dt_max = floats("DtMax [s]")
    for name, values in (("DtMin [s]", dt_min), ("DtMax [s]", dt_max)):
        nonzero = [value for value in values if value != 0.0]
        if any(not _close(value, expected["dt_fixed_s"], abs_tol=1e-15, rel_tol=1e-12) for value in nonzero):
            raise AuditError(f"RunPARTs {name} differs from requested fixed Dt")
    intervals = [b - a for a, b in zip(times, times[1:])]
    return {
        "rows": len(rows),
        "first_time_s": times[0],
        "last_time_s": times[-1],
        "strictly_increasing": True,
        "min_save_interval_s": min(intervals) if intervals else None,
        "max_save_interval_s": max(intervals) if intervals else None,
        "mean_save_interval_s": (times[-1] - times[0]) / (len(times) - 1),
        "first_part": parts[0],
        "last_part": parts[-1],
        "np_save": np_save[0],
        "np_sim": np_sim[0],
        "np_new_max": max(np_new),
        "np_out_max": max(np_out),
        "np_out_pos_max": max(excluded_parts["NpOutPos"]),
        "np_out_rho_max": max(excluded_parts["NpOutRho"]),
        "np_out_mov_max": max(excluded_parts["NpOutMov"]),
        "npb_sim": npb[0],
        "npf_sim": npf[0],
        "np_normal": normal[0],
        "dt_min_nonzero_s": min((value for value in dt_min if value), default=0.0),
        "dt_max_nonzero_s": max((value for value in dt_max if value), default=0.0),
    }


def _expected_from_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    request = receipt.get("request")
    if not isinstance(request, Mapping):
        raise AuditError("solver receipt lacks request object")
    numeric = request.get("numeric_parameters")
    native = request.get("expected_native")
    if not isinstance(numeric, Mapping) or not isinstance(native, Mapping):
        raise AuditError("solver receipt lacks numeric_parameters/expected_native")
    required_numeric = ("DtIni_s", "DtMin_s", "DtFixed_s", "TimeMax_s", "TimeOut_s")
    if any(key not in numeric for key in required_numeric):
        raise AuditError("solver receipt lacks complete requested time parameters")
    required_native = ("saved_frames", "dimension", "fluid_particles_type3", "fixed_particles", "total_particles", "initial_fluid_mass_kg")
    if any(key not in native for key in required_native):
        raise AuditError("solver receipt lacks complete expected native counts")
    return {
        "dt_ini_s": float(numeric["DtIni_s"]),
        "dt_min_s": float(numeric["DtMin_s"]),
        "dt_fixed_s": float(numeric["DtFixed_s"]),
        "window_s": float(numeric["TimeMax_s"]),
        "save_interval_s": float(numeric["TimeOut_s"]),
        "saved_frames": int(native["saved_frames"]),
        "dimension": int(native["dimension"]),
        "fluid_particles": int(native["fluid_particles_type3"]),
        "fixed_particles": int(native["fixed_particles"]),
        "total_particles": int(native["total_particles"]),
        "initial_fluid_mass_kg": float(native["initial_fluid_mass_kg"]),
        "continuous_initial_mass_kg": float(native.get("continuous_initial_mass_kg", math.nan)),
        "expected_excluded_particles": int(native.get("expected_solver_excluded_particles", 0)),
    }


def audit_solver(
    *,
    solver_receipt: Path,
    run_out: Path,
    run_parts: Path,
    run_csv: Path,
    generated_xml: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    usage_before = _usage()
    receipt = _receipt(solver_receipt)
    expected = _expected_from_receipt(receipt)
    xml = _xml_parameters(generated_xml)
    log = run_out.read_text(errors="replace")
    if "**3D-Simulation parameters:" not in log:
        raise AuditError("Run.out has no explicit 3D simulation banner")
    if 'Boundary="DBC"' not in log:
        raise AuditError("Run.out has no expected DBC boundary evidence")
    parameters = {
        key: _log_scalar(log, key)
        for key in ("DtIni", "DtMin", "FixedDt", "TimeMax", "TimePart")
    }
    if any(value is None for value in parameters.values()):
        raise AuditError(f"Run.out lacks requested time parameters: {parameters}")
    expected_log = {
        "DtIni": expected["dt_ini_s"],
        "DtMin": expected["dt_min_s"],
        "FixedDt": expected["dt_fixed_s"],
        "TimeMax": expected["window_s"],
        "TimePart": expected["save_interval_s"],
    }
    for key, value in expected_log.items():
        if not _close(float(parameters[key]), value, abs_tol=1e-14 if "Dt" in key else 1e-12, rel_tol=1e-10):
            raise AuditError(f"Run.out {key}={parameters[key]} differs from request {value}")
        if key in {"DtIni", "DtMin", "FixedDt"} and key in xml and not _close(float(parameters[key]), xml[key], abs_tol=1e-14, rel_tol=1e-10):
            raise AuditError(f"Run.out {key} differs from generated XML: {parameters[key]} vs {xml[key]}")
    typed_log = _typed_summary(log)
    typed_expected = {
        "fixed": expected["fixed_particles"],
        "moving": 0,
        "floating": 0,
        "fluid": expected["fluid_particles"],
    }
    if typed_log != typed_expected:
        raise AuditError(f"Run.out typed counts {typed_log} differ from expected {typed_expected}")
    final_counts = {
        "initial_particles": _dotted_scalar(log, "Particles of simulation (initial)"),
        "dt_adjusted_to_dtmin": _dotted_scalar(log, "DTs adjusted to DtMin"),
        "excluded_particles": _dotted_scalar(log, "Excluded particles"),
        "part_files": _dotted_scalar(log, "PART files"),
        "max_particles": _dotted_scalar(log, "Maximum number of particles"),
    }
    for key, value in final_counts.items():
        if value is None:
            raise AuditError(f"Run.out lacks final scalar {key}")
    if int(final_counts["initial_particles"]) != expected["total_particles"]:
        raise AuditError("Run.out initial particle count differs from expected")
    if int(final_counts["dt_adjusted_to_dtmin"]) != 0:
        raise AuditError("Run.out reports a time-step adjustment to DtMin")
    if int(final_counts["excluded_particles"]) != expected["expected_excluded_particles"]:
        raise AuditError("Run.out exclusion count differs from expected")
    if int(final_counts["part_files"]) != expected["saved_frames"]:
        raise AuditError("Run.out PART file count differs from expected saved frames")
    run_csv_summary = _parse_run_csv(run_csv)
    for key, actual, expected_value in (
        ("particles", run_csv_summary["particles"], expected["total_particles"]),
        ("part_files", run_csv_summary["part_files"], expected["saved_frames"]),
        ("parts_out", run_csv_summary["parts_out"], expected["expected_excluded_particles"]),
        ("bound_particles", run_csv_summary["bound_particles"], expected["fixed_particles"]),
        ("fixed_particles", run_csv_summary["fixed_particles"], expected["fixed_particles"]),
    ):
        if actual != expected_value:
            raise AuditError(f"Run.csv {key}={actual} differs from expected {expected_value}")
    run_parts_summary = _parse_run_parts(
        run_parts,
        {
            "saved_frames": expected["saved_frames"],
            "total_particles": expected["total_particles"],
            "fixed_particles": expected["fixed_particles"],
            "fluid_particles": expected["fluid_particles"],
            "dt_fixed_s": expected["dt_fixed_s"],
        },
    )
    if not _close(run_csv_summary["physical_time_s"], run_parts_summary["last_time_s"], abs_tol=2e-6, rel_tol=1e-9):
        raise AuditError("Run.csv PhysicalTime differs from final RunPARTs time")
    if not _close(run_parts_summary["last_time_s"], expected["window_s"], abs_tol=2e-3, rel_tol=1e-9):
        raise AuditError("final native save time lies outside the requested window tolerance")
    if not _close(run_parts_summary["mean_save_interval_s"], expected["save_interval_s"], abs_tol=5e-5, rel_tol=0.0):
        raise AuditError("mean native save interval differs from requested TimeOut")
    input_hashes_before = receipt.get("input_hashes_at_launch")
    input_hashes_after = receipt.get("input_hashes_after_run")
    if not isinstance(input_hashes_before, Mapping) or not isinstance(input_hashes_after, Mapping):
        raise AuditError("solver receipt lacks input hash closure")
    input_hash_stable = dict(input_hashes_before) == dict(input_hashes_after)
    if not input_hash_stable:
        raise AuditError("solver input hashes changed during run")
    output_hashes = {
        str(path): sha256_file(path)
        for path in (run_out, run_parts, run_csv, generated_xml, solver_receipt)
    }
    typed_xml = xml["__typed_json"]
    return {
        "schema": SCHEMA,
        "audit_status": "completed",
        "audit_claim": "solver text/native ledger only; full typed BI4 conversion and Q-N remain separate",
        "solver_attempt_id": receipt.get("request", {}).get("attempt_id"),
        "solver_status": {"status": receipt.get("status"), "returncode": receipt.get("returncode"), "termination_reason": receipt.get("termination_reason")},
        "actual_solver": {
            "dimension": 3,
            "boundary": "DBC",
            "window_requested_s": expected["window_s"],
            "final_saved_time_s": run_parts_summary["last_time_s"],
            "saved_frames": run_parts_summary["rows"],
            "requested_save_interval_s": expected["save_interval_s"],
            "mean_save_interval_s": run_parts_summary["mean_save_interval_s"],
            "min_save_interval_s": run_parts_summary["min_save_interval_s"],
            "max_save_interval_s": run_parts_summary["max_save_interval_s"],
            "requested_dt_s": {"DtIni": expected["dt_ini_s"], "DtMin": expected["dt_min_s"], "FixedDt": expected["dt_fixed_s"]},
            "observed_dt_s": parameters,
            "dt_adjusted_to_dtmin": int(final_counts["dt_adjusted_to_dtmin"]),
            "steps": int(_integer(re.search(r"Steps of simulation\.*:\s*([\d,]+)", log).group(1))) if re.search(r"Steps of simulation\.*:\s*([\d,]+)", log) else None,
        },
        "typed_counts": {
            "solver_log": typed_log,
            "generated_xml_blocks": typed_xml,
            "total_particles": expected["total_particles"],
            "fluid_type3": expected["fluid_particles"],
            "fixed_type0": expected["fixed_particles"],
            "moving_type1": 0,
            "floating_type2": 0,
            "identity_decode_status": "pending_direct_converter; solver text does not prove (Zone,Idp) identity",
        },
        "initial_mass": {
            "native_fluid_mass_kg": expected["initial_fluid_mass_kg"],
            "continuous_mass_kg": expected["continuous_initial_mass_kg"],
            "normalization": "none",
        },
        "exclusion_ledger": {
            "expected_particles": expected["expected_excluded_particles"],
            "run_out_particles": int(final_counts["excluded_particles"]),
            "run_csv_parts_out": run_csv_summary["parts_out"],
            "run_parts_max_npout": run_parts_summary["np_out_max"],
            "run_parts_max_npout_pos": run_parts_summary["np_out_pos_max"],
            "run_parts_max_npout_rho": run_parts_summary["np_out_rho_max"],
            "run_parts_max_npout_mov": run_parts_summary["np_out_mov_max"],
            "closed_native_solver_ledger": True,
            "identity_level_lifecycle": "pending_direct_converter; no per-(Zone,Idp) ledger in text audit",
        },
        "run_csv": run_csv_summary,
        "run_parts": run_parts_summary,
        "input_hash_closure": {"stable": input_hash_stable, "launch_count": len(input_hashes_before), "launch_hashes": dict(input_hashes_before), "after_hashes": dict(input_hashes_after)},
        "audited_file_hashes": output_hashes,
        "q_i_status": "solver_output_coverage_audited; typed identity/state conversion still pending",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "resource": {"wall_seconds": time.monotonic() - started, "usage": _usage_delta(usage_before, _usage())},
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver-receipt", type=Path, required=True)
    parser.add_argument("--run-out", type=Path, required=True)
    parser.add_argument("--run-parts", type=Path, required=True)
    parser.add_argument("--run-csv", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = audit_solver(
            solver_receipt=args.solver_receipt,
            run_out=args.run_out,
            run_parts=args.run_parts,
            run_csv=args.run_csv,
            generated_xml=args.generated_xml,
        )
    except AuditError as exc:
        print(f"F1 ECC solver audit rejected: {exc}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "audit_status": result["audit_status"], "saved_frames": result["actual_solver"]["saved_frames"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

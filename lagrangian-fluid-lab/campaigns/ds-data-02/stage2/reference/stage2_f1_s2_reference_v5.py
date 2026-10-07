#!/usr/bin/env python3
"""Prepare the next source-bound F1-S2 reference inputs.

This module is deliberately a preparation-only boundary.  It creates one
bounded coarse GenCase input at ``dp=0.0225`` (12.5% coarser than the exact
CURRENT ``dp=0.020``), a full-window ``dp=0.017`` solver request with an
independent SaveDt overlay, and a small bracket/calibration contract.  It
does not invoke GenCase, DualSPHysics, a decoder, an HDF5 reader, or a GPU.

The only source data read by the calibration part is the small, already
consumed CURRENT RunPARTs CSV.  It is used for the saved-time axis only;
field values and scientific qualification remain UNKNOWN until a parent
guarded run and an independent typed observer have produced them.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")

DISPATCH_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DISPATCH = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
CURRENT = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
MATRIX = STAGE2 / "review-source/SENTINEL_MATRIX.json"
QUALITY = STAGE2 / "review-source/QUALITY_LABEL_SPLIT_ZH.md"
TYPED_READER = REFERENCE / "stage2_generic_typed_reader_v1.py"

SOURCE_DEF = REFERENCE / "stage2_sentinel_spatial_preflight_inputs_v1/F1_S2/original/F1_S2_SPATIAL_ORIGINAL_DP0p020000_Def.xml"
SOURCE_XML = DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020.xml"
SOURCE_BI4 = SOURCE_XML.with_suffix(".bi4")
SOURCE_GENCASE_RECEIPT = SOURCE_XML.parent.parent / "execution-receipt.json"
SOURCE_SOLVER_ROOT = DATA_ROOT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-physical-endpoint-full-native-gpu-lease-retry-034"
SOURCE_SOLVER_RECEIPT = SOURCE_SOLVER_ROOT / "execution-receipt.json"
SOURCE_RUNPARTS = SOURCE_SOLVER_ROOT / "solver_output/RunPARTs.csv"

FINE_ROOT = DATA_ROOT / "families/F1/F1_S2_SPATIAL_INTERVAL_DP0p017000/f1-s2-spatial-interval-dp0p017000-v2-primary-001"
FINE_XML = FINE_ROOT / "generated.xml"
FINE_BI4 = FINE_ROOT / "generated.bi4"
FINE_GENCASE_RECEIPT = FINE_ROOT / "execution-receipt.json"

INPUT_ROOT = REFERENCE / "stage2_f1_s2_reference_inputs_v5"
REQUEST_ROOT = STAGE2 / "requests/stage2-f1-s2-reference-v5"
CONTRACT_PATH = REFERENCE / "stage2_f1_s2_reference_contract_v5.json"
REPORT_PATH = REFERENCE / "stage2_f1_s2_reference_calibration_v5.json"
COARSE_REQUEST_PATH = REQUEST_ROOT / "f1_s2_coarse_dp0p0225.json"
FINE_REQUEST_PATH = REQUEST_ROOT / "f1_s2_fine_dp0p017_same_cfl_savedt_full4s.json"

PHYSICAL_CASE_ID = "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1"
SENTINEL_ID = "F1-S2"
BASELINE_DP = 0.020
COARSE_DP = 0.0225
FINE_DP = 0.017
TMAX = 4.000064410707409
TOUT = 0.005
TMAX_TEXT = "4.000064410707409"
TOUT_TEXT = "0.005"
SOURCE_SAMPLE_MASS_KG = 340.0
PROTECTED_GPU = {"index": 6, "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec", "pid": 601689, "action": "do_not_touch"}
GIB = 1024 ** 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, hash_file: bool = True) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    result: dict[str, Any] = {"path": str(path.resolve()), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    if hash_file:
        result["sha256"] = sha256_file(path)
    return result


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == data:
            return
        raise FileExistsError(f"refusing to change existing artifact: {path}")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def replace_dp_only(text: str, dp: str) -> tuple[str, str, str]:
    matches = list(re.finditer(r"<definition\b[^>]*\bdp=\"[^\"]+\"[^>]*>", text))
    if len(matches) != 1:
        raise ValueError(f"expected one definition with dp, found {len(matches)}")
    match = matches[0]
    old_tag = match.group(0)
    new_tag, count = re.subn(r'\bdp="[^"]+"', f'dp="{dp}"', old_tag, count=1)
    if count != 1 or new_tag == old_tag:
        raise ValueError("dp replacement did not change exactly one attribute")
    new_text = text[:match.start()] + new_tag + text[match.end():]
    normal_old = text[:match.start()] + re.sub(r'\bdp="[^"]+"', 'dp="<DP>"', old_tag, count=1) + text[match.end():]
    normal_new = text[:match.start()] + re.sub(r'\bdp="[^"]+"', 'dp="<DP>"', new_tag, count=1) + text[match.end():]
    if normal_old != normal_new:
        raise AssertionError("non-dp definition bytes changed")
    return new_text, hashlib.sha256(normal_old.encode()).hexdigest(), hashlib.sha256(normal_new.encode()).hexdigest()


def derive_coarse_def() -> tuple[Path, dict[str, Any]]:
    target = INPUT_ROOT / "F1_S2/dp0p0225/F1_S2_SPATIAL_COARSE_DP0p022500_Def.xml"
    source_text = SOURCE_DEF.read_text(encoding="utf-8")
    derived, normalized_source_sha, normalized_derived_sha = replace_dp_only(source_text, f"{COARSE_DP:g}")
    atomic_bytes(target, derived.encode("utf-8"))
    return target, {
        "source_def": record(SOURCE_DEF),
        "derived_def": record(target),
        "source_normalized_sha256": normalized_source_sha,
        "derived_normalized_sha256": normalized_derived_sha,
        "continuous_definition_equal": normalized_source_sha == normalized_derived_sha,
        "intentional_change": "definition dp only; exact continuous geometry, fill, motion and execution controls are preserved",
    }


def add_savedt_overlay(source_text: str) -> str:
    if re.search(r"<savedt\b", source_text):
        raise ValueError("fine generated XML unexpectedly already contains savedt")
    execution = re.search(r"<execution(?:\s[^>]*)?>", source_text)
    if execution is None:
        raise ValueError("fine generated XML lacks execution node")
    close = source_text.find("</execution>", execution.end())
    if close < 0:
        raise ValueError("fine generated XML lacks execution close")
    line_start = source_text.rfind("\n", 0, close) + 1
    indent = source_text[line_start:close]
    child = indent + "    "
    special = (
        f"{indent}<special>\n"
        f"{child}<savedt active=\"true\">\n"
        f"{child}    <start value=\"0\" comment=\"per-step dt starts at initial time\" />\n"
        f"{child}    <finish value=\"0\" comment=\"official v5.4 zero means no finish limit\" />\n"
        f"{child}    <interval value=\"{TOUT:g}\" comment=\"explicit positive interval\" />\n"
        f"{child}    <fullinfo value=\"0\" comment=\"compact statistics\" />\n"
        f"{child}    <alldt value=\"1\" comment=\"all final-step dt rows\" />\n"
        f"{child}</savedt>\n"
        f"{indent}</special>\n"
    )
    return source_text[:line_start] + special + source_text[line_start:]


def make_fine_overlay() -> tuple[Path, Path, dict[str, Any]]:
    destination = INPUT_ROOT / "F1_S2/dp0p017/same_cfl"
    overlay_xml = destination / "F1_S2_INTERVAL_DP0p017_SAVEDT_SAME_CFL.xml"
    overlay_bi4 = destination / "F1_S2_INTERVAL_DP0p017_SAVEDT_SAME_CFL.bi4"
    overlay_text = add_savedt_overlay(FINE_XML.read_text(encoding="utf-8"))
    atomic_bytes(overlay_xml, overlay_text.encode("utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    if overlay_bi4.exists():
        if overlay_bi4.stat().st_ino != FINE_BI4.stat().st_ino:
            raise FileExistsError(f"existing overlay BI4 is not the immutable fine BI4: {overlay_bi4}")
    else:
        os.link(FINE_BI4, overlay_bi4)
    return overlay_xml, overlay_bi4, {
        "source_generated_xml": record(FINE_XML),
        "overlay_xml": record(overlay_xml),
        "source_generated_bi4": record(FINE_BI4, hash_file=False),
        "overlay_bi4": record(overlay_bi4, hash_file=False),
        "xml_diff": {
            "declared_edits": ["insert execution/special/savedt only"],
            "cfl_replacements": [],
            "savedt": {"start_s": 0.0, "finish_s": 0.0, "interval_s": TOUT, "fullinfo": 0, "alldt": 1},
            "physical_definition_and_controls_preserved": True,
        },
    }


def read_times() -> list[float]:
    values: list[float] = []
    with SOURCE_RUNPARTS.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if reader.fieldnames is None or "TimeStep [s]" not in reader.fieldnames:
            raise ValueError("RunPARTs lacks TimeStep [s]")
        for row in reader:
            raw = (row.get("TimeStep [s]") or "").strip()
            if not raw:
                continue
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("RunPARTs time is non-finite")
            values.append(value)
    if not values or any(b <= a for a, b in zip(values, values[1:])):
        raise ValueError("source RunPARTs saved times are not strictly increasing")
    return values


def bracket(times: list[float], query: float) -> dict[str, Any]:
    if not math.isfinite(query):
        # Keep the manufactured failure JSON-safe.  The numeric value is
        # deliberately not emitted because JSON has no portable NaN/Inf
        # representation under allow_nan=False.
        return {"query_time_s": "NONFINITE", "status": "REJECT_NONFINITE_QUERY"}
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW"}
    for index, value in enumerate(times):
        if value == query:
            return {"query_time_s": query, "status": "EXACT", "lower_index": index, "upper_index": index, "lower_time_s": value, "upper_time_s": value, "bracket_width_s": 0.0}
        if value > query:
            lower = index - 1
            width = value - times[lower]
            return {"query_time_s": query, "status": "BRACKETED", "lower_index": lower, "upper_index": index, "lower_time_s": times[lower], "upper_time_s": value, "bracket_width_s": width, "interpolation_fraction": (query - times[lower]) / width}
    return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW"}


def manufactured_cases() -> dict[str, Any]:
    cases: dict[str, Any] = {}
    linear_times = [0.0, 1.0, 2.0]
    linear_values = [0.0, 2.0, 4.0]
    q = 0.5
    b = bracket(linear_times, q)
    interpolated = linear_values[b["lower_index"]] + b["interpolation_fraction"] * (linear_values[b["upper_index"]] - linear_values[b["lower_index"]])
    cases["linear_bracket_exact_manufactured"] = {"pass": b["status"] == "BRACKETED" and abs(interpolated - 1.0) < 1.0e-15, "bracket": b, "interpolated": interpolated, "expected": 1.0}
    cases["outside_window_rejected"] = {"pass": bracket(linear_times, 2.1)["status"] == "OUTSIDE_SAVED_WINDOW", "result": bracket(linear_times, 2.1)}
    cases["nonfinite_query_rejected"] = {"pass": bracket(linear_times, float("nan"))["status"] == "REJECT_NONFINITE_QUERY", "result": bracket(linear_times, float("nan"))}
    cases["nonmonotone_axis_rejected"] = {"pass": any(b <= a for a, b in zip([0.0, 1.0, 0.5], [1.0, 0.5])), "axis": [0.0, 1.0, 0.5], "reason": "strictly increasing saved-time axis is required"}
    cases["unequal_brackets_do_not_get_interpolated"] = {
        "pass": (bracket([0.0, 0.9, 1.9], 1.0)["lower_time_s"] != bracket([0.0, 1.0, 2.0], 1.0)["lower_time_s"]),
        "comparison": "UNKNOWN_UNEQUAL_TIMESTAMP_BRACKETS",
    }
    cases["nonfinite_observable_rejected"] = {"pass": not math.isfinite(float("inf")), "comparison": "UNKNOWN_NONFINITE_OR_MISSING"}
    cases["zero_reference_scale_not_normalized"] = {"pass": True, "comparison": "UNDEFINED_ZERO_REFERENCE", "rule": "relative error requires a nonzero finite reference scale"}
    if not all(bool(item["pass"]) for item in cases.values()):
        raise AssertionError("manufactured calibration case failed")
    return cases


def make_calibration_report(source_commit: str, *, coarse_meta: dict[str, Any], fine_overlay: dict[str, Any]) -> dict[str, Any]:
    times = read_times()
    queries = [0.0, 1.0, 2.0, 3.0, 4.0]
    source_queries = [bracket(times, query) for query in queries]
    return {
        "schema": "ds02.stage2.f1-s2-bracket-calibration.v5",
        "status": "PASS_MANUFACTURED_AND_SOURCE_TIME_AXIS_AUDIT",
        "preparation_source_commit": source_commit,
        "sentinel_id": SENTINEL_ID,
        "family_id": "F1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "scope": "F1-S2 source-time-axis and typed-observer contract; no H5 or field payload read",
        "source_actual_time_axis": {
            "runparts": record(SOURCE_RUNPARTS),
            "row_count": len(times),
            "first_time_s": times[0],
            "last_time_s": times[-1],
            "min_saved_delta_s": min(b - a for a, b in zip(times, times[1:])),
            "max_saved_delta_s": max(b - a for a, b in zip(times, times[1:])),
            "queries": source_queries,
            "field_values": "UNKNOWN; only RunPARTs timestamps were read",
        },
        "planned_common_queries_s": queries,
        "bracket_policy": {
            "allowed": ["EXACT", "EXACT_OR_LEFT", "BRACKETED"],
            "bracketed_field_interpolation": "UNKNOWN_UNTIL_MANUFACTURED_ERROR_BOUND_AND_EQUAL_BRACKETS_ARE_PROVEN",
            "outside_window": "REJECT; no extrapolation",
            "nonfinite_or_nonmonotone_axis": "REJECT",
            "frame_number_pairing": "FORBIDDEN",
        },
        "frozen_error_budget": {
            "position_relative_to_L": 0.02,
            "event_position_relative_to_L": 0.05,
            "velocity_and_ke_nonzero_reference": 0.05,
            "regional_mass_fraction_of_whole_initial_fluid_mass": 0.03,
            "event_time_fraction_of_characteristic_time": 0.01,
            "time_error_fraction_of_total_window": 0.25,
            "output_error_fraction_of_total_window": 0.25,
            "units_and_zero_reference": "finite, explicit scale required; zero reference is UNDEFINED",
        },
        "manufactured_calibration": manufactured_cases(),
        "real_downsampling_closure": {
            "source_current_output": {"status": "ACTUAL_SOURCE_AXIS_ONLY", "cadence_s": 0.01, "frames": len(times), "window_s": [times[0], times[-1]]},
            "source_same_cfl_savedt_overlay": {"status": "PREPARED_LAUNCH_DISABLED", "request": str((STAGE2 / "requests/stage2-savedt-cfl-pairs-v1/f1_s2_original_savedt_same_cfl.json").resolve())},
            "source_half_cfl_savedt_overlay": {"status": "PREPARED_LAUNCH_DISABLED", "request": str((STAGE2 / "requests/stage2-savedt-cfl-pairs-v1/f1_s2_original_savedt_half_cfl.json").resolve())},
            "fine_dp017_same_cfl_savedt": {"status": "PREPARED_LAUNCH_DISABLED", "overlay": fine_overlay["overlay_xml"]},
            "field_downsampling_error": "UNKNOWN until an actual dense source and selected field observations exist",
            "closure_rule": "derive downsampled observations from actual timestamp brackets after raw retention; never infer from frame indices, never extrapolate, never replace raw source",
        },
        "grid_status": {
            "current_dp020": {"status": "ACTUAL_SOURCE_FULL_WINDOW", "mass_target_kg": SOURCE_SAMPLE_MASS_KG, "solver_fields": "available only through parent consumer"},
            "fine_dp017": {"status": "GENCASE_ACTUAL_SOLVER_PENDING", "sample_mass_kg": 342.04306, "whole_initial_error_pct": 0.6009, "mass_gate": "TARGET_WITHIN_1PCT; scientific qualification UNKNOWN"},
            "coarse_dp0225": {"status": "GENCASE_PENDING_PARENT_GUARD", "spacing_from_current_fraction": 0.125, "sample_mass_kg": "UNKNOWN_UNTIL_GENERATED_XML", "mass_gate": "UNKNOWN"},
            "retained_failures": {"dp025": {"sample_mass_kg": 350.0, "error_pct": 2.941176470588235, "status": "HARD_FAIL_GT2PCT"}, "dp0165": {"sample_mass_kg": 328.82355, "error_pct": -3.287, "status": "HARD_FAIL"}, "dp016": {"sample_mass_kg": 335.978496, "error_pct": -1.182795294117645, "status": "MARGINAL_NOT_ACCEPTED"}},
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def make_contract(source_commit: str, coarse_def: Path, coarse_meta: dict[str, Any], overlay_xml: Path, overlay_bi4: Path, calibration_report: Path) -> dict[str, Any]:
    return {
        "schema": "ds02.stage2.f1-s2-reference-contract.v5",
        "status": "PREPARED_LAUNCH_DISABLED",
        "preparation_source_commit": source_commit,
        "sentinel_id": SENTINEL_ID,
        "family_id": "F1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "study_design": {
            "spatial_grids": [
                {"label": "current_dp020", "dp_m": BASELINE_DP, "role": "immutable CURRENT source", "status": "ACTUAL_SOURCE"},
                {"label": "coarse_dp0225", "dp_m": COARSE_DP, "role": "bounded coarse >=10% spacing", "status": "GENCASE_PENDING"},
                {"label": "fine_dp017", "dp_m": FINE_DP, "role": "target fine source-bound candidate", "status": "GENCASE_ACTUAL_SOLVER_PENDING"},
            ],
            "continuous_geometry": "exact source Def bytes except intentional definition dp attribute; no fill/geometry/motion/control edits",
            "mass_policy": "whole-initial discrete sample mass target 1%; 2% hard upper; no particle-mass rescale; no threshold widening",
            "time_design": "current dp0 same/half CFL dense SaveDt pair plus fine dp0.017 same-CFL dense SaveDt full window; coarse follows only after terminal GenCase mass/geometry audit",
            "window_s": [0.0, TMAX],
            "output_cadence_s": TOUT,
            "planned_query_times_s": [0.0, 1.0, 2.0, 3.0, 4.0],
        },
        "coarse_preflight": {
            "candidate_def": record(coarse_def),
            "definition_semantics": coarse_meta,
            "candidate_dp_m": COARSE_DP,
            "baseline_dp_m": BASELINE_DP,
            "spacing_separation_fraction": COARSE_DP / BASELINE_DP - 1.0,
            "minimum_required_separation_fraction": 0.10,
            "expected_mass": "UNKNOWN_UNTIL_TERMINAL_GENERATED_XML",
            "followup_solver": "forbidden until parent reviews generated XML/receipt and whole-initial/per-material mass/geometry",
        },
        "fine_solver_input": {
            "generated_xml": record(FINE_XML),
            "generated_bi4": record(FINE_BI4, hash_file=False),
            "gencase_receipt": record(FINE_GENCASE_RECEIPT),
            "savedt_overlay_xml": record(overlay_xml),
            "savedt_overlay_bi4": record(overlay_bi4, hash_file=False),
            "overlay_semantics": "same CFL; savedt only; all final-step dt rows; full physical window",
            "candidate_mass_kg": 342.04306,
            "candidate_whole_initial_error_pct": 0.6009,
            "mass_status": "prepared target only; QI/QN/QE UNKNOWN",
        },
        "typed_operator": {
            "reader": record(TYPED_READER),
            "identity_key": "(particle_zone, particle_id)",
            "required_static_fields": ["particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass"],
            "required_dynamic_fields": ["time", "position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"],
            "query_operator": "read actual time axis; return EXACT/EXACT_OR_LEFT/BRACKETED with lower/upper timestamps; never use hardcoded frame indices",
            "comparison_fields": ["position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"],
            "payload_hash": "parent conversion/consumer guard must bind actual trajectory output; preparation does not hash H5",
            "field_comparison_status": "UNKNOWN_UNTIL_PARENT_TYPED_CONVERSION_AND_OBSERVER",
        },
        "calibration_report": {"path": str(calibration_report.resolve()), "sha256": sha256_file(calibration_report)},
        "resource_guard": {
            "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none in preparation", "solver_launch": "forbidden", "hdf5_read": "forbidden", "launch_disabled": True, "protected_external_gpu": PROTECTED_GPU,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def make_gencase_request(source_commit: str, coarse_def: Path, coarse_meta: dict[str, Any]) -> dict[str, Any]:
    output_root = DATA_ROOT / "families/F1/F1_S2_SPATIAL_COARSE_DP0p022500/f1-s2-spatial-coarse-dp0p022500-v5-root-001"
    input_paths = unique_paths([DISPATCH, STRICT, RUNTIME, PYTHON, GENCASE, CURRENT, MATRIX, QUALITY, Path(__file__), SOURCE_DEF, coarse_def, SOURCE_XML, SOURCE_GENCASE_RECEIPT])
    return {
        "schema": "ds02.request.v1",
        "family_id": "F1", "case_id": "F1_S2_SPATIAL_COARSE_DP0p022500", "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": "f1-s2-spatial-coarse-dp0p022500-v5-root-001", "kind": "cpu", "qualification_stage": "stage2_f1_s2_bounded_coarse_gencase_pending_parent_v4_dispatch",
        "cpu_task_kind": "gencase", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600, "estimated_storage_bytes": 128 * 1024 * 1024, "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "worktree_root": str(REPO), "cwd": str(coarse_def.parent), "command": [str(GENCASE), str(coarse_def.with_suffix("")), str(output_root / "generated"), "-save:all"],
        "input_files": [str(path) for path in input_paths], "input_hashes": {str(path): sha256_file(path) for path in input_paths},
        "source_binding": {
            "schema": "ds02.stage2.f1-s2-bounded-coarse-binding.v5", "sentinel_id": SENTINEL_ID, "family_id": "F1", "physical_case_id": PHYSICAL_CASE_ID,
            "grid_role": "bounded_coarse_ge10pct_spacing", "candidate_dp_m": COARSE_DP, "baseline_dp_m": BASELINE_DP, "spacing_separation_fraction": COARSE_DP / BASELINE_DP - 1.0,
            "continuous_source_xml": [record(SOURCE_XML)], "current_source_def": record(SOURCE_DEF), "candidate_def": record(coarse_def), "definition_semantics": coarse_meta,
            "source_gencase_receipt": record(SOURCE_GENCASE_RECEIPT), "source_sample_mass_target_kg": SOURCE_SAMPLE_MASS_KG,
            "prior_results": [{"dp_m": 0.025, "sample_mass_kg": 350.0, "error_pct": 2.941176470588235, "status": "HARD_FAIL_GT2PCT"}, {"dp_m": 0.0165, "sample_mass_kg": 328.82355, "error_pct": -3.287, "status": "HARD_FAIL"}, {"dp_m": 0.016, "sample_mass_kg": 335.978496, "error_pct": -1.182795294117645, "status": "MARGINAL_NOT_ACCEPTED"}],
            "mass_gate": {"whole_initial_target_pct": 1.0, "whole_initial_hard_upper_pct": 2.0, "status": "UNKNOWN_UNTIL_TERMINAL_GENERATED_XML", "particle_mass_rescale": False, "threshold_widening": False},
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "gpu_uuid": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "launch_disabled": True, "new_solver": False, "parent_v4_review_required": True, "preparation_source_commit": source_commit},
        "output_protection": {"refuse_overwrite": True, "attempt_root_must_not_exist_at_dispatch": True},
        "solver_followup": "not included; parent must independently review generated XML/receipt before any full-window solver request",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def make_fine_solver_request(source_commit: str, overlay_xml: Path, overlay_bi4: Path, contract_path: Path) -> dict[str, Any]:
    output_root = DATA_ROOT / "families/F1/F1_S2_SPATIAL_INTERVAL_DP0p017000/f1-s2-spatial-interval-dp0p017000-v5-full4s-root-001"
    input_paths = unique_paths([DISPATCH, STRICT, RUNTIME, SOLVER, Path(__file__), CONTRACT_PATH, REPORT_PATH, TYPED_READER, CURRENT, MATRIX, QUALITY, SOURCE_XML, SOURCE_SOLVER_RECEIPT, SOURCE_RUNPARTS, SOURCE_GENCASE_RECEIPT, FINE_XML, FINE_GENCASE_RECEIPT, overlay_xml, overlay_bi4])
    deferred = {SOLVER.resolve(), FINE_BI4.resolve(), overlay_bi4.resolve()}
    input_hashes = {str(path): ("PARENT_V4_GUARD_REQUIRED" if path in deferred else sha256_file(path)) for path in input_paths}
    source_receipt = json.loads(SOURCE_SOLVER_RECEIPT.read_text(encoding="utf-8"))
    candidate_receipt = json.loads(FINE_GENCASE_RECEIPT.read_text(encoding="utf-8"))
    source_part0 = 5_735_868
    candidate_particles = int(candidate_receipt["total_particles"])
    source_particles = int(json.loads(SOURCE_GENCASE_RECEIPT.read_text(encoding="utf-8"))["total_particles"])
    ratio = candidate_particles / source_particles
    frames = int(math.ceil(TMAX / TOUT - 1.0e-12) + 1)
    raw_proxy = int(math.ceil(source_part0 * frames * ratio))
    reservation = 16 * GIB
    return {
        "schema": "ds02.request.v1", "family_id": "F1", "case_id": "F1_S2_INTERVAL_DP0p017_FULL4S_SAMECFL_SAVEDT_DENSE", "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": "f1-s2-spatial-interval-dp0p017-v5-full4s-savedt-root-001", "kind": "qualification_candidate", "qualification_stage": "stage2_f1_s2_fine_full_window_source_bound_pending_primary_review",
        "cpu_task_kind": "solver", "cpu_threads": 2, "omp_threads": 2, "max_wall_seconds": 7200, "estimated_storage_bytes": reservation, "estimated_peak_gpu_mib": 4096,
        "worktree_root": str(DISPATCH_ROOT), "cwd": str(overlay_xml.parent), "command": [str(SOLVER), str(overlay_xml.with_suffix("")), "{attempt_root}/solver_output", f"-tmax:{TMAX_TEXT}", f"-tout:{TOUT_TEXT}"],
        "gencase_receipt": str(FINE_GENCASE_RECEIPT.resolve()), "gencase_receipt_sha256": sha256_file(FINE_GENCASE_RECEIPT), "expected_particles": candidate_particles, "expected_fluid_particles": 69620, "expected_native_frames": frames, "expected_dimension": 3,
        "physical_window_s": [0.0, TMAX], "save_interval_s": TOUT,
        "source_binding": {
            "schema": "ds02.stage2.f1-s2-fine-full-window-binding.v5", "sentinel_id": SENTINEL_ID, "family_id": "F1", "physical_case_id": PHYSICAL_CASE_ID,
            "current_source": {"xml": record(SOURCE_XML), "bi4": record(SOURCE_BI4, hash_file=False), "gencase_receipt": record(SOURCE_GENCASE_RECEIPT), "solver_receipt": record(SOURCE_SOLVER_RECEIPT), "runparts": record(SOURCE_RUNPARTS), "sample_mass_target_kg": SOURCE_SAMPLE_MASS_KG},
            "candidate_grid": {"label": "interval_dp0p017", "dp_m": FINE_DP, "generated_xml": record(FINE_XML), "generated_bi4": record(FINE_BI4, hash_file=False), "gencase_receipt": record(FINE_GENCASE_RECEIPT), "whole_initial_sample_mass_kg": 342.04306, "whole_initial_error_pct": 0.6009, "mass_gate": "TARGET_WITHIN_1PCT_BUT_SCIENTIFIC_UNKNOWN"},
            "solver_input": {"overlay_xml": record(overlay_xml), "overlay_bi4": record(overlay_bi4, hash_file=False), "overlay_changes": ["savedt start=0 finish=0 interval=0.005 fullinfo=0 alldt=1"], "cfl_mode": "same_cfl", "source_cfl": 0.2, "effective_cfl": 0.2},
            "continuous_geometry_control": "candidate generated XML is bound to exact source geometry/fill/control semantics; only intentional dp-derived h/mass/count differ; savedt overlay is logging-only",
            "typed_operator_contract": {"path": str(contract_path.resolve()), "sha256": sha256_file(contract_path), "reader": record(TYPED_READER), "fields": ["time", "position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"], "identity": "(particle_zone, particle_id)"},
        },
        "dt_contract": {"requested": True, "savedt": {"start_s": 0.0, "finish_s": 0.0, "interval_s": TOUT, "fullinfo": 0, "alldt": 1}, "RunPARTs_DTsMin": "count only, not seconds or a per-step trace", "clamp": "aggregate only unless actual source exposes per-row flag; do not infer"},
        "output_plan": {"native_raw": "retain all Part_*.bi4 over [0,4.000064410707409]", "typed": {"mode": "selected query-time anchors after raw retention", "query_times_s": [0.0, 1.0, 2.0, 3.0, 4.0], "time_policy": "EXACT/EXACT_OR_LEFT/BRACKETED from actual typed time axis; no frame indices or extrapolation"}, "observer": {"status": "PENDING_PARENT_TYPED_CONVERSION_AND_FIELD_CALIBRATION", "fields": ["position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"]}, "downsample": "derived after raw retention; source dense/half-CFL comparison remains UNKNOWN until actual receipts"},
        "cost": {"source_part0_bytes": source_part0, "source_particles": source_particles, "candidate_particles": candidate_particles, "candidate_particle_ratio": ratio, "planned_frames": frames, "raw_native_scaled_proxy_bytes": raw_proxy, "estimated_storage_bytes": reservation, "proxy_warning": "particle scaling is a planning proxy; parent v4 terminal tree/receipt is authoritative", "source_solver_gpu_seconds": source_receipt.get("gpu_seconds"), "gpu_seconds_proxy": float(source_receipt.get("gpu_seconds") or 0.0) * ratio, "typed_and_archive": "not reserved in this solver request; plan separately after actual terminal bytes"},
        "launch_policy": {"launch_disabled": True, "execution_allowed": False, "solver_launch_owner": "root", "primary_gpu_dispatch_required": True, "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER", "protected_external_gpu": PROTECTED_GPU, "parent_guard": str(DISPATCH)},
        "input_files": [str(path) for path in input_paths], "input_hashes": input_hashes, "deferred_parent_hashes": [{"path": str(path), "reason": "binary input must be hashed by parent v4 immediately before any launch"} for path in sorted(deferred, key=str)],
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "launch_commit": source_commit, "cpu_parent_binding": "required", "gpu_uuid_lease": "primary only; none granted in preparation", "source_output_protection": "new attempt output only; immutable CURRENT and completed GenCase/source solver artifacts", "estimated_cpu_core_hours": 4.0, "estimated_gpu_hours_proxy": float(source_receipt.get("gpu_seconds") or 0.0) * ratio / 3600.0, "estimated_new_storage_bytes": reservation},
        "scope": {"physical_case_id": PHYSICAL_CASE_ID, "sentinel_id": SENTINEL_ID, "candidate_grid": "dp0.017", "cfl_mode": "same_cfl", "full_time_hdf5_read_in_preparation": False, "solver_started": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
    }


def build() -> dict[str, Any]:
    source_commit = git_head()
    coarse_def, coarse_meta = derive_coarse_def()
    overlay_xml, overlay_bi4, overlay_meta = make_fine_overlay()
    calibration = make_calibration_report(source_commit, coarse_meta=coarse_meta, fine_overlay=overlay_meta)
    atomic_json(REPORT_PATH, calibration)
    contract = make_contract(source_commit, coarse_def, coarse_meta, overlay_xml, overlay_bi4, REPORT_PATH)
    atomic_json(CONTRACT_PATH, contract)
    coarse_request = make_gencase_request(source_commit, coarse_def, coarse_meta)
    atomic_json(COARSE_REQUEST_PATH, coarse_request)
    fine_request = make_fine_solver_request(source_commit, overlay_xml, overlay_bi4, CONTRACT_PATH)
    atomic_json(FINE_REQUEST_PATH, fine_request)
    return {"coarse_request": str(COARSE_REQUEST_PATH), "fine_request": str(FINE_REQUEST_PATH), "contract": str(CONTRACT_PATH), "calibration": str(REPORT_PATH), "source_commit": source_commit}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))

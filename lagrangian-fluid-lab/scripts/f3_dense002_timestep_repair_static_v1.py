#!/usr/bin/env python3
"""Build a read-only numerical proposal for the F3 dense .002 s source.

The existing dense source misses the registered 20 microsecond saved-time
bound because completed solver steps straddle the .002 s output grid.  Earlier
repair proposals selected a coefficient that is rounded down by DualSPHysics'
float ``CoefDtMin`` parser.  This tool evaluates that failure and a single
explicit ``DtMin`` repair using the solver's double-valued parameter path.

This is a static, constant-step argument.  It reads JSON/XML/source files and
never opens an H5 file, launches a solver, mutates a prepared case, or writes
the central ledger.  A binary source-generation canary remains required.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np


OUTPUT_INTERVAL_S = 0.002
TIME_MAX_S = 8.35
EXPECTED_INTERVALS = 4175
EXPECTED_FRAMES = EXPECTED_INTERVALS + 1
CADENCE_TOLERANCE_S = 2.0e-5
TARGET_STEPS = 91

PREPARED_REL = (
    "campaigns/core-v1/cfd/f3-native-mls-sources/prepared-v2/"
    "f3_production_amp1p1_native002/prepared.json"
)
XML_REL = (
    "campaigns/core-v1/cfd/f3-native-mls-sources/prepared-v2/"
    "f3_production_amp1p1_native002/F3_CELL3_plain_0p0075.xml"
)
DEF_XML_REL = (
    "campaigns/core-v1/cfd/f3-native-mls-sources/prepared-v2/"
    "f3_production_amp1p1_native002/F3_CELL3_plain_0p0075_Def.xml"
)
SOLVER_REL = "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
JSph_REL = "vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp"
JSph_HEADER_REL = "vendor/official/DualSPHysics_v5.4/src/source/JSph.h"
JSph_GPU_REL = "vendor/official/DualSPHysics_v5.4/src/source/JSphGpu.cpp"
CASE_PARTS_REL = "vendor/official/DualSPHysics_v5.4/src/source/JCaseParts.h"
STATIC_REVIEW_REL = (
    "campaigns/core-v1/material/evidence/f3-dense-cadence-diagnosis-v1/"
    "root-static-repair-review-v1.json"
)
DIAGNOSIS_REL = (
    "campaigns/core-v1/material/evidence/f3-dense-cadence-diagnosis-v1/"
    "dense1p0-vs-dense1p1-cadence-diagnosis-v3.json"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def lab_path(lab: Path, relative: str) -> Path:
    return (lab.resolve() / relative).resolve()


def immutable_json(path: Path, value: Any) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"immutable evidence already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def _finite_positive(value: float, name: str) -> float:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive, got {value!r}")
    return float(value)


def xml_parameters(path: Path) -> dict[str, float]:
    root = ET.parse(path).getroot()
    nodes = root.findall("./execution/parameters/parameter")
    required = {"TimeMax", "TimeOut", "CoefDtMin", "DtIni", "DtMin", "DtFixed"}
    values: dict[str, float] = {}
    for node in nodes:
        key = node.get("key")
        raw = node.get("value")
        if key is None or raw is None or key not in required:
            continue
        try:
            values[key] = float(raw)
        except ValueError as exc:
            raise ValueError(f"non-numeric parameter {key!r} in {path}") from exc
    missing = sorted(required - values.keys())
    if missing:
        raise ValueError(f"missing parameters in {path}: {missing}")
    return values


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _prepared_value(prepared: dict[str, Any], key: str) -> Any:
    case = prepared.get("case", {})
    config = prepared.get("config", {})
    if key in prepared:
        return prepared[key]
    if key in case:
        return case[key]
    if key in config:
        return config[key]
    raise KeyError(key)


def static_schedule(dt_s: float, *, interval_s: float, intervals: int,
                    tolerance_s: float) -> dict[str, Any]:
    """Model TimeStep += dt and save at the first completed step >= target."""
    dt_s = _finite_positive(dt_s, "dt_s")
    interval_s = _finite_positive(interval_s, "interval_s")
    if intervals < 1:
        raise ValueError("intervals must be positive")
    time_s = 0.0
    target_s = interval_s
    errors: list[float] = []
    step_counts: list[int] = []
    total_steps = 0
    for _index in range(1, intervals + 1):
        local_steps = 0
        while time_s < target_s:
            time_s += dt_s
            local_steps += 1
            total_steps += 1
            if local_steps > 1_000_000:
                raise RuntimeError("static scheduler guard exceeded")
        errors.append(time_s - target_s)
        step_counts.append(local_steps)
        target_s += interval_s
    error_array = np.asarray(errors, dtype=np.float64)
    bad = np.flatnonzero(np.abs(error_array) > tolerance_s)
    return {
        "dt_s": dt_s,
        "interval_s": interval_s,
        "intervals": int(intervals),
        "frames_including_initial": int(intervals + 1),
        "total_steps": int(total_steps),
        "max_abs_error_s": float(np.max(np.abs(error_array))),
        "max_abs_error_us": float(np.max(np.abs(error_array)) * 1.0e6),
        "max_error_index_one_based": int(np.argmax(np.abs(error_array)) + 1),
        "final_error_s": float(error_array[-1]),
        "final_time_s": float(time_s),
        "bad_count": int(bad.size),
        "first_bad_index_one_based": int(bad[0] + 1) if bad.size else None,
        "bad_indices_first32_one_based": [int(index + 1) for index in bad[:32]],
        "step_count_min": int(min(step_counts)),
        "step_count_max": int(max(step_counts)),
        "step_count_unique_first32": sorted({int(x) for x in step_counts})[:32],
        "pass_20us_bound": bool(bad.size == 0),
    }


def _input_record(path: Path, lab: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def build_report(lab: Path, *, script_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    prepared_path = lab_path(lab, PREPARED_REL)
    xml_path = lab_path(lab, XML_REL)
    def_xml_path = lab_path(lab, DEF_XML_REL)
    solver_path = lab_path(lab, SOLVER_REL)
    static_review_path = lab_path(lab, STATIC_REVIEW_REL)
    diagnosis_path = lab_path(lab, DIAGNOSIS_REL)
    source_paths = {
        "JSph.cpp": lab_path(lab, JSph_REL),
        "JSph.h": lab_path(lab, JSph_HEADER_REL),
        "JSphGpu.cpp": lab_path(lab, JSph_GPU_REL),
        "JCaseParts.h": lab_path(lab, CASE_PARTS_REL),
    }
    required_paths = [prepared_path, xml_path, def_xml_path, solver_path,
                      static_review_path, diagnosis_path, script_path, *source_paths.values()]
    for path in required_paths:
        if not path.is_file():
            raise FileNotFoundError(path)

    prepared = read_json(prepared_path)
    xml_values = xml_parameters(xml_path)
    def_values = xml_parameters(def_xml_path)
    if xml_values != def_values:
        raise ValueError("prepared XML and Def.xml execution parameters differ")
    if not math.isclose(xml_values["TimeOut"], OUTPUT_INTERVAL_S, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError("dense source TimeOut is not the registered .002 s cadence")
    if not math.isclose(xml_values["TimeMax"], TIME_MAX_S, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("dense source TimeMax is not the complete 8.35 s window")
    if xml_values["DtMin"] != 0.0 or xml_values["DtFixed"] != 0.0:
        raise ValueError("current source is no longer the expected coefficient-controlled baseline")
    if not math.isclose(xml_values["CoefDtMin"], 0.05, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("current source CoefDtMin is not the registered .05 baseline")

    static_review = read_json(static_review_path)
    diagnosis = read_json(diagnosis_path)
    current_dt_s = _finite_positive(float(diagnosis["solver_schedule_comparison"]["candidate_run_out"]["dt_min_s"]), "current_dt_s")
    dt_ini_s = _finite_positive(float(diagnosis["solver_schedule_comparison"]["candidate_run_out"]["dt_ini_s"]), "dt_ini_s")
    old_coef_decimal = OUTPUT_INTERVAL_S / TARGET_STEPS / dt_ini_s
    old_coef_float32 = float(np.float32(old_coef_decimal))
    old_coef_dt_s = dt_ini_s * old_coef_float32
    target_dt_s = OUTPUT_INTERVAL_S / TARGET_STEPS
    target_dt_float32_down_s = float(np.float32(target_dt_s))
    target_dt_float32_up_s = float(np.nextafter(np.float32(target_dt_s), np.float32(np.inf)))
    # The explicit XML DtMin is parsed as double.  Using the upward float32
    # neighbour gives a measurable margin against repeated double additions,
    # while staying below the existing baseline floor.
    candidate_dt_s = target_dt_float32_up_s
    candidate_coef_if_used = candidate_dt_s / dt_ini_s

    current_schedule = static_schedule(current_dt_s, interval_s=OUTPUT_INTERVAL_S,
                                        intervals=EXPECTED_INTERVALS,
                                        tolerance_s=CADENCE_TOLERANCE_S)
    old_schedule = static_schedule(old_coef_dt_s, interval_s=OUTPUT_INTERVAL_S,
                                   intervals=EXPECTED_INTERVALS,
                                   tolerance_s=CADENCE_TOLERANCE_S)
    candidate_schedule = static_schedule(candidate_dt_s, interval_s=OUTPUT_INTERVAL_S,
                                          intervals=EXPECTED_INTERVALS,
                                          tolerance_s=CADENCE_TOLERANCE_S)
    input_files = {
        "prepared": _input_record(prepared_path, lab),
        "xml": _input_record(xml_path, lab),
        "def_xml": _input_record(def_xml_path, lab),
        "solver_binary": _input_record(solver_path, lab),
        "static_review": _input_record(static_review_path, lab),
        "existing_diagnosis": _input_record(diagnosis_path, lab),
    }
    source_semantics = {
        name: {"path": str(path.resolve()), "sha256": sha256(path)}
        for name, path in source_paths.items()
    }
    report = {
        "schema": "core.material.f3.dense002_timestep_repair_static.v1",
        "created_at_utc": utc_now(),
        "status": "static_complete_no_cfd",
        "qualification_claim": "none; repaired source remains qualification_only",
        "launch_allowed": False,
        "central_ledger_mutation": False,
        "h5_access": {"opened": False, "active_h5_read": False},
        "analysis_code": {"path": str(script_path.resolve()), "sha256": sha256(script_path)},
        "source_provenance": {
            "source_asset_id": _prepared_value(prepared, "source_asset_id"),
            "case_id": _prepared_value(prepared, "case_id"),
            "matrix_rows": _prepared_value(prepared, "matrix_rows"),
            "q": _prepared_value(prepared, "q"),
            "drive_amplitude": _prepared_value(prepared, "drive_amplitude"),
            "dp_m": _prepared_value(prepared, "dp_m"),
            "time_max_s": _prepared_value(prepared, "time_max_s"),
            "output_interval_s": _prepared_value(prepared, "output_interval_s"),
            "input_files": input_files,
        },
        "solver_semantics": {
            "parameter_paths": {
                "CoefDtMin": "JSph::ConfigBasic -> GetValueFloat",
                "DtMin": "JSph::ConfigBasic -> GetValueDouble",
                "computed_default": "JSph::ConfigConstants2: if(!DtMin) DtMin=(KernelH/Cs0)*CoefDtMin",
                "clamp": "JSphGpu::DtVariable: if(dt < DtMin) dt=DtMin",
                "save_condition": "JSphGpuSingle::Run: if(TimeStep >= TimePartNext) SaveData()",
            },
            "source_files": source_semantics,
            "interpretation": (
                "A nonzero explicit DtMin bypasses the float CoefDtMin product. "
                "The static schedule assumes accepted steps equal the candidate floor; "
                "the binary canary must measure whether the variable CFL step remains "
                "at or below that floor."
            ),
        },
        "registered_gate": {
            "output_interval_s": OUTPUT_INTERVAL_S,
            "time_max_s": TIME_MAX_S,
            "expected_intervals": EXPECTED_INTERVALS,
            "expected_frames": EXPECTED_FRAMES,
            "cadence_tolerance_s": CADENCE_TOLERANCE_S,
            "cadence_tolerance_us": CADENCE_TOLERANCE_S * 1e6,
            "threshold_change": False,
            "posthoc_timestamp_rewrite": False,
            "interpolation": False,
        },
        "arithmetic": {
            "target_steps_per_interval": TARGET_STEPS,
            "target_dt_s": target_dt_s,
            "target_dt_float32_down_s": target_dt_float32_down_s,
            "target_dt_float32_up_s": target_dt_float32_up_s,
            "current_dt_min_s_from_terminal_runout": current_dt_s,
            "dt_ini_s_from_terminal_runout": dt_ini_s,
            "old_proposal_coef_decimal": old_coef_decimal,
            "old_proposal_coef_float32": old_coef_float32,
            "old_proposal_dt_min_s_after_float32": old_coef_dt_s,
            "candidate_explicit_DtMin_s": candidate_dt_s,
            "candidate_equivalent_coef_for_diagnostic_only": candidate_coef_if_used,
            "candidate_relative_to_current_dt": candidate_dt_s / current_dt_s - 1.0,
            "candidate_91_step_overshoot_us": (TARGET_STEPS * candidate_dt_s - OUTPUT_INTERVAL_S) * 1e6,
            "old_91_step_error_us": (TARGET_STEPS * old_coef_dt_s - OUTPUT_INTERVAL_S) * 1e6,
            "reason": (
                "The old coefficient target is rounded downward as float32, so 91 steps "
                "undershoot .002 s and completed-step ceiling selects 92 steps. "
                "The candidate is an explicit double DtMin equal to the upward float32 "
                "neighbor of .002/91, giving a positive margin without raising the "
                "existing minimum floor."
            ),
        },
        "constant_step_schedule_model": {
            "model": "float64 repeated TimeStep += dt; save at first completed step >= k*TimeOut",
            "current_baseline": current_schedule,
            "old_float32_rounded_proposal": old_schedule,
            "candidate_explicit_DtMin": candidate_schedule,
        },
        "repair": {
            "repair_id": "F3_DENSE002_EXPLICIT_DTMIN_FLOAT64_UP_V1",
            "fresh_lineage_required": True,
            "xml_parameter_override": {
                "DtMin": format(candidate_dt_s, ".17g"),
                "CoefDtMin": format(xml_values["CoefDtMin"], ".17g"),
                "DtFixed": format(xml_values["DtFixed"], ".17g"),
                "TimeOut": format(xml_values["TimeOut"], ".17g"),
                "TimeMax": format(xml_values["TimeMax"], ".17g"),
            },
            "preserve": [
                "F3 recipe, amplitude=1.1, dp=.0075, boundary and forcing inputs",
                "CFL=.05 and all material/wall/finite-state audit gates",
                "native .002 s output and complete 8.35 s window",
                "no interpolation and no post-hoc timestamp rewrite",
            ],
            "expected_static_result": {
                "max_abs_error_us": candidate_schedule["max_abs_error_us"],
                "bad_count": candidate_schedule["bad_count"],
                "final_time_s": candidate_schedule["final_time_s"],
                "total_steps_constant_floor_model": candidate_schedule["total_steps"],
            },
        },
        "canary_requirements": {
            "status": "design_only_not_submitted",
            "bounded_source_generation": "fresh prepared directory and new runner/snapshot; no mutation of current dense002 source",
            "required_measurements": [
                "Run.out DtMin, DtMax, DtModif and total steps",
                "all 4176 saved timestamps and exact max abs error against i*.002",
                "audit v2 hard_integrity_pass including wall, finite state and per-particle mass",
                "input, solver, runner, prepared XML and generated source hashes",
            ],
            "acceptance": [
                "all 4176 timestamps satisfy abs(t_i - i*.002) <= 2e-5 s",
                "no timestamp rewrite or interpolation",
                "unchanged source wall/finite/validity/mass gates pass",
                "repaired output remains qualification_only and is not substituted into T1/T2",
            ],
            "failure_action": "retain current negative qualification status and discard repaired lineage for matrix use",
        },
        "limits": [
            "This report is a static constant-step calculation, not execution of the registered binary.",
            "Explicit DtMin is a lower clamp; a canary must show that the computed CFL step does not exceed the proposed floor enough to break the cadence bound.",
            "Changing DtMin changes the numerical time-step schedule, so any repaired source requires independent source audit and qualification-only review.",
            "No material gate, cadence tolerance, or existing source result is changed by this proposal.",
        ],
    }
    proposal = {
        "schema": "core.material.f3.dense002_timestep_repair_proposal.v2",
        "created_at_utc": report["created_at_utc"],
        "status": "preregistered_static_only",
        "qualification_claim": "none; do not submit or use as T1/T2 source",
        "repair_id": report["repair"]["repair_id"],
        "analysis_report_path": None,
        "analysis_report_sha256": None,
        "launch_allowed": False,
        "central_ledger_mutation": False,
        "active_h5_read": False,
        "input_hashes": input_files,
        "solver_source_hashes": source_semantics,
        "candidate": {
            "parameter": "explicit XML DtMin parsed by GetValueDouble",
            "DtMin_s": candidate_dt_s,
            "DtMin_decimal": format(candidate_dt_s, ".17g"),
            "CoefDtMin_preserved": xml_values["CoefDtMin"],
            "DtFixed_preserved": xml_values["DtFixed"],
            "output_interval_s": OUTPUT_INTERVAL_S,
            "time_max_s": TIME_MAX_S,
            "target_steps_per_interval": TARGET_STEPS,
        },
        "static_decision": {
            "old_float32_rounded_proposal_pass_20us": old_schedule["pass_20us_bound"],
            "candidate_pass_20us": candidate_schedule["pass_20us_bound"],
            "candidate_max_abs_error_us": candidate_schedule["max_abs_error_us"],
            "candidate_bad_count": candidate_schedule["bad_count"],
            "threshold_changed": False,
        },
        "required_next_step": "root may separately freeze a bounded fresh source-generation canary after reviewing this static result",
        "not_allowed": [
            "do not modify or relabel the existing dense002 output",
            "do not replace timestamps after generation",
            "do not inherit T1/T2 status",
            "do not submit CFD from this proposal automatically",
        ],
    }
    return report, proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--proposal-output", type=Path, required=True)
    args = parser.parse_args(argv)
    lab = args.lab_root.resolve()
    script_path = Path(__file__).resolve()
    report, proposal = build_report(lab, script_path=script_path)
    report_path = args.output.resolve()
    proposal["analysis_report_path"] = str(report_path)
    immutable_json(report_path, report)
    proposal["analysis_report_sha256"] = sha256(report_path)
    immutable_json(args.proposal_output, proposal)
    result = {
        "report": str(report_path),
        "report_sha256": sha256(report_path),
        "proposal": str(args.proposal_output.resolve()),
        "proposal_sha256": sha256(args.proposal_output.resolve()),
        "candidate_max_abs_error_us": report["repair"]["expected_static_result"]["max_abs_error_us"],
        "candidate_bad_count": report["repair"]["expected_static_result"]["bad_count"],
        "old_float32_proposal_max_abs_error_us": report["constant_step_schedule_model"]["old_float32_rounded_proposal"]["max_abs_error_us"],
        "launch_allowed": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

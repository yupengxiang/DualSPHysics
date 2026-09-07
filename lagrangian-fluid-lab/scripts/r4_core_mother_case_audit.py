#!/usr/bin/env python3
"""Read-only R4 qualification audit for the first core mother case.

This module deliberately does not import the campaign runner, GenCase, a
solver wrapper, h5py, numpy, or any GPU helper.  It only reads the committed
W05/R3 reports plus existing text/runtime evidence and writes the two new R4
audit artefacts when invoked as a script.

The audit keeps four facts separate:

* an official physical anchor exists;
* a case definition was prepared;
* a solver attempt completed;
* the completed run is compatible with a proposed common protocol.

In particular, a GenCase ``.bi4`` is not treated as a solver trajectory and a
legacy one-resolution development run is not silently promoted to a
three-resolution matrix cell.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN_REL = Path("campaigns/v0.1-candidate")
CAMPAIGN = LAB / CAMPAIGN_REL
DEFAULT_JSON = CAMPAIGN / "r4-core-mother-case-audit.json"
DEFAULT_MD = CAMPAIGN / "R4-CORE-MOTHER-CASE-AUDIT.md"

LEVELS = ("coarse", "medium", "fine")
FAMILIES = ("F1", "F3")

# R3's mass-matched choices are retained as the only evidence-backed spatial
# schedule for the new common matrix.  The W05 official anchor is kept on its
# original schedule and is not relabelled as one of these custom runs.
R3_RESOLUTIONS = {
    "F1": {"coarse": 0.035, "medium": 0.024, "fine": 0.014},
    "F3": {"coarse": 0.035, "medium": 0.028, "fine": 0.022},
}

COMMON_A1_PROTOCOL = {
    "saved_output_cadence_s": 0.01,
    "integrator": "Verlet",
    "step_algorithm": 1,
    "verlet_steps": 40,
    "boundary_formulation": "DBC",
    "F1_time_max_s": 1.5,
    "F3_time_max_s": 0.9,
}

# These are the smallest same-family ladders already represented by the
# repository's custom cases.  F1_opposing_columns is intentionally retained
# as an alternate: it has two initial fluid sources and therefore changes the
# mother-case initial-condition axis rather than only the background topology.
BACKGROUND_SPECS = {
    "F1": (
        {
            "background_id": "plain_dam_break",
            "label": "plain dam-break",
            "legacy_case_id": "F1_dam_break_plain",
            "r3_prefix": None,
            "source_definition": "cases/F1/F1_dam_break_plain/F1_dam_break_plain_Def.xml",
            "mechanism": "collapse-runup-return",
            "selection_reason": "single-source closed control for the obstacle ladder",
        },
        {
            "background_id": "center_obstacle",
            "label": "center obstacle",
            "legacy_case_id": "F1_center_obstacle",
            "r3_prefix": None,
            "source_definition": "cases/F1/F1_center_obstacle/F1_center_obstacle_Def.xml",
            "mechanism": "split-around-obstacle",
            "selection_reason": "single-source one-obstacle topology between plain and twin",
        },
        {
            "background_id": "twin_obstacle_split_remerge",
            "label": "twin obstacle split-remerge",
            "legacy_case_id": "F1_twin_obstacle",
            "r3_prefix": "R3_F1_twin_obstacle_split_remerge_massmatched",
            "source_definition": "cases/F1/F1_twin_obstacle/F1_twin_obstacle_Def.xml",
            "mechanism": "multi-path-split-remerge",
            "selection_reason": "the only F1 custom background with an R3 three-resolution run",
        },
    ),
    "F3": (
        {
            "background_id": "impulse_slosh",
            "label": "impulse slosh",
            "legacy_case_id": "F3_impulse_slosh",
            "r3_prefix": None,
            "source_definition": "cases/F3/F3_impulse_slosh/F3_impulse_slosh_Def.xml",
            "mechanism": "free-surface-phase-memory",
            "selection_reason": "no-baffle single-source control",
        },
        {
            "background_id": "baffled_exchange",
            "label": "baffled exchange",
            "legacy_case_id": "F3_baffled_slosh",
            "r3_prefix": "R3_F3_baffled_exchange_massmatched",
            "source_definition": "cases/F3/F3_baffled_slosh/F3_baffled_slosh_Def.xml",
            "mechanism": "baffle-exchange-repeated-impact",
            "selection_reason": "the only F3 custom background with an R3 three-resolution run",
        },
        {
            "background_id": "transverse_slosh",
            "label": "transverse slosh",
            "legacy_case_id": "F3_transverse_slosh",
            "r3_prefix": None,
            "source_definition": "cases/F3/F3_transverse_slosh/F3_transverse_slosh_Def.xml",
            "mechanism": "transverse-slosh",
            "selection_reason": "orthogonal forcing/topology control already present in the custom set",
        },
    ),
}

ALTERNATE_BACKGROUNDS = {
    "F1": [
        {
            "background_id": "opposing_columns",
            "case_id": "F1_opposing_columns",
            "source_definition": "cases/F1/F1_opposing_columns/F1_opposing_columns_Def.xml",
            "reason_deferred": "two initial fluid sources; separate initial-condition axis",
        },
    ],
    "F3": [
        {
            "background_id": "perforated_proxy",
            "case_id": "W08_F3_topology_perforated_proxy_00",
            "source_definition": "campaigns/v0.1-candidate/cases/w08/topology/F3_perforated_proxy/W08_F3_topology_perforated_proxy_Def.xml",
            "reason_deferred": "W08 topology holdout; candidate-only and no three-resolution matrix",
        },
    ],
}


def relpath(path: Path, root: Path) -> str:
    """Return a stable repository-relative path for audit output."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_fingerprint(path: Path, root: Path) -> dict[str, Any]:
    """Fingerprint text evidence, while keeping large binary payloads cheap."""

    result: dict[str, Any] = {"path": relpath(path, root), "exists": path.is_file()}
    if not path.is_file():
        return result
    result["bytes"] = path.stat().st_size
    if path.suffix.lower() not in {".bi4", ".h5", ".pt", ".zip", ".pdf", ".xls", ".ods", ".png"}:
        result["sha256"] = sha256(path)
    else:
        result["sha256"] = None
        result["hash_note"] = "binary payload not hashed by the CPU metadata audit"
    return result


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def numeric(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    parsed = numeric(value)
    return int(parsed) if parsed is not None else None


def parse_command_flag(command: Iterable[Any], flag: str) -> float | None:
    prefix = f"-{flag}:"
    for token in command:
        text = str(token)
        if text.startswith(prefix):
            return numeric(text[len(prefix):])
    return None


def parse_xml_controls(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return {"parse_error": True}
    definition = root.find(".//geometry/definition")
    params = {
        node.get("key"): node.get("value")
        for node in root.findall(".//execution/parameters/parameter")
        if node.get("key")
    }
    step_algorithm = params.get("StepAlgorithm")
    integrator = {"1": "Verlet", "2": "Symplectic"}.get(str(step_algorithm), step_algorithm)
    return {
        "dp_m": numeric(definition.get("dp")) if definition is not None else None,
        "time_max_s": numeric(params.get("TimeMax")),
        "saved_output_cadence_s": numeric(params.get("TimeOut")),
        "step_algorithm": integer(step_algorithm),
        "integrator": integrator,
        "verlet_steps": integer(params.get("VerletSteps")),
        "save_pos_double": integer(params.get("SavePosDouble")),
        "boundary_parameter": params.get("Boundary"),
    }


def parse_solver_log(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(errors="replace")
    result: dict[str, Any] = {}
    patterns = (
        ("integrator", r'StepAlgorithm="?([^"\r\n]+)'),
        ("time_max_s", r"TimeMax=([0-9.eE+\-]+)"),
        ("steps", r"Steps of simulation\.+:\s*([0-9,]+)"),
        ("integration_line", r"Time integration scheme:\s*([^\r\n]+)"),
        ("finished", r"Finished execution \(code=0\)"),
    )
    for key, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1) if match.lastindex else True
        if key in {"time_max_s"}:
            result[key] = numeric(value)
        elif key == "steps":
            result[key] = integer(value)
        elif key == "integrator":
            result[key] = value.strip()
        elif key == "integration_line":
            result[key] = value.strip()
            result.setdefault("integrator", value.strip().split("(", 1)[0].strip())
        else:
            result[key] = value
    return result


def parse_run_csv(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    lines = [line.strip() for line in path.read_text(errors="replace").splitlines() if line.strip()]
    header_line = next((line for line in lines if line.startswith("#RunName;")), None)
    if header_line is None:
        return {}
    data_lines = [line for line in lines if not line.startswith("#")]
    if not data_lines:
        return {}
    headers = header_line[1:].split(";")
    values = next(csv.reader([data_lines[-1]], delimiter=";"))
    return dict(zip(headers, values))


def find_file(candidates: Iterable[Path]) -> Path | None:
    for path in candidates:
        if path.is_file():
            return path
    return None


def run_directory_candidates(root: Path, case_id: str) -> list[Path]:
    campaign = root / CAMPAIGN_REL
    return [
        campaign / "runs" / case_id,
        root / "runs" / case_id,
    ]


def resolve_attempt(root: Path, case_id: str) -> tuple[Path | None, dict[str, Any]]:
    for run_dir in run_directory_candidates(root, case_id):
        latest = run_dir / "latest.json"
        if latest.is_file():
            payload = load_json(latest)
            value = payload.get("attempt_directory")
            if value:
                attempt = Path(value)
                if not attempt.is_absolute():
                    attempt = root / attempt
                if attempt.is_dir():
                    return attempt, payload
        attempts = run_dir / "attempts"
        complete = sorted(attempts.glob("*.complete"))
        if complete:
            attempt = complete[-1]
            return attempt, load_json(attempt / "attempt.json")
    return None, {}


def artifact_paths_for_case(root: Path, case_id: str, source_definition: str) -> dict[str, Path]:
    campaign = root / CAMPAIGN_REL
    source = root / source_definition
    if case_id.startswith("W05_"):
        generated = campaign / "artifacts" / "w05" / case_id / "generated"
    elif case_id.startswith("R3_"):
        generated = campaign / "artifacts" / "r3-g2-f1-f3" / case_id / "generated"
    else:
        generated = source.parent / "generated"
    return {
        "source_definition": source,
        "generated_xml": generated / f"{case_id}.xml",
        "generated_log": generated / "gencase.stdout.log",
        "generated_out": generated / f"{case_id}.out",
        "generated_bi4": generated / f"{case_id}.bi4",
    }


def detect_boundary(configuration: str | None) -> str | None:
    if not configuration:
        return None
    if "mDBC" in configuration:
        return "mDBC"
    if re.search(r"\bDBC\b", configuration):
        return "DBC"
    return None


def execution_record(
    root: Path,
    case_id: str,
    source_definition: str,
    *,
    planned_dp_m: float | None = None,
    planned_time_max_s: float | None = None,
    planned_cadence_s: float | None = None,
    planned_integrator: str | None = None,
    planned_boundary: str | None = None,
) -> dict[str, Any]:
    """Read one case's generated and solver evidence without executing anything."""

    paths = artifact_paths_for_case(root, case_id, source_definition)
    attempt_dir, attempt_payload = resolve_attempt(root, case_id)
    runtime_dir = find_file([directory / "Run.csv" for directory in run_directory_candidates(root, case_id)])
    solver_log = find_file([directory / "solver.stdout.log" for directory in run_directory_candidates(root, case_id)])
    run_csv = runtime_dir
    if attempt_dir is not None:
        attempt_run_csv = attempt_dir / "Run.csv"
        attempt_log = attempt_dir / "process.stdout.log"
        run_csv = find_file([attempt_run_csv, run_csv] if run_csv else [attempt_run_csv])
        solver_log = find_file([attempt_log, solver_log] if solver_log else [attempt_log])

    xml_controls = parse_xml_controls(paths["generated_xml"])
    log_controls = parse_solver_log(solver_log) if solver_log else {}
    csv_controls = parse_run_csv(run_csv) if run_csv else {}
    command = attempt_payload.get("command", []) if isinstance(attempt_payload, dict) else []

    observed_dp = numeric(csv_controls.get("Dp")) or numeric(xml_controls.get("dp_m"))
    command_time_max = parse_command_flag(command, "tmax")
    command_cadence = parse_command_flag(command, "tout")
    time_max = command_time_max or log_controls.get("time_max_s") or xml_controls.get("time_max_s")
    saved_cadence = command_cadence or xml_controls.get("saved_output_cadence_s")
    physical_time = numeric(csv_controls.get("PhysicalTime"))
    frames = integer(csv_controls.get("PartFiles"))
    actual_cadence = None
    if physical_time is not None and frames is not None and frames > 1:
        actual_cadence = physical_time / (frames - 1)
    integrator = log_controls.get("integrator") or xml_controls.get("integrator")
    boundary = detect_boundary(csv_controls.get("Configuration"))
    if boundary is None:
        # The generated XML does not use the same human-readable names in all
        # historical cases.  A numeric Boundary=1 is the DBC source-case path.
        boundary = "DBC" if xml_controls.get("boundary_parameter") in {"1", 1} else None
    data_directory = None
    if attempt_dir is not None:
        data_directory = attempt_dir / "data"
    else:
        data_directory = find_file([directory / "data" / "Part_0000.bi4" for directory in run_directory_candidates(root, case_id)])
        data_directory = data_directory.parent if data_directory else None
    particle_files = sorted(data_directory.glob("Part_*.bi4")) if data_directory else []

    generated_exists = paths["generated_xml"].is_file() or paths["generated_out"].is_file()
    finished = bool(log_controls.get("finished"))
    attempt_completed = attempt_payload.get("status") == "completed" if attempt_payload else False
    run_csv_complete = bool(run_csv and csv_controls.get("PhysicalTime") and csv_controls.get("PartFiles"))
    data_complete = bool(particle_files)
    executed = (attempt_completed and run_csv_complete and data_complete) or (
        not attempt_payload and finished and run_csv_complete and data_complete
    )
    if executed:
        evidence_status = "executed"
        status_reason = "completed solver evidence: status/log, Run.csv and Part_*.bi4"
    elif generated_exists:
        evidence_status = "prepared_only"
        status_reason = "generated definition/GenCase evidence exists but no completed solver evidence"
    else:
        evidence_status = "missing"
        status_reason = "no generated definition or completed solver evidence found"

    target_matches = {
        "dp": planned_dp_m is not None and observed_dp is not None and abs(observed_dp - planned_dp_m) <= 1e-9,
        "time_max": planned_time_max_s is not None and time_max is not None and abs(time_max - planned_time_max_s) <= 0.011,
        "saved_cadence": planned_cadence_s is not None and actual_cadence is not None and abs(actual_cadence - planned_cadence_s) <= 5e-4,
        "integrator": planned_integrator is not None and integrator == planned_integrator,
        "boundary": planned_boundary is not None and boundary == planned_boundary,
    }
    target_compatible = evidence_status == "executed" and all(target_matches.values())

    evidence_files = [paths["source_definition"], paths["generated_xml"], paths["generated_log"], paths["generated_out"]]
    if attempt_dir is not None:
        evidence_files.extend([attempt_dir / "attempt.json", attempt_dir / "process.stdout.log", attempt_dir / "Run.csv"])
    else:
        evidence_files.extend([solver_log] if solver_log else [])
        evidence_files.extend([run_csv] if run_csv else [])
    evidence_files = [path for path in evidence_files if path is not None and path.is_file()]

    return {
        "case_id": case_id,
        "evidence_status": evidence_status,
        "status_reason": status_reason,
        "source_definition": relpath(paths["source_definition"], root),
        "generated_xml": relpath(paths["generated_xml"], root) if paths["generated_xml"].is_file() else None,
        "attempt_directory": relpath(attempt_dir, root) if attempt_dir else None,
        "attempt_id": attempt_payload.get("attempt_id") if attempt_payload else None,
        "run_evidence": {
            "attempt_record": relpath(attempt_dir / "attempt.json", root) if attempt_dir and (attempt_dir / "attempt.json").is_file() else None,
            "solver_log": relpath(solver_log, root) if solver_log else None,
            "run_csv": relpath(run_csv, root) if run_csv else None,
            "particle_file_count": len(particle_files),
            "particle_file_bytes": sum(path.stat().st_size for path in particle_files),
        },
        "observed": {
            "dp_m": observed_dp,
            "time_max_s": time_max,
            "time_end_s": physical_time,
            "saved_output_cadence_config_s": saved_cadence,
            "output_cadence_s": actual_cadence,
            "frames": frames,
            "steps": log_controls.get("steps") or integer(csv_controls.get("Steps")),
            "integrator": integrator,
            "step_algorithm": xml_controls.get("step_algorithm"),
            "verlet_steps": xml_controls.get("verlet_steps"),
            "boundary_formulation": boundary,
            "configuration": csv_controls.get("Configuration"),
        },
        "target": {
            "dp_m": planned_dp_m,
            "time_max_s": planned_time_max_s,
            "saved_output_cadence_s": planned_cadence_s,
            "integrator": planned_integrator,
            "boundary_formulation": planned_boundary,
        },
        "target_matches": target_matches,
        "target_compatible": target_compatible,
        "evidence_fingerprints": [file_fingerprint(path, root) for path in evidence_files],
    }


def compact_case_controls(case: dict[str, Any]) -> dict[str, Any]:
    observed = case.get("observed", {})
    return {
        "case_id": case["case_id"],
        "evidence_status": case["evidence_status"],
        "dp_m": observed.get("dp_m"),
        "time_max_s": observed.get("time_max_s"),
        "time_end_s": observed.get("time_end_s"),
        "output_cadence_s": observed.get("output_cadence_s"),
        "frames": observed.get("frames"),
        "integrator": observed.get("integrator"),
        "boundary_formulation": observed.get("boundary_formulation"),
        "steps": observed.get("steps"),
    }


def summarize_profile(name: str, cases: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    executed = [case for case in cases if case["evidence_status"] == "executed"]
    cadences = [case["observed"]["output_cadence_s"] for case in executed if case["observed"].get("output_cadence_s") is not None]
    tmax = [case["observed"]["time_max_s"] for case in executed if case["observed"].get("time_max_s") is not None]
    time_end = [case["observed"]["time_end_s"] for case in executed if case["observed"].get("time_end_s") is not None]
    integrators = sorted({case["observed"].get("integrator") for case in executed if case["observed"].get("integrator")})
    boundaries = sorted({case["observed"].get("boundary_formulation") for case in executed if case["observed"].get("boundary_formulation")})
    return {
        "name": name,
        "case_ids": [case["case_id"] for case in cases],
        "executed_count": len(executed),
        "cadence_s": {
            "median": statistics.median(cadences) if cadences else None,
            "min": min(cadences) if cadences else None,
            "max": max(cadences) if cadences else None,
        },
        "time_max_s": {"min": min(tmax) if tmax else None, "max": max(tmax) if tmax else None},
        "time_end_s": {"min": min(time_end) if time_end else None, "max": max(time_end) if time_end else None},
        "integrators": integrators,
        "boundary_formulations": boundaries,
        "cases": [compact_case_controls(case) for case in cases],
        "evidence_paths": sorted({fingerprint["path"] for case in cases for fingerprint in case.get("evidence_fingerprints", [])}),
    }


def w05_anchor_audit(root: Path, w05: dict[str, Any]) -> dict[str, Any]:
    campaign = root / CAMPAIGN_REL
    official_root = root / "vendor/official/DualSPHysics_v5.4"
    external_root = campaign / "artifacts/w05/external"
    definitions = {
        "F1": "vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml",
        "F3": "vendor/official/DualSPHysics_v5.4/examples/mdbc/03_Sloshing/CaseSloshingLR_Def.xml",
    }
    reference_paths = {
        "F1": [
            campaign / "artifacts/w05/external/SPHERIC_Test2.zip",
            external_root / "test2/test_case_2_exp_data.xls",
        ],
        "F3": [
            official_root / "examples/mdbc/03_Sloshing/EXP_Pressure_SPHERIC_Benchmark#10.txt",
        ],
    }
    result: dict[str, Any] = {}
    for family in FAMILIES:
        w05_cases = []
        for level in LEVELS:
            case_id = f"W05_{family}_{level}"
            source = definitions[family]
            w05_cases.append(execution_record(root, case_id, source))
        metrics = w05.get("external_validation", {}).get(family, {})
        compact_metrics: dict[str, Any] = {}
        if family == "F1":
            compact_metrics = {
                "H2_rmse_m": {level: metrics.get(level, {}).get("surface_elevation", {}).get("H2", {}).get("rmse_m") for level in LEVELS},
                "H4_rmse_m": {level: metrics.get(level, {}).get("surface_elevation", {}).get("H4", {}).get("rmse_m") for level in LEVELS},
                "P1_rmse_pa": {level: metrics.get(level, {}).get("pressure", {}).get("P1", {}).get("rmse_pa") for level in LEVELS},
            }
        else:
            compact_metrics = {
                "pressure_rmse_pa": {level: metrics.get(level, {}).get("pressure_rmse_pa") for level in LEVELS},
                "simulated_peak_pa": {level: metrics.get(level, {}).get("simulated_peak_pa") for level in LEVELS},
                "experimental_peak_pa": {level: metrics.get(level, {}).get("experimental_peak_pa") for level in LEVELS},
                "peak_time_error_s": {level: metrics.get(level, {}).get("peak_time_error_s") for level in LEVELS},
            }
        result[family] = {
            "official_test": "SPHERIC Test 02" if family == "F1" else "SPHERIC Test 10",
            "status": "anchor_present_partial_not_full_gold",
            "exact_official_physical_source_present": (official_root / Path(definitions[family]).relative_to("vendor/official/DualSPHysics_v5.4")).is_file(),
            "three_resolution_runs_completed": all(case["evidence_status"] == "executed" for case in w05_cases),
            "w05_case_ids": [case["case_id"] for case in w05_cases],
            "observed_controls": [compact_case_controls(case) for case in w05_cases],
            "reference_evidence": [file_fingerprint(path, root) for path in reference_paths[family]],
            "external_metrics_summary": compact_metrics,
            "full_gold_equivalence": False,
            "limitations": (
                "F1 H2/H4 are development-level anchors; H1/H3 and impact pressure are not Gold, and W05 tout=0.02 s undersamples the impulse."
                if family == "F1" else
                "F3 Test 10 pressure is impulsive and variable; the three resolutions do not jointly converge in full trace, peak and timing."
            ),
            "evidence_paths": [
                "campaigns/v0.1-candidate/W05-CONCLUSION.md",
                "campaigns/v0.1-candidate/w05-validation-anchors.json",
                "campaigns/v0.1-candidate/cases/w05/resolution-matrix.json",
                definitions[family],
            ],
        }
    return result


def r3_selected_case_ids(r3: dict[str, Any], family: str) -> set[str]:
    selected = set()
    for item in r3.get("run_results_new_backgrounds", []):
        case_id = item.get("case_id", "")
        if case_id.startswith(f"R3_{family}_") and "massmatched" in case_id:
            selected.add(case_id)
    return selected


def a1_matrix_audit(root: Path, r3: dict[str, Any]) -> dict[str, Any]:
    families: dict[str, Any] = {}
    all_cells: list[dict[str, Any]] = []
    for family in FAMILIES:
        family_cells: list[dict[str, Any]] = []
        for spec in BACKGROUND_SPECS[family]:
            for level in LEVELS:
                target_dp = R3_RESOLUTIONS[family][level]
                target_tmax = COMMON_A1_PROTOCOL[f"{family}_time_max_s"]
                selected_case_id = None
                if spec["r3_prefix"]:
                    selected_case_id = f"{spec['r3_prefix']}_{level}"
                candidate_ids = [selected_case_id] if selected_case_id else []
                candidate_ids.append(spec["legacy_case_id"] if level == "coarse" else None)
                candidate_ids = [case_id for case_id in candidate_ids if case_id]
                observed_case = None
                for case_id in candidate_ids:
                    record = execution_record(
                        root,
                        case_id,
                        spec["source_definition"],
                        planned_dp_m=target_dp,
                        planned_time_max_s=target_tmax,
                        planned_cadence_s=COMMON_A1_PROTOCOL["saved_output_cadence_s"],
                        planned_integrator=COMMON_A1_PROTOCOL["integrator"],
                        planned_boundary=COMMON_A1_PROTOCOL["boundary_formulation"],
                    )
                    if observed_case is None:
                        observed_case = record
                    if record["evidence_status"] == "executed" and record["target_compatible"]:
                        observed_case = record
                        break
                    if record["evidence_status"] == "executed" and observed_case["evidence_status"] != "executed":
                        observed_case = record
                if observed_case is None:
                    observed_case = {
                        "case_id": f"R4_{family}_{spec['background_id']}_{level}",
                        "evidence_status": "missing",
                        "status_reason": "no candidate case id supplied",
                        "source_definition": spec["source_definition"],
                        "observed": {
                            "dp_m": None,
                            "time_max_s": None,
                            "time_end_s": None,
                            "output_cadence_s": None,
                            "frames": None,
                            "integrator": None,
                            "boundary_formulation": None,
                        },
                        "target_matches": {key: False for key in ("dp", "time_max", "saved_cadence", "integrator", "boundary")},
                        "target_compatible": False,
                        "evidence_fingerprints": [],
                    }
                cell = {
                    "family": family,
                    "background_id": spec["background_id"],
                    "background_label": spec["label"],
                    "mechanism": spec["mechanism"],
                    "level": level,
                    "target_dp_m": target_dp,
                    "target_time_max_s": target_tmax,
                    "observed_case": observed_case,
                    "evidence_status": observed_case["evidence_status"],
                    "target_compatible": observed_case.get("target_compatible", False),
                    "selection_reason": spec["selection_reason"],
                }
                family_cells.append(cell)
                all_cells.append(cell)
        evidence_count = sum(cell["evidence_status"] == "executed" for cell in family_cells)
        target_count = sum(cell["target_compatible"] for cell in family_cells)
        families[family] = {
            "selected_backgrounds": [spec["background_id"] for spec in BACKGROUND_SPECS[family]],
            "cell_count": len(family_cells),
            "executed_evidence_cells": evidence_count,
            "missing_execution_cells": sum(cell["evidence_status"] == "missing" for cell in family_cells),
            "prepared_only_cells": sum(cell["evidence_status"] == "prepared_only" for cell in family_cells),
            "target_compatible_cells": target_count,
            "evidence_coverage": f"{evidence_count}/{len(family_cells)}",
            "target_compatible_coverage": f"{target_count}/{len(family_cells)}",
            "complete": evidence_count == len(family_cells),
            "common_protocol_complete": target_count == len(family_cells),
            "cells": family_cells,
            "alternate_backgrounds": ALTERNATE_BACKGROUNDS[family],
        }

    rejected_preflight = [
        item for item in r3.get("gencase_preflight", {}).get("rejected_common_dp_m", [])
    ]
    return {
        "scope": "three custom backgrounds by three resolutions; W05 official anchors remain a separate A0 reference",
        "families": families,
        "total_cells": len(all_cells),
        "total_executed_evidence_cells": sum(cell["evidence_status"] == "executed" for cell in all_cells),
        "total_target_compatible_cells": sum(cell["target_compatible"] for cell in all_cells),
        "r3_rejected_common_dp_preflight_m": rejected_preflight,
        "r3_preflight_not_counted_as_execution": True,
        "evidence_paths": [
            "campaigns/v0.1-candidate/r3-g2-f1-f3-matrix.json",
            "campaigns/v0.1-candidate/cases/r3-g2-f1-f3/matrix.json",
            "cases/manifest.json",
            "reports/runtime/prepare-summary.json",
            "reports/runtime/run-summary.json",
            "reports/runtime/quality-gates.json",
            "reports/runtime/trajectory-audit.json",
        ],
    }


def existing_profiles(root: Path, a1: dict[str, Any], w05: dict[str, Any], r3: dict[str, Any]) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    w05_cases = []
    for family in FAMILIES:
        for level in LEVELS:
            w05_cases.append(execution_record(
                root,
                f"W05_{family}_{level}",
                "vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml"
                if family == "F1" else
                "vendor/official/DualSPHysics_v5.4/examples/mdbc/03_Sloshing/CaseSloshingLR_Def.xml",
            ))
    profiles.append(summarize_profile("W05 official F1/F3 anchors", w05_cases, root))

    legacy_cases = []
    for family in FAMILIES:
        for spec in BACKGROUND_SPECS[family]:
            legacy_cases.append(execution_record(root, spec["legacy_case_id"], spec["source_definition"]))
    profiles.append(summarize_profile("legacy custom one-resolution probes", legacy_cases, root))

    r3_cases = []
    for family in FAMILIES:
        for spec in BACKGROUND_SPECS[family]:
            if not spec["r3_prefix"]:
                continue
            for level in LEVELS:
                r3_cases.append(execution_record(
                    root,
                    f"{spec['r3_prefix']}_{level}",
                    spec["source_definition"],
                ))
    profiles.append(summarize_profile("R3 selected custom three-resolution backgrounds", r3_cases, root))
    return profiles


def resolution_evidence(r3: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for family in FAMILIES:
        topology = r3.get("families", {}).get(family, {}).get("background_2_topology_numerical", {})
        results = topology.get("three_resolution_results", {})
        result[family] = {
            "background": topology.get("name"),
            "resolution_change": results.get("resolution_change", {}),
            "interpretation": topology.get("validation_scope"),
        }
    return result


def a2_audit(root: Path, profiles: list[dict[str, Any]], w05: dict[str, Any], r3: dict[str, Any]) -> dict[str, Any]:
    official = next(profile for profile in profiles if profile["name"].startswith("W05"))
    legacy = next(profile for profile in profiles if profile["name"].startswith("legacy"))
    r3_profile = next(profile for profile in profiles if profile["name"].startswith("R3"))
    return {
        "observed_profiles": profiles,
        "recommended_first_core_protocol": {
            "family": "F1",
            "case_id": "F1_obstacle_ladder",
            "spatial_schedule_m": R3_RESOLUTIONS["F1"],
            "integrator": "Verlet",
            "step_algorithm": 1,
            "verlet_steps": 40,
            "boundary_formulation": "DBC",
            "base_saved_output_cadence_s": 0.001,
            "time_window_s": [0.0, 1.5],
            "event_window_s": [0.35, 0.55],
            "event_window_basis": "SPHERIC Test 02 P1-P4 experimental first impulse maxima occur at about 0.415-0.459 s",
            "rationale": "Verlet/DBC is the common formulation of the selected custom ladder and R3; W05 mDBC/Symplectic remains the external A0 anchor, not a silently mixed control.",
        },
        "gaps": [
            {
                "id": "integrator_and_boundary_mismatch",
                "status": "open",
                "observed": {
                    "W05_anchor": {"integrator": official["integrators"], "boundary": official["boundary_formulations"]},
                    "legacy_custom": {"integrator": legacy["integrators"], "boundary": legacy["boundary_formulations"]},
                    "R3_custom": {"integrator": r3_profile["integrators"], "boundary": r3_profile["boundary_formulations"]},
                },
                "required": "one frozen protocol per A1 matrix; do not pool W05 mDBC/Symplectic with custom DBC/Verlet as if identical",
            },
            {
                "id": "event_output_cadence",
                "status": "open",
                "observed": {
                    "W05_F1_s": official["cadence_s"],
                    "legacy_custom_s": legacy["cadence_s"],
                    "R3_custom_s": r3_profile["cadence_s"],
                },
                "required": "0.001 s base output for the first F1 event window; R3 downsampling 0.01 to 0.05 s cannot recreate omitted solver states",
            },
            {
                "id": "time_window_alignment",
                "status": "open",
                "observed": {
                    "W05_F1_s": official["time_max_s"],
                    "legacy_custom_s": legacy["time_max_s"],
                    "R3_custom_s": r3_profile["time_max_s"],
                },
                "required": "first-core bounded window [0, 1.5] s plus fixed event scoring window [0.35, 0.55] s; 0-6 s is needed only for a full Test 02 trace claim",
            },
            {
                "id": "external_observable_scope",
                "status": "open",
                "observed": "W05 F1 has H1-H4 and P1-P8 metrics; R3 custom backgrounds have no compatible external observation",
                "required": "declare H2/H4 as limited macro anchors, add event peak/time/impulse for F1 pressure, and never transfer A0 truth to custom topologies",
            },
            {
                "id": "f1_resolution_stability",
                "status": "open",
                "observed": resolution_evidence(r3).get("F1"),
                "required": "top-two-resolution primary path/destination observable within the pre-registered 0.05 screening threshold; R3 twin currently reports TV 0.0714 and 0.1556",
            },
            {
                "id": "t2_destination_contract",
                "status": "open",
                "observed": {
                    "destination_spec_linked_count": 0,
                    "t2_contract_ready_count": 0,
                    "wall_visibility_true_count": 0,
                },
                "required": "explicit per-background destination regions, wall/open-face/rim policy, initial-mass denominator and closure evidence; this audit does not modify tracer or transport files",
            },
        ],
        "evidence_paths": [
            "campaigns/v0.1-candidate/W05-CONCLUSION.md",
            "campaigns/v0.1-candidate/R3-G2-F1-F3-CONCLUSION.md",
            "campaigns/v0.1-candidate/r3-g2-f1-f3-matrix.json",
            "campaigns/v0.1-candidate/R3-G2-TRANSPORT-SPEC-CONCLUSION.md",
            "campaigns/v0.1-candidate/r3-g2-transport-spec-audit.json",
        ],
    }


def planned_runs() -> list[dict[str, Any]]:
    runs = []
    for spec in BACKGROUND_SPECS["F1"]:
        for level in LEVELS:
            runs.append({
                "case_id": f"R4_F1_{spec['background_id']}_{level}",
                "family": "F1",
                "background_id": spec["background_id"],
                "level": level,
                "source_definition": spec["source_definition"],
                "dp_m": R3_RESOLUTIONS["F1"][level],
                "time_max_s": 1.5,
                "saved_output_cadence_s": 0.001,
                "integrator": "Verlet",
                "step_algorithm": 1,
                "verlet_steps": 40,
                "boundary_formulation": "DBC",
                "time_window_s": [0.0, 1.5],
                "event_window_s": [0.35, 0.55],
                "execute": False,
                "authorization": "blocked_until_R4_CORE_MOTHER_CASE_GATE",
                "purpose": "canonical common-control rerun; existing W05/R3/legacy evidence is not silently pooled",
                "required_observables": [
                    "numerical particle position/velocity trajectory",
                    "source-conditioned path occupancy or destination mass vector",
                    "F1 event pressure peak time, peak amplitude and impulse in the fixed event window",
                    "H2/H4 macro elevation when the official Test 02 geometry is selected",
                ],
            })
    return runs


def t2_contract_audit(root: Path) -> dict[str, Any]:
    path = root / CAMPAIGN_REL / "r3-g2-transport-spec-audit.json"
    payload = load_json(path)
    release = payload.get("release", {})
    return {
        "source": relpath(path, root),
        "formal_ready": bool(payload.get("formal_ready", False)),
        "destination_spec_linked_count": release.get("destination_spec_linked_count", 0),
        "destination_spec_valid_count": release.get("destination_spec_valid_count", 0),
        "wall_visibility_true_count": release.get("wall_visibility_true_count", 0),
        "t2_contract_ready_count": release.get("t2_contract_ready_count", 0),
        "open_blockers": payload.get("open_blockers", []),
    }


def decision_payload(a1: dict[str, Any], a2: dict[str, Any], t2: dict[str, Any], r3: dict[str, Any]) -> dict[str, Any]:
    f1 = a1["families"]["F1"]
    structural_evidence = f1["executed_evidence_cells"] > 0
    current_gate_pass = False
    return {
        "execution_authorization": "NO_GO",
        "execution_authorization_scope": "formal R4 core-mother-case run; no solver/GPU/CFD was started by this audit",
        "development_route": "GO_T1_ONLY" if structural_evidence else "NO_GO",
        "development_route_scope": "existing candidate numerical particle trajectories only; not a formal matrix or T2 benchmark",
        "formal_t1_t2_route": "GO_T1_T2" if current_gate_pass else "NO_GO",
        "current_gate_pass": current_gate_pass,
        "rules": {
            "GO_T1_T2": {
                "requires": [
                    "A0 official anchor present and its limited/full observable scope explicitly reported",
                    "A1 selected 3x3 custom matrix is 9/9 executed under one frozen control protocol",
                    "closed-domain identity/time/finite-state audit passes with zero unexplained numerical mass loss",
                    "top-two-resolution primary path/destination observable passes the pre-registered 0.05 screening threshold",
                    "A2 fixed 0.001 s event-capable output, fixed [0,1.5] s window and named F1 event observables are present",
                    "T2 destination specification and wall/open-face visibility/closure evidence are complete",
                ],
                "current_missing": [
                    "A1 F1 evidence is 5/9 and target-compatible is 3/9",
                    "A2 control/cadence/time-window conflicts are open",
                    "R3 F1 twin resolution TV is 0.0714 and 0.1556 against a 0.05 screen",
                    "T2 linked destination specifications and wall visibility are zero",
                ],
            },
            "GO_T1_ONLY": {
                "requires": [
                    "same numerical structural/resolution evidence as T1 portion of the gate",
                    "T2 may remain candidate-only, but the report must not label destination truth as accepted",
                ],
                "current": "available only as a development route over existing closed trajectories; the formal R4 9-cell gate is not passed",
            },
            "NO_GO": {
                "triggers": [
                    "missing/prepared-only cells in the formal 3x3 matrix",
                    "mixed integrator/boundary/cadence without a declared re-run boundary",
                    "identity/time/finite-state failure or unexplained numerical loss",
                    "resolution instability of the declared primary observable",
                ],
                "current": "formal execution is held until the single R4 gate is re-audited",
            },
        },
        "observed_resolution_evidence": resolution_evidence(r3),
        "t2_contract": t2,
        "acceptance_gate_id": "R4_CORE_MOTHER_CASE_GATE_v1",
    }


def acceptance_gate(a1: dict[str, Any], a2: dict[str, Any], t2: dict[str, Any], r3: dict[str, Any]) -> dict[str, Any]:
    f1 = a1["families"]["F1"]
    f1_tv = r3.get("families", {}).get("F1", {}).get("background_2_topology_numerical", {}).get("three_resolution_results", {}).get("resolution_change", {})
    conditions = [
        {
            "id": "A0_official_anchor",
            "required": True,
            "current_status": "partial_pass",
            "evidence": "W05 F1 Test 02 anchor exists at three resolutions; full Gold observable equivalence is explicitly false",
        },
        {
            "id": "A1_nine_executed_cells",
            "required": True,
            "current_status": "fail",
            "evidence": f"F1 selected ladder has {f1['executed_evidence_cells']}/9 executed-evidence cells and {f1['target_compatible_cells']}/9 target-compatible cells",
        },
        {
            "id": "A2_common_control_protocol",
            "required": True,
            "current_status": "fail",
            "evidence": "W05 is mDBC/Symplectic at 0.02 s, legacy custom is DBC/Verlet at 0.05 s, and R3 custom is DBC/Verlet at 0.01 s",
        },
        {
            "id": "A2_event_sampling_and_window",
            "required": True,
            "current_status": "fail",
            "evidence": "no existing F1 matrix has the proposed 0.001 s output and fixed [0.35,0.55] s event window",
        },
        {
            "id": "closed_trajectory_quality_and_resolution",
            "required": True,
            "current_status": "fail",
            "evidence": f"R3 F1 twin reports coarse-medium TV={f1_tv.get('coarse_to_medium_mass_fraction_tv')} and medium-fine TV={f1_tv.get('medium_to_fine_mass_fraction_tv')}; the 0.05 screening threshold is exceeded",
        },
        {
            "id": "T2_destination_closure",
            "required": True,
            "current_status": "fail",
            "evidence": f"linked destination specs={t2.get('destination_spec_linked_count')}, wall_visibility_true={t2.get('wall_visibility_true_count')}, T2-ready={t2.get('t2_contract_ready_count')}",
        },
    ]
    return {
        "gate_id": "R4_CORE_MOTHER_CASE_GATE_v1",
        "kind": "single_and_gate_with_tiered_decision",
        "status": "not_passed",
        "pass_rule": "All required conditions must pass. GO_T1_T2 additionally requires T2 destination closure; GO_T1_ONLY is allowed only for a numerically passing T1 portion and remains candidate-only for T2.",
        "screening_thresholds": {
            "top_two_resolution_primary_distribution_tv_max": 0.05,
            "event_sampling_cadence_s_max": 0.001,
            "time_window_s": [0.0, 1.5],
            "event_window_s": [0.35, 0.55],
            "numerical_loss_fraction_max": 0.0,
        },
        "conditions": conditions,
        "current_blocking_conditions": [condition["id"] for condition in conditions if condition["current_status"] == "fail"],
    }


def input_paths(root: Path, a1: dict[str, Any], profiles: list[dict[str, Any]]) -> list[Path]:
    paths = [
        root / CAMPAIGN_REL / "W05-CONCLUSION.md",
        root / CAMPAIGN_REL / "w05-validation-anchors.json",
        root / CAMPAIGN_REL / "R3-G2-F1-F3-CONCLUSION.md",
        root / CAMPAIGN_REL / "r3-g2-f1-f3-matrix.json",
        root / CAMPAIGN_REL / "cases/r3-g2-f1-f3/matrix.json",
        root / "cases/manifest.json",
        root / "reports/runtime/prepare-summary.json",
        root / "reports/runtime/run-summary.json",
        root / "reports/runtime/quality-gates.json",
        root / "reports/runtime/trajectory-audit.json",
        root / CAMPAIGN_REL / "r3-g2-transport-spec-audit.json",
    ]
    for family in FAMILIES:
        for spec in BACKGROUND_SPECS[family]:
            paths.append(root / spec["source_definition"])
    for profile in profiles:
        for relative in profile.get("evidence_paths", []):
            paths.append(root / relative)
    # Preserve first occurrence while keeping the manifest stable.
    return list(dict.fromkeys(path for path in paths if path.is_file()))


def build_audit(lab_root: Path | str = LAB) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    campaign = root / CAMPAIGN_REL
    w05 = load_json(campaign / "w05-validation-anchors.json")
    r3 = load_json(campaign / "r3-g2-f1-f3-matrix.json")
    a0 = w05_anchor_audit(root, w05)
    a1 = a1_matrix_audit(root, r3)
    profiles = existing_profiles(root, a1, w05, r3)
    a2 = a2_audit(root, profiles, w05, r3)
    t2 = t2_contract_audit(root)
    gate = acceptance_gate(a1, a2, t2, r3)
    decision = decision_payload(a1, a2, t2, r3)
    planned = planned_runs()
    audit_inputs = [file_fingerprint(path, root) for path in input_paths(root, a1, profiles)]
    return {
        "schema_version": 1,
        "audit_id": "R4_CORE_MOTHER_CASE_AUDIT",
        "audit_mode": "read_only_cpu_metadata_audit",
        "audit_revision": "r4-core-mother-case-audit-v1",
        "scope": "R4 reviewer package A/D mainline preparation for the first core mother case",
        "current_conclusion": {
            "first_core_mother_case": "F1_obstacle_ladder",
            "formal_execution_authorization": "NO_GO",
            "development_numerical_route": "GO_T1_ONLY",
            "go_t1_t2": False,
            "why_f1_first": [
                "W05 provides a three-resolution 3D SPHERIC Test 02 anchor.",
                "F1 custom cases are closed single-source 3D backgrounds, so the A0 reference and A1 candidates share dimensional semantics.",
                "F3 Test 10 is useful but W05 is 2D while the R3/custom F3 backgrounds are 3D, and its pressure acceptance remains partial.",
            ],
        },
        "read_only_policy": {
            "solver_invocations": 0,
            "gencase_invocations": 0,
            "gpu_queries": 0,
            "writes_performed_by_audit": [
                "campaigns/v0.1-candidate/r4-core-mother-case-audit.json",
                "campaigns/v0.1-candidate/R4-CORE-MOTHER-CASE-AUDIT.md",
            ],
            "protected_scopes": [
                "F6 files and reports",
                "tracer/passive-tracer files and reports",
                "G4 experiments and reports",
                "vendor/official source tree",
                "all pre-existing reports, work packages and run directories",
            ],
        },
        "A0_official_anchor_audit": a0,
        "A1_three_background_by_three_resolution_audit": a1,
        "A2_control_cadence_window_observable_audit": a2,
        "t2_contract_audit": t2,
        "acceptance_gate": gate,
        "decision": decision,
        "recommended_next_runs": {
            "count": len(planned),
            "maximum_allowed_by_request": 9,
            "all_execute_false": all(not item["execute"] for item in planned),
            "runs": planned,
        },
        "audit_inputs": audit_inputs,
        "evidence_interpretation": {
            "official_anchor": "W05 exact official physical source and external reference are present, but limited observable scope is authoritative.",
            "execution": "Only solver attempt/log/Run.csv/Part_*.bi4 evidence counts as executed; generated XML/GenCase output alone is prepared_only.",
            "resolution": "R3 rejected common dp preflights are reported but never counted as completed cells.",
            "cross_background": "No external Test 02/Test 10 result is transferred to a custom topology background.",
        },
    }


def cell_status(cell: dict[str, Any]) -> str:
    status = cell["evidence_status"]
    compatible = cell["target_compatible"]
    if status == "executed" and compatible:
        return "existing / target-compatible"
    if status == "executed":
        return "existing / control or dp mismatch"
    if status == "prepared_only":
        return "prepared only / not run"
    return "missing"


def render_markdown(payload: dict[str, Any]) -> str:
    current = payload["current_conclusion"]
    a0 = payload["A0_official_anchor_audit"]
    a1 = payload["A1_three_background_by_three_resolution_audit"]
    a2 = payload["A2_control_cadence_window_observable_audit"]
    gate = payload["acceptance_gate"]
    decision = payload["decision"]
    protocol = a2["recommended_first_core_protocol"]
    lines = [
        "# R4 core mother case audit",
        "",
        "状态：**只读资格审计；没有启动 GPU、CFD、GenCase 或 solver。**",
        "",
        f"首个候选：**`{current['first_core_mother_case']}`**。正式执行授权为 **`{current['formal_execution_authorization']}`**；现有开发级数值轨可继续 **`{current['development_numerical_route']}`**，但不能称为 T2 或正式物理接受。",
        "",
        "本审计新增两个独立产物，并只读取 W05/R3 证据、现有运行元数据和文本日志。它把官方 anchor、已执行、仅预检和缺失单元分开，不改既有报告或工作包。",
        "",
        "## 结论摘要",
        "",
        "- A0：SPHERIC Test 02（F1）和 Test 10（F3）均已有 W05 官方物理 anchor 与三分辨率运行；两者都是 `anchor_present_partial_not_full_gold`，不是 full-Gold 等价。",
        f"- A1：选定的 F1 三背景×三分辨率有 **{a1['families']['F1']['executed_evidence_cells']}/9 执行证据、{a1['families']['F1']['target_compatible_cells']}/9 目标控制兼容**；F3 同样为 **{a1['families']['F3']['executed_evidence_cells']}/9、{a1['families']['F3']['target_compatible_cells']}/9**。",
        "- A2：W05、legacy custom、R3 custom 的 integrator/boundary/cadence/time window 不同；当前没有可以直接作为共同主矩阵的 0.001 s F1 event-window 输出。",
        "- 单一 gate 当前不通过：形式化下一次运行保持 `NO_GO`；若只继续已有闭域数值轨，范围限定为 `GO_T1_ONLY` development candidate。",
        "",
        "## A0：官方 Test 02/10 是否已有等价 anchor",
        "",
        "“等价”在这里分成两层：官方物理定义/参考数据等价，以及所有观测量都可作 Gold 的科学等价。前者为是，后者为否。",
        "",
        "| family | official test | W05 三档 | 运行控制 | 判定 |",
        "|---|---|---|---|---|",
    ]
    for family in FAMILIES:
        row = a0[family]
        controls = row["observed_controls"]
        integrators = sorted({item.get("integrator") for item in controls if item.get("integrator")})
        boundaries = sorted({item.get("boundary_formulation") for item in controls if item.get("boundary_formulation")})
        cadences = sorted({round(item["output_cadence_s"], 6) for item in controls if item.get("output_cadence_s") is not None})
        windows = sorted({item.get("time_max_s") for item in controls if item.get("time_max_s") is not None})
        lines.append(f"| {family} | {row['official_test']} | {', '.join(row['w05_case_ids'])} | {integrators}/{boundaries}; cadence {cadences} s; tmax {windows} s | {row['status']} |")
    lines.extend([
        "",
        "W05 的直接限制必须保留：F1 只有 H2/H4 可作为开发级宏观锚点，H1/H3 与冲击压力不能被水位结果背书；F3 的压力峰值、峰时和全时程没有共同收敛。R3 也明确“不把新拓扑背景冒充等价 anchor”。",
        "",
        "## A1：三背景×三分辨率覆盖",
        "",
        "A1 的主矩阵是 custom same-family ladder；W05 官方 anchor 单独作为 A0 reference。F1 选 `plain_dam_break / center_obstacle / twin_obstacle_split_remerge`，F3 选 `impulse_slosh / baffled_exchange / transverse_slosh`。`F1_opposing_columns` 留作 alternate，因为它改变了初始流体源数量。",
        "",
        "| family | 背景 | coarse | medium | fine | 执行证据 | 目标兼容 |",
        "|---|---|---|---|---|---:|---:|",
    ])
    for family in FAMILIES:
        for background in a1["families"][family]["selected_backgrounds"]:
            cells = [cell for cell in a1["families"][family]["cells"] if cell["background_id"] == background]
            by_level = {cell["level"]: cell for cell in cells}
            statuses = [cell_status(by_level[level]) for level in LEVELS]
            executed = sum(cell["evidence_status"] == "executed" for cell in cells)
            compatible = sum(cell["target_compatible"] for cell in cells)
            lines.append(f"| {family} | `{background}` | {statuses[0]} | {statuses[1]} | {statuses[2]} | {executed}/3 | {compatible}/3 |")
    lines.extend([
        "",
        "要点：",
        "",
        "- legacy custom coarse case 有 solver/Run.csv/trajectory evidence，但使用约 0.04 m、0.05 s；它是已执行证据，不是 R3 mass-matched 目标 cell。",
        "- R3 twin/baffled 的 mass-matched 三档是当前唯一完整的 custom 3×1 background evidence；R3 把 `[0.04, 0.03, 0.02]` 的共同 dp 作为 GenCase-only preflight 拒绝，不能计作运行。",
        "- R3 F1 twin 的终态质量分布 TV 为 coarse→medium `0.0714`、medium→fine `0.1556`，因此当前 F1 topology evidence 不能直接通过 0.05 resolution screen；R3 F3 baffled 的 `0.00365/0.00500` 仅说明数值机制稳定，不能替代外部观测。",
        "",
        "## A2：cadence、integrator、time window、observable",
        "",
        "现有运行 profile：",
        "",
        "| profile | output cadence | tmax | integrator | boundary |",
        "|---|---|---|---|---|",
    ])
    for profile in a2["observed_profiles"]:
        cadence = profile["cadence_s"]
        lines.append(
            f"| {profile['name']} | {cadence['min']}–{cadence['max']} s (median {cadence['median']}) | {profile['time_max_s']['min']}–{profile['time_max_s']['max']} s | {profile['integrators']} | {profile['boundary_formulations']} |"
        )
    lines.extend([
        "",
        "首个 F1 core 的最小 bounded protocol：",
        "",
        f"- 空间档：`{protocol['spatial_schedule_m']}` m；integrator `{protocol['integrator']}` (`StepAlgorithm={protocol['step_algorithm']}`, `VerletSteps={protocol['verlet_steps']}`)，边界 `{protocol['boundary_formulation']}`。",
        f"- 全时窗：`{protocol['time_window_s'][0]}–{protocol['time_window_s'][1]} s`；基础保存 cadence：`{protocol['base_saved_output_cadence_s']} s`。固定 event window：`{protocol['event_window_s'][0]}–{protocol['event_window_s'][1]} s`，依据 Test 02 P1–P4 首次实验峰约 0.415–0.459 s。",
        "- T1 primary：身份保持、位置/速度轨迹、path occupancy；T2 primary：每背景显式 destination 的初始质量分母、分流/重汇质量向量和 closure。",
        "- 外部观测：只把官方 F1 的 H2/H4 作为 limited macro anchor；压力必须新增 peak time、peak amplitude、impulse，不能继续只看低频全时程 RMSE。",
        "",
        "未闭合缺口：",
        "",
    ])
    for gap in a2["gaps"]:
        lines.append(f"- `{gap['id']}`：{gap['required']}（现状：{gap['observed']}）。")
    lines.extend([
        "",
        "## 单一 acceptance gate 与三态判定",
        "",
        f"Gate：**`{gate['gate_id']}`**。它是一个 AND gate；所有 required condition 都通过才可接受。`GO_T1_T2` 还必须有 T2 destination closure；若 T1 数值部分通过而 T2 仍 candidate-only，最多只能 `GO_T1_ONLY`。",
        "",
        "| condition | 当前状态 |",
        "|---|---|",
    ])
    for condition in gate["conditions"]:
        lines.append(f"| `{condition['id']}` | **{condition['current_status']}** — {condition['evidence']} |")
    lines.extend([
        "",
        "判定所需证据：",
        "",
        "- `GO_T1_T2`：9/9 同一控制协议的不可变完成记录；闭域 identity/time/finite-state 与零 unexplained numerical loss；每背景 top-two resolution 的主 path/destination observable 通过预注册 0.05 screen；0.001 s event-capable cadence 与固定时窗；以及 destination/wall/open-face/质量 closure 完整。",
        "- `GO_T1_ONLY`：上述 T1 数值结构与分辨率证据通过，但 T2 仍只允许 candidate-only；不能把目的地标签或 wall visibility 说成已接受真值。当前已有开发轨可以继续这个范围，但形式化 R4 9-cell gate 尚未通过。",
        "- `NO_GO`：正式执行遇到 missing/prepared-only cell、混合控制未重跑、identity/time/finite-state 失败或主 observable 分辨率不稳定时触发。当前正式下一次运行保持 `NO_GO`，这是 gate hold，不是对所有开发轨的永久否定。",
        "",
        "## 建议下一次真正运行的最多 9 个工况",
        "",
        "以下 9 个是**规范化重跑清单**，全部 `execute=false`。因为已有 W05/R3/legacy 工况的 integrator、边界、dp、cadence 和 tmax 不一致，建议用同一 R4 protocol 重建 3×3；若资源需要缩减，最低填缺是 plain/center 的 medium/fine 四格，但那仍不能通过共同控制 gate。",
        "",
        "| # | case | background | level | dp (m) | tmax (s) | tout (s) | integrator |",
        "|---:|---|---|---|---:|---:|---:|---|",
    ])
    for index, run in enumerate(payload["recommended_next_runs"]["runs"], start=1):
        lines.append(f"| {index} | `{run['case_id']}` | `{run['background_id']}` | {run['level']} | {run['dp_m']} | {run['time_max_s']} | {run['saved_output_cadence_s']} | {run['integrator']} |")
    lines.extend([
        "",
        "每个工况还必须输出：Part trajectory、Run.csv/solver log、source-conditioned path/destination observable，以及固定 F1 event-window 的 pressure peak/time/impulse。执行前另需完成同 background 的 CPU GenCase mass/geometry preflight；本审计不执行该 preflight。",
        "",
        "## 可复核入口",
        "",
        "- `campaigns/v0.1-candidate/W05-CONCLUSION.md` 与 `w05-validation-anchors.json`：官方 F1/F3 anchor 及限制。",
        "- `campaigns/v0.1-candidate/R3-G2-F1-F3-CONCLUSION.md` 与 `r3-g2-f1-f3-matrix.json`：R3 两背景×三分辨率、cadence 下采样、TV 和 blocker。",
        "- `reports/runtime/run-summary.json`、`quality-gates.json`、`trajectory-audit.json`：legacy custom 执行/质量/轨迹证据。",
        "- `campaigns/v0.1-candidate/r3-g2-transport-spec-audit.json`：当前 T2 linked destination 与 wall visibility 为 0 的契约证据。",
        "",
        "审计产物本身只允许写入：`scripts/r4_core_mother_case_audit.py`、`r4-core-mother-case-audit.json`、`R4-CORE-MOTHER-CASE-AUDIT.md` 和 `test_r4_core_mother_case_*.py`。",
        "",
    ])
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], json_path: Path = DEFAULT_JSON, md_path: Path = DEFAULT_MD) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    md_path.write_text(render_markdown(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB, help="lab root; defaults to this script's parent")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--md-out", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.lab_root.resolve()
    payload = build_audit(root)
    json_path = args.json_out.resolve() if args.json_out else root / DEFAULT_JSON.relative_to(LAB)
    md_path = args.md_out.resolve() if args.md_out else root / DEFAULT_MD.relative_to(LAB)
    write_outputs(payload, json_path, md_path)
    print(json.dumps({
        "audit_id": payload["audit_id"],
        "formal_execution_authorization": payload["current_conclusion"]["formal_execution_authorization"],
        "development_numerical_route": payload["current_conclusion"]["development_numerical_route"],
        "F1_evidence_cells": payload["A1_three_background_by_three_resolution_audit"]["families"]["F1"]["evidence_coverage"],
        "F1_target_compatible_cells": payload["A1_three_background_by_three_resolution_audit"]["families"]["F1"]["target_compatible_coverage"],
        "F3_evidence_cells": payload["A1_three_background_by_three_resolution_audit"]["families"]["F3"]["evidence_coverage"],
        "next_run_count": payload["recommended_next_runs"]["count"],
        "solver_invocations": payload["read_only_policy"]["solver_invocations"],
        "gencase_invocations": payload["read_only_policy"]["gencase_invocations"],
        "gpu_queries": payload["read_only_policy"]["gpu_queries"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build an independent, read-only L2-R F6 blocker contract.

The audit deliberately does not import the C3R controller, update the L2-R
resume state, launch GenCase/DualSPHysics, or edit an existing report.  It
reads the retained C3R/F6 artifacts and the vendored v5.4 source/documentation
and emits a new contract either to stdout or to an explicitly supplied path.

The contract keeps three questions separate:

* Are the normals complete for the intended F6 floating route and for the
  fixed-body mDBC controls?
* Does an existing fixed-box DBC/mDBC force-gauge comparison close the force
  contract, or is it only a diagnostic control?
* What does the Chrono warning mean for the two allowed follow-up routes
  (fixed-body hydrostatics versus a separate dynamic floating-body run)?

No return-code-0 solver run is treated as physical acceptance.  In
particular, a zero-normal diagnostic with changed wall geometry is retained as
diagnostic evidence and is never promoted as a nominal repair.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
REPO = LAB.parent
SCHEMA = "l2.f6r.blocker_contract.v1"
BLOCKER_ID = "F6_MDBC_NORMALS_CHRONO_FORCE_GAUGE_CONTRACT"
ZERO_NORMAL_TOLERANCE_M = 1.0e-12
FORCE_STABILITY_FRACTION = 0.05

F6_ROOT = LAB / "campaigns" / "v0.1-candidate"
L2_RESUME = LAB / "campaigns" / "l2-multifamily" / "resume-c6b28c8"

DEFAULT_PATHS = {
    "c3r": L2_RESUME / "c3r-evidence.json",
    "preflight": F6_ROOT / "r3-g2-f6-mdbc-preflight.json",
    "zero_normal": F6_ROOT / "r3-g2-f6-mdbc-zero-normal-preflight.json",
    "static": F6_ROOT / "r3-g2-f6-static-buoyancy.json",
    "wall": F6_ROOT / "r3-f6-wall-ghost-geometry.json",
    "test14": F6_ROOT / "r3-g2-f6-test14.json",
    "dbc_force": F6_ROOT / "cases" / "r3-fixed-box-force-gauge" / "fixed-box-force-gauge-report.json",
    "mdbc_force": F6_ROOT / "cases" / "r3-fixed-box-force-gauge" / "mdbc-fixed-box-force-gauge-report.json",
    "runtime_normals": F6_ROOT / "cases" / "r3-fixed-box-force-gauge" / "r4-mdbc-runtime-zero-normal-audit.json",
    "f6_mdbc_definition": F6_ROOT / "cases" / "r3-g2-f6-mdbc-preflight" / "R3_F6_mdbc_preflight_neg074_coarse_Def.xml",
    "f6_dbc_definition": F6_ROOT / "cases" / "r3-g2-f6-test14" / "R3_F6_test14_float1_neg074_coarse_Def.xml",
    "fixed_mdbc_definition": F6_ROOT / "cases" / "r3-fixed-box-force-gauge" / "fixed_box_mdbc_canonical_Def.xml",
    "policy": F6_ROOT / "R3-E0-E1-EXECUTION-POLICY.md",
    "hydrostatic": F6_ROOT / "cases" / "r3-f6-fixed-hydrostatic" / "r3-f6-fixed-hydrostatic.md",
}


SOURCE_MARKERS: dict[str, tuple[str, ...]] = {
    "vendor/official/DualSPHysics_v5.4/src/source/JPartsLoad4.cpp": (
        "BoundNor",
        "Checks boundary normals data in file",
    ),
    "vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp": (
        "UseNormals",
        "CfgInit_NormalsGhost.vtk",
        "fixed or moving boundary particles without normal data",
    ),
    "vendor/official/DualSPHysics_v5.4/src/source/JSphCpu_mdbc.cpp": (
        "BoundNor",
        "ghost",
    ),
    "vendor/official/DualSPHysics_v5.4/src/source/JDsGaugeSystem.cpp": (
        "AddGaugeForce",
        "mkbound",
        "fixed or moving",
    ),
    "vendor/official/DualSPHysics_v5.4/src/source/JDsGaugeItem.cpp": (
        "Saves Force data measured from boundary particles",
        "selected fixed or moving particles",
    ),
    "vendor/official/DualSPHysics_v5.4/src/source/JDsGauge_ker.cu": (
        "Interaction_GaugeForce",
        "fluid",
    ),
    "vendor/official/DualSPHysics_v5.4/src/source/JChronoObjects.cpp": (
        "UseCollision",
        "bodyfloating",
        "bodyfixed",
    ),
    "vendor/official/DualSPHysics_v5.4/src/source/JChronoData.h": (
        "SetUseCollision",
        "Collision",
    ),
    "vendor/official/DualSPHysics_v5.4/examples/mdbc/08_FloatingWaves/CaseFloatingWaves_Def.xml": (
        "GeometryForNormals",
        "Boundary",
        "RigidAlgorithm",
    ),
    "vendor/official/DualSPHysics_v5.4/examples/mdbc/09_FloatingDuck/CaseDuckling_Def.xml": (
        "GeometryForNormals",
        "Boundary",
        "RigidAlgorithm",
    ),
}

DOCUMENT_MARKERS: dict[str, tuple[str, ...]] = {
    "R3-E0-E1-EXECUTION-POLICY.md": (
        "The body is fixed during E1",
        "Chrono integration is a separate follow-up",
        "no unexplained zero normals",
    ),
    "cases/r3-f6-fixed-hydrostatic/r3-f6-fixed-hydrostatic.md": (
        "normal completeness",
        "fixed-body semantics",
        "Chrono isolation",
        "force measurement path",
    ),
    "R3-G2-F6-MDBC-PREFLIGHT.md": (
        "zero boundary normals",
        "Chrono",
        "Finished execution (code=0)",
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO.resolve()))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_evidence(path: Path, *, required: bool = False) -> dict[str, Any]:
    path = Path(path)
    exists = path.is_file()
    result: dict[str, Any] = {
        "path": repo_relative(path),
        "absolute_path": str(path.resolve()),
        "exists": exists,
        "required": required,
    }
    if exists:
        result.update({"bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return result


def read_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = file_evidence(path, required=True)
    if not path.is_file():
        evidence["error"] = "missing_file"
        return {}, evidence
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        evidence["error"] = f"{error.__class__.__name__}"
        return {}, evidence
    if not isinstance(payload, dict):
        evidence["error"] = "json_root_is_not_object"
        return {}, evidence
    return payload, evidence


def nested(payload: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(payload, dict):
            return None
        payload = payload.get(key)
    return payload


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _git_head() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def _marker_evidence(path: Path, markers: Iterable[str], *, required: bool) -> dict[str, Any]:
    result = file_evidence(path, required=required)
    found: dict[str, int | None] = {}
    if path.is_file():
        text = path.read_text(errors="replace")
        lines = text.splitlines()
        for marker in markers:
            found[marker] = next(
                (index for index, line in enumerate(lines, start=1) if marker.lower() in line.lower()),
                None,
            )
    else:
        found = {marker: None for marker in markers}
    result["markers"] = found
    result["all_markers_present"] = bool(found) and all(line is not None for line in found.values())
    return result


def audit_source_and_documentation() -> dict[str, Any]:
    source_records = []
    for relative, markers in SOURCE_MARKERS.items():
        source_records.append(_marker_evidence(LAB / relative, markers, required=True))
    document_records = []
    for relative, markers in DOCUMENT_MARKERS.items():
        document_records.append(_marker_evidence(F6_ROOT / relative, markers, required=True))
    all_present = all(item["exists"] and item["all_markers_present"] for item in source_records + document_records)
    return {
        "status": "complete" if all_present else "incomplete",
        "source_files": source_records,
        "documents": document_records,
        "interpretation": {
            "normal_storage_and_ghost": "JPartsLoad4/JSph/JSphCpu_mdbc evidence binds BoundNor, zero-normal accounting and the ghost construction.",
            "force_gauge_semantics": "JGauge force is configured by mkbound and is a fluid-pressure interaction on fixed or moving boundary particles; it is not total body/support force.",
            "chrono_semantics": "JChronoObjects exposes collision and fixed/floating body paths; official floating mDBC examples expose Boundary=2 and a RigidAlgorithm parameter.",
        },
    }


def parse_definition(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence": file_evidence(path, required=True),
        "parse_error": None,
        "boundary": None,
        "rigid_algorithm": None,
        "has_floatings_container": False,
        "floating_count": 0,
        "bodyfixed_count": 0,
        "bodymoving_count": 0,
        "bodyfloating_count": 0,
        "normal_section_present": False,
        "normal_geometry_file": None,
        "force_gauges": [],
    }
    if not path.is_file():
        result["parse_error"] = "missing_file"
        return result
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        result["parse_error"] = error.__class__.__name__
        return result
    parameters = {
        element.attrib.get("key"): element.attrib.get("value")
        for element in root.findall(".//parameter")
        if element.attrib.get("key")
    }
    result["boundary"] = _as_int(parameters.get("Boundary"))
    result["rigid_algorithm"] = _as_int(parameters.get("RigidAlgorithm"))
    floatings = root.find(".//floatings")
    result["has_floatings_container"] = floatings is not None
    result["floating_count"] = len(root.findall(".//floatings/floating"))
    result["bodyfixed_count"] = len(root.findall(".//chrono/bodyfixed")) + len(root.findall(".//bodyfixed"))
    result["bodymoving_count"] = len(root.findall(".//chrono/bodymoving")) + len(root.findall(".//bodymoving"))
    result["bodyfloating_count"] = len(root.findall(".//chrono/bodyfloating")) + len(root.findall(".//bodyfloating"))
    normals = root.find(".//normals")
    result["normal_section_present"] = normals is not None
    normal_geometry = root.find(".//normals/norgeometry/geometryfile")
    if normal_geometry is not None:
        result["normal_geometry_file"] = normal_geometry.attrib.get("file")
    for force in root.findall(".//force"):
        target = force.find("./target")
        result["force_gauges"].append({
            "name": force.attrib.get("name"),
            "mkbound": target.attrib.get("mkbound") if target is not None else None,
        })
    return result


def _normal_row(
    *,
    label: str,
    total: Any,
    zero: Any,
    fixed_zero: Any,
    floating_zero: Any,
    source: str,
    completeness: Any = None,
    finite: Any = None,
    positive_sizes: Any = None,
) -> dict[str, Any]:
    total_i = _as_int(total)
    zero_i = _as_int(zero)
    fixed_i = _as_int(fixed_zero)
    floating_i = _as_int(floating_zero)
    return {
        "label": label,
        "source": source,
        "total": total_i,
        "zero_count": zero_i,
        "zero_fraction": (zero_i / total_i) if total_i and zero_i is not None else None,
        "fixed_or_moving_zero_count": fixed_i,
        "floating_zero_count": floating_i,
        "reported_complete": _bool(completeness),
        "finite": _bool(finite),
        "positive_sizes": _bool(positive_sizes),
        "zero_free": zero_i == 0 if zero_i is not None else False,
    }


def audit_normals(
    *,
    preflight: dict[str, Any],
    zero_normal: dict[str, Any],
    mdbc_force: dict[str, Any],
    runtime_normals: dict[str, Any],
) -> dict[str, Any]:
    normal = preflight.get("normal_completeness", {})
    gencase = nested(preflight, "gencase", "normal_data") or {}
    solver = nested(preflight, "solver", "normal_data") or {}
    f6_row = _normal_row(
        label="F6 floating mDBC coarse preflight",
        total=_first_not_none(normal.get("boundnor_array_count"), normal.get("gencase_boundary_count"), gencase.get("boundary_count")),
        zero=_first_not_none(normal.get("boundnor_direct_zero_count"), normal.get("gencase_zero_count"), gencase.get("zero_count")),
        fixed_zero=_first_not_none(normal.get("boundnor_direct_fixed_zero_count"), normal.get("solver_fixed_or_moving_zero_count"), solver.get("fixed_or_moving_zero_count")),
        floating_zero=_first_not_none(normal.get("boundnor_direct_floating_zero_count"), normal.get("solver_floating_zero_count"), solver.get("floating_zero_count")),
        source="r3-g2-f6-mdbc-preflight.json",
        completeness=normal.get("complete_for_all_boundary_particles"),
    )
    f6_row.update({
        "effective_boundary": solver.get("effective_boundary"),
        "solver_finished_code_0": solver.get("solver_finished_code_0"),
        "normal_warning_present": solver.get("normal_warning_present"),
        "ghost_path_reported": solver.get("ghost_path_reported"),
    })

    diagnostic_rows: list[dict[str, Any]] = []
    for item in zero_normal.get("results", []):
        record = item.get("record", {}) if isinstance(item, dict) else {}
        gencase_item = nested(item, "gencase", "normal_data") or {}
        solver_item = nested(item, "solver", "normal_data") or {}
        normal_item = item.get("normal_completeness", {}) if isinstance(item, dict) else {}
        zero_count = normal_item.get("boundnor_zero_count")
        zero_count = _first_not_none(zero_count, gencase_item.get("zero_count"))
        diagnostic_rows.append(_normal_row(
            label=record.get("variant_id") or record.get("case_id") or "unnamed zero-normal variant",
            total=_first_not_none(normal_item.get("boundnor_array_count"), gencase_item.get("boundary_count")),
            zero=zero_count,
            fixed_zero=_first_not_none(normal_item.get("boundnor_fixed_zero_count"), solver_item.get("fixed_or_moving_zero_count")),
            floating_zero=_first_not_none(normal_item.get("boundnor_floating_zero_count"), solver_item.get("floating_zero_count")),
            source="r3-g2-f6-mdbc-zero-normal-preflight.json",
            completeness=normal_item.get("complete_for_all_boundary_particles"),
        ))
    baseline = next((row for row in diagnostic_rows if "baseline" in row["label"].lower()), None)
    radius_offset_candidates = [
        row for row in diagnostic_rows
        if "radius" in row["label"].lower() or "minus" in row["label"].lower() or "plus" in row["label"].lower()
    ]

    fixed_rows: list[dict[str, Any]] = []
    for case in mdbc_force.get("cases", []):
        audit = case.get("normal_ghost_audit", {})
        checks = audit.get("checks", {})
        fixed_rows.append({
            "case_id": case.get("case_id"),
            "run_label": case.get("run_label"),
            "normal_count": audit.get("normal_count"),
            "zero_count": audit.get("normal_zero_count"),
            "ghost_zero_count": audit.get("ghost_zero_count"),
            "normal_size_nonpositive_count": audit.get("normal_size_nonpositive_count"),
            "arrays_finite": checks.get("arrays_finite"),
            "ghost_vector_is_double_normal": checks.get("ghost_vector_is_double_normal"),
            "ghost_size_is_double_normal_size": checks.get("ghost_size_is_double_normal_size"),
            "no_zero_normals": checks.get("no_zero_normals"),
            "normal_sizes_positive": checks.get("normal_sizes_positive"),
            "gate": audit.get("gate"),
            "source": "mdbc-fixed-box-force-gauge-report.json",
        })
    runtime_summary = runtime_normals.get("summary", {})
    runtime_rows = {
        "zero_free_all_cases": runtime_summary.get("runtime_zero_free_all_cases"),
        "zero_counts_by_resolution": runtime_summary.get("runtime_zero_normal_counts_by_resolution", {}),
        "overall_evidence_status": runtime_summary.get("overall_evidence_status"),
        "threshold_m": nested(runtime_normals, "thresholds", "zero_normal_norm_lte_m"),
    }

    checks = {
        "f6_floating_normals_complete": (
            f6_row["reported_complete"] is True
            and f6_row["zero_free"]
            and f6_row["fixed_or_moving_zero_count"] == 0
        ),
        "f6_nominal_preflight_zero_free": f6_row["zero_free"],
        "fixed_box_mdbc_controls_zero_free": bool(fixed_rows) and all(
            row["zero_count"] == 0 and row["no_zero_normals"] is True and row["normal_sizes_positive"] is True
            for row in fixed_rows
        ),
        "runtime_fixed_box_zero_free": runtime_rows["zero_free_all_cases"] is True,
        "radius_offset_is_not_promoted": bool(radius_offset_candidates) or baseline is None,
    }
    return {
        "status": "closed" if all(checks.values()) else "blocked",
        "gate": all(checks.values()),
        "tolerance_m": ZERO_NORMAL_TOLERANCE_M,
        "f6_target": f6_row,
        "candidate_diagnostics": {
            "baseline": baseline,
            "radius_offset_candidates": radius_offset_candidates,
            "promotion_policy": "A changed tank-normal radius is diagnostic only; it cannot close the nominal F6 geometry gate.",
        },
        "fixed_box_controls": fixed_rows,
        "runtime_fixed_box_audit": runtime_rows,
        "checks": checks,
        "conclusion": (
            "F6 normal completeness is closed."
            if all(checks.values())
            else "F6 normals remain blocked: the retained floating preflight has non-zero BoundNor gaps and the fixed-box runtime controls also retain thresholded zero normals."
        ),
        "release_conditions": [
            "For the nominal transformed Float1 geometry, serialize BoundNor with zero fixed/moving normals at every intended resolution.",
            "Show finite, strictly positive normal sizes and a complete boundary-to-ghost mapping; a solver return code of 0 is insufficient.",
            "Repeat the zero-normal audit after runtime initialization and retain the raw normal/ghost artifacts.",
            "Do not use inward-radius candidate results as a nominal repair unless the changed wall geometry is separately revalidated and explicitly accepted.",
        ],
    }


def _resolve_report_path(report_path: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return report_path.parent / candidate


def _read_force_csv(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file(), "errors": []}
    if not path.is_file():
        result["errors"].append("missing_file")
        return result
    try:
        first_line = path.read_text(errors="replace").splitlines()[0]
        delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream, delimiter=delimiter)
            rows = list(reader)
    except (OSError, IndexError, csv.Error) as error:
        result["errors"].append(error.__class__.__name__)
        return result
    required = ("time [s]", "forcez [N]")
    if not reader.fieldnames or not all(name in reader.fieldnames for name in required):
        result["errors"].append("missing_required_columns")
        result["columns"] = reader.fieldnames or []
        return result
    numeric_rows: list[dict[str, float]] = []
    for index, row in enumerate(rows, start=2):
        converted: dict[str, float] = {}
        for key in reader.fieldnames:
            try:
                value = float(row[key])
            except (TypeError, ValueError):
                result["errors"].append(f"non_numeric:{key}:line{index}")
                break
            converted[key] = value
        else:
            numeric_rows.append(converted)
    finite = all(math.isfinite(value) for row in numeric_rows for value in row.values())
    result.update({
        "columns": reader.fieldnames or [],
        "sample_count": len(numeric_rows),
        "finite": finite,
        "sha256": sha256_file(path),
    })
    if not numeric_rows:
        result["errors"].append("no_numeric_rows")
        return result
    times = [row["time [s]"] for row in numeric_rows]
    result["time_min_s"] = min(times)
    result["time_max_s"] = max(times)
    end = result["time_max_s"]
    start = end - 0.20
    window = [row for row in numeric_rows if row["time [s]"] >= start - 1.0e-12]
    forcez = [row["forcez [N]"] for row in window]
    forcex = [row.get("forcex [N]", math.nan) for row in window]
    forcey = [row.get("forcey [N]", math.nan) for row in window]
    if forcez:
        mean = sum(forcez) / len(forcez)
        variance = sum((value - mean) ** 2 for value in forcez) / len(forcez)
        result["last_0p20s"] = {
            "start_s": start,
            "end_s": end,
            "samples": len(forcez),
            "forcez_mean_n": mean,
            "forcez_std_n": math.sqrt(variance),
            "forcez_min_n": min(forcez),
            "forcez_max_n": max(forcez),
            "forcex_mean_n": sum(forcex) / len(forcex) if all(math.isfinite(x) for x in forcex) else None,
            "forcey_mean_n": sum(forcey) / len(forcey) if all(math.isfinite(x) for x in forcey) else None,
        }
    return result


def _find_case(cases: Any, *needles: str) -> dict[str, Any] | None:
    if not isinstance(cases, list):
        return None
    for case in cases:
        if not isinstance(case, dict):
            continue
        haystack = " ".join(str(case.get(key, "")) for key in ("case_id", "run_label", "label")).lower()
        if all(needle.lower() in haystack for needle in needles):
            return case
    return None


def _force_case_summary(report_path: Path, case: dict[str, Any] | None, reference: float | None) -> dict[str, Any]:
    if case is None:
        return {"present": False, "errors": ["case_not_found"]}
    gauge = case.get("force_gauge", {})
    csv_path = _resolve_report_path(report_path, gauge.get("signed_csv"))
    csv_audit = _read_force_csv(csv_path) if csv_path else {"exists": False, "errors": ["missing_signed_csv_path"]}
    window = csv_audit.get("last_0p20s", {})
    mean = _as_float(window.get("forcez_mean_n"))
    std = _as_float(window.get("forcez_std_n"))
    ref = reference or 78.48
    return {
        "present": True,
        "case_id": case.get("case_id"),
        "run_label": case.get("run_label"),
        "acceptance_status": case.get("acceptance_status"),
        "force_gauge": {
            "csv": file_evidence(csv_path, required=True) if csv_path else None,
            "csv_audit": csv_audit,
            "source_semantics": case.get("force_gauge", {}).get("header"),
        },
        "fixed_body_mapping": case.get("fixed_body_mapping_gate", {}),
        "normal_ghost_audit": {
            "zero_count": nested(case, "normal_ghost_audit", "normal_zero_count"),
            "gate": nested(case, "normal_ghost_audit", "gate"),
            "no_zero_normals": nested(case, "normal_ghost_audit", "checks", "no_zero_normals"),
        },
        "screen": case.get("screen", {}),
        "reference_fz_n": ref,
        "last_0p20s": window,
        "reference_error_percent": abs(mean - ref) / ref * 100.0 if mean is not None and ref else None,
        "finite_trace": csv_audit.get("finite") is True and not csv_audit.get("errors"),
        "stable_force": std is not None and std <= ref * FORCE_STABILITY_FRACTION,
    }


def audit_force_gauge_comparison(
    *,
    dbc_report: dict[str, Any],
    dbc_report_path: Path,
    mdbc_report: dict[str, Any],
    mdbc_report_path: Path,
    f6_reports: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    dbc_ref = _as_float(nested(dbc_report, "analytical_reference", "fz_n"))
    mdbc_ref = _as_float(nested(mdbc_report, "analytical_reference", "fz_n"))
    reference = dbc_ref if dbc_ref is not None else mdbc_ref
    dbc_case = _find_case(dbc_report.get("cases"), "dbc", "gravity")
    mdbc_cases = [
        case for case in mdbc_report.get("cases", [])
        if isinstance(case, dict) and "mdbc" in str(case.get("case_id", "")).lower()
    ]
    dbc = _force_case_summary(dbc_report_path, dbc_case, reference)
    mdbc = [_force_case_summary(mdbc_report_path, case, reference) for case in mdbc_cases]
    mdbc_with_trace = [item for item in mdbc if item.get("present") and item.get("finite_trace")]
    pair_reference_match = dbc_ref is not None and mdbc_ref is not None and abs(dbc_ref - mdbc_ref) <= 1.0e-6
    pair_semantics_match = bool(dbc_report.get("source_semantics")) and bool(mdbc_report.get("source_semantics"))
    pair_has_fixed_mapping = bool(dbc.get("fixed_body_mapping", {}).get("source_mkbound_maps_to_fixed")) and all(
        bool(item.get("fixed_body_mapping", {}).get("source_mkbound_maps_to_one_fixed_row")) for item in mdbc
    )
    mdbc_no_zero = bool(mdbc_with_trace) and all(
        item.get("normal_ghost_audit", {}).get("no_zero_normals") is True for item in mdbc_with_trace
    )
    mdbc_stable = bool(mdbc_with_trace) and all(item.get("stable_force") is True for item in mdbc_with_trace)
    # The fixed-box reports prove a bounded control path.  They are not the
    # transformed Float1 F6 target, so they cannot close F6 by themselves.
    f6_target_cases = []
    for report in f6_reports:
        for case in report.get("cases", []) if isinstance(report.get("cases"), list) else []:
            if isinstance(case, dict) and "f6" in str(case.get("case_id", "")).lower() and "force_gauge" in case:
                f6_target_cases.append(case.get("case_id"))
        if "force_gauge" in report and report.get("family") == "F6":
            f6_target_cases.append(report.get("case_id", "F6"))
    checks = {
        "fixed_box_dbc_and_mdbc_pair_present": dbc.get("present") is True and bool(mdbc_with_trace),
        "analytical_reference_matches": pair_reference_match,
        "gauge_source_semantics_recorded": pair_semantics_match,
        "fixed_body_mapping_recorded": pair_has_fixed_mapping,
        "all_control_traces_finite": dbc.get("finite_trace") is True and all(item.get("finite_trace") for item in mdbc_with_trace),
        "mdbc_control_zero_normal_gate": mdbc_no_zero,
        "mdbc_control_stable_force_gate": mdbc_stable,
        "transformed_f6_force_gauge_present": bool(f6_target_cases),
    }
    return {
        "status": "closed" if all(checks.values()) else "blocked",
        "gate": all(checks.values()),
        "reference_fz_n": reference,
        "semantics": "signed pressure interaction on selected fixed/moving boundary particles; excludes gravity, support reaction and viscosity",
        "fixed_box_control": {
            "dbc": dbc,
            "mdbc": mdbc,
            "pair_reference_match": pair_reference_match,
            "pair_semantics_match": pair_semantics_match,
            "interpretation": "The paired fixed-box traces are a useful control comparison, but their candidate status and normal/force failures prevent physical acceptance.",
        },
        "f6_target": {
            "force_gauge_case_ids": f6_target_cases,
            "present": bool(f6_target_cases),
            "interpretation": "No force-gauge trace for the transformed Float1 F6 target is retained in the audited F6 reports.",
        },
        "checks": checks,
        "release_conditions": [
            "Materialize a fixed-body transformed-Float1 XML with an explicit force gauge whose mkbound maps only to the intended fixed body.",
            "Run matched DBC control and mDBC candidate cases at the same geometry, fluid, gravity, time horizon and output cadence.",
            "Retain finite multi-window Fx/Fy/Fz traces, displacement/volume reference and raw attempt provenance.",
            "Require the F6 mDBC normal gate, no unexplained exclusion/penetration, stable late-window force and the declared rho*g*V_sub comparison before any acceptance claim.",
        ],
    }


def audit_chrono_contract(
    *,
    preflight: dict[str, Any],
    f6_mdbc_definition: dict[str, Any],
    f6_dbc_definition: dict[str, Any],
    fixed_mdbc_definition: dict[str, Any],
    hydrostatic_document: Path,
    policy_document: Path | None = None,
) -> dict[str, Any]:
    solver = nested(preflight, "solver", "normal_data") or {}
    warning = solver.get("chrono_collision_warning") is True
    f6_float = f6_mdbc_definition.get("has_floatings_container") is True or f6_mdbc_definition.get("floating_count", 0) > 0
    f6_rigid = f6_mdbc_definition.get("rigid_algorithm")
    fixed_control_has_floatings = fixed_mdbc_definition.get("has_floatings_container") is True
    doc_text = hydrostatic_document.read_text(errors="replace") if hydrostatic_document.is_file() else ""
    if policy_document is not None and policy_document.is_file():
        doc_text += "\n" + policy_document.read_text(errors="replace")
    warning_text = bool(re.search(r"Chrono.*(warning|blocked)|warning.*Chrono", doc_text, flags=re.IGNORECASE))
    checks = {
        "warning_is_recorded": warning,
        "floating_mdbc_route_is_affected": warning and f6_float,
        "current_floating_route_is_not_chrono3": f6_rigid != 3,
        "fixed_body_control_definition_is_separate": not fixed_control_has_floatings,
        "policy_keeps_chrono_separate_from_e1": "Chrono integration is a separate follow-up" in doc_text,
    }
    release_checks = {
        "no_unresolved_chrono_warning": not warning,
        "fixed_body_control_definition_is_separate": not fixed_control_has_floatings,
        "policy_keeps_chrono_separate_from_e1": "Chrono integration is a separate follow-up" in doc_text,
        "target_route_is_explicit": (not f6_float) or f6_rigid == 3,
    }
    return {
        "status": "closed" if all(release_checks.values()) else "blocked",
        "gate": all(release_checks.values()),
        "warning": {
            "recorded_by_solver_evidence": warning,
            "historical_document_mentions_warning": warning_text,
            "solver_finished_code_0": solver.get("solver_finished_code_0"),
            "meaning": "The mDBC floating collision path asks for Chrono contact handling; return code 0 does not resolve this warning.",
        },
        "definitions": {
            "f6_mdbc_candidate": f6_mdbc_definition,
            "f6_dbc_route": f6_dbc_definition,
            "fixed_box_mdbc_control": fixed_mdbc_definition,
        },
        "checks": checks,
        "release_checks": release_checks,
        "release_paths": {
            "e1_fixed_body_hydrostatic": [
                "Remove the floating-body/Chrono path from the transformed-Float1 E1 definition; use fixed boundary particles and an explicit fixed-body force gauge.",
                "Keep Chrono integration out of the E1 DBC-vs-mDBC comparison and retain a solver log showing no unresolved floating mDBC collision warning.",
            ],
            "separate_dynamic_floating_body": [
                "If the target is intentionally dynamic/floating, configure and record RigidAlgorithm=3 with the Chrono collision/body model and contact parameters.",
                "Retain Chrono contact output, body state, force/torque and penetration evidence; do not mix that result into the fixed-body E1 gate.",
            ],
        },
    }


def _blocker_records(normals: dict[str, Any], force: dict[str, Any], chrono: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "F6_NORMAL_COMPLETENESS",
            "status": "closed" if normals["gate"] else "blocked",
            "observed": normals["conclusion"],
            "release_conditions": normals["release_conditions"],
        },
        {
            "id": "F6_FORCE_GAUGE_MATCHED_CONTROL",
            "status": "closed" if force["gate"] else "blocked",
            "observed": "A fixed-box DBC/mDBC gauge pair exists, but it is not an accepted transformed-Float1 F6 gauge contract.",
            "release_conditions": force["release_conditions"],
        },
        {
            "id": "F6_CHRONO_CONTACT_SEMANTICS",
            "status": "closed" if chrono["gate"] else "blocked",
            "observed": chrono["warning"]["meaning"],
            "release_conditions": chrono["release_paths"],
        },
    ]


def build_contract(paths: dict[str, Path] | None = None) -> dict[str, Any]:
    selected = dict(DEFAULT_PATHS)
    if paths:
        selected.update(paths)
    c3r, c3r_evidence = read_json(selected["c3r"])
    preflight, preflight_evidence = read_json(selected["preflight"])
    zero_normal, zero_normal_evidence = read_json(selected["zero_normal"])
    static, static_evidence = read_json(selected["static"])
    wall, wall_evidence = read_json(selected["wall"])
    test14, test14_evidence = read_json(selected["test14"])
    dbc_force, dbc_force_evidence = read_json(selected["dbc_force"])
    mdbc_force, mdbc_force_evidence = read_json(selected["mdbc_force"])
    runtime_normals, runtime_normals_evidence = read_json(selected["runtime_normals"])

    f6_mdbc_definition = parse_definition(selected["f6_mdbc_definition"])
    f6_dbc_definition = parse_definition(selected["f6_dbc_definition"])
    fixed_mdbc_definition = parse_definition(selected["fixed_mdbc_definition"])
    normals = audit_normals(
        preflight=preflight,
        zero_normal=zero_normal,
        mdbc_force=mdbc_force,
        runtime_normals=runtime_normals,
    )
    force = audit_force_gauge_comparison(
        dbc_report=dbc_force,
        dbc_report_path=selected["dbc_force"],
        mdbc_report=mdbc_force,
        mdbc_report_path=selected["mdbc_force"],
        f6_reports=(preflight, static, wall, test14),
    )
    chrono = audit_chrono_contract(
        preflight=preflight,
        f6_mdbc_definition=f6_mdbc_definition,
        f6_dbc_definition=f6_dbc_definition,
        fixed_mdbc_definition=fixed_mdbc_definition,
        hydrostatic_document=selected["hydrostatic"],
        policy_document=selected["policy"],
    )
    blockers = _blocker_records(normals, force, chrono)
    all_closed = all(item["status"] == "closed" for item in blockers)
    input_evidence = {
        key: value for key, value in {
            "c3r": c3r_evidence,
            "preflight": preflight_evidence,
            "zero_normal": zero_normal_evidence,
            "static": static_evidence,
            "wall": wall_evidence,
            "test14": test14_evidence,
            "dbc_force": dbc_force_evidence,
            "mdbc_force": mdbc_force_evidence,
            "runtime_normals": runtime_normals_evidence,
        }.items()
    }
    return {
        "schema": SCHEMA,
        "stage": "F6R",
        "created_at_utc": utc_now(),
        "audit_commit": _git_head(),
        "audit_policy": {
            "read_only": True,
            "new_solver_execution": False,
            "resume_modified": False,
            "old_reports_modified": False,
            "solver_source_modified": False,
            "interpretation": "This is a blocker audit, not a solver run or qualification receipt.",
        },
        "upstream_c3r": {
            "status": c3r.get("status"),
            "decision": c3r.get("decision"),
            "reported_f6_status": nested(c3r, "f6_bounded_evidence_or_external_blocker", "status"),
            "reported_f6_blocker_id": nested(c3r, "f6_bounded_evidence_or_external_blocker", "blocker_id"),
            "new_solver_execution": nested(c3r, "execution_policy", "new_solver_execution"),
            "source": c3r_evidence,
        },
        "status": "complete_with_findings" if not all_closed else "complete",
        "decision": "blocked_external" if not all_closed else "blocker_contract_closed",
        "blocker_id": BLOCKER_ID if not all_closed else None,
        "blocker_statement": (
            "F6 remains externally blocked: nominal transformed-Float1 normal completeness, a matched transformed-Float1 force-gauge closure, and the floating-versus-fixed Chrono contact semantics are not all closed."
            if not all_closed
            else "The audited F6 blocker contract is closed; this does not itself constitute physical qualification."
        ),
        "input_evidence": input_evidence,
        "source_and_documentation": audit_source_and_documentation(),
        "observed": {
            "f6_preflight_acceptance_status": preflight.get("acceptance_status"),
            "f6_static_acceptance_status": static.get("acceptance_status"),
            "f6_wall_acceptance_status": wall.get("acceptance_status"),
            "f6_test14_scientific_acceptance": test14.get("scientific_acceptance"),
            "normal_contract": normals,
            "force_gauge_contract": force,
            "chrono_contract": chrono,
        },
        "blockers": blockers,
        "required_to_unblock": [
            "Close F6_NORMAL_COMPLETENESS on the nominal transformed Float1 geometry at the intended resolutions.",
            "Create the fixed-body transformed-Float1 DBC control and mDBC candidate with explicit force gauges and matched provenance.",
            "Resolve Chrono semantics by keeping it separate from E1 fixed-body hydrostatics, or by explicitly running a separate RigidAlgorithm=3 dynamic contact route.",
            "Only after the above, run the bounded F6 physical comparison and retain mass, penetration, pressure/force, body-state and multi-window evidence.",
        ],
        "do_not_claim": [
            "Do not call a solver return code of 0 mDBC physical acceptance.",
            "Do not promote radius-offset zero-normal diagnostics to the nominal F6 geometry.",
            "Do not use the fixed-box DBC/mDBC control as a transformed-Float1 F6 result.",
            "Do not mix a dynamic Chrono contact experiment into the fixed-body E1 hydrostatic gate.",
        ],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional new JSON path; stdout is always emitted.")
    parser.add_argument("--c3r", type=Path, default=DEFAULT_PATHS["c3r"])
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PATHS["preflight"])
    parser.add_argument("--zero-normal", type=Path, default=DEFAULT_PATHS["zero_normal"])
    parser.add_argument("--static", type=Path, default=DEFAULT_PATHS["static"])
    parser.add_argument("--wall", type=Path, default=DEFAULT_PATHS["wall"])
    parser.add_argument("--test14", type=Path, default=DEFAULT_PATHS["test14"])
    parser.add_argument("--dbc-force", type=Path, default=DEFAULT_PATHS["dbc_force"])
    parser.add_argument("--mdbc-force", type=Path, default=DEFAULT_PATHS["mdbc_force"])
    parser.add_argument("--runtime-normals", type=Path, default=DEFAULT_PATHS["runtime_normals"])
    parser.add_argument("--f6-mdbc-definition", type=Path, default=DEFAULT_PATHS["f6_mdbc_definition"])
    parser.add_argument("--f6-dbc-definition", type=Path, default=DEFAULT_PATHS["f6_dbc_definition"])
    parser.add_argument("--fixed-mdbc-definition", type=Path, default=DEFAULT_PATHS["fixed_mdbc_definition"])
    parser.add_argument("--hydrostatic-document", type=Path, default=DEFAULT_PATHS["hydrostatic"])
    args = parser.parse_args(argv)
    paths = {
        "c3r": args.c3r,
        "preflight": args.preflight,
        "zero_normal": args.zero_normal,
        "static": args.static,
        "wall": args.wall,
        "test14": args.test14,
        "dbc_force": args.dbc_force,
        "mdbc_force": args.mdbc_force,
        "runtime_normals": args.runtime_normals,
        "f6_mdbc_definition": args.f6_mdbc_definition,
        "f6_dbc_definition": args.f6_dbc_definition,
        "fixed_mdbc_definition": args.fixed_mdbc_definition,
        "hydrostatic": args.hydrostatic_document,
    }
    report = build_contract(paths)
    if args.output:
        _write_json(args.output, report)
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "decision": report["decision"],
        "blocker_id": report["blocker_id"],
        "normal_status": report["observed"]["normal_contract"]["status"],
        "force_gauge_status": report["observed"]["force_gauge_contract"]["status"],
        "chrono_status": report["observed"]["chrono_contract"]["status"],
        "output": str(args.output) if args.output else None,
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"complete", "complete_with_findings"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

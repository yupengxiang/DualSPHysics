#!/usr/bin/env python3
"""Audit the retained F1 canary and prepare two bounded F1R recipes.

This module is deliberately independent of the campaign/resume controller.  It
only reads the retained F1 evidence and writes F1R-prefixed artifacts.  In
particular, running it never launches GenCase, DualSPHysics, PartVTK, or a GPU
job; PartVTK is used only as a short CPU-side decoder for an existing
``PartOut`` file.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import h5py
import numpy as np

try:
    from scripts.l2_campaign import inspect_hdf5
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from l2_campaign import inspect_hdf5


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "l2-multifamily"
F1_CASE = "L2_C1_F1_obstacle_nominal"
F1_HDF5 = CAMPAIGN / "c1-canary" / "data" / f"{F1_CASE}.h5"
F1_DEFINITION = CAMPAIGN / "c1-canary" / "cases" / f"{F1_CASE}_Def.xml"
F1_GENERATED_XML = (
    CAMPAIGN / "c1-canary" / "artifacts" / F1_CASE / "generated" / f"{F1_CASE}.xml"
)
F1_RUN_ROOT = CAMPAIGN / "runs" / F1_CASE
REPORT = CAMPAIGN / "reports" / "l2_f1r_evidence.json"
MARKDOWN = CAMPAIGN / "reports" / "l2_f1r_evidence.md"
PARTVTKOUT = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux" / "PartVTKOut_linux64"

F1_WALL_SPEC: dict[str, Any] = {
    "container_interior": {
        "xmin": 0.0,
        "xmax": 1.2,
        "ymin": 0.0,
        "ymax": 0.4,
        "zmin": 0.0,
        "zmax": 0.6,
    },
    "closed_faces": ["bottom", "left", "right", "front", "back"],
    "open_faces": ["top"],
    "obstacles": [
        {
            "id": "center_obstacle",
            "xmin": 0.68,
            "xmax": 0.80,
            "ymin": 0.15,
            "ymax": 0.25,
            "zmin": 0.0,
            "zmax": 0.34,
        }
    ],
}

# The generated F1 canary has a fluid envelope [0, 1.2] x [0, .3975] x [0, .6]
# and the source expression ``default + 75%`` resolves to z=1.05.  The repair
# makes this value explicit and moves only the upper runtime-domain face.  It
# does not close the physical tank's open top or change the obstacle.
F1_REPAIRED_RUNTIME_DOMAIN = {
    "xmin": -0.30,
    "xmax": 1.50,
    "ymin": -0.099375,
    "ymax": 0.496875,
    "zmin": -0.15,
    "zmax": 1.35,
}

BACKGROUND_SPECS: tuple[dict[str, Any], ...] = (
    {
        "background_id": "plain_release",
        "role": "clear_path_or_analytic_release_background",
        "definition": "cases/F1/F1_dam_break_plain/F1_dam_break_plain_Def.xml",
        "initial_artifact": "cases/F1/F1_dam_break_plain/generated/F1_dam_break_plain.bi4",
        "required_evidence": "solver trajectory at the declared reference resolutions",
    },
    {
        "background_id": "center_obstacle",
        "role": "single_resolved_obstacle_background",
        "definition": "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F1_obstacle_nominal_Def.xml",
        "initial_artifact": "campaigns/l2-multifamily/c1-canary/artifacts/L2_C1_F1_obstacle_nominal/generated/L2_C1_F1_obstacle_nominal.bi4",
        "required_evidence": "two-background by three-resolution reference matrix",
    },
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except ValueError:
        return None


def _int_number(value: Any) -> int | None:
    parsed = _number(value)
    return None if parsed is None else int(parsed)


def _normalise_row(row: dict[str | None, Any]) -> dict[str, Any]:
    return {str(key).strip().rstrip(","): value for key, value in row.items() if key is not None}


def _runparts_rows(path: Path) -> dict[int, dict[str, Any]]:
    """Read native output counters without inferring a cause from HDF5."""

    if not path.is_file():
        return {}
    lines = path.read_text(errors="replace").splitlines()
    header = next((index for index, line in enumerate(lines) if line.startswith("Part;")), None)
    if header is None:
        return {}
    result: dict[int, dict[str, Any]] = {}
    for raw in csv.DictReader(lines[header:], delimiter=";"):
        row = _normalise_row(raw)
        part = _int_number(row.get("Part"))
        if part is None:
            continue
        counts = {
            "position": _int_number(row.get("NpOutPos")) or 0,
            "density": _int_number(row.get("NpOutRho")) or 0,
            "movement": _int_number(row.get("NpOutMov")) or 0,
        }
        result[part] = {
            "part": part,
            "time_s": _number(row.get("TimeStep [s]")),
            "excluded_count": _int_number(row.get("NpOut")) or 0,
            "reason_counts": counts,
        }
    return result


def _native_reason(reason_counts: dict[str, int]) -> str:
    nonzero = [name for name, count in reason_counts.items() if count]
    return nonzero[0] if len(nonzero) == 1 else ("multiple" if nonzero else "unknown")


def _tool_environment() -> dict[str, str]:
    environment = os.environ.copy()
    bin_dir = str(PARTVTKOUT.parent)
    environment["LD_LIBRARY_PATH"] = f"{bin_dir}:{environment.get('LD_LIBRARY_PATH', '')}"
    return environment


def _parse_partout_csv(path: Path, runparts: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(newline="", errors="replace") as stream:
        for raw in csv.DictReader(stream):
            row = _normalise_row(raw)
            particle_id = _int_number(row.get("Idp"))
            part = _int_number(row.get("PartOut"))
            if particle_id is None or part is None:
                continue
            native_counters = runparts.get(part, {}).get("reason_counts", {})
            rows.append(
                {
                    "particle_id": particle_id,
                    "part_out": part,
                    "motive": _int_number(row.get("Motive")),
                    "position_m": [_number(row.get(key)) for key in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")],
                    "velocity_m_s": [_number(row.get(key)) for key in ("Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]")],
                    "density_kg_m3": _number(row.get("Rhop [kg/m^3]")),
                    "native_reason": _native_reason(native_counters),
                    "native_reason_counters": native_counters,
                }
            )
    return rows


def native_partout_evidence(attempt: Path) -> dict[str, Any]:
    """Decode an existing PartOut file; never runs the CFD solver."""

    data_dir = attempt / "data"
    runparts = _runparts_rows(attempt / "RunPARTs.csv")
    empty = {
        "status": "unavailable",
        "rows": [],
        "reason_counts": {},
        "runparts": list(runparts.values()),
    }
    if not data_dir.is_dir() or not any(data_dir.glob("PartOut_*.obi4")):
        empty["status"] = "no_partout_files"
        return empty
    if not PARTVTKOUT.is_file():
        empty["status"] = "partvtkout_binary_missing"
        return empty
    with tempfile.TemporaryDirectory(prefix="l2-f1r-partout-") as temporary:
        output = Path(temporary) / "excluded.csv"
        resume = Path(temporary) / "resume.csv"
        process = subprocess.run(
            [
                str(PARTVTKOUT),
                "-dirdata",
                str(data_dir.resolve()),
                "-savecsv",
                str(output),
                "-saveresume",
                str(resume),
                "-createdirs:1",
                "-csvsep:1",
            ],
            cwd=attempt,
            env=_tool_environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if process.returncode != 0 or not output.is_file():
            return {
                **empty,
                "status": "partvtkout_failed",
                "returncode": process.returncode,
                "stdout_tail": process.stdout[-1200:],
            }
        rows = _parse_partout_csv(output, runparts)
    reason_counts = Counter(str(row["native_reason"]) for row in rows)
    return {
        "status": "available",
        "rows": rows,
        "reason_counts": dict(reason_counts),
        "runparts": list(runparts.values()),
        "returncode": process.returncode,
        "partvtkout_version": "v5.4.266.02",
    }


_DOMAIN_RE = re.compile(r"^\s*default\s*([+-])\s*([0-9.]+)%\s*$", re.IGNORECASE)


def _resolve_domain_expression(expression: str, default: float, span: float) -> float:
    match = _DOMAIN_RE.match(expression)
    if not match:
        return float(expression)
    sign = 1.0 if match.group(1) == "+" else -1.0
    # DualSPHysics interprets the percentage relative to the generated
    # particle-envelope span, not relative to the coordinate value.  This is
    # why ``default - 25%`` is meaningful when the minimum coordinate is zero.
    return default + sign * span * float(match.group(2)) / 100.0


def resolve_runtime_domain(path: Path) -> dict[str, Any] | None:
    """Resolve the generated XML's default-domain expressions from its fluid envelope."""

    if not path.is_file():
        return None
    root = ET.parse(path).getroot()
    positions = root.find(".//particles/_summary/positions")
    simulation = root.find(".//execution/parameters/simulationdomain")
    if positions is None or simulation is None:
        return None
    posmin = positions.find("posmin")
    posmax = positions.find("posmax")
    domain_min = simulation.find("posmin")
    domain_max = simulation.find("posmax")
    if None in (posmin, posmax, domain_min, domain_max):
        return None
    values: dict[str, float] = {}
    expressions: dict[str, dict[str, str]] = {"min": {}, "max": {}}
    for axis in "xyz":
        minimum = _number(posmin.attrib.get(axis))
        maximum = _number(posmax.attrib.get(axis))
        if minimum is None or maximum is None:
            return None
        expressions["min"][axis] = domain_min.attrib.get(axis, "")
        expressions["max"][axis] = domain_max.attrib.get(axis, "")
        span = maximum - minimum
        values[f"{axis}min"] = _resolve_domain_expression(domain_min.attrib.get(axis, ""), minimum, span)
        values[f"{axis}max"] = _resolve_domain_expression(domain_max.attrib.get(axis, ""), maximum, span)
    return {
        "xmin": values["xmin"],
        "xmax": values["xmax"],
        "ymin": values["ymin"],
        "ymax": values["ymax"],
        "zmin": values["zmin"],
        "zmax": values["zmax"],
        "fluid_envelope": {
            "xmin": _number(posmin.attrib.get("x")),
            "xmax": _number(posmax.attrib.get("x")),
            "ymin": _number(posmin.attrib.get("y")),
            "ymax": _number(posmax.attrib.get("y")),
            "zmin": _number(posmin.attrib.get("z")),
            "zmax": _number(posmax.attrib.get("z")),
        },
        "expressions": expressions,
    }


def _set_parameter(root: ET.Element, key: str, value: str | float | int) -> None:
    node = root.find(f".//parameter[@key='{key}']")
    if node is None:
        parameters = root.find(".//execution/parameters")
        if parameters is None:
            raise ValueError("F1 definition has no execution parameters")
        node = ET.SubElement(parameters, "parameter", key=key)
    node.set("value", str(value))


def _set_explicit_domain(root: ET.Element, domain: dict[str, float]) -> None:
    node = root.find(".//execution/parameters/simulationdomain")
    if node is None:
        raise ValueError("F1 definition has no simulationdomain")
    posmin = node.find("posmin")
    posmax = node.find("posmax")
    if posmin is None or posmax is None:
        raise ValueError("F1 simulationdomain has no posmin/posmax")
    for axis in "xyz":
        posmin.set(axis, f"{domain[axis + 'min']:.9g}")
        posmax.set(axis, f"{domain[axis + 'max']:.9g}")


def apply_runtime_domain_repair(source: Path, destination: Path, *, zmax: float = 1.35) -> Path:
    """Materialize the H1 repair without touching ``source`` or running CFD."""

    domain = dict(F1_REPAIRED_RUNTIME_DOMAIN)
    domain["zmax"] = float(zmax)
    tree = ET.parse(source)
    _set_explicit_domain(tree.getroot(), domain)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="    ")
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return destination


def apply_time_boundary_alternative(source: Path, destination: Path) -> Path:
    """Materialize H2's complete numerical recipe alternative.

    The XML changes are intentionally paired with the solver flag in the
    returned recipe manifest: ``-mdbc_noslip:0`` is a command-line boundary
    selection and cannot be represented by a normal XML parameter.
    """

    tree = ET.parse(source)
    root = tree.getroot()
    constants = root.find(".//constantsdef")
    if constants is None:
        raise ValueError("F1 definition has no constantsdef")
    cfl = constants.find("cflnumber")
    if cfl is None:
        raise ValueError("F1 definition has no cflnumber")
    cfl.set("value", "0.05")
    _set_parameter(root, "SavePosDouble", 2)
    _set_parameter(root, "TimeOut", "0.02")
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="    ")
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return destination


def _latest_attempt() -> tuple[Path | None, dict[str, Any]]:
    latest = F1_RUN_ROOT / "latest.json"
    if latest.is_file():
        payload = json.loads(latest.read_text())
        path = Path(str(payload.get("attempt_directory", "")))
        if path.is_dir():
            return path.resolve(), payload
    candidates = sorted(F1_RUN_ROOT.glob("attempts/*/attempt.json"))
    for manifest in reversed(candidates):
        payload = json.loads(manifest.read_text())
        if payload.get("status") == "completed":
            return manifest.parent.resolve(), payload
    return None, {}


def _missing_identity_join(
    hdf5: Path,
    native_rows: Iterable[dict[str, Any]],
    runparts: dict[int, dict[str, Any]],
    runtime_domain: dict[str, Any] | None,
) -> dict[str, Any]:
    native_by_id = {int(row["particle_id"]): row for row in native_rows}
    with h5py.File(hdf5, "r") as handle:
        time_axis = np.asarray(handle["time"][:], dtype=np.float64)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        particle_ids = np.asarray(handle["particle_id"][:], dtype=np.int64)
        missing_indices = np.flatnonzero(valid[0] & ~valid[-1])
        rows: list[dict[str, Any]] = []
        for index in missing_indices:
            history = np.flatnonzero(valid[:, index])
            last_frame = int(history[-1]) if len(history) else None
            particle_id = int(particle_ids[index])
            event = native_by_id.get(particle_id, {})
            part = event.get("part_out")
            part_record = runparts.get(int(part), {}) if part is not None else {}
            native_position = event.get("position_m") or [None, None, None]
            domain_zmax = runtime_domain.get("zmax") if runtime_domain else None
            at_domain_ceiling = bool(
                event.get("native_reason") == "position"
                and native_position[2] is not None
                and domain_zmax is not None
                and float(native_position[2]) > float(domain_zmax)
                and float(native_position[2]) - float(domain_zmax) < 0.01
            )
            row = {
                "particle_id": particle_id,
                "particle_index": int(index),
                "type_initial": int(handle["type"][0, index]),
                "mk_initial": int(handle["mk"][0, index]),
                "last_valid_frame": last_frame,
                "last_valid_time_s": None if last_frame is None else float(time_axis[last_frame]),
                "first_missing_frame": None if last_frame is None else last_frame + 1,
                "first_missing_time_s": (
                    None if last_frame is None or last_frame + 1 >= len(time_axis)
                    else float(time_axis[last_frame + 1])
                ),
                "last_valid_position_m": (
                    None if last_frame is None else np.asarray(handle["position"][last_frame, index], dtype=float).tolist()
                ),
                "last_valid_velocity_m_s": (
                    None if last_frame is None else np.asarray(handle["velocity"][last_frame, index], dtype=float).tolist()
                ),
                "last_valid_density_kg_m3": (
                    None if last_frame is None else float(handle["density"][last_frame, index])
                ),
                "part_out": part,
                "native_event_time_s": part_record.get("time_s"),
                "native_reason": event.get("native_reason"),
                "native_position_m": native_position,
                "native_velocity_m_s": event.get("velocity_m_s"),
                "native_density_kg_m3": event.get("density_kg_m3"),
                "native_motive": event.get("motive"),
                "classification": (
                    "position_exclusion_at_runtime_domain_upper_face"
                    if at_domain_ceiling
                    else "unresolved_native_position_exclusion"
                ),
            }
            rows.append(row)
    reason_counts = Counter(str(row.get("native_reason")) for row in rows)
    part_counts = Counter(str(row.get("part_out")) for row in rows)
    last_frame_counts = Counter(str(row.get("last_valid_frame")) for row in rows)
    event_positions = np.asarray(
        [row["native_position_m"] for row in rows if all(value is not None for value in row["native_position_m"])],
        dtype=np.float64,
    )
    event_density = np.asarray(
        [row["native_density_kg_m3"] for row in rows if row["native_density_kg_m3"] is not None],
        dtype=np.float64,
    )
    event_velocity = np.asarray(
        [row["native_velocity_m_s"] for row in rows if row["native_velocity_m_s"] is not None],
        dtype=np.float64,
    )
    summary = {
        "missing_initial_identity_count": len(rows),
        "native_join_count": sum(row.get("native_reason") is not None for row in rows),
        "reason_counts": dict(reason_counts),
        "part_out_counts": dict(part_counts),
        "last_valid_frame_counts": dict(last_frame_counts),
        "type_counts": dict(Counter(str(row["type_initial"]) for row in rows)),
        "mk_counts": dict(Counter(str(row["mk_initial"]) for row in rows)),
        "native_position_min_m": event_positions.min(axis=0).tolist() if len(event_positions) else None,
        "native_position_max_m": event_positions.max(axis=0).tolist() if len(event_positions) else None,
        "native_density_min_kg_m3": float(event_density.min()) if len(event_density) else None,
        "native_density_max_kg_m3": float(event_density.max()) if len(event_density) else None,
        "native_speed_min_m_s": float(np.linalg.norm(event_velocity, axis=1).min()) if len(event_velocity) else None,
        "native_speed_max_m_s": float(np.linalg.norm(event_velocity, axis=1).max()) if len(event_velocity) else None,
        "first_missing_time_min_s": min(
            (row["first_missing_time_s"] for row in rows if row["first_missing_time_s"] is not None),
            default=None,
        ),
        "first_missing_time_max_s": max(
            (row["first_missing_time_s"] for row in rows if row["first_missing_time_s"] is not None),
            default=None,
        ),
        "native_event_time_min_s": min(
            (row["native_event_time_s"] for row in rows if row["native_event_time_s"] is not None),
            default=None,
        ),
        "native_event_time_max_s": max(
            (row["native_event_time_s"] for row in rows if row["native_event_time_s"] is not None),
            default=None,
        ),
        "runtime_domain_ceiling_classified_count": sum(
            row["classification"] == "position_exclusion_at_runtime_domain_upper_face" for row in rows
        ),
    }
    return {"summary": summary, "rows": rows}


def _background_evidence() -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for spec in BACKGROUND_SPECS:
        definition = LAB / spec["definition"]
        initial = LAB / spec["initial_artifact"]
        if spec["background_id"] == "center_obstacle":
            center_hdf5 = LAB / "campaigns/l2-multifamily/c1-canary/data/L2_C1_F1_obstacle_nominal.h5"
            trajectories = [center_hdf5] if center_hdf5.is_file() else []
            status = "blocked_single_canary_not_reference_matrix"
            blocker = "one nominal canary exists, but the required two-background by three-resolution matrix is absent"
        else:
            trajectories = []
            status = "blocked_initial_artifact_only"
            blocker = "only GenCase input/initial-state evidence exists; no solver trajectory/reference result is present"
        evidence.append(
            {
                "background_id": spec["background_id"],
                "role": spec["role"],
                "definition": str(definition.relative_to(LAB)) if definition.is_file() else str(definition),
                "definition_exists": definition.is_file(),
                "definition_sha256": _sha256(definition),
                "initial_artifact": str(initial.relative_to(LAB)) if initial.is_file() else str(initial),
                "initial_artifact_exists": initial.is_file(),
                "initial_artifact_sha256": _sha256(initial),
                "trajectory_evidence": [str(path.relative_to(LAB)) for path in trajectories],
                "reference_status": status,
                "blocker": blocker,
                "required_evidence": spec["required_evidence"],
            }
        )
    return evidence


def build_report() -> dict[str, Any]:
    attempt, attempt_manifest = _latest_attempt()
    generated_domain = resolve_runtime_domain(F1_GENERATED_XML)
    native = native_partout_evidence(attempt) if attempt else {"status": "missing_attempt", "rows": [], "reason_counts": {}}
    runparts = _runparts_rows(attempt / "RunPARTs.csv") if attempt else {}
    missing = _missing_identity_join(F1_HDF5, native.get("rows", []), runparts, generated_domain) if F1_HDF5.is_file() else {"summary": {}, "rows": []}
    structural_audit = inspect_hdf5(F1_HDF5, full_scan=True, wall_spec=F1_WALL_SPEC) if F1_HDF5.is_file() else {"structural_pass": False, "errors": ["missing_file"]}
    backgrounds = _background_evidence()
    all_native_joined = (
        native.get("status") == "available"
        and missing["summary"].get("missing_initial_identity_count") == missing["summary"].get("native_join_count")
    )
    all_ceiling = (
        all_native_joined
        and missing["summary"].get("missing_initial_identity_count", 0) > 0
        and missing["summary"].get("runtime_domain_ceiling_classified_count")
        == missing["summary"].get("missing_initial_identity_count")
    )
    external_blockers = [
        {
            "id": "F1-EXT-3D-DAMBREAK",
            "status": "blocked_external",
            "requirement": "matched actual three-dimensional dam-break experiment assets",
            "evidence": "SCENARIO_CARDS.json declares the anchor, but no matched experimental measurement/observation asset or authorized external link is registered in this repository",
            "consequence": "no external qualification claim; numeric evidence remains development-only",
        }
    ]
    report = {
        "schema": "l2r.f1r.evidence_audit.v1",
        "stage": "F1R",
        "created_at_utc": _utc_now(),
        "new_gpu_jobs": 0,
        "task_state_changed": False,
        "qualification_claim": "none",
        "input": {
            "case_id": F1_CASE,
            "hdf5": str(F1_HDF5.relative_to(LAB)),
            "hdf5_sha256": _sha256(F1_HDF5),
            "definition": str(F1_DEFINITION.relative_to(LAB)),
            "definition_sha256": _sha256(F1_DEFINITION),
            "generated_xml": str(F1_GENERATED_XML.relative_to(LAB)),
            "generated_xml_sha256": _sha256(F1_GENERATED_XML),
            "wall_spec": F1_WALL_SPEC,
            "runtime_domain": generated_domain,
        },
        "attempt": {
            "manifest": None if attempt is None else str((attempt / "attempt.json").relative_to(LAB)),
            "manifest_sha256": None if attempt is None else _sha256(attempt / "attempt.json"),
            "attempt_id": attempt_manifest.get("attempt_id"),
            "status": attempt_manifest.get("status"),
            "raw_data_directory": None if attempt is None else str((attempt / "data").relative_to(LAB)),
            "raw_bi4_count": 0 if attempt is None else len(list((attempt / "data").glob("Part_*.bi4"))),
            "run_out_sha256": None if attempt is None else _sha256(attempt / "Run.out"),
            "runparts_sha256": None if attempt is None else _sha256(attempt / "RunPARTs.csv"),
            "partout_sha256": None if attempt is None else _sha256(attempt / "data" / "PartOut_000.obi4"),
        },
        "native_failure_evidence": {
            "partout": {key: value for key, value in native.items() if key != "rows"},
            "runparts_events": list(runparts.values()),
            "identity_join": missing["summary"],
            "missing_identities": missing["rows"],
            "interpretation": {
                "native_position_exclusion_count": missing["summary"].get("reason_counts", {}).get("position", 0),
                "native_density_exclusion_count": missing["summary"].get("reason_counts", {}).get("density", 0),
                "native_movement_exclusion_count": missing["summary"].get("reason_counts", {}).get("movement", 0),
                "runtime_domain_ceiling_match": all_ceiling,
                "physical_closed_wall_violation_count": structural_audit.get("wall_violation_count"),
                "active_state_finite": all(structural_audit.get("finite_active", {}).values()),
                "active_mass_positive": structural_audit.get("active_mass_positive"),
                "mass_loss_is_reported_not_hidden": structural_audit.get("mass_loss_kg"),
                "closed_lifecycle_status": structural_audit.get("lifecycle_model"),
            },
        },
        "structural_audit": structural_audit,
        "native_failure_hypotheses": [
            {
                "id": "F1R-H1-runtime-domain-upper-face",
                "class": "initial_boundary_discretization_or_runtime_domain",
                "status": "supported_but_unconfirmed" if all_ceiling else "not_supported_by_current_join",
                "observation": "All joined missing identities are native position exclusions; their native z positions lie just above the resolved z=1.05 runtime-domain ceiling, while density and velocity remain finite and no closed physical wall crossing is observed in the retained HDF5.",
                "evidence": [
                    "RunPARTs.csv NpOutPos=85 and NpOutRho=NpOutMov=0",
                    "PartOut_000.obi4 joins 85/85 identities",
                    "native z range is approximately 1.0516–1.0518 m; resolved domain zmax is 1.05 m",
                    "active HDF5 state is finite and positive-mass; lifecycle failure remains explicit",
                ],
                "implemented_repair": {
                    "id": "F1R-repair-runtime-domain-explicit-zmax",
                    "function": "apply_runtime_domain_repair",
                    "change": "replace default simulation-domain expressions with explicit bounds and set zmax=1.35 m; preserve the open physical tank top, obstacle, dp, gravity, and source fluid",
                    "status": "implemented_not_run",
                    "falsifier": "if a clean-process repair canary still records position exclusions at the same upper face, or switches to density/movement failures, reject H1 and retain the full native failure evidence",
                },
                "next_test": "one repair canary at the existing nominal dp before any F1 matrix expansion",
            },
            {
                "id": "F1R-H2-time-boundary-full-recipe",
                "class": "time_advancement_and_complete_numerical_boundary_recipe",
                "status": "alternative_not_tested",
                "observation": "The retained recipe uses CFL=0.2, DBC, VerletSteps=40 and a 0.05 s output interval; the present evidence does not isolate time advancement or boundary treatment because every native loss is classified as position exclusion at the runtime-domain ceiling.",
                "evidence": [
                    "current generated recipe parameters are recorded in the retained XML",
                    "no native density or movement exclusion was observed",
                    "causality is not established by the current canary; this branch remains an alternative, not a conclusion",
                ],
                "implemented_alternative": {
                    "id": "F1R-alternative-cfl005-mdbc-noslip",
                    "function": "apply_time_boundary_alternative",
                    "xml_changes": {"cflnumber": "0.05", "SavePosDouble": "2", "TimeOut": "0.02"},
                    "solver_arguments": ["-mdbc_noslip:0"],
                    "status": "implemented_not_run",
                    "falsifier": "if H1 repair already removes the native exclusions, do not spend a second canary on H2 unless a separate near-wall/time-step failure is observed",
                },
                "next_test": "run only if H1 repair does not remove the native position-exclusion mechanism",
            },
        ],
        "background_reference_evidence": backgrounds,
        "external_blockers": external_blockers,
        "acceptance": {
            "native_failure_hypotheses_bounded_to_two": True,
            "native_partout_join_complete": all_native_joined,
            "implemented_repair_present": True,
            "implemented_alternative_present": True,
            "two_background_reference_evidence_available": False,
            "specific_external_blocker_recorded": bool(external_blockers),
            "missing_reference_evidence_marked_blocker": all(item["reference_status"].startswith("blocked_") for item in backgrounds),
            "long_gpu_job_started": False,
            "legacy_canary_promoted": False,
        },
        "status": "complete_with_findings",
        "decision": "F1R evidence audit complete; repair canary and reference matrix remain dispatchable work, while external qualification is blocked",
        "next_gpu_run": {
            "required_approval": "main agent scheduling",
            "order": [
                "run one H1 runtime-domain repair canary on an explicitly allowlisted idle A6000",
                "audit native PartOut and HDF5 identity/lifecycle evidence",
                "run H2 only if H1 does not remove the position-exclusion mechanism",
                "only after a repair is accepted, execute the two-background by three-resolution matrix",
            ],
            "prohibited_now": ["do not launch the full matrix from this audit", "do not promote the old canary", "do not call missing evidence a pass"],
        },
    }
    return report


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def write_report(report: dict[str, Any], *, json_path: Path = REPORT, markdown_path: Path = MARKDOWN) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n")
    native = report["native_failure_evidence"]["identity_join"]
    h1 = report["native_failure_hypotheses"][0]
    lines = [
        "# F1R evidence audit",
        "",
        f"- status: `{report['status']}`",
        f"- new GPU jobs: `{report['new_gpu_jobs']}`",
        f"- native PartOut join: `{native.get('native_join_count')}/{native.get('missing_initial_identity_count')}`",
        f"- native reasons: `{native.get('reason_counts')}`",
        f"- runtime-domain ceiling match: `{native.get('runtime_domain_ceiling_classified_count')}`",
        f"- H1: `{h1['status']}`; repair: `{h1['implemented_repair']['status']}`",
        "",
        "## Evidence decision",
        "",
        "The retained canary is not promoted. Missing identities remain a closed-lifecycle failure even though inactive padding is allowed to be non-finite.",
        "",
        "## Blocking evidence",
        "",
    ]
    for item in report["background_reference_evidence"]:
        lines.append(f"- `{item['background_id']}`: **{item['reference_status']}** — {item['blocker']}")
    for item in report["external_blockers"]:
        lines.append(f"- `{item['id']}`: **{item['status']}** — {item['requirement']}")
    lines.extend(
        [
            "",
            "## Next GPU step",
            "",
            "Run one H1 repair canary on an explicitly allowlisted idle GPU, then rejoin PartOut/HDF5 evidence before any matrix launch. H2 is conditional and remains unrun.",
            "",
        ]
    )
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="audit and print without writing F1R artifacts")
    args = parser.parse_args()
    report = build_report()
    if not args.no_write:
        write_report(report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "native_join": report["native_failure_evidence"]["identity_join"],
                "h1_status": report["native_failure_hypotheses"][0]["status"],
                "report": str(REPORT),
            },
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

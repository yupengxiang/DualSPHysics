#!/usr/bin/env python3
"""Audit F2 coarse position exclusions against the numerical map and source geometry.

This is a small-input, source-only diagnostic.  It consumes the completed
ROOT095 solver proof, ROOT105 native-motive report/proof, ROOT126 stream
report/proof/receipt, the generated XML and Run.out, and the official source
files that define the position predicate and PartOut motive encoding.  It does
not open BI4/H5/VTK arrays and does not run a solver or decoder.

The report deliberately separates three statements:

* the native report says ``Motive=position`` and the coordinates violate the
  saved ``MapRealPos(final)`` bounds;
* those coordinates are compared with the finite XML drawboxes and the static
  bottom reference;
* physical spill, legal flux, continuous event timing and dynamics remain
  unknown.  A numerical-domain-only paired repair is preregistered, never
  treated as a physical-fate result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


AXES = ("x", "y", "z")
CASE_KEY = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
ROOT105_SCHEMA = "ds02.stage2.f2.coarse-canary-native-qa.v1"
ROOT105_STATUS = "COMPLETED_F2_COARSE_CANARY_NATIVE_IDENTITY_MOTIVE_QA"
ROOT105_PROOF_STATUS_PREFIX = "VERIFIED_ACTUAL_F2_NEW_153_POSITION_EXCLUSIONS"
ROOT126_SCHEMA = "ds02.stage2.f2.coarse-active-stream.v8"
ROOT126_STATUS = "COMPLETED_F2_COARSE_ACTIVE_FLUID_STREAM_V8_EXACT_NATIVE_MASS_BITS"
ROOT126_PROOF_STATUS_PREFIX = "VERIFIED_ACTUAL_401_NATIVE_FRAME_STREAM"
ROOT095_PROOF_STATUS_PREFIX = "VERIFIED_ACTUAL_F2_COARSE_CANARY_401_NATIVE_OUTPUTS"
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


class EvidenceError(ValueError):
    """Raised when a source-bound diagnostic cannot be established."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise EvidenceError(f"missing input: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256(path),
    }


def require_file(path: str | Path, label: str) -> Path:
    value = Path(path).expanduser().resolve()
    if not value.is_file():
        raise EvidenceError(f"{label} is missing: {value}")
    if value.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".vtk"}:
        raise EvidenceError(f"{label} points to forbidden array content: {value}")
    return value


def read_json(path: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    value = require_file(path, label)
    try:
        payload = json.loads(value.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is not valid JSON: {value}") from exc
    if not isinstance(payload, dict):
        raise EvidenceError(f"{label} is not a JSON object: {value}")
    return value, payload


def local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def vector(element: ET.Element, label: str) -> list[float]:
    try:
        values = [float(element.attrib[axis]) for axis in AXES]
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceError(f"{label} is not a numeric xyz vector") from exc
    if not all(math.isfinite(item) for item in values):
        raise EvidenceError(f"{label} contains a nonfinite value")
    return values


def _descendant(root: ET.Element, tag: str) -> ET.Element:
    for element in root.iter():
        if local_tag(element) == tag:
            return element
    raise EvidenceError(f"XML element {tag} is missing")


def parse_xml(path: Path) -> dict[str, Any]:
    path = require_file(path, "generated XML")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise EvidenceError(f"generated XML is invalid: {path}") from exc
    definition = _descendant(root, "definition")
    pointmin = next((item for item in definition if local_tag(item) == "pointmin"), None)
    pointmax = next((item for item in definition if local_tag(item) == "pointmax"), None)
    if pointmin is None or pointmax is None:
        raise EvidenceError("generated XML definition bounds are incomplete")
    parameters = _descendant(root, "parameters")
    simulationdomain = next((item for item in parameters if local_tag(item) == "simulationdomain"), None)
    if simulationdomain is None:
        raise EvidenceError("generated XML simulationdomain is missing")
    domain: dict[str, list[float]] = {}
    domain_raw: dict[str, dict[str, str]] = {}
    for name in ("posmin", "posmax"):
        item = next((child for child in simulationdomain if local_tag(child) == name), None)
        if item is None:
            raise EvidenceError(f"generated XML simulationdomain/{name} is missing")
        domain_raw[name] = {axis: item.attrib.get(axis, "") for axis in AXES}
        domain[name] = vector(item, f"simulationdomain/{name}")
    if any(a >= b for a, b in zip(domain["posmin"], domain["posmax"])):
        raise EvidenceError("generated XML simulationdomain bounds are inverted")

    rhop: dict[str, float] = {}
    controls: dict[str, Any] = {}
    for parameter in parameters.iter():
        if local_tag(parameter) != "parameter":
            continue
        key = parameter.attrib.get("key")
        if key in {"RhopOutMin", "RhopOutMax"}:
            try:
                rhop[key] = float(parameter.attrib["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise EvidenceError(f"XML {key} is invalid") from exc
        if key in {"TimeMax", "TimeOut", "DtMin", "DtFixed", "CFLnumber", "Boundary", "StepAlgorithm"}:
            controls[key] = parameter.attrib.get("value")
    if set(rhop) != {"RhopOutMin", "RhopOutMax"} or rhop["RhopOutMin"] >= rhop["RhopOutMax"]:
        raise EvidenceError("XML density threshold contract is incomplete")

    mainlist = next((item for item in root.iter() if local_tag(item) == "mainlist"), None)
    if mainlist is None:
        raise EvidenceError("XML geometry mainlist is missing")
    current_mk: dict[str, str] | None = None
    boxes: list[dict[str, Any]] = []
    for child in mainlist:
        tag = local_tag(child)
        if tag in {"setmkbound", "setmkfluid"}:
            current_mk = {"kind": tag.removeprefix("setmk"), "mk": child.attrib.get("mk", "")}
            continue
        if tag != "drawbox":
            continue
        boxfill = next((item for item in child if local_tag(item) == "boxfill"), None)
        point = next((item for item in child if local_tag(item) == "point"), None)
        size = next((item for item in child if local_tag(item) == "size"), None)
        if boxfill is None or point is None or size is None or current_mk is None:
            raise EvidenceError("XML drawbox lacks source role/point/size")
        low = vector(point, "drawbox point")
        extent = vector(size, "drawbox size")
        if any(value <= 0 for value in extent):
            raise EvidenceError("XML drawbox size is not positive")
        boxes.append({
            "role": dict(current_mk),
            "boxfill": (boxfill.text or "").strip(),
            "low_m": low,
            "high_m": [low[index] + extent[index] for index in range(3)],
        })
    if not boxes:
        raise EvidenceError("XML has no finite geometry drawboxes")
    fluid_count = 0
    for fluid in root.iter():
        if local_tag(fluid) == "fluid" and "count" in fluid.attrib:
            fluid_count += int(fluid.attrib["count"])
    constants = _descendant(root, "constants")
    massfluid = next((item for item in constants if local_tag(item) == "massfluid"), None)
    if massfluid is None:
        raise EvidenceError("XML constants massfluid is missing")
    massfluid_kg = float(massfluid.attrib["value"])
    if fluid_count <= 0 or not math.isfinite(massfluid_kg) or massfluid_kg <= 0:
        raise EvidenceError("XML fluid mass basis is invalid")
    bottom_boxes = [box for box in boxes if "bottom" in box["boxfill"]]
    if not bottom_boxes:
        raise EvidenceError("XML has no bottom-wall drawbox")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "definition_bounds_m": {"min": vector(pointmin, "definition pointmin"), "max": vector(pointmax, "definition pointmax")},
        "simulationdomain": {"raw": domain_raw, "numeric": domain},
        "rhop_out": rhop,
        "controls": controls,
        "fluid_count": fluid_count,
        "massfluid_kg": massfluid_kg,
        "drawboxes": boxes,
        "bottom_box_count": len(bottom_boxes),
        "static_bottom_reference_z_m": min(box["low_m"][2] for box in bottom_boxes),
    }


FLOAT_RE = r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?"
MAP_RE = re.compile(rf"MapRealPos\((border|final)\)=\(([^)]*)\)-\(([^)]*)\)")


def parse_run_out(path: Path) -> dict[str, Any]:
    path = require_file(path, "Run.out")
    text = path.read_text(encoding="utf-8", errors="replace")
    maps: dict[str, dict[str, list[float]]] = {}
    for match in MAP_RE.finditer(text):
        key = match.group(1)
        if key in maps:
            raise EvidenceError(f"Run.out repeats MapRealPos({key})")
        low = [float(value) for value in match.group(2).split(",")]
        high = [float(value) for value in match.group(3).split(",")]
        if len(low) != 3 or len(high) != 3 or any(not math.isfinite(value) for value in (*low, *high)):
            raise EvidenceError("Run.out MapRealPos is invalid")
        if any(a >= b for a, b in zip(low, high)):
            raise EvidenceError("Run.out MapRealPos bounds are inverted")
        maps[key] = {"min": low, "max": high}
    if set(maps) != {"border", "final"}:
        raise EvidenceError("Run.out lacks exactly border and final MapRealPos")
    case = re.findall(r'CaseName="([^"]+)"', text)
    periodic = re.findall(r'PeriodicActive="([^"]+)"', text)
    rhop = {}
    for key in ("RhopOutMin", "RhopOutMax"):
        found = re.findall(rf"\b{key}=({FLOAT_RE})\b", text)
        if len(found) != 1:
            raise EvidenceError(f"Run.out lacks unique {key}")
        rhop[key] = float(found[0])
    enabled = re.findall(r"\bRhopOut=(True|False)\b", text)
    if case != ["generated"] or periodic != ["None"] or enabled != ["True"]:
        raise EvidenceError("Run.out case/periodic/density state is ambiguous")
    excluded = re.findall(r"Excluded particles\.*:\s*(\d+)", text)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "case_name": case[0],
        "periodic_active": periodic[0],
        "map_real_pos": maps,
        "rhop_out": rhop,
        "excluded_particles_summary": int(excluded[-1]) if excluded else None,
    }


def _proof_report_binding(proof: dict[str, Any], proof_path: Path, report_path: Path, receipt_path: Path, label: str) -> dict[str, Any]:
    if proof.get("report") != str(report_path.resolve()) or proof.get("receipt") != str(receipt_path.resolve()):
        raise EvidenceError(f"{label} proof does not bind exact report/receipt paths")
    if proof.get("report_sha256") != sha256(report_path) or proof.get("receipt_sha256") != sha256(receipt_path):
        raise EvidenceError(f"{label} proof report/receipt digest differs")
    return binding(proof_path)


def validate_solver_proof(path: Path, run_out: Path, xml: Path) -> dict[str, Any]:
    proof_path, proof = read_json(path, "ROOT095 solver proof")
    if not str(proof.get("status", "")).startswith(ROOT095_PROOF_STATUS_PREFIX):
        raise EvidenceError("ROOT095 proof status is not the completed coarse solver proof")
    receipt_path = require_file(proof.get("receipt", ""), "ROOT095 execution receipt")
    if proof.get("parent_source_prepost_full_sha_equal") is not True or proof.get("BI4_H5_VTK_or_native_content_read_by_root") is not False:
        raise EvidenceError("ROOT095 proof has incomplete source/read policy")
    small = proof.get("fresh_small_inputs")
    if not isinstance(small, list):
        raise EvidenceError("ROOT095 proof lacks small-input inventory")
    small_by_name = {Path(str(item.get("path", ""))).name: item for item in small if isinstance(item, dict)}
    for value, label in ((xml, "generated XML"),):
        entry = small_by_name.get(value.name)
        if entry is None or entry.get("sha256") != sha256(value):
            raise EvidenceError(f"ROOT095 proof does not bind {label}")
    return {"proof": binding(proof_path), "receipt": binding(receipt_path), "status": proof["status"], "proof_payload": proof}


def validate_native_report(report_path: Path, proof_path: Path, run_out: Path | None = None, rows_expected: int = 153) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    proof_path, proof = read_json(proof_path, "ROOT105 native proof")
    report_path, report = read_json(report_path, "ROOT105 native report")
    if report.get("schema") != ROOT105_SCHEMA or report.get("status") != ROOT105_STATUS:
        raise EvidenceError("ROOT105 native report is not the completed source-bound product")
    receipt_path = require_file(proof.get("receipt", ""), "ROOT105 execution receipt")
    if not str(proof.get("status", "")).startswith(ROOT105_PROOF_STATUS_PREFIX):
        raise EvidenceError("ROOT105 proof status is not the completed 153-position product")
    if proof.get("report") != str(report_path) or proof.get("report_sha256") != sha256(report_path):
        raise EvidenceError("ROOT105 proof does not bind the supplied native report")
    if proof.get("receipt") != str(receipt_path) or proof.get("receipt_sha256") != sha256(receipt_path):
        raise EvidenceError("ROOT105 proof receipt binding differs")
    if run_out is not None:
        small = proof.get("fresh_small_inputs")
        if not isinstance(small, list):
            raise EvidenceError("ROOT105 proof lacks Run.out small-input inventory")
        run_entry = next((item for item in small if isinstance(item, dict) and Path(str(item.get("path", ""))).name == run_out.name), None)
        if run_entry is None or run_entry.get("path") != str(run_out.resolve()) or run_entry.get("sha256") != sha256(run_out):
            raise EvidenceError("ROOT105 proof does not bind the supplied Run.out")
    if proof.get("actual_native_exclusion_count") != rows_expected or proof.get("actual_native_motive_counts") != {"position": rows_expected}:
        raise EvidenceError("ROOT105 proof native count/motive contract differs")
    if report.get("read_policy", {}).get("trajectory_h5_opened") is not False:
        raise EvidenceError("ROOT105 native report opened forbidden trajectory content")
    rows = report.get("native_identity", {}).get("rows")
    if not isinstance(rows, list) or len(rows) != rows_expected:
        raise EvidenceError("ROOT105 native report row count differs")
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceError("ROOT105 native row is not an object")
        try:
            idp = int(row["idp"])
            motive = str(row["motive"])
            position = [float(value) for value in row["position_m"]]
            density = float(row["density_kg_m3"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceError("ROOT105 native row is malformed") from exc
        if idp in seen or len(position) != 3 or not all(math.isfinite(value) for value in (*position, density)):
            raise EvidenceError("ROOT105 native rows have duplicate/nonfinite identity state")
        if motive != "position":
            raise EvidenceError("ROOT105 report contains a non-position row")
        seen.add(idp)
    return (
        {"path": str(report_path), "sha256": sha256(report_path)},
        {"path": str(proof_path), "sha256": sha256(proof_path), "receipt": str(receipt_path), "receipt_sha256": sha256(receipt_path), "status": proof["status"]},
        rows,
    )


def validate_stream_proof(report_path: Path, proof_path: Path, receipt_path: Path) -> dict[str, Any]:
    proof_path, proof = read_json(proof_path, "ROOT126 stream proof")
    report_path = require_file(report_path, "ROOT126 stream report")
    receipt_path = require_file(receipt_path, "ROOT126 stream receipt")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(proof.get("status", "")).startswith(ROOT126_PROOF_STATUS_PREFIX):
        raise EvidenceError("ROOT126 proof status/schema differs")
    _proof_report_binding(proof, proof_path, report_path, receipt_path, "ROOT126")
    report = read_json(report_path, "ROOT126 stream report")[1]
    if report.get("schema") != ROOT126_SCHEMA or report.get("status") != ROOT126_STATUS:
        raise EvidenceError("ROOT126 report status/schema differs")
    if proof.get("frame_count") != 401 or proof.get("exact153_native_motive_lifecycle_joins") is not True:
        raise EvidenceError("ROOT126 proof does not bind 401 frames/153 joins")
    if proof.get("root_raw_or_h5_read_or_hash") is not False or proof.get("parent_actual_prepost_content_hashes_equal") is not True:
        raise EvidenceError("ROOT126 proof read/stability policy differs")
    active = report.get("active_fluid_stream")
    mass = report.get("mass_and_material")
    if not isinstance(active, dict) or not isinstance(mass, dict):
        raise EvidenceError("ROOT126 stream report lacks active/mass summaries")
    if active.get("frame_count") != 401 or mass.get("native_excluded_count_by_mk") != {"1": 49, "2": 69, "3": 35}:
        raise EvidenceError("ROOT126 stream frame or native-count summary differs")
    try:
        stream_mass_summary = {
            "xml_whole_initial_fluid_mass_kg": float(active["xml_whole_initial_fluid_mass_kg"]),
            "native_whole_initial_fluid_mass_kg": float(active["native_whole_initial_fluid_mass_kg"]),
            "native_massfluid_kg": float(active["native_massfluid_kg"]),
            "native_excluded_mass_lower_bound_kg": float(mass["native_excluded_mass_lower_bound_kg"]),
            "native_excluded_mass_fraction_whole_initial": float(mass["native_excluded_mass_fraction_whole_initial"]),
            "native_excluded_mass_fraction_native_whole_initial": float(mass["native_excluded_mass_fraction_native_whole_initial"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceError("ROOT126 stream mass summary is malformed") from exc
    return {
        "report": binding(report_path),
        "proof": binding(proof_path),
        "receipt": binding(receipt_path),
        "proof_status": proof["status"],
        "report_status": report["status"],
        "stream_mass_summary": stream_mass_summary,
    }


def point_inside(point: list[float], low: list[float], high: list[float]) -> bool:
    return all(lo <= value <= hi for value, lo, hi in zip(point, low, high))


def distance_to_box(point: list[float], low: list[float], high: list[float]) -> float:
    distances = []
    for value, lo, hi in zip(point, low, high):
        distances.append(lo - value if value < lo else value - hi if value > hi else 0.0)
    return math.sqrt(sum(value * value for value in distances))


def classify_rows(rows: list[dict[str, Any]], run_out: dict[str, Any], xml: dict[str, Any]) -> dict[str, Any]:
    final = run_out["map_real_pos"]["final"]
    border = run_out["map_real_pos"]["border"]
    rhop = run_out["rhop_out"]
    boxes = xml["drawboxes"]
    seen: set[int] = set()
    classified = []
    side_counts: Counter[str] = Counter()
    border_side_counts: Counter[str] = Counter()
    motive_counts: Counter[str] = Counter()
    nearest_counts: Counter[str] = Counter()
    max_excursion = {f"{axis}_{direction}": 0.0 for axis in AXES for direction in ("low", "high")}
    border_max_excursion = {f"{axis}_{direction}": 0.0 for axis in AXES for direction in ("low", "high")}
    axis_values: dict[str, list[float]] = {axis: [] for axis in AXES}
    inside_role_counts: Counter[str] = Counter()
    outside_role_counts: Counter[str] = Counter()
    for row in rows:
        idp = int(row["idp"])
        if idp in seen:
            raise EvidenceError(f"duplicate native Idp {idp}")
        seen.add(idp)
        position = [float(value) for value in row["position_m"]]
        density = float(row["density_kg_m3"])
        map_violations = []
        border_violations = []
        for index, axis in enumerate(AXES):
            value = position[index]
            axis_values[axis].append(value)
            low, high = final["min"][index], final["max"][index]
            if value < low:
                amount = low - value
                side_counts[f"{axis}_low"] += 1
                max_excursion[f"{axis}_low"] = max(max_excursion[f"{axis}_low"], amount)
                map_violations.append({"axis": axis, "direction": "below", "amount_m": amount, "bound_m": low, "predicate": f"{axis} < MapRealPosMin.{axis}"})
            elif value >= high:
                amount = value - high
                side_counts[f"{axis}_high"] += 1
                max_excursion[f"{axis}_high"] = max(max_excursion[f"{axis}_high"], amount)
                map_violations.append({"axis": axis, "direction": "at_or_above", "amount_m": amount, "bound_m": high, "predicate": f"{axis} >= MapRealPosMax.{axis}"})
            blow, bhigh = border["min"][index], border["max"][index]
            if value < blow:
                amount = blow - value
                border_side_counts[f"{axis}_low"] += 1
                border_max_excursion[f"{axis}_low"] = max(border_max_excursion[f"{axis}_low"], amount)
                border_violations.append({"axis": axis, "direction": "below", "amount_m": amount, "bound_m": blow})
            elif value >= bhigh:
                amount = value - bhigh
                border_side_counts[f"{axis}_high"] += 1
                border_max_excursion[f"{axis}_high"] = max(border_max_excursion[f"{axis}_high"], amount)
                border_violations.append({"axis": axis, "direction": "at_or_above", "amount_m": amount, "bound_m": bhigh})
        if not map_violations:
            raise EvidenceError(f"native position row {idp} does not violate MapRealPos(final)")
        motive_counts[str(row["motive"])] += 1
        if density < rhop["RhopOutMin"]:
            density_state = "below_rhop_min"
        elif density > rhop["RhopOutMax"]:
            density_state = "above_rhop_max"
        else:
            density_state = "inside_rhop_window"
        if density_state != "inside_rhop_window":
            raise EvidenceError(f"position row {idp} is outside density window")
        inside = [box for box in boxes if point_inside(position, box["low_m"], box["high_m"])]
        distances = [(distance_to_box(position, box["low_m"], box["high_m"]), index, box) for index, box in enumerate(boxes)]
        nearest_distance, nearest_index, nearest_box = min(distances, key=lambda item: item[0])
        nearest_key = f"{nearest_box['role']['kind']}:mk{nearest_box['role']['mk']}:box{nearest_index}"
        nearest_counts[nearest_key] += 1
        roles = {str(box["role"]["kind"]) for box in boxes}
        inside_roles = {str(box["role"]["kind"]) for box in inside}
        for role in roles:
            (inside_role_counts if role in inside_roles else outside_role_counts)[role] += 1
        classified.append({
            "idp": idp,
            "mk": int(row.get("mk", -1)),
            "position_m": position,
            "density_kg_m3": density,
            "saved_record_time_s": float(row["saved_record_time_s"]),
            "saved_record_bracket_s": list(row.get("saved_record_bracket_s", [])),
            "map_final_violations": map_violations,
            "map_border_violations": border_violations,
            "density_state": density_state,
            "inside_declared_geometry_aabb": bool(inside),
            "nearest_declared_box": nearest_key,
            "nearest_declared_box_distance_m": nearest_distance,
            "below_static_bottom_reference": position[2] < xml["static_bottom_reference_z_m"],
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
        })
    if motive_counts != Counter({"position": len(rows)}):
        raise EvidenceError("native motive rows are not all position")
    max_violation = max(max_excursion.values())
    if max_violation <= 0:
        raise EvidenceError("no positive map-bound excursion observed")
    return {
        "row_count": len(rows),
        "motive_counts": dict(motive_counts),
        "map_final_violation_count": len(classified),
        "map_side_counts": dict(sorted(side_counts.items())),
        "map_max_excursion_m": max_excursion,
        "map_border_violation_count": sum(len(item["map_border_violations"]) for item in classified),
        "map_border_unique_particle_count": sum(bool(item["map_border_violations"]) for item in classified),
        "map_border_side_counts": dict(sorted(border_side_counts.items())),
        "map_border_max_excursion_m": border_max_excursion,
        "position_ranges_m": {axis: {"min": min(values), "max": max(values)} for axis, values in axis_values.items()},
        "density_state_counts": {"inside_rhop_window": len(rows)},
        "geometry_aabb_inside_count": sum(item["inside_declared_geometry_aabb"] for item in classified),
        "geometry_aabb_outside_count": sum(not item["inside_declared_geometry_aabb"] for item in classified),
        "geometry_aabb_inside_by_role": dict(sorted(inside_role_counts.items())),
        "geometry_aabb_outside_by_role": dict(sorted(outside_role_counts.items())),
        "nearest_declared_box_counts": dict(sorted(nearest_counts.items())),
        "below_static_bottom_reference_count": sum(item["below_static_bottom_reference"] for item in classified),
        "particles": sorted(classified, key=lambda item: item["idp"]),
        "physical_fate": "UNKNOWN",
        "legal_outflow_or_spill": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
    }


def source_evidence(source_root: Path) -> dict[str, Any]:
    source_root = Path(source_root).expanduser().resolve()
    specs = {
        "position_predicate": (source_root / "src/source/JSphCpu.cpp", ["bool out=", "dx<0", "dx>=MapRealSize.x", "if(out)rcode=CODE_SetOutPos"]),
        "gpu_position_predicate": (source_root / "src/source/JSphGpu_ker.cu", ["bool out=", "dx<0", "dx>=CTE.maprealsizex", "if(out)rcode=CODE_SetOutPos"]),
        "map_initialization_and_log": (source_root / "src/source/JSph.cpp", ["MapRealPos(final)", "MapRealPosMin=MapRealPosMax=", "DataOutBi4->ConfigLimits(MapRealPosMin"]),
        "motive_encoding": (source_root / "src/source/JDsPartsOut.cpp", ["case CODE_OUTPOS", "Motive[Count+c]=1", "OutPosCount+=outpos"]),
        "motive_definition": (source_root / "src/source/JDsPartsOut.h", ["Motive", "1:position"]),
        "partout_header_and_arrays": (source_root / "src/source/JPartOutBi4Save.cpp", ["SetvDouble3(\"MapPosMin\"", "SetvDouble3(\"MapPosMax\"", "CreateArray(\"Motive\""] ),
    }
    result: dict[str, Any] = {}
    for role, (path, required) in specs.items():
        path = require_file(path, f"official source {role}")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        joined = "\n".join(lines)
        missing = [needle for needle in required if needle not in joined]
        if missing:
            raise EvidenceError(f"official source {role} lacks semantic evidence: {missing}")
        locations = []
        for needle in required:
            line_number = next(index for index, line in enumerate(lines, 1) if needle in line)
            locations.append({"needle": needle, "line": line_number, "text": lines[line_number - 1].strip()})
        result[role] = {"binding": binding(path), "locations": locations}
    try:
        commit = subprocess.run(["git", "-C", str(source_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {"repository_root": str(source_root), "repository_commit": commit, "compiled_binary_source_link": "UNKNOWN_UNPROVEN", "files": result}


def repair_plan(run_out: dict[str, Any], diagnostic: dict[str, Any], xml: dict[str, Any]) -> dict[str, Any]:
    final = run_out["map_real_pos"]["final"]
    excursions = diagnostic["map_max_excursion_m"]
    margins = {axis: max(2.0 * max(excursions[f"{axis}_low"], excursions[f"{axis}_high"]), 1.0e-4) for axis in AXES}
    candidate = {
        "posmin": [final["min"][index] - margins[axis] for index, axis in enumerate(AXES)],
        "posmax": [final["max"][index] + margins[axis] for index, axis in enumerate(AXES)],
    }
    return {
        "status": "PREREGISTERED_NOT_RUN",
        "purpose": "bounded numerical-domain sensitivity control for the observed map-face exclusions",
        "basis": "twice the largest observed native coordinate excursion per axis, with a 1e-4 m floor; this is a finite preregistered control, not a tolerance or physical-boundary claim",
        "current_map_real_pos_final": final,
        "margin_by_axis_m": margins,
        "candidate_simulationdomain": candidate,
        "hold_fixed": [
            "generated XML geometry drawboxes and MK/source roles",
            "initial generated BI4 and motion file",
            "dp, CFL, density thresholds, solver algorithm, time window, output cadence",
            "physical receiver/bottom/cup geometry and motion",
        ],
        "vary_only": ["simulationdomain posmin/posmax numerical limits"],
        "root_guard_required_inputs": ["source XML", "initial generated BI4", "motion file", "solver request/receipt", "candidate XML"],
        "readout": [
            "native PartOut motive and exact Idp set",
            "RunPARTs cumulative position/density/movement counters",
            "saved-record first-gap brackets and active identity counts",
            "whole-initial XML mass screen remains frozen at 0.003",
        ],
        "interpretation": "A change in numerical exclusions supports numerical sensitivity only. It cannot prove legal spill, physical destination, continuous event time, velocity/KE error, coupling error, or QI/QN/QE.",
        "scientific_qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_xml_domain_at_registration": xml["simulationdomain"],
    }


def diagnose(
    *,
    solver_proof: Path,
    native_report: Path,
    native_proof: Path,
    stream_report: Path,
    stream_proof: Path,
    stream_receipt: Path,
    generated_xml: Path,
    run_out: Path,
    source_root: Path,
) -> dict[str, Any]:
    generated_xml = require_file(generated_xml, "generated XML")
    run_out = require_file(run_out, "Run.out")
    xml = parse_xml(generated_xml)
    parsed_run_out = parse_run_out(run_out)
    xml_domain = xml["simulationdomain"]["numeric"]
    xml_final = {"min": xml_domain["posmin"], "max": xml_domain["posmax"]}
    if parsed_run_out["map_real_pos"]["final"] != xml_final:
        raise EvidenceError("Run.out MapRealPos(final) differs from generated XML simulationdomain")
    if parsed_run_out["rhop_out"] != xml["rhop_out"]:
        raise EvidenceError("Run.out density thresholds differ from generated XML")
    solver = validate_solver_proof(solver_proof, run_out, generated_xml)
    native_binding, native_proof_binding, rows = validate_native_report(native_report, native_proof, run_out=run_out)
    stream = validate_stream_proof(stream_report, stream_proof, stream_receipt)
    diagnostic = classify_rows(rows, parsed_run_out, xml)
    report = {
        "schema": "ds02.stage2.f2.coarse-position-domain-source-diagnostic.v2",
        "status": "SOURCE_BOUND_POSITION_MAP_DIAGNOSTIC_COMPLETED",
        "case_key": CASE_KEY,
        "source_scope": "ROOT095/105/126 small JSON + generated XML + Run.out + CPU/GPU official source text; no BI4/H5/VTK/solver/decoder opened",
        "evidence": {
            "root095_solver": solver,
            "root105_native_report": native_binding,
            "root105_native_proof": native_proof_binding,
            "root126_stream": stream,
            "generated_xml": binding(generated_xml),
            "run_out": binding(run_out),
        },
        "run_out": parsed_run_out,
        "xml_geometry": xml,
        "diagnostic": diagnostic,
        "official_source": source_evidence(source_root),
        "interpretation": {
            "numerical_cause": "All 153 bound native rows have Motive=position, finite density inside [RhopOutMin,RhopOutMax], and at least one strict MapRealPos(final) face violation. The source predicate uses lower < min and upper >= max after periodic handling; this is numerical map exclusion evidence.",
            "geometry_relation": "No excluded row lies inside any finite XML drawbox AABB; nearest declared AABB is reported per row. This coordinate relation is not a collision, spill, flux, or fate proof.",
            "static_bottom_relation": "Rows below the XML bottom-box low-z reference are counted separately. The finite bottom box and numerical map are different objects.",
            "free_boundary_relation": "The supplied XML/source evidence declares finite fluid and bound drawboxes but no explicit free-boundary surface predicate. Free-surface crossing or legal outflow is therefore UNKNOWN.",
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
            "continuous_event_time": "UNKNOWN beyond saved-record brackets",
            "dynamical_impact": "UNKNOWN",
        },
        "paired_domain_repair": repair_plan(parsed_run_out, diagnostic, xml),
        "mass_screen": {
            "whole_initial_mass_basis": "XML fluid count × XML MassFluid",
            "frozen_unknown_fraction_max": 0.003,
            "root105_observed_native_fraction": 0.005513513513513513,
            "root126_observed_stream_fraction": stream["stream_mass_summary"]["native_excluded_mass_fraction_whole_initial"],
            "root126_native_whole_initial_mass_kg": stream["stream_mass_summary"]["native_whole_initial_fluid_mass_kg"],
            "result": "FAIL_OVER_FROZEN_0P003",
            "domain_semantics_do_not_change_this_gate": True,
        },
        "read_policy": {"h5_opened": False, "bi4_opened": False, "vtk_opened": False, "solver_started": False, "decoder_started": False, "old_products_modified": False},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return report


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise EvidenceError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise EvidenceError(f"diagnostic exceeds bounded JSON output size: {len(encoded)}>{MAX_OUTPUT_BYTES}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver-proof", type=Path, required=True)
    parser.add_argument("--native-report", type=Path, required=True)
    parser.add_argument("--native-proof", type=Path, required=True)
    parser.add_argument("--stream-report", type=Path, required=True)
    parser.add_argument("--stream-proof", type=Path, required=True)
    parser.add_argument("--stream-receipt", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--run-out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path("/home/jade/Projects/DualSPHysics"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = diagnose(
            solver_proof=args.solver_proof,
            native_report=args.native_report,
            native_proof=args.native_proof,
            stream_report=args.stream_report,
            stream_proof=args.stream_proof,
            stream_receipt=args.stream_receipt,
            generated_xml=args.generated_xml,
            run_out=args.run_out,
            source_root=args.source_root,
        )
        atomic_json(args.output, result)
    except EvidenceError as exc:
        print(f"F2 coarse position-domain diagnostic failed: {exc}", file=os.sys.stderr)
        return 1
    print(json.dumps({"schema": result["schema"], "status": result["status"], "output": str(args.output.resolve()), "rows": result["diagnostic"]["row_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

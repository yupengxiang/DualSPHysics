#!/usr/bin/env python3
"""Guarded initial-support QA for the F3-S2 commensurate ``dp=.003`` case.

This forward-only worker consumes the completed official GenCase candidate and
the already-produced three-grid support products.  It checks the source
control/owner lineage, the actual generated XML counts, and the generated
Fluid/Bound VTK point clouds.  Candidate XML, receipt, control, and VTK files
are deferred inputs: the parent runtime must reserve and guard them; this
worker records every declared input before parsing or decoding and again after
the decode.  ``PARENT_GUARD_COMPUTED`` is retained as an external status and
is never substituted for the worker's first SHA.

The owner is a source physical contract.  The inner fluid selector and the
boundary box are resolution-dependent producer envelopes.  Their exact
``dp``-derived relation is reported as initial geometry evidence only.  No
solver, BI4, HDF5, PartVTK, physical-fate, flux, QI, QN, or QE claim is made.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
from typing import Any, Callable
import xml.etree.ElementTree as ET

import numpy as np


SCHEMA = "ds02.stage2.f3.s2.dp003.initial-support-qa.v1"
MANIFEST_SCHEMA = "ds02.stage2.f3.s2.dp003.initial-support-qa.manifest.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
SOURCE_XML_SHA256 = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
SOURCE_CONTROL_SHA256 = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
PREPARED_REPORT_SHA256 = "82c9234cdda3c687a04513755c7bd1d73faf7627fa3027026ff158385ac6dd41"
PRIOR_SUPPORT_SHA256 = "3a882f545b4393f1d56863c54a6057871c31ba44e5db64a9a01cea7f343c64c0"
TARGET_DP_M = 0.003
SOURCE_DP_M = 0.006
RHO_KG_M3 = 1000.0
OWNER_LOW_M = [-0.45, -0.09, 0.0]
OWNER_SIZE_M = [0.9, 0.18, 0.09]
TANK_SIZE_M = [0.9, 0.18, 0.51]
OWNER_HIGH_M = [OWNER_LOW_M[i] + OWNER_SIZE_M[i] for i in range(3)]
OWNER_MASS_KG = 14.58
EXPECTED_FLUID_COUNT = 540000
EXPECTED_MASSFLUID_KG = 0.000027
EXPECTED_SAMPLE_MASS_KG = 14.58
HARD_VTK_MARGIN_MULTIPLIER = 3.0


class AuditError(ValueError):
    """Raised when a deferred or source-bound input fails the QA contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise AuditError(f"missing input file: {path}")
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


def capture_records(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {label: record(path) for label, path in paths.items()}


def prepost_guarded_decode(
    paths: dict[str, Path], decoder: Callable[[], Any]
) -> tuple[Any, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Record a complete input closure before and after the payload decode."""
    pre = capture_records(paths)
    value = decoder()
    post = capture_records(paths)
    if pre != post:
        changed = [label for label in paths if pre[label] != post[label]]
        raise AuditError(f"input changed during decode: {', '.join(changed)}")
    return value, pre, post


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise AuditError(f"{label} is not a regular file: {path}")
    return path


def write_new(path: Path, value: Any) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def local(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def canonical(node: ET.Element) -> tuple[Any, ...]:
    return (local(node), tuple(sorted(node.attrib.items())), (node.text or "").strip(),
            tuple(canonical(child) for child in list(node)))


def first(root: ET.Element, name: str, label: str) -> ET.Element:
    found = [node for node in root.iter() if local(node) == name]
    if not found:
        raise AuditError(f"{label} has no <{name}>")
    return found[0]


def number(value: str | None, label: str) -> float:
    if value is None:
        raise AuditError(f"{label} has no numeric value")
    try:
        result = float(value)
    except ValueError as exc:
        raise AuditError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise AuditError(f"{label} is not finite")
    return result


def vector(node: ET.Element, label: str) -> list[float]:
    return [number(node.get(axis), f"{label}.{axis}") for axis in "xyz"]


def parse_drawboxes(root: ET.Element, label: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fluid: list[dict[str, Any]] = []
    bound: list[dict[str, Any]] = []
    for mainlist in (node for node in root.iter() if local(node) == "mainlist"):
        active_fluid: int | None = None
        active_bound: int | None = None
        for node in list(mainlist):
            kind = local(node)
            if kind == "setmkfluid":
                active_fluid, active_bound = int(node.get("mk", "0")), None
                continue
            if kind == "setmkbound":
                active_fluid, active_bound = None, int(node.get("mk", "0"))
                continue
            if kind != "drawbox":
                continue
            point = next((child for child in node if local(child) == "point"), None)
            size = next((child for child in node if local(child) == "size"), None)
            if point is None or size is None:
                raise AuditError(f"{label} drawbox lacks point/size")
            low = vector(point, f"{label}.drawbox.point")
            size_m = vector(size, f"{label}.drawbox.size")
            if any(item <= 0 for item in size_m):
                raise AuditError(f"{label} drawbox has non-positive size")
            entry = {
                "low_m": low,
                "size_m": size_m,
                "high_m": [low[i] + size_m[i] for i in range(3)],
                "volume_m3": math.prod(size_m),
                "mkfluid": active_fluid,
                "mkbound": active_bound,
                "boxfill": next((child.text or "" for child in node if local(child) == "boxfill"), "").strip(),
            }
            if active_fluid is not None:
                fluid.append(entry)
            elif active_bound is not None:
                bound.append(entry)
    return fluid, bound


def parse_xml(path: Path, label: str) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    case = first(root, "casedef", label)
    definition = first(case, "definition", label)
    particles = first(root, "particles", label)
    counts: dict[str, int] = {}
    for child in list(particles):
        if local(child) in {"fixed", "fluid", "floating", "moving"} and child.get("count") is not None:
            counts[local(child)] = counts.get(local(child), 0) + int(child.get("count"))
    massfluid = first(root, "massfluid", label)
    controls = [node for node in root.iter() if local(node) == "acctimesfile"]
    control_name = controls[0].get("value") if controls else None
    if not control_name:
        raise AuditError(f"{label} has no acctimesfile")
    fluid_boxes, bound_boxes = parse_drawboxes(root, label)
    return {
        "casedef": canonical(case),
        "dp_m": number(definition.get("dp"), f"{label}.dp"),
        "counts": counts,
        "total_particles": sum(counts.values()),
        "massfluid_kg": number(massfluid.get("value"), f"{label}.massfluid"),
        "sample_fluid_mass_kg": counts.get("fluid", 0) * number(massfluid.get("value"), f"{label}.massfluid"),
        "control_name": control_name,
        "fluid_boxes": fluid_boxes,
        "bound_boxes": bound_boxes,
    }


def parse_control(path: Path, label: str) -> dict[str, Any]:
    times: list[float] = []
    row_count = 0
    header: list[str] | None = None
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, delimiter=";")
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            if header is None:
                header = [cell.strip().lstrip("#") for cell in row]
                continue
            if len(row) != len(header):
                raise AuditError(f"{label} control row width mismatch")
            values = []
            for cell in row:
                try:
                    value = float(cell.strip())
                except ValueError as exc:
                    raise AuditError(f"{label} control has non-numeric value") from exc
                if not math.isfinite(value):
                    raise AuditError(f"{label} control has non-finite value")
                values.append(value)
            times.append(values[0])
            row_count += 1
    if header is None or not row_count or header[0].lower() != "time":
        raise AuditError(f"{label} control lacks Time header/rows")
    if any(later < earlier for earlier, later in zip(times, times[1:])):
        raise AuditError(f"{label} control time is not monotonic")
    return {"header": header, "row_count": row_count, "time_first_s": times[0],
            "time_last_s": times[-1], "time_monotonic_non_decreasing": True}


def read_vtk_points(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    data = path.read_bytes()
    match = re.search(rb"(?m)^POINTS\s+(\d+)\s+float\r?\n", data)
    if match is None:
        raise AuditError(f"{path} has no binary float POINTS section")
    count = int(match.group(1))
    offset = match.end()
    size = count * 3 * 4
    if offset + size > len(data):
        raise AuditError(f"{path} POINTS payload is truncated")
    points = np.frombuffer(data, dtype=">f4", count=count * 3, offset=offset).reshape((-1, 3)).copy()
    if not np.isfinite(points).all():
        raise AuditError(f"{path} contains non-finite points")
    return points, {"point_count": count, "points_offset": offset, "points_bytes": size}


def read_fluid_vtk(path: Path, expected_count: int, begin: int, count: int) -> tuple[np.ndarray, dict[str, Any]]:
    points, meta = read_vtk_points(path)
    if points.shape[0] != expected_count:
        raise AuditError(f"Fluid VTK count {points.shape[0]} != actual XML count {expected_count}")
    data = path.read_bytes()
    pdata = re.compile(rb"(?m)^POINT_DATA\s+(\d+)\r?\n").search(
        data, meta["points_offset"] + meta["points_bytes"]
    )
    if pdata is None or int(pdata.group(1)) != expected_count:
        raise AuditError("Fluid VTK has no matching POINT_DATA")
    scalar = re.compile(rb"(?m)^SCALARS\s+Idp\s+unsigned_int(?:\s+1)?\r?\n").search(data, pdata.end())
    if scalar is None:
        raise AuditError("Fluid VTK has no unsigned-int Idp scalar")
    lookup = re.match(rb"LOOKUP_TABLE\s+default\r?\n", data[scalar.end():])
    if lookup is None:
        raise AuditError("Fluid Idp scalar has no default lookup table")
    offset = scalar.end() + lookup.end()
    size = expected_count * 4
    if offset + size > len(data):
        raise AuditError("Fluid Idp payload is truncated")
    ids = np.frombuffer(data, dtype=">u4", count=expected_count, offset=offset).copy()
    global_ids = np.arange(begin, begin + count, dtype=np.uint32)
    local_ids = np.arange(count, dtype=np.uint32)
    if np.array_equal(np.sort(ids), np.sort(global_ids)):
        mapping = "GLOBAL_XML_PARTICLE_IDS"
    elif np.array_equal(np.sort(ids), local_ids):
        mapping = "LOCAL_FLUID_ORDER_TO_XML_IDS"
    else:
        raise AuditError("Fluid VTK Idp values do not match actual XML fluid range")
    return points, {**meta, "idp_mapping": mapping, "idp_count": int(ids.size), "idp_scalar": "unsigned_int"}


def axis_summary(points: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for axis, index in zip("xyz", range(3)):
        values = np.unique(points[:, index])
        diffs = np.diff(values)
        result[axis] = {
            "unique_count": int(values.size),
            "min_m": float(values[0]),
            "max_m": float(values[-1]),
            "spacing_min_m": float(diffs.min()) if diffs.size else 0.0,
            "spacing_max_m": float(diffs.max()) if diffs.size else 0.0,
        }
    return result


def derived_envelope(dp_m: float) -> dict[str, Any]:
    half = dp_m / 2.0
    return {
        "dp_m": dp_m,
        "pointref_m": [half, half, half],
        "fluid_selector": {
            "low_m": [OWNER_LOW_M[i] + half for i in range(3)],
            "size_m": [OWNER_SIZE_M[i] - dp_m for i in range(3)],
            "high_m": [OWNER_HIGH_M[i] - half for i in range(3)],
        },
        "boundary_xml_envelope": {
            "low_m": [OWNER_LOW_M[0] - half, OWNER_LOW_M[1] - half, OWNER_LOW_M[2] - half],
            "size_m": [OWNER_SIZE_M[0] + dp_m, OWNER_SIZE_M[1] + dp_m, TANK_SIZE_M[2] + half],
            "high_m": [OWNER_HIGH_M[0] + half, OWNER_HIGH_M[1] + half, TANK_SIZE_M[2]],
        },
        "basis": "half-cell pointref and boundary-envelope construction from the source owner/tank dimensions",
    }


def _close(left: list[float], right: list[float], tol: float = 1e-12) -> bool:
    return len(left) == len(right) and all(abs(a - b) <= tol for a, b in zip(left, right))


def relation(points: np.ndarray, low: list[float], high: list[float], tolerance: float) -> dict[str, Any]:
    lower = np.asarray(low, dtype=np.float64)
    upper = np.asarray(high, dtype=np.float64)
    inside = np.all((points >= lower - tolerance) & (points <= upper + tolerance), axis=1)
    return {
        "low_m": list(low), "high_m": list(high), "tolerance_m": tolerance,
        "inside_closed_count": int(inside.sum()), "outside_closed_count": int((~inside).sum()),
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise AuditError(f"{label} must be a JSON object")
    return value


def check_spec(spec: dict[str, Any], label: str, *, allow_parent_sentinel: bool = False) -> Path:
    if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
        raise AuditError(f"{label} lacks a path binding")
    path = require_file(spec["path"], label)
    expected = spec.get("sha256")
    actual = sha256(path)
    if expected == "PARENT_GUARD_COMPUTED" and allow_parent_sentinel:
        pass
    elif not isinstance(expected, str) or actual != expected:
        raise AuditError(f"{label} digest differs from its binding")
    if isinstance(spec.get("bytes"), int) and path.stat().st_size != spec["bytes"]:
        raise AuditError(f"{label} byte count differs from its binding")
    return path


def completed_receipt(path: Path, label: str) -> dict[str, Any]:
    receipt = load_json(path, label)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AuditError(f"{label} is not completed with return code 0")
    if receipt.get("schema") not in {None, "ds02.execution-receipt.v1"}:
        raise AuditError(f"{label} has an unexpected receipt schema")
    return receipt


def source_projection(report: dict[str, Any]) -> dict[str, Any]:
    binding = report.get("physical_binding") or {}
    geometry = binding.get("geometry") or {}
    initial = binding.get("initial_state") or {}
    return {
        "geometry": geometry,
        "density_kg_m3": binding.get("density_kg_m3"),
        "initial_state": initial,
        "controls": binding.get("controls"),
        "control_family_id": binding.get("control_family_id"),
        "geometry_family_id": binding.get("geometry_family_id"),
        "physical_case_id": binding.get("physical_case_id"),
    }


def historical_grid_audit(
    manifest: dict[str, Any], prior: dict[str, Any], input_paths: dict[str, Path]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = manifest.get("historical_grids")
    if not isinstance(rows, list) or [row.get("grid_id") for row in rows] != ["original_dp006", "coarse_dp0075", "fine_dp0048"]:
        raise AuditError("historical grid order must be original/coarse/fine")
    result: list[dict[str, Any]] = []
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        grid_id = row["grid_id"]
        expected = prior.get("cases", {}).get(grid_id)
        if not isinstance(expected, dict):
            raise AuditError(f"prior support lacks {grid_id}")
        xml = check_spec(row["xml"], f"{grid_id} generated XML")
        control = check_spec(row["control"], f"{grid_id} control")
        receipt_path = check_spec(row["receipt"], f"{grid_id} receipt")
        records[f"historical.{grid_id}.xml"] = record(xml)
        records[f"historical.{grid_id}.control"] = record(control)
        records[f"historical.{grid_id}.receipt"] = record(receipt_path)
        parsed = parse_xml(xml, grid_id)
        control_summary = parse_control(control, grid_id)
        receipt = completed_receipt(receipt_path, f"{grid_id} receipt")
        generated = expected.get("generated") or {}
        expected_forcing = (expected.get("forcing_control") or {}).get("file") or {}
        if records[f"historical.{grid_id}.control"]["sha256"] != expected_forcing.get("sha256"):
            raise AuditError(f"{grid_id} control does not match immutable ROOT081 report")
        for field, actual, target in (
            ("dp_m", parsed["dp_m"], generated.get("dp_m")),
            ("fluid_count", parsed["counts"].get("fluid"), generated.get("fluid_count")),
            ("total_particles", parsed["total_particles"], generated.get("total_particles")),
            ("massfluid_kg", parsed["massfluid_kg"], generated.get("massfluid_kg")),
        ):
            if isinstance(target, float):
                if abs(float(actual) - target) > 1e-12:
                    raise AuditError(f"{grid_id} {field} differs from ROOT081")
            elif actual != target:
                raise AuditError(f"{grid_id} {field} differs from ROOT081")
        if abs(parsed["sample_fluid_mass_kg"] - float(generated.get("sample_mass_kg"))) > 1e-9:
            raise AuditError(f"{grid_id} sample mass differs from ROOT081")
        if receipt.get("output_root") and Path(str(receipt["output_root"])).resolve() != Path(str(expected.get("receipt", {}).get("output_root", receipt["output_root"]))).resolve():
            # ROOT081 has the authoritative output path; if a producer omits it
            # in its compact receipt, the actual receipt path still remains a
            # valid immutable source record.
            raise AuditError(f"{grid_id} receipt output root differs from ROOT081")
        if not parsed["fluid_boxes"] or not parsed["bound_boxes"]:
            raise AuditError(f"{grid_id} lacks fluid/bound producer boxes")
        fluid_box = parsed["fluid_boxes"][0]
        bound_box = parsed["bound_boxes"][0]
        fluid_inside_owner = all(
            fluid_box["low_m"][axis] >= OWNER_LOW_M[axis] - 1e-9
            and fluid_box["high_m"][axis] <= OWNER_HIGH_M[axis] + 1e-9
            for axis in range(3)
        )
        boundary_covers_tank = all(
            bound_box["low_m"][axis] <= OWNER_LOW_M[axis] + 1e-9
            and bound_box["high_m"][axis] >= (OWNER_HIGH_M[axis] if axis < 2 else TANK_SIZE_M[axis]) - 1e-9
            for axis in range(3)
        )
        result.append({
            "grid_id": grid_id,
            "case_id": row.get("case_id"),
            "xml": records[f"historical.{grid_id}.xml"],
            "control": records[f"historical.{grid_id}.control"],
            "receipt": records[f"historical.{grid_id}.receipt"],
            "xml_summary": parsed,
            "control_summary": control_summary,
            "receipt_status": receipt.get("status"),
            "owner_geometry_inherited": {"low_m": OWNER_LOW_M, "size_m": OWNER_SIZE_M, "tank_size_m": TANK_SIZE_M},
            "continuous_owner_status": "SOURCE_CONTRACT_ONLY",
            "physical_interface_geometry_diagnostic": {
                "fluid_selector_inside_owner_box": fluid_inside_owner,
                "boundary_box_covers_owner_and_tank_extent": boundary_covers_tank,
                "not_a_continuous_owner_or_no_penetration_proof": True,
            },
            "control_semantic_comparison": {
                "header": control_summary["header"],
                "time_range_s": [control_summary["time_first_s"], control_summary["time_last_s"]],
                "byte_identity_with_candidate_source": records[f"historical.{grid_id}.control"]["sha256"] == SOURCE_CONTROL_SHA256,
            },
        })
    controls = [row["control_summary"] for row in result]
    result_meta = {
        "same_header": len({tuple(item["header"]) for item in controls}) == 1,
        "same_time_range": len({(item["time_first_s"], item["time_last_s"]) for item in controls}) == 1,
        "byte_identical": len({item["control"]["sha256"] for item in result}) == 1,
        "interpretation": "three source/control products are hash-closed; semantic header/time agreement does not prove identical forcing bytes or solver equivalence",
    }
    return result, {"historical_summary": result_meta, **records}


def candidate_audit(manifest: dict[str, Any], input_paths: dict[str, Path], pre: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], np.ndarray, np.ndarray, dict[str, Any], dict[str, Any]]:
    candidate = manifest.get("candidate")
    if not isinstance(candidate, dict):
        raise AuditError("candidate product binding is missing")
    report_path = input_paths["candidate.report"]
    receipt_path = input_paths["candidate.receipt"]
    generated_xml = input_paths["candidate.generated_xml"]
    generated_control = input_paths["candidate.generated_control"]
    fluid_vtk = input_paths["candidate.fluid_vtk"]
    bound_vtk = input_paths["candidate.bound_vtk"]
    report = load_json(report_path, "candidate GenCase report")
    receipt = completed_receipt(receipt_path, "candidate GenCase receipt")
    if report.get("schema") != "ds02.stage2.f3.s2.commensurate-dp003-gencase.v1" or report.get("status") != "COMPLETED_F3_S2_COMMENSURATE_DP003_GENCASE":
        raise AuditError("candidate report is not the reviewed official GenCase completion")
    if report.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise AuditError("candidate physical case differs")
    request = receipt.get("request", {})
    if isinstance(request, dict) and request.get("case_id") not in {None, candidate.get("case_id")}:
        raise AuditError("candidate receipt request case differs")
    if request is not None and not isinstance(request, dict):
        raise AuditError("candidate receipt request is not an object")
    if receipt.get("output_root") and Path(str(receipt["output_root"])).resolve() != Path(str(candidate["output_root"])).resolve():
        raise AuditError("candidate receipt output root differs from manifest")
    binding = report.get("source_binding") or {}
    if binding.get("source_xml", {}).get("sha256") != SOURCE_XML_SHA256:
        raise AuditError("candidate report source XML binding differs")
    if binding.get("source_control", {}).get("sha256") != SOURCE_CONTROL_SHA256:
        raise AuditError("candidate report source control binding differs")
    owner_binding = binding.get("continuous_owner") or {}
    if owner_binding.get("low_m") != OWNER_LOW_M or owner_binding.get("size_m") != OWNER_SIZE_M or abs(float(owner_binding.get("mass_kg", -1.0)) - OWNER_MASS_KG) > 1e-12:
        raise AuditError("candidate report continuous-owner binding differs")
    scope = report.get("scope") or {}
    if scope.get("solver_started") or scope.get("gpu_started") or scope.get("source_bi4_read") or scope.get("trajectory_h5_read"):
        raise AuditError("candidate report claims prohibited solver/native work")
    projection = parse_xml(generated_xml, "candidate generated XML")
    if abs(projection["dp_m"] - TARGET_DP_M) > 1e-12:
        raise AuditError("candidate generated XML dp differs")
    if projection["counts"].get("fluid") != EXPECTED_FLUID_COUNT:
        raise AuditError(f"candidate actual XML fluid count {projection['counts'].get('fluid')} != {EXPECTED_FLUID_COUNT}")
    if projection["counts"].get("fixed", 0) <= 0:
        raise AuditError("candidate actual XML fixed count is empty")
    if abs(projection["massfluid_kg"] - EXPECTED_MASSFLUID_KG) > 1e-12:
        raise AuditError("candidate actual XML MassFluid differs")
    if abs(projection["sample_fluid_mass_kg"] - EXPECTED_SAMPLE_MASS_KG) > 1e-9:
        raise AuditError("candidate actual XML sample mass differs")
    envelope = derived_envelope(TARGET_DP_M)
    fluid_box = projection["fluid_boxes"][0] if projection["fluid_boxes"] else None
    bound_box = projection["bound_boxes"][0] if projection["bound_boxes"] else None
    if fluid_box is None or bound_box is None:
        raise AuditError("candidate XML lacks fluid/bound boxes")
    if not _close(fluid_box["low_m"], envelope["fluid_selector"]["low_m"]) or not _close(fluid_box["size_m"], envelope["fluid_selector"]["size_m"]):
        raise AuditError("candidate fluid selector is not the dp-derived owner envelope")
    if not _close(bound_box["low_m"], envelope["boundary_xml_envelope"]["low_m"]) or not _close(bound_box["size_m"], envelope["boundary_xml_envelope"]["size_m"]):
        raise AuditError("candidate boundary XML box is not the dp-derived envelope")
    if projection["control_name"] != Path(manifest["source"]["control"]["path"]).name:
        raise AuditError("candidate generated XML control basename differs")
    if sha256(generated_control) != SOURCE_CONTROL_SHA256:
        raise AuditError("candidate generated control differs from source control")
    official = report.get("official_gencase") or {}
    generated_record = official.get("generated_xml") or {}
    if generated_record.get("path") and Path(str(generated_record["path"])).resolve() != generated_xml.resolve():
        raise AuditError("candidate report generated XML path differs")
    if generated_record.get("sha256") and generated_record["sha256"] != pre["candidate.generated_xml"]["sha256"]:
        raise AuditError("candidate report generated XML digest differs")
    estimate = report.get("preflight_estimate") or {}
    if estimate.get("fluid_particles") not in {None, EXPECTED_FLUID_COUNT}:
        raise AuditError("candidate estimate fluid count disagrees with design")
    begin = projection["counts"]["fixed"]
    fluid_points, fluid_meta = read_fluid_vtk(fluid_vtk, projection["counts"]["fluid"], begin, projection["counts"]["fluid"])
    bound_points, bound_meta = read_vtk_points(bound_vtk)
    if bound_meta["point_count"] != projection["counts"]["fixed"]:
        raise AuditError("candidate Bound VTK count does not equal actual XML fixed count")
    return projection, envelope, report, fluid_points, bound_points, fluid_meta, bound_meta


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "manifest")
    manifest_pre = record(manifest_path)
    manifest = load_json(manifest_path, "manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise AuditError("unexpected dp003 support manifest schema")
    if manifest.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise AuditError("manifest physical case differs")
    source = manifest.get("source") or {}
    source_paths = {
        "source.xml": check_spec(source["xml"], "source XML"),
        "source.control": check_spec(source["control"], "source control"),
        "source.prepared_report": check_spec(source["prepared_report"], "prepared source report"),
        "source.prior_support_report": check_spec(source["prior_support_report"], "prior support report"),
    }
    if sha256(source_paths["source.xml"]) != SOURCE_XML_SHA256 or sha256(source_paths["source.control"]) != SOURCE_CONTROL_SHA256:
        raise AuditError("source XML/control is not the reviewed S2 closure")
    if sha256(source_paths["source.prepared_report"]) != PREPARED_REPORT_SHA256 or sha256(source_paths["source.prior_support_report"]) != PRIOR_SUPPORT_SHA256:
        raise AuditError("source report closure differs")
    source_report = load_json(source_paths["source.prepared_report"], "prepared source report")
    projection = source_projection(source_report)
    geometry = projection["geometry"]
    initial = geometry.get("initial_fluid") or {}
    tank = geometry.get("tank") or {}
    if initial.get("low_m") != OWNER_LOW_M or initial.get("size_m") != OWNER_SIZE_M or tank.get("size_m") != TANK_SIZE_M:
        raise AuditError("prepared continuous owner/tank geometry differs")
    if (projection["initial_state"] or {}).get("initial_mass_total_kg") != OWNER_MASS_KG:
        raise AuditError("prepared continuous owner mass differs")
    prior_path = source_paths["source.prior_support_report"]
    prior = load_json(prior_path, "prior support report")
    input_paths: dict[str, Path] = {"manifest": manifest_path, **source_paths}
    historical_specs = manifest.get("historical_grids") or []
    for row in historical_specs:
        grid = row["grid_id"]
        input_paths[f"historical.{grid}.xml"] = require_file(row["xml"]["path"], f"{grid} XML")
        input_paths[f"historical.{grid}.control"] = require_file(row["control"]["path"], f"{grid} control")
        input_paths[f"historical.{grid}.receipt"] = require_file(row["receipt"]["path"], f"{grid} receipt")
    candidate = manifest.get("candidate") or {}
    for role in ("report", "receipt", "generated_xml", "generated_control", "fluid_vtk", "bound_vtk"):
        input_paths[f"candidate.{role}"] = require_file(candidate[role]["path"], f"candidate {role}")
    pre_records = capture_records(input_paths)
    if pre_records["manifest"] != manifest_pre:
        raise AuditError("manifest changed before audit")
    for role in ("source.xml", "source.control", "source.prepared_report", "source.prior_support_report"):
        if pre_records[role]["sha256"] != source[role.split(".", 1)[1]]["sha256"]:
            raise AuditError(f"{role} changed before audit")
    for role in ("candidate.report", "candidate.receipt", "candidate.generated_xml", "candidate.generated_control", "candidate.fluid_vtk", "candidate.bound_vtk"):
        spec = candidate[role.split(".", 1)[1]]
        expected = spec.get("sha256")
        if expected and expected != "PARENT_GUARD_COMPUTED" and pre_records[role]["sha256"] != expected:
            raise AuditError(f"{role} differs from candidate binding")
        if isinstance(spec.get("bytes"), int) and pre_records[role]["bytes"] != spec["bytes"]:
            raise AuditError(f"{role} byte count differs from candidate binding")
    historical, historical_records = historical_grid_audit(manifest, prior, input_paths)
    if pre_records["manifest"] != record(manifest_path):
        raise AuditError("manifest changed during source audit")
    def decode_candidate() -> tuple[Any, ...]:
        return candidate_audit(manifest, input_paths, pre_records)
    decoded, decode_pre, post_records = prepost_guarded_decode(input_paths, decode_candidate)
    if decode_pre != pre_records:
        raise AuditError("input changed between first pre-record and candidate decode")
    candidate_xml, envelope, candidate_report, fluid_points, bound_points, fluid_meta, bound_meta = decoded
    fluid_relation = relation(fluid_points, envelope["fluid_selector"]["low_m"], envelope["fluid_selector"]["high_m"], max(1e-8, TARGET_DP_M * 1e-5))
    owner_relation = relation(fluid_points, OWNER_LOW_M, OWNER_HIGH_M, max(1e-8, TARGET_DP_M * 1e-5))
    boundary_low = envelope["boundary_xml_envelope"]["low_m"]
    boundary_high = envelope["boundary_xml_envelope"]["high_m"]
    margin = HARD_VTK_MARGIN_MULTIPLIER * TARGET_DP_M + 2e-6
    boundary_vtk_relation = relation(bound_points, [x - margin for x in boundary_low], [x + margin for x in boundary_high], 0.0)
    post_source = {key: post_records[key] for key in pre_records}
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_F3_S2_DP003_INITIAL_SUPPORT_SOURCE_CLOSED",
        "physical_case_id": PHYSICAL_CASE_ID,
        "source": {
            "xml": pre_records["source.xml"],
            "control": pre_records["source.control"],
            "prepared_report": pre_records["source.prepared_report"],
            "prior_support_report": pre_records["source.prior_support_report"],
            "continuous_owner": {"low_m": OWNER_LOW_M, "size_m": OWNER_SIZE_M, "tank_size_m": TANK_SIZE_M, "mass_kg": OWNER_MASS_KG},
        },
        "historical_three_grid": {"rows": historical, "comparison": historical_records["historical_summary"]},
        "candidate": {
            "report": pre_records["candidate.report"],
            "receipt": pre_records["candidate.receipt"],
            "generated_xml": pre_records["candidate.generated_xml"],
            "generated_control": pre_records["candidate.generated_control"],
            "generated_xml_summary_actual": candidate_xml,
            "actual_counts_authoritative": True,
            "preflight_estimate_is_not_count_evidence": True,
            "gencase_report_status": candidate_report.get("status"),
        },
        "dp_derived_envelope": {
            **envelope,
            "source_owner_preserved": True,
            "fluid_selector_is_discrete_producer_envelope": True,
            "boundary_xml_is_interface_envelope_only": True,
            "physical_fate_not_inferred": True,
        },
        "vtk_support": {
            "fluid": {**fluid_meta, "input_record": pre_records["candidate.fluid_vtk"], "axis_summary": axis_summary(fluid_points),
                       "dp_selector_relation": fluid_relation, "owner_relation": owner_relation},
            "bound": {**bound_meta, "input_record": pre_records["candidate.bound_vtk"], "axis_summary": axis_summary(bound_points),
                       "conservative_xml_envelope_relation": boundary_vtk_relation,
                       "conservative_margin_m": margin,
                       "interpretation": "finite/count and conservative envelope diagnostic; not a no-penetration or physical-flux proof"},
        },
        "input_stability": {
            "pre_decode": pre_records,
            "pre_decode_immediate": decode_pre,
            "post_decode": post_source,
            "all_records_equal": pre_records == decode_pre == post_source,
            "pre_record_completed_before_any_xml_or_vtk_decode": True,
            "post_record_completed_after_candidate_decode": True,
            "parent_guard_status": "PARENT_GUARD_COMPUTED_REQUIRED_EXTERNAL_RECEIPT",
            "worker_first_sha_is_authoritative_for_this_process": True,
        },
        "scientific_status": {
            "source_control_owner_and_initial_geometry": "CLOSED_FOR_THIS_AUDIT",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "continuous_owner_validation": "SOURCE_CONTRACT_ONLY",
            "physical_interface_no_penetration": "UNKNOWN",
            "physical_fate": "UNKNOWN", "flux": "UNKNOWN", "dynamics": "UNKNOWN",
        },
        "scope": {
            "gencase_started": False, "solver_started": False, "gpu_started": False,
            "fluid_vtk_read": True, "bound_vtk_read": True,
            "bi4_opened": False, "hdf5_opened": False, "partvtk_opened": False,
            "old_products_modified": False,
        },
    }
    write_new(output_path, report)
    return report


def self_test() -> dict[str, Any]:
    payload = (
        b"# vtk DataFile Version 3.0\nsmall\nBINARY\nDATASET POLYDATA\n"
        b"POINTS 2 float\n" + struct.pack(">ffffff", -0.4485, -0.0885, 0.0015, 0.4485, 0.0885, 0.0885)
        + b"\nPOINT_DATA 2\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n"
        + struct.pack(">II", 10, 11) + b"\n"
    )
    import tempfile
    with tempfile.TemporaryDirectory(prefix="f3-dp003-support-") as directory:
        path = Path(directory) / "fluid.vtk"
        path.write_bytes(payload)
        points, meta = read_fluid_vtk(path, 2, 10, 2)
        if meta["idp_mapping"] != "GLOBAL_XML_PARTICLE_IDS" or not np.isfinite(points).all():
            raise AssertionError("positive VTK fixture failed")
        bad = Path(directory) / "bad.vtk"
        bad.write_bytes(payload.replace(b"unsigned_int", b"float"))
        try:
            read_fluid_vtk(bad, 2, 10, 2)
        except AuditError:
            pass
        else:
            raise AssertionError("wrong Idp type accepted")
    env = derived_envelope(TARGET_DP_M)
    if env["fluid_selector"]["low_m"] != [-0.4485, -0.0885, 0.0015]:
        raise AssertionError("dp-derived selector envelope changed")
    return {"status": "PASS", "bi4_opened": False, "hdf5_opened": False, "gencase_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            result = self_test()
        else:
            if not args.manifest or not args.output:
                parser.error("--manifest and --output are required")
            result = audit(Path(args.manifest), Path(args.output))
    except Exception as exc:
        print(f"F3 dp003 initial support QA failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"schema": result.get("schema", "self-test"), "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

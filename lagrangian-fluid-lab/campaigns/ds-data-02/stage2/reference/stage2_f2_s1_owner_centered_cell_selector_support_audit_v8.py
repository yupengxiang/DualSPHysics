#!/usr/bin/env python3
"""Guarded F2-S1 cell-selector support audit (V8).

This worker is deliberately separate from the consumed V4/V6 audits.  The
ROOT076 GenCase product is a new representation: its generated XML contains
27,750 fluid particles in three 9,250-particle blocks, while the continuous
owner remains the three frozen 0.325 x 0.22 x 0.088 m source boxes (18.876 kg
at rho0=1000).  The worker checks that representation after the v8 parent has
reserved the CPU attempt.  It reads no BI4, HDF5, solver output, or source
history.  It computes full pre/post SHA and complete stat records for the
generated Fluid/Bound VTK files itself; those files are therefore explicitly
worker-owned guarded inputs, not silently treated as v8 parent input hashes.

The report is an initial support/mass/control diagnostic only.  It never
rescale particles and never grants QI/QN/QE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import tempfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


OWNER_MASS_KG = 18.876
OWNER_LAYER_LOWS = [
    [0.05, -0.11, 0.700],
    [0.05, -0.11, 0.788],
    [0.05, -0.11, 0.876],
]
OWNER_LAYER_SIZE = [0.325, 0.22, 0.088]
EXPECTED_DP = 0.0088
EXPECTED_SHAPE_MODE = "dp | actual | bound"
EXPECTED_SELECTOR_LOWS = [
    [0.0541, -0.1056, 0.7044],
    [0.0541, -0.1056, 0.7924],
    [0.0541, -0.1056, 0.8804],
]
EXPECTED_SELECTOR_SIZE = [0.3168, 0.2112, 0.0792]
EXPECTED_BLOCK_COUNT = 9250
EXPECTED_FLUID_COUNT = 27750
TOL = 1e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, digest: bool = True) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path) if digest else None,
    }


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable audit output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def lname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def finite(values: list[float], label: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"non-finite {label}: {values}")


def fattr(node: ET.Element, name: str, label: str | None = None) -> float:
    label = label or name
    value = float(node.attrib[name])
    if not math.isfinite(value):
        raise ValueError(f"non-finite {label}")
    return value


def vec(node: ET.Element | None, label: str) -> list[float] | None:
    if node is None:
        return None
    values = [fattr(node, axis, f"{label}.{axis}") for axis in "xyz"]
    finite(values, label)
    return values


def parse_box(node: ET.Element, label: str) -> dict[str, Any]:
    point = next((child for child in node if lname(child.tag) == "point"), None)
    size = next((child for child in node if lname(child.tag) == "size"), None)
    low = vec(point, f"{label}.point")
    extent = vec(size, f"{label}.size")
    if low is None or extent is None:
        raise ValueError(f"{label} missing point/size")
    if any(value <= 0 for value in extent):
        raise ValueError(f"{label} has non-positive size")
    high = [low[i] + extent[i] for i in range(3)]
    finite(high, f"{label}.high")
    layers = next((child for child in node if lname(child.tag) == "layers"), None)
    fill = next((child.text or "" for child in node if lname(child.tag) == "boxfill"), "").strip()
    return {
        "low_m": low,
        "high_m": high,
        "size_m": extent,
        "boxfill": fill,
        "layers": dict(layers.attrib) if layers is not None else None,
        "comment": node.get("cmt"),
    }


def parse_xml(path: Path, *, generated: bool) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = next((node for node in root.iter() if lname(node.tag) == "definition"), None)
    if definition is None:
        raise ValueError(f"missing definition in {path}")
    dp = fattr(definition, "dp", "definition.dp")
    pointref = vec(next((child for child in definition if lname(child.tag) == "pointref"), None), "definition.pointref")
    pointmin = vec(next((child for child in definition if lname(child.tag) == "pointmin"), None), "definition.pointmin")
    pointmax = vec(next((child for child in definition if lname(child.tag) == "pointmax"), None), "definition.pointmax")
    mainlist = next((node for node in root.iter() if lname(node.tag) == "mainlist"), None)
    if mainlist is None:
        raise ValueError(f"missing geometry mainlist in {path}")
    shape_mode = "full"
    box_limit = "full"
    mkfluid: int | None = None
    mkbound: int | None = None
    fluid_boxes: list[dict[str, Any]] = []
    boundary_boxes: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    for child in list(mainlist):
        tag = lname(child.tag)
        if tag == "setshapemode":
            shape_mode = (child.text or "").strip()
            operations.append({"op": tag, "value": shape_mode})
        elif tag == "setboxlimitmode":
            box_limit = child.get("mode", "UNKNOWN")
            operations.append({"op": tag, "mode": box_limit})
        elif tag == "setmkfluid":
            mkfluid = int(child.attrib["mk"]); mkbound = None
            operations.append({"op": tag, "mkfluid": mkfluid})
        elif tag == "setmkbound":
            mkbound = int(child.attrib["mk"]); mkfluid = None
            operations.append({"op": tag, "mkbound": mkbound})
        elif tag == "drawbox":
            box = parse_box(child, "drawbox")
            box.update({"box_limit_mode": box_limit, "mkfluid": mkfluid, "mkbound": mkbound})
            if mkfluid is not None:
                fluid_boxes.append(box)
            elif mkbound is not None:
                boundary_boxes.append(box)
            else:
                raise ValueError("drawbox has no active MK")
            operations.append({"op": tag, "box": box})
        elif tag in {"setdrawmode", "clipplane", "clipreset", "shapeout", "drawextrude"}:
            operations.append({"op": tag, "attributes": dict(child.attrib), "text": (child.text or "").strip()})

    parameters = {
        node.get("key"): node.get("value")
        for node in root.iter()
        if lname(node.tag) == "parameter" and node.get("key") is not None
    }
    cfl_values = [fattr(node, "value", "cflnumber") for node in root.iter() if lname(node.tag) == "cflnumber"]
    motion_files = [node.get("name") for node in root.iter() if lname(node.tag) == "file" and node.get("name")]
    constantsdef = next((node for node in root.iter() if lname(node.tag) == "constantsdef"), None)
    gravity = vec(constantsdef.find("gravity") if constantsdef is not None else None, "gravity")

    result: dict[str, Any] = {
        "path": str(path.resolve()),
        "dp_m": dp,
        "pointref_m": pointref,
        "pointmin_m": pointmin,
        "pointmax_m": pointmax,
        "shape_mode": shape_mode,
        "fluid_boxes": fluid_boxes,
        "boundary_boxes": boundary_boxes,
        "operations": operations,
        "parameters": parameters,
        "cflnumber": cfl_values,
        "gravity_m_per_s2": gravity,
        "motion_files": motion_files,
        "particles_summary": None,
        "fluid_blocks": [],
        "particle_blocks": [],
        "fluid_count": None,
        "massfluid_kg": None,
    }
    if not generated:
        return result
    particles = next((node for node in root.iter() if lname(node.tag) == "particles"), None)
    if particles is None:
        raise ValueError(f"generated XML has no particles: {path}")
    blocks = []
    for node in particles:
        if lname(node.tag) != "fluid":
            continue
        if all(key in node.attrib for key in ("mkfluid", "mk", "begin", "count")):
            blocks.append({
                "mkfluid": int(node.attrib["mkfluid"]),
                "mk": int(node.attrib["mk"]),
                "begin": int(node.attrib["begin"]),
                "count": int(node.attrib["count"]),
            })
    if not blocks:
        raise ValueError("generated XML has no typed fluid blocks")
    particle_blocks = []
    for node in particles:
        tag = lname(node.tag)
        if tag not in {"fixed", "moving", "floating", "fluid"}:
            continue
        if all(key in node.attrib for key in ("begin", "count")):
            particle_blocks.append({
                "kind": tag,
                "mk": node.get("mk"),
                "mkfluid": node.get("mkfluid"),
                "begin": int(node.attrib["begin"]),
                "count": int(node.attrib["count"]),
            })
    mass_node = next((node for node in root.iter() if lname(node.tag) == "massfluid"), None)
    if mass_node is None:
        raise ValueError("generated XML has no massfluid")
    mass = fattr(mass_node, "value", "massfluid")
    result.update({
        "particles_summary": dict(particles.attrib),
        "fluid_blocks": blocks,
        "particle_blocks": particle_blocks,
        "fluid_count": sum(item["count"] for item in blocks),
        "massfluid_kg": mass,
    })
    return result


def read_vtk_points(path: Path, expected_count: int | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    data = path.read_bytes()
    match = re.compile(rb"(?m)^POINTS\s+(\d+)\s+float\r?\n").search(data)
    if match is None:
        raise ValueError(f"missing POINTS in {path}")
    count = int(match.group(1))
    if expected_count is not None and count != expected_count:
        raise ValueError(f"VTK point count {count} != expected {expected_count}")
    offset = match.end()
    payload_bytes = count * 3 * np.dtype(">f4").itemsize
    if offset + payload_bytes > len(data):
        raise ValueError(f"truncated POINTS payload in {path}")
    points = np.frombuffer(data, dtype=">f4", count=count * 3, offset=offset).reshape((-1, 3)).copy()
    if not np.isfinite(points).all():
        raise ValueError(f"non-finite VTK points in {path}")
    return points, {"point_count": count, "points_payload_offset": offset, "points_payload_bytes": payload_bytes}


def read_vtk_fluid(path: Path, expected_count: int, blocks: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    points, header = read_vtk_points(path, expected_count)
    data = path.read_bytes()
    point_data = re.compile(rb"(?m)^POINT_DATA\s+(\d+)\r?\n").search(data, header["points_payload_offset"] + header["points_payload_bytes"])
    if point_data is None or int(point_data.group(1)) != expected_count:
        raise ValueError("missing matching POINT_DATA")
    scalar_matches = list(re.compile(rb"(?m)^SCALARS\s+([^\s]+)\s+([^\s]+)(?:\s+(\d+))?\r?\n").finditer(data, point_data.end()))
    idp_matches = [item for item in scalar_matches if item.group(1) == b"Idp"]
    if len(idp_matches) != 1:
        raise ValueError(f"expected one Idp scalar, got {len(idp_matches)}")
    scalar = idp_matches[0]
    scalar_type = scalar.group(2).decode("ascii", errors="replace")
    components = int(scalar.group(3) or b"1")
    if scalar_type != "unsigned_int" or components != 1:
        raise ValueError(f"Idp contract mismatch: {scalar_type!r}/{components}")
    lookup = re.match(rb"LOOKUP_TABLE\s+default\r?\n", data[scalar.end():])
    if lookup is None:
        raise ValueError("Idp has no LOOKUP_TABLE default")
    ids_offset = scalar.end() + lookup.end()
    ids_bytes = expected_count * np.dtype(">u4").itemsize
    if ids_offset + ids_bytes > len(data):
        raise ValueError("truncated Idp payload")
    raw_ids = np.frombuffer(data, dtype=">u4", count=expected_count, offset=ids_offset).copy()
    global_ids = np.concatenate([
        np.arange(item["begin"], item["begin"] + item["count"], dtype=np.uint32)
        for item in blocks
    ])
    if np.array_equal(np.sort(raw_ids), np.sort(global_ids)):
        mapped = raw_ids
        mapping = "GLOBAL_XML_PARTICLE_IDS"
    elif np.array_equal(np.sort(raw_ids), np.arange(expected_count, dtype=np.uint32)):
        local_to_global = np.empty(expected_count, dtype=np.uint32)
        cursor = 0
        for item in blocks:
            n = item["count"]
            local_to_global[cursor:cursor + n] = np.arange(item["begin"], item["begin"] + n, dtype=np.uint32)
            cursor += n
        mapped = local_to_global[raw_ids]
        mapping = "LOCAL_FLUID_ORDER_TO_XML_IDS"
    else:
        raise ValueError("Idp values match neither XML global ranges nor local fluid order")
    separator = "NONE"
    ids_end = ids_offset + ids_bytes
    if data[ids_end:ids_end + 2] == b"\r\n":
        separator = "CRLF"
    elif data[ids_end:ids_end + 1] == b"\n":
        separator = "LF"
    next_offset = ids_end + (2 if separator == "CRLF" else 1 if separator == "LF" else 0)
    next_header = data[next_offset:next_offset + 120].split(b"\n", 1)[0].decode("ascii", errors="replace")
    return points, mapped, {
        **header,
        "idp_scalar_name": "Idp",
        "idp_scalar_type": scalar_type,
        "idp_components": components,
        "idp_payload_offset": ids_offset,
        "idp_payload_bytes": ids_bytes,
        "idp_mapping": mapping,
        "idp_count": int(raw_ids.size),
        "post_payload_separator": separator,
        "next_section_header": next_header,
        "idp_contract": "SCALARS Idp unsigned_int; LOOKUP_TABLE default; explicit big-endian uint32 payload; no FIELD-order assumption",
    }


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
            "spacing_values_m": sorted({round(float(value), 10) for value in diffs})[:20],
        }
    return result


def relation(points: np.ndarray, low: list[float], size: list[float], dp: float) -> dict[str, Any]:
    lo = np.asarray(low, dtype=np.float64)
    hi = lo + np.asarray(size, dtype=np.float64)
    tol = max(1e-7, dp * 1e-5)
    inside = np.all((points >= lo - tol) & (points <= hi + tol), axis=1)
    strict = np.all((points > lo + tol) & (points < hi - tol), axis=1)
    return {
        "low_m": [float(value) for value in lo],
        "high_m": [float(value) for value in hi],
        "tolerance_m": tol,
        "inside_closed_count": int(inside.sum()),
        "outside_closed_count": int((~inside).sum()),
        "strict_interior_count": int((strict).sum()),
        "boundary_tie_count": int((inside & ~strict).sum()),
    }


def near(a: list[float] | None, b: list[float], tol: float = TOL) -> bool:
    return a is not None and len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def controls(xml: dict[str, Any]) -> dict[str, Any]:
    keys = ("TimeMax", "TimeOut", "Boundary", "Kernel", "ViscoTreatment", "Visco", "DensityDT", "Shifting", "SlipMode", "StepAlgorithm")
    return {key: xml["parameters"].get(key) for key in keys}


def compare_control(source: dict[str, Any], candidate: dict[str, Any], generated: dict[str, Any], source_motion_sha: str, candidate_motion_sha: str) -> dict[str, Any]:
    return {
        "source_shape_mode": source["shape_mode"],
        "candidate_shape_mode": candidate["shape_mode"],
        "generated_shape_mode": generated["shape_mode"],
        "expected_candidate_shape_mode": EXPECTED_SHAPE_MODE,
        "source_dp_m": source["dp_m"],
        "candidate_dp_m": candidate["dp_m"],
        "generated_dp_m": generated["dp_m"],
        "source_pointref_m": source["pointref_m"],
        "candidate_pointref_m": candidate["pointref_m"],
        "source_motion_sha256": source_motion_sha,
        "candidate_motion_sha256": candidate_motion_sha,
        "motion_byte_identical": source_motion_sha == candidate_motion_sha,
        "source_cflnumber": source["cflnumber"],
        "candidate_cflnumber": candidate["cflnumber"],
        "generated_cflnumber": generated["cflnumber"],
        "source_parameters": controls(source),
        "candidate_parameters": controls(candidate),
        "generated_parameters": controls(generated),
        "source_boundary_boxes": source["boundary_boxes"],
        "candidate_boundary_boxes": candidate["boundary_boxes"],
        "boundary_geometry_equal": source["boundary_boxes"] == candidate["boundary_boxes"],
        "control_scope": "source/candidate/generated XML and motion closure only; no CFD or solver qualification",
    }


def _receipt_status(receipt: dict[str, Any]) -> tuple[str, int | None]:
    status = str(receipt.get("status", "")).lower()
    return status, receipt.get("returncode")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    generated_xml = args.generated_xml.resolve()
    fluid_vtk = args.fluid_vtk.resolve()
    bound_vtk = args.bound_vtk.resolve()
    receipt_path = args.receipt.resolve()
    candidate_def = args.candidate_def.resolve()
    source_def = args.source_def.resolve()
    candidate_motion = args.candidate_motion.resolve()
    source_motion = args.source_motion.resolve()
    gencase_request_path = args.gencase_request.resolve()
    owner_closure = args.owner_closure.resolve() if args.owner_closure else None

    dynamic_paths = {"generated_xml": generated_xml, "fluid_vtk": fluid_vtk, "bound_vtk": bound_vtk, "execution_receipt": receipt_path}
    dynamic_pre = {name: record(path) for name, path in dynamic_paths.items()}
    static_paths = {
        "candidate_def": candidate_def,
        "source_def": source_def,
        "candidate_motion": candidate_motion,
        "source_motion": source_motion,
        "gencase_request": gencase_request_path,
    }
    if owner_closure is not None:
        static_paths["owner_closure"] = owner_closure
    static_pre = {name: record(path) for name, path in static_paths.items()}
    expected_static = {
        "candidate_def": args.expected_candidate_def_sha,
        "source_def": args.expected_source_def_sha,
        "candidate_motion": args.expected_candidate_motion_sha,
        "source_motion": args.expected_source_motion_sha,
        "gencase_request": args.expected_gencase_request_sha,
        "owner_closure": args.expected_owner_closure_sha,
    }
    for key, expected in expected_static.items():
        if expected:
            if key not in static_pre or static_pre[key]["sha256"] != expected:
                raise ValueError(f"{key} SHA mismatch before audit")
    for key, expected in (("generated_xml", args.expected_generated_xml_sha), ("execution_receipt", args.expected_receipt_sha)):
        if expected and dynamic_pre[key]["sha256"] != expected:
            raise ValueError(f"{key} SHA mismatch before audit")

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    status, returncode = _receipt_status(receipt)
    if status not in {"completed", "complete", "success", "completed0"} or returncode not in (0, None):
        raise ValueError(f"GenCase receipt is not a completed zero-return product: {status}/{returncode}")
    request = json.loads(gencase_request_path.read_text(encoding="utf-8"))
    embedded = receipt.get("request")
    request_sha = receipt.get("request_sha256")
    if request_sha and request_sha != sha256(gencase_request_path):
        raise ValueError("terminal receipt request_sha256 does not match bound GenCase request")
    if isinstance(embedded, dict):
        if embedded.get("case_id") != request.get("case_id") or embedded.get("attempt_id") != request.get("attempt_id"):
            raise ValueError("terminal receipt embedded request identity differs from bound GenCase request")
    actual_out = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if actual_out != generated_xml.parent:
        raise ValueError(f"receipt output_root {actual_out} != generated input parent {generated_xml.parent}")

    source = parse_xml(source_def, generated=False)
    candidate = parse_xml(candidate_def, generated=False)
    generated = parse_xml(generated_xml, generated=True)
    if generated["fluid_count"] != EXPECTED_FLUID_COUNT:
        raise ValueError(f"generated XML fluid count {generated['fluid_count']} != expected {EXPECTED_FLUID_COUNT}")
    if len(generated["fluid_blocks"]) != 3 or any(block["count"] != EXPECTED_BLOCK_COUNT for block in generated["fluid_blocks"]):
        raise ValueError("generated XML fluid blocks are not three 9250-particle ranges")

    points, ids, fluid_contract = read_vtk_fluid(fluid_vtk, generated["fluid_count"], generated["fluid_blocks"])
    bound_points, bound_contract = read_vtk_points(bound_vtk)
    block_reports = []
    for index, block in enumerate(generated["fluid_blocks"]):
        selected = points[(ids >= block["begin"]) & (ids < block["begin"] + block["count"])]
        if selected.shape[0] != block["count"]:
            raise ValueError(f"fluid block {index} Idp count mismatch")
        owner_rel = relation(selected, OWNER_LAYER_LOWS[index], OWNER_LAYER_SIZE, generated["dp_m"])
        selector_rel = relation(selected, generated["fluid_boxes"][index]["low_m"], generated["fluid_boxes"][index]["size_m"], generated["dp_m"])
        block_reports.append({
            **block,
            "vtk_count": int(selected.shape[0]),
            "sample_mass_kg": float(selected.shape[0] * generated["massfluid_kg"]),
            "axis_summary": axis_summary(selected),
            "owner_source_box_relation": owner_rel,
            "candidate_selector_relation": selector_rel,
        })

    dynamic_post = {name: record(path) for name, path in dynamic_paths.items()}
    static_post = {name: record(path) for name, path in static_paths.items()}
    if dynamic_pre != dynamic_post:
        raise RuntimeError("generated XML/VTK/receipt changed during F2 V8 audit")
    if static_pre != static_post:
        raise RuntimeError("source/control binding changed during F2 V8 audit")

    sample_mass = float(generated["fluid_count"] * generated["massfluid_kg"])
    relative = sample_mass / OWNER_MASS_KG - 1.0
    if abs(relative) <= 0.01:
        mass_gate = "PASS_SOURCE_OWNER_SAMPLE_DIAGNOSTIC_WITHIN_ONE_PERCENT"
    elif abs(relative) <= 0.02:
        mass_gate = "MARGINAL_SOURCE_OWNER_SAMPLE_DIAGNOSTIC_ONE_TO_TWO_PERCENT"
    else:
        mass_gate = "HARDFAIL_SOURCE_OWNER_SAMPLE_DIAGNOSTIC_OVER_TWO_PERCENT"
    support_outside = sum(item["owner_source_box_relation"]["outside_closed_count"] for item in block_reports)
    support_gate = "PASS_DISCRETE_SUPPORT_INSIDE_FROZEN_OWNER_BOXES" if support_outside == 0 else "FAIL_DISCRETE_SUPPORT_OUTSIDE_FROZEN_OWNER_BOXES"
    selector_ok = (
        abs(candidate["dp_m"] - EXPECTED_DP) <= TOL
        and candidate["shape_mode"] == EXPECTED_SHAPE_MODE
        and len(candidate["fluid_boxes"]) == 3
        and all(near(candidate["fluid_boxes"][i]["low_m"], EXPECTED_SELECTOR_LOWS[i]) and near(candidate["fluid_boxes"][i]["size_m"], EXPECTED_SELECTOR_SIZE) for i in range(3))
    )
    source_geometry_ok = (
        abs(source["dp_m"] - 0.01) <= TOL
        and source["shape_mode"] == "dp | bound"
        and len(source["fluid_boxes"]) == 3
        and all(near(source["fluid_boxes"][i]["low_m"], OWNER_LAYER_LOWS[i]) and near(source["fluid_boxes"][i]["size_m"], OWNER_LAYER_SIZE) for i in range(3))
    )
    control = compare_control(source, candidate, generated, static_pre["source_motion"]["sha256"], static_pre["candidate_motion"]["sha256"])
    return {
        "schema": "ds02.stage2.f2-s1.owner-centered-cell-selector-support-audit.v8",
        "status": "COMPLETED_INITIAL_XML_VTK_SUPPORT_AUDIT",
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "scope": {
            "generated_xml_read": True,
            "generated_fluid_vtk_read": True,
            "generated_bound_vtk_read": True,
            "terminal_gencase_receipt_read": True,
            "source_candidate_motion_read": True,
            "native_bi4_read": False,
            "hdf5_read": False,
            "solver_started": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "parent_v8_input_closure": {
            "runtime_input_files_are_digest_bound": True,
            "runtime_input_files_exclude_large_vtk": True,
            "worker_owned_large_inputs": [str(fluid_vtk), str(bound_vtk)],
            "worker_owned_large_inputs_pre_post_sha_and_complete_stat": True,
            "parent_receipt_does_not_claim_vtk_input_hash": True,
            "source_integrity_scope": "worker post-reservation pre/post hash/stat only for generated VTK; v8 runtime hashes listed small inputs",
        },
        "inputs": {
            "dynamic_pre": dynamic_pre,
            "dynamic_post": dynamic_post,
            "dynamic_pre_post_equal": True,
            "static_pre": static_pre,
            "static_post": static_post,
            "static_pre_post_equal": True,
            "complete_stat_and_sha": True,
        },
        "receipt_scope": {key: receipt.get(key) for key in ("status", "returncode", "output_root", "bytes", "elapsed_seconds", "cpu_core_seconds", "terminal_storage_guard")},
        "generated_definition": {
            key: generated[key] for key in ("dp_m", "pointref_m", "pointmin_m", "pointmax_m", "shape_mode", "particles_summary", "fluid_blocks", "particle_blocks", "fluid_count", "massfluid_kg", "fluid_boxes", "boundary_boxes", "operations")
        },
        "source_and_candidate": {
            "source": {key: source[key] for key in ("dp_m", "pointref_m", "shape_mode", "fluid_boxes", "boundary_boxes", "parameters", "cflnumber", "motion_files")},
            "candidate": {key: candidate[key] for key in ("dp_m", "pointref_m", "shape_mode", "fluid_boxes", "boundary_boxes", "parameters", "cflnumber", "motion_files")},
            "expected_candidate_representation": {"dp_m": EXPECTED_DP, "shape_mode": EXPECTED_SHAPE_MODE, "selector_low_m": EXPECTED_SELECTOR_LOWS, "selector_size_m": EXPECTED_SELECTOR_SIZE},
            "candidate_selector_contract": "PASS" if selector_ok else "FAIL",
            "frozen_source_owner_box_contract": "PASS" if source_geometry_ok else "FAIL",
        },
        "vtk_support": {
            "fluid": {key: value for key, value in fluid_contract.items() if key != "mapped_ids"},
            "fluid_axis_summary": axis_summary(points),
            "bound": bound_contract,
            "bound_axis_summary": axis_summary(bound_points),
            "per_mk": block_reports,
            "support_gate": support_gate,
            "interpretation": "Observed discrete support is compared with frozen owner boxes. It does not prove continuous clipping, quadrature, or solver equivalence.",
        },
        "control_audit": control,
        "mass_audit": {
            "owner_continuous_mass_kg": OWNER_MASS_KG,
            "generated_fluid_count": generated["fluid_count"],
            "generated_massfluid_kg": generated["massfluid_kg"],
            "generated_sample_mass_kg": sample_mass,
            "relative_error_vs_frozen_owner_fraction": relative,
            "relative_error_vs_frozen_owner_percent": relative * 100.0,
            "gate": mass_gate,
            "mass_rescale": False,
            "continuous_mass_semantics": "18.876 kg is the frozen source drawbox owner target; generated sample sum is a discrete diagnostic and cannot redefine it.",
        },
        "qualification": {
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "reason": "initial XML/VTK support/control audit only; no CFD or physical observer qualification",
            "support_gate": support_gate,
            "mass_gate": mass_gate,
        },
    }


def self_test() -> dict[str, Any]:
    # Exercise the real binary framing, including a non-FIELD section after
    # Idp. This catches the old offset/flags and FIELD-order assumptions.
    points = struct.pack(">6f", 0.0, 0.0, 0.0, 0.01, 0.0, 0.0)
    ids = struct.pack(">2I", 101, 102)
    payload = (
        b"# vtk DataFile Version 3.0\nfixture\nBINARY\nDATASET POLYDATA\n"
        b"POINTS 2 float\n" + points + b"\nPOINT_DATA 2\n"
        b"SCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n" + ids + b"\nFIELD FieldData 0\n"
    )
    with tempfile.TemporaryDirectory(prefix="f2-v8-vtk-selftest-") as directory:
        path = Path(directory) / "fixture.vtk"
        path.write_bytes(payload)
        decoded_points, decoded_ids, contract = read_vtk_fluid(path, 2, [{"begin": 101, "count": 2}])
        if decoded_points.shape != (2, 3) or decoded_ids.tolist() != [101, 102]:
            raise AssertionError("binary VTK fixture failed")
        bad = Path(directory) / "bad.vtk"
        bad.write_bytes(payload.replace(b"unsigned_int", b"float"))
        try:
            read_vtk_fluid(bad, 2, [{"begin": 101, "count": 2}])
        except ValueError:
            pass
        else:
            raise AssertionError("wrong Idp type accepted")
    return {"status": "PASS", "vtk_positive": True, "wrong_idp_rejected": True, "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("generated-xml", "fluid-vtk", "bound-vtk", "receipt", "candidate-def", "source-def", "candidate-motion", "source-motion", "gencase-request", "owner-closure", "output"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("candidate-def", "source-def", "candidate-motion", "source-motion", "gencase-request", "owner-closure", "generated-xml", "receipt"):
        parser.add_argument(f"--expected-{name}-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = [args.generated_xml, args.fluid_vtk, args.bound_vtk, args.receipt, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.gencase_request, args.output]
    if any(value is None for value in required):
        parser.error("all generated/static paths and --output are required unless --self-test")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "mass_gate": report["mass_audit"]["gate"], "support_gate": report["vtk_support"]["support_gate"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

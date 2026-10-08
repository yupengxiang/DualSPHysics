#!/usr/bin/env python3
"""Audit the actual F5-S1 fine GenCase product, V3.

This is a bounded XML/VTK audit for the ROOT068 GenCase product.  It reads
the generated XML, the generated fluid and bound VTK point sets, and the
terminal GenCase receipt.  The candidate/source Def, transformed motion
table, owner contract, and previously verified source-control records are
checked as small immutable inputs.  No BI4, HDF5, solver output, or CFD is
read.

The source particle mass (253.264 kg) is retained as a discrete producer
diagnostic.  The owner contract supplies a sloped closed bed, finite tank,
and clipped fluid-box geometry but does not publish a scalar continuous
fluid mass.  The audit therefore reports the unclipped box volume only as a
geometric envelope and never upgrades the source sample-mass comparison into
a continuous-initial-state pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


SOURCE_SAMPLE_MASS_KG = 253.264
SOURCE_DP_M = 0.02
EXPECTED_CANDIDATE_DP_M = 0.0155478404873736
SOURCE_PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
MASS_ONE_PERCENT = 0.01
MASS_TWO_PERCENT = 0.02


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
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
        "sha256": sha256(path),
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


def finite(values: list[float], label: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"non-finite {label}: {values}")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def number(value: str | None, label: str) -> float:
    if value is None:
        raise ValueError(f"missing numeric value for {label}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric value for {label}")
    return result


def vector(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise ValueError(f"missing vector {label}")
    values = [number(node.get(axis), f"{label}.{axis}") for axis in "xyz"]
    finite(values, label)
    return values


def parse_box(node: ET.Element, label: str) -> dict[str, Any]:
    point = next((child for child in node if local_name(child.tag) == "point"), None)
    size = next((child for child in node if local_name(child.tag) == "size"), None)
    low = vector(point, f"{label}.point")
    extent = vector(size, f"{label}.size")
    if any(value <= 0.0 for value in extent):
        raise ValueError(f"non-positive {label} extent")
    high = [low[i] + extent[i] for i in range(3)]
    finite(high, f"{label}.high")
    fill = next((child.text or "" for child in node if local_name(child.tag) == "boxfill"), "").strip()
    layers = next((child for child in node if local_name(child.tag) == "layers"), None)
    return {
        "low_m": low,
        "high_m": high,
        "size_m": extent,
        "boxfill": fill,
        "layers": dict(layers.attrib) if layers is not None else None,
        "comment": node.get("cmt"),
    }


def parse_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = next((node for node in root.iter() if local_name(node.tag) == "definition"), None)
    if definition is None:
        raise ValueError(f"missing definition in {path}")
    dp = number(definition.get("dp"), "definition.dp")
    pointref_node = next((node for node in definition if local_name(node.tag) == "pointref"), None)
    pointref = vector(pointref_node, "definition.pointref") if pointref_node is not None else None
    pointmin_node = next((node for node in definition if local_name(node.tag) == "pointmin"), None)
    pointmax_node = next((node for node in definition if local_name(node.tag) == "pointmax"), None)
    bounds = {"min_m": vector(pointmin_node, "definition.pointmin"), "max_m": vector(pointmax_node, "definition.pointmax")} if pointmin_node is not None and pointmax_node is not None else None

    mainlist = next((node for node in root.iter() if local_name(node.tag) == "mainlist"), None)
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
        tag = local_name(child.tag)
        if tag == "setshapemode":
            shape_mode = (child.text or "").strip()
            operations.append({"op": tag, "value": shape_mode})
        elif tag == "setboxlimitmode":
            box_limit = child.get("mode", "UNKNOWN")
            operations.append({"op": tag, "mode": box_limit})
        elif tag == "setmkfluid":
            mkfluid = int(child.get("mk", "0")); mkbound = None
            operations.append({"op": tag, "mkfluid": mkfluid})
        elif tag in {"setmkbound", "setmkvoid"}:
            mkbound = int(child.get("mk", "0")) if tag == "setmkbound" else None; mkfluid = None
            operations.append({"op": tag, "mkbound": mkbound})
        elif tag == "drawbox":
            box = parse_box(child, "drawbox")
            box.update({"shape_mode": shape_mode, "box_limit_mode": box_limit, "mkfluid": mkfluid, "mkbound": mkbound})
            if mkfluid is not None:
                fluid_boxes.append(box)
            elif mkbound is not None:
                boundary_boxes.append(box)
            else:
                raise ValueError("drawbox has no active fluid or bound material")
            operations.append({"op": tag, "box": box})
        elif tag in {"drawextrude", "clipplane", "clipreset", "shapeout", "setdrawmode"}:
            operations.append({"op": tag, "attributes": dict(child.attrib), "text": (child.text or "").strip()})

    parameters = {
        node.get("key"): node.get("value")
        for node in root.iter()
        if local_name(node.tag) == "parameter" and node.get("key") is not None
    }
    cfl = [number(node.get("value"), "cflnumber") for node in root.iter() if local_name(node.tag) == "cflnumber"]
    motion_files = [node.get("name") for node in root.iter() if local_name(node.tag) == "file" and node.get("name")]
    motion_windows = [dict(node.attrib) for node in root.iter() if local_name(node.tag) in {"begin", "mvpredef"} and (node.get("finish") or node.get("duration"))]
    particles = next((node for node in root.iter() if local_name(node.tag) == "particles"), None)
    if particles is None:
        # A source/candidate Def is a template and has no generated
        # execution/particles or execution/constants/massfluid section.
        return {
            "path": str(path.resolve()), "dp_m": dp, "pointref_m": pointref,
            "definition_bounds_m": bounds, "fluid_boxes": fluid_boxes,
            "boundary_boxes": boundary_boxes, "operations": operations,
            "particles_summary": None, "fluid_blocks": [], "fluid_count": None,
            "massfluid_kg": None, "parameters": parameters, "cflnumber": cfl,
            "motion_files": motion_files, "motion_windows": motion_windows,
        }
    fluid_blocks: list[dict[str, Any]] = []
    for node in particles:
        if local_name(node.tag) != "fluid":
            continue
        if not all(key in node.attrib for key in ("mkfluid", "mk", "begin", "count")):
            continue
        fluid_blocks.append({
            "mkfluid": int(node.get("mkfluid", "0")),
            "mk": int(node.get("mk", "0")),
            "begin": int(node.get("begin", "0")),
            "count": int(node.get("count", "0")),
        })
    if not fluid_blocks:
        raise ValueError(f"no typed fluid blocks in {path}")
    constants = next((node for node in root.iter() if local_name(node.tag) == "constants"), None)
    mass_node = next((node for node in (list(constants) if constants is not None else []) if local_name(node.tag) == "massfluid"), None)
    massfluid = number(mass_node.get("value") if mass_node is not None else None, "constants.massfluid")
    return {
        "path": str(path.resolve()),
        "dp_m": dp,
        "pointref_m": pointref,
        "definition_bounds_m": bounds,
        "fluid_boxes": fluid_boxes,
        "boundary_boxes": boundary_boxes,
        "operations": operations,
        "particles_summary": dict(particles.attrib),
        "fluid_blocks": fluid_blocks,
        "fluid_count": sum(block["count"] for block in fluid_blocks),
        "massfluid_kg": massfluid,
        "parameters": parameters,
        "cflnumber": cfl,
        "motion_files": motion_files,
        "motion_windows": motion_windows,
    }


def normalized_definition(path: Path) -> str:
    data = path.read_bytes()
    data, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb"\1<DP>\2", data, count=1)
    if count != 1:
        raise ValueError(f"expected one definition dp in {path}")
    return hashlib.sha256(data).hexdigest()


def read_vtk_points(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    data = path.read_bytes()
    match = re.search(rb"(?m)^POINTS\s+(\d+)\s+float\r?\n", data)
    if match is None:
        raise ValueError(f"missing binary POINTS in {path}")
    count = int(match.group(1))
    offset = match.end()
    byte_count = count * 3 * np.dtype(">f4").itemsize
    if offset + byte_count > len(data):
        raise ValueError(f"truncated POINTS payload in {path}")
    points = np.frombuffer(data, dtype=">f4", count=count * 3, offset=offset).reshape((-1, 3)).copy()
    if not np.isfinite(points).all():
        raise ValueError(f"non-finite VTK point in {path}")
    return points, {"point_count": count, "points_offset": offset, "points_bytes": byte_count}


def read_vtk_fluid(path: Path, expected_count: int, blocks: list[dict[str, Any]]) -> tuple[np.ndarray, dict[str, Any]]:
    points, header = read_vtk_points(path)
    if points.shape[0] != expected_count:
        raise ValueError(f"fluid VTK count {points.shape[0]} != generated XML count {expected_count}")
    data = path.read_bytes()
    point_data_re = re.compile(rb"(?m)^POINT_DATA\s+(\d+)\r?\n")
    point_data = point_data_re.search(data, header["points_offset"] + header["points_bytes"])
    if point_data is None or int(point_data.group(1)) != expected_count:
        raise ValueError("fluid VTK missing matching POINT_DATA")
    scalars_re = re.compile(rb"(?m)^SCALARS\s+([^\s]+)\s+([^\s]+)(?:\s+(\d+))?\r?\n")
    scalars = list(scalars_re.finditer(data, point_data.end()))
    idp = [m for m in scalars if m.group(1) == b"Idp"]
    if len(idp) != 1 or idp[0].group(2) != b"unsigned_int" or int(idp[0].group(3) or b"1") != 1:
        raise ValueError("fluid VTK has no unique unsigned-int Idp scalar")
    lookup = re.match(rb"LOOKUP_TABLE\s+default\r?\n", data[idp[0].end():])
    if lookup is None:
        raise ValueError("fluid Idp scalar lacks LOOKUP_TABLE default")
    ids_offset = idp[0].end() + lookup.end()
    ids_bytes = expected_count * np.dtype(">u4").itemsize
    if ids_offset + ids_bytes > len(data):
        raise ValueError("truncated fluid Idp payload")
    raw_ids = np.frombuffer(data, dtype=">u4", count=expected_count, offset=ids_offset).copy()
    global_ids = np.concatenate([np.arange(block["begin"], block["begin"] + block["count"], dtype=np.uint32) for block in blocks])
    if np.array_equal(np.sort(raw_ids), np.sort(global_ids)):
        mapped_ids = raw_ids
        mapping = "GLOBAL_XML_PARTICLE_IDS"
    elif np.array_equal(np.sort(raw_ids), np.arange(expected_count, dtype=np.uint32)):
        cursor = 0
        mapping_array = np.empty(expected_count, dtype=np.uint32)
        for block in blocks:
            n = block["count"]
            mapping_array[cursor:cursor + n] = np.arange(block["begin"], block["begin"] + n, dtype=np.uint32)
            cursor += n
        mapped_ids = mapping_array[raw_ids]
        mapping = "LOCAL_FLUID_ORDER_TO_XML_IDS"
    else:
        raise ValueError("fluid VTK Idp values do not match XML fluid ranges")
    return points, {**header, "idp_mapping": mapping, "idp_scalar": "unsigned_int", "idp_count": int(raw_ids.size), "mapped_ids": mapped_ids}


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
            "spacing_values_m": sorted({round(float(value), 10) for value in diffs})[:16],
        }
    return result


def inside_relation(points: np.ndarray, box: dict[str, Any] | None, dp: float) -> dict[str, Any]:
    if box is None:
        return {"status": "UNKNOWN_NO_ACTIVE_FLUID_BOX"}
    low = np.asarray(box["low_m"], dtype=np.float64)
    high = np.asarray(box["high_m"], dtype=np.float64)
    tol = max(1e-7, dp * 1e-5)
    inside = np.all((points >= low - tol) & (points <= high + tol), axis=1)
    strict = np.all((points > low + tol) & (points < high - tol), axis=1)
    return {
        "box_low_m": box["low_m"],
        "box_high_m": box["high_m"],
        "boundary_tolerance_m": tol,
        "inside_closed_count": int(inside.sum()),
        "outside_closed_count": int((~inside).sum()),
        "strict_interior_count": int(strict.sum()),
        "boundary_tie_count": int((inside & ~strict).sum()),
    }


def box_volume(box: dict[str, Any]) -> float:
    return math.prod(box["size_m"])


def owner_geometry(owner_path: Path) -> dict[str, Any]:
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    params = owner.get("parameters", {})
    fluid = params.get("fluid_box_m")
    if not (isinstance(fluid, list) and len(fluid) == 2):
        raise ValueError("owner contract has no two-corner fluid_box_m")
    low = [float(value) for value in fluid[0]]
    high = [float(value) for value in fluid[1]]
    extent = [high[i] - low[i] for i in range(3)]
    finite(low + high + extent, "owner fluid box")
    if any(value <= 0.0 for value in extent):
        raise ValueError("owner fluid box has non-positive extent")
    volume = math.prod(extent)
    return {
        "physical_case_id": owner.get("physical_case_id"),
        "geometry_family_id": owner.get("geometry_family_id"),
        "fluid_box_low_m": low,
        "fluid_box_high_m": high,
        "fluid_box_envelope_size_m": extent,
        "fluid_box_envelope_volume_m3": volume,
        "unclipped_envelope_mass_if_density_1000_kg": volume * 1000.0,
        "bed_representation": params.get("bed_representation"),
        "bed_closed": params.get("bed_closed"),
        "bed_extrusion_y_bounds_m": params.get("bed_extrusion_y_bounds_m"),
        "bed_profile_lower_xz_m": params.get("bed_profile_lower_xz_m"),
        "bed_profile_upper_xz_m": params.get("bed_profile_upper_xz_m"),
        "boundary_method": params.get("boundary_method"),
        "owner_expected_counts": owner.get("expected_counts"),
        "continuous_owner_mass_kg": "UNKNOWN_UNSPECIFIED_BY_OWNER_CONTRACT",
        "mass_semantics": "The envelope mass is not a continuous-fluid target: the clipplane, closed sloped bed, tank, and draw order define the actual region. No scalar owner mass is published here.",
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _root072_hash_anchor(path: Path, audit_receipt: dict[str, Any]) -> str:
    """Return the hash recorded by the consumed ROOT072 guard.

    ROOT072 failed in the VTK parser before producing a scientific report, but
    its parent guard did record launch/end hashes.  Those hashes are the only
    accepted source binding here.  The current worker still hashes the files
    after its own reservation so that it can detect replacement or mutation.
    """
    launch = audit_receipt.get("input_hashes_at_launch")
    after = audit_receipt.get("input_hashes_after_run")
    if not isinstance(launch, dict) or not isinstance(after, dict):
        raise ValueError("ROOT072 receipt has no launch/end input hash maps")
    key = str(path.resolve())
    if key not in launch or key not in after:
        raise ValueError(f"ROOT072 receipt has no hash for {key}")
    if launch[key] != after[key]:
        raise ValueError(f"ROOT072 launch/end hash mismatch for {key}")
    value = launch[key]
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"ROOT072 hash is not a SHA-256 digest for {key}")
    return value


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    generated_xml = args.generated_xml.resolve()
    fluid_vtk = args.fluid_vtk.resolve()
    bound_vtk = args.bound_vtk.resolve()
    receipt = args.receipt.resolve()
    source_vtk_receipt = args.source_vtk_receipt.resolve()
    source_vtk_audit = load_json(source_vtk_receipt)
    static = {
        "candidate_def": args.candidate_def.resolve(),
        "source_def": args.source_def.resolve(),
        "candidate_motion": args.candidate_motion.resolve(),
        "source_motion": args.source_motion.resolve(),
        "source_xml": args.source_xml.resolve(),
        "owner": args.owner.resolve(),
        "source_sample_contract": args.source_sample_contract.resolve(),
        "effective_control": args.effective_control.resolve(),
        "source_solver_receipt": args.source_solver_receipt.resolve(),
        "source_vtk_receipt": source_vtk_receipt,
    }
    expected = {
        "candidate_def": args.expected_candidate_def_sha,
        "source_def": args.expected_source_def_sha,
        "candidate_motion": args.expected_candidate_motion_sha,
        "source_motion": args.expected_source_motion_sha,
        "source_xml": args.expected_source_xml_sha,
        "owner": args.expected_owner_sha,
        "source_sample_contract": args.expected_source_sample_contract_sha,
        "effective_control": args.expected_effective_control_sha,
        "source_solver_receipt": args.expected_source_solver_receipt_sha,
        "source_vtk_receipt": args.expected_source_vtk_receipt_sha,
    }
    static_pre = {key: record(path) for key, path in static.items()}
    for key, expected_sha in expected.items():
        if expected_sha and static_pre[key]["sha256"] != expected_sha:
            raise ValueError(f"{key} SHA mismatch before audit")
    outputs_pre = {"generated_xml": record(generated_xml), "fluid_vtk": record(fluid_vtk), "bound_vtk": record(bound_vtk), "execution_receipt": record(receipt)}
    root072_paths = {
        "generated_xml": generated_xml,
        "fluid_vtk": fluid_vtk,
        "bound_vtk": bound_vtk,
        "execution_receipt": receipt,
        "source_solver_receipt": static["source_solver_receipt"],
    }
    root072_hashes = {key: _root072_hash_anchor(path, source_vtk_audit) for key, path in root072_paths.items()}
    for key in ("generated_xml", "fluid_vtk", "bound_vtk", "execution_receipt"):
        if outputs_pre[key]["sha256"] != root072_hashes[key]:
            raise ValueError(f"current {key} SHA differs from ROOT072 guarded anchor")
    if static_pre["source_solver_receipt"]["sha256"] != root072_hashes["source_solver_receipt"]:
        raise ValueError("current source solver receipt SHA differs from ROOT072 guarded anchor")
    terminal_receipt = load_json(receipt)
    if str(terminal_receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or int(terminal_receipt.get("returncode", 0)) != 0:
        raise ValueError("GenCase receipt is not a completed zero-return terminal product")

    generated = parse_xml(generated_xml)
    source = parse_xml(static["source_def"])
    candidate = parse_xml(static["candidate_def"])
    source_generated = parse_xml(static["source_xml"])
    fluid_points, fluid_vtk_meta = read_vtk_fluid(fluid_vtk, generated["fluid_count"], generated["fluid_blocks"])
    bound_points, bound_vtk_meta = read_vtk_points(bound_vtk)
    fluid_relation = inside_relation(fluid_points, generated["fluid_boxes"][0] if generated["fluid_boxes"] else None, generated["dp_m"])
    outputs_post = {"generated_xml": record(generated_xml), "fluid_vtk": record(fluid_vtk), "bound_vtk": record(bound_vtk), "execution_receipt": record(receipt)}
    static_post = {key: record(path) for key, path in static.items()}
    if outputs_pre != outputs_post or static_pre != static_post:
        raise RuntimeError("an input changed during F5 XML/VTK audit")

    generated_mass = generated["fluid_count"] * generated["massfluid_kg"]
    source_relative = generated_mass / SOURCE_SAMPLE_MASS_KG - 1.0
    source_mass_gate = "PASS_SOURCE_SAMPLE_DIAGNOSTIC_WITHIN_ONE_PERCENT" if abs(source_relative) <= MASS_ONE_PERCENT else "MARGINAL_SOURCE_SAMPLE_DIAGNOSTIC_ONE_TO_TWO_PERCENT" if abs(source_relative) <= MASS_TWO_PERCENT else "HARDFAIL_SOURCE_SAMPLE_DIAGNOSTIC_OVER_TWO_PERCENT"
    owner = owner_geometry(static["owner"])
    control_equal = normalized_definition(static["source_def"]) == normalized_definition(static["candidate_def"])
    source_motion_sha = static_pre["source_motion"]["sha256"]
    candidate_motion_sha = static_pre["candidate_motion"]["sha256"]
    control_comparison = {
        "normalized_source_candidate_definition_equal_except_dp": control_equal,
        "source_dp_m": source["dp_m"],
        "candidate_dp_m": candidate["dp_m"],
        "generated_dp_m": generated["dp_m"],
        "source_motion_sha256": source_motion_sha,
        "candidate_motion_sha256": candidate_motion_sha,
        "motion_byte_identical": source_motion_sha == candidate_motion_sha,
        "source_motion_files": source["motion_files"],
        "candidate_motion_files": candidate["motion_files"],
        "generated_motion_files": generated["motion_files"],
        "source_cflnumber": source["cflnumber"],
        "candidate_cflnumber": candidate["cflnumber"],
        "generated_cflnumber": generated["cflnumber"],
        "source_parameters": {key: source["parameters"].get(key) for key in ("TimeMax", "TimeOut", "Boundary", "Kernel", "ViscoTreatment", "Visco", "DensityDT", "Shifting")},
        "candidate_parameters": {key: candidate["parameters"].get(key) for key in ("TimeMax", "TimeOut", "Boundary", "Kernel", "ViscoTreatment", "Visco", "DensityDT", "Shifting")},
        "generated_parameters": {key: generated["parameters"].get(key) for key in ("TimeMax", "TimeOut", "Boundary", "Kernel", "ViscoTreatment", "Visco", "DensityDT", "Shifting")},
        "historical_solver_window_s": [0.0, 16.0],
        "xml_timemax_s": float(generated["parameters"].get("TimeMax", "nan")),
        "xml_timeout_s": float(generated["parameters"].get("TimeOut", "nan")),
        "control_scope": "GenCase/XML control closure only; historical -tmax:16 and source SaveDt/RunPARTs are provenance, not a new solver run.",
    }
    return {
        "schema": "ds02.stage2.f5-s1.initial-gencase-support-audit.v3",
        "status": "COMPLETED_INITIAL_XML_VTK_SUPPORT_AUDIT",
        "sentinel_id": "F5-S1",
        "family_id": "F5",
        "physical_case_id": SOURCE_PHYSICAL_CASE_ID,
        "scope": {
            "generated_xml_read": True,
            "generated_fluid_vtk_read": True,
            "generated_bound_vtk_read": True,
            "execution_receipt_read": True,
            "candidate_source_xml_read": True,
            "owner_geometry_read": True,
            "bi4_read": False,
            "hdf5_read": False,
            "solver_started": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "inputs": {"generated_pre": outputs_pre, "generated_post": outputs_post, "generated_pre_post_equal": True, "static_pre": static_pre, "static_post": static_post, "static_pre_post_equal": True, "complete_stat_and_sha": True},
        "root072_guarded_hash_anchor": {
            "receipt_path": str(source_vtk_receipt),
            "receipt_status": source_vtk_audit.get("status"),
            "receipt_returncode": source_vtk_audit.get("returncode"),
            "receipt_scientific_status": "FAILED_PARSER_BEFORE_GEOMETRY",
            "launch_end_hashes_equal": True,
            "anchored_sha256": root072_hashes,
            "vtk_hash_source": "ROOT072 input_hashes_at_launch and input_hashes_after_run",
            "stat_scope": "ROOT072 did not provide a scientific pre/post stat proof; this V3 worker records and compares current guarded pre/post stat+SHA",
            "scientific_credit": "NONE",
        },
        "receipt_scope": {key: terminal_receipt.get(key) for key in ("status", "returncode", "output_root", "bytes", "elapsed_seconds", "cpu_core_seconds")},
        "generated_definition": {key: generated[key] for key in ("dp_m", "pointref_m", "definition_bounds_m", "particles_summary", "fluid_blocks", "fluid_count", "massfluid_kg", "fluid_boxes", "boundary_boxes", "operations")},
        "vtk_support": {
            "fluid": {key: value for key, value in fluid_vtk_meta.items() if key != "mapped_ids"},
            "fluid_axis_summary": axis_summary(fluid_points),
            "fluid_box_relation": fluid_relation,
            "bound": bound_vtk_meta,
            "bound_axis_summary": axis_summary(bound_points),
            "finite_points": True,
            "interpretation": "Generated point clouds are observed support diagnostics. The sloped closed-bed point cloud and fluid cloud do not establish a continuous-region mass without the owner clipping/overlap quadrature contract.",
        },
        "source_and_candidate": {
            "source_definition": source,
            "candidate_definition": candidate,
            "source_generated_xml": source_generated,
            "normalized_definition_equal_except_dp": control_equal,
            "source_sample_mass_kg": SOURCE_SAMPLE_MASS_KG,
            "source_sample_mass_role": "discrete producer sample diagnostic; not continuous owner mass",
        },
        "owner_continuous_geometry": owner,
        "control_audit": control_comparison,
        "mass_audit": {
            "generated_sample_mass_kg": generated_mass,
            "generated_fluid_count": generated["fluid_count"],
            "generated_massfluid_kg": generated["massfluid_kg"],
            "source_discrete_sample_mass_kg": SOURCE_SAMPLE_MASS_KG,
            "relative_error_vs_source_discrete_fraction": source_relative,
            "relative_error_vs_source_discrete_percent": 100.0 * source_relative,
            "source_discrete_gate": source_mass_gate,
            "continuous_owner_mass_kg": owner["continuous_owner_mass_kg"],
            "continuous_owner_gate": "UNKNOWN_OWNER_MASS_NOT_SCALARIZED",
            "mass_rescale": False,
            "qualification": "A source-relative sample gate is diagnostic only; it cannot establish continuous-owner initial-state equivalence.",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "small XML/VTK initial support and control audit only; no CFD or observer qualification"},
    }


def self_test() -> dict[str, Any]:
    # Exercise the real binary VTK framing used by generated_Fluid.vtk. This
    # catches the Python re.search flags/offset API mistake without touching
    # any campaign data.
    import struct
    import tempfile

    header = (
        b"# vtk DataFile Version 3.0\n"
        b"tiny\nBINARY\nDATASET POLYDATA\n"
        b"POINTS 1 float\n"
    )
    payload = struct.pack(">fff", 0.1, 0.2, 0.3)
    tail = (
        b"\nPOINT_DATA 1\n"
        b"SCALARS Idp unsigned_int 1\n"
        b"LOOKUP_TABLE default\n"
        + struct.pack(">I", 0)
        + b"\n"
    )
    with tempfile.TemporaryDirectory(prefix="f5-vtk-v2-selftest-") as tmp:
        tiny = Path(tmp) / "tiny.vtk"
        tiny.write_bytes(header + payload + tail)
        points, meta = read_vtk_fluid(tiny, 1, [{"begin": 0, "count": 1}])
        if points.shape != (1, 3) or meta["idp_mapping"] != "GLOBAL_XML_PARTICLE_IDS":
            raise AssertionError("tiny binary VTK Idp framing self-test failed")
        bad = Path(tmp) / "bad.vtk"
        bad.write_bytes(header + payload + tail.replace(b"unsigned_int", b"float"))
        try:
            read_vtk_fluid(bad, 1, [{"begin": 0, "count": 1}])
        except ValueError as exc:
            if "unsigned-int Idp" not in str(exc):
                raise
        else:
            raise AssertionError("invalid Idp type was accepted")
    return {
        "status": "PASS",
        "sample_mass_is_discrete_diagnostic": True,
        "continuous_owner_mass_without_scalar_contract": "UNKNOWN",
        "binary_vtk_tiny_positive": True,
        "binary_vtk_tiny_wrong_idp_rejected": True,
        "bi4_read": False,
        "hdf5_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("generated-xml", "fluid-vtk", "bound-vtk", "receipt", "source-vtk-receipt", "candidate-def", "source-def", "candidate-motion", "source-motion", "source-xml", "owner", "source-sample-contract", "effective-control", "source-solver-receipt", "output"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("candidate-def", "source-def", "candidate-motion", "source-motion", "source-xml", "owner", "source-sample-contract", "effective-control", "source-solver-receipt", "source-vtk-receipt"):
        parser.add_argument(f"--expected-{name}-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = [args.generated_xml, args.fluid_vtk, args.bound_vtk, args.receipt, args.source_vtk_receipt, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.owner, args.source_sample_contract, args.effective_control, args.source_solver_receipt, args.output]
    if any(value is None for value in required):
        parser.error("all generated/static paths and --output are required unless --self-test")
    expected_names = ("candidate_def", "source_def", "candidate_motion", "source_motion", "source_xml", "owner", "source_sample_contract", "effective_control", "source_solver_receipt", "source_vtk_receipt")
    if any(not getattr(args, f"expected_{name}_sha") for name in expected_names):
        parser.error("all expected static SHA arguments are required")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "generated_sample_mass_kg": report["mass_audit"]["generated_sample_mass_kg"], "source_discrete_gate": report["mass_audit"]["source_discrete_gate"], "continuous_owner_gate": report["mass_audit"]["continuous_owner_gate"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

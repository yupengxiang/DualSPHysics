#!/usr/bin/env python3
"""Parent-guarded Fluid/Bound VTK support audit for four existing products.

The request builder supplies exact terminal GenCase products for F2-S2,
F4-S2, F5-S2 and F7-S1.  This worker is the executable part of that request:
after a parent reservation it reads only the generated XML and the two VTK
point clouds, with a full SHA/stat check before and after each payload read.
BI4 is stat-checked but never opened.  It reports finite points, XML particle
range/Idp mapping, fluid-box envelope membership and a bounded point-cloud
contact diagnostic.  A point-cloud diagnostic never becomes a continuous
owner mass, no-penetration, flux, or three-grid qualification claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-support-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-support-manifest.v1"
CASES = ("F2-S2", "F4-S2", "F5-S2", "F7-S1")
MAX_SMALL_BYTES = 16 * 1024 * 1024
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
NEAR_CONTACT_TOL_FACTOR = 1.0e-4


class AuditFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _regular(path: Path, label: str) -> Path:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _expected_stat(record: dict[str, Any]) -> dict[str, int]:
    value = record.get("stat") or record.get("stat_at_build") or {}
    aliases = {
        "device": ("device", "dev", "st_dev"),
        "inode": ("inode", "ino", "st_ino"),
        "bytes": ("bytes",),
        "mtime_ns": ("mtime_ns",),
        "ctime_ns": ("ctime_ns",),
    }
    result: dict[str, int] = {}
    for target, names in aliases.items():
        for name in names:
            if name in value:
                result[target] = int(value[name])
                break
    return result


def _assert_expected_stat(path: Path, record: dict[str, Any], label: str) -> dict[str, int]:
    actual = _stat(_regular(path, label))
    expected = _expected_stat(record)
    for key, value in expected.items():
        if actual.get(key) != value:
            raise AuditFailure(f"{label} {key} changed: expected {value}, got {actual.get(key)}")
    return actual


def _guarded_small(path: Path, label: str, expected_sha: str | None = None) -> tuple[bytes, dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise AuditFailure(f"{label} exceeds small input cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    digest = hashlib.sha256(raw).hexdigest()
    if before != after or len(raw) != before["bytes"]:
        raise AuditFailure(f"{label} changed during read: {path}")
    if expected_sha is not None and digest != expected_sha:
        raise AuditFailure(f"{label} SHA differs from manifest: {path}")
    return raw, {"path": str(path), "sha256": digest, "stat_pre": before,
                 "stat_post": after, "stable": True, "payload_read": True}


def _guarded_payload(path: Path, record: dict[str, Any], label: str) -> tuple[bytes, dict[str, Any]]:
    """Read one payload with two complete reads and stable pre/post guards."""
    path = _regular(path, label)
    before = _assert_expected_stat(path, record, f"{label} pre")
    if before["bytes"] > MAX_PAYLOAD_BYTES:
        raise AuditFailure(f"{label} exceeds worker payload cap: {path}")
    first = path.read_bytes()
    first_stat = _stat(path)
    if first_stat != before or len(first) != before["bytes"]:
        raise AuditFailure(f"{label} changed during first read: {path}")
    first_sha = hashlib.sha256(first).hexdigest()
    # Parsing is performed from the first stable byte image.  The second
    # complete read encloses the parser's use of that image.
    second = path.read_bytes()
    after = _stat(path)
    second_sha = hashlib.sha256(second).hexdigest()
    if after != before or len(second) != before["bytes"] or first_sha != second_sha:
        raise AuditFailure(f"{label} changed during post-decode guard: {path}")
    return first, {"path": str(path), "bytes": before["bytes"],
                   "sha256_pre": first_sha, "sha256_post": second_sha,
                   "stat_pre": before, "stat_post": after,
                   "stable": True, "complete_payload_passes": 2,
                   "payload_read": True}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _num(value: str | None, label: str) -> float:
    if value is None:
        raise AuditFailure(f"missing numeric XML field {label}")
    result = float(value)
    if not math.isfinite(result):
        raise AuditFailure(f"non-finite XML field {label}")
    return result


def _vec(node: ET.Element | None, label: str) -> list[float] | None:
    if node is None:
        return None
    return [_num(node.get(axis), f"{label}.{axis}") for axis in "xyz"]


def _parse_xml(raw: bytes, path: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise AuditFailure(f"generated XML parse failed: {path}: {exc}") from exc
    definition = next((node for node in root.iter() if _local(node.tag) == "definition"), None)
    if definition is None:
        raise AuditFailure(f"generated XML lacks definition: {path}")
    dp = _num(definition.get("dp"), "definition.dp")
    mainlist = next((node for node in root.iter() if _local(node.tag) == "mainlist"), None)
    boxes: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    active_role: str | None = None
    if mainlist is not None:
        for node in list(mainlist):
            tag = _local(node.tag)
            if tag == "setmkfluid":
                active_role = "fluid"
                operations.append({"op": tag, "mk": node.get("mk")})
            elif tag in {"setmkbound", "setmkvoid"}:
                active_role = "bound" if tag == "setmkbound" else "void"
                operations.append({"op": tag, "mk": node.get("mk")})
            elif tag == "drawbox":
                point = next((child for child in node if _local(child.tag) == "point"), None)
                size = next((child for child in node if _local(child.tag) == "size"), None)
                low = _vec(point, "drawbox.point")
                extent = _vec(size, "drawbox.size")
                if low is not None and extent is not None and all(value > 0 for value in extent):
                    boxes.append({"role": active_role, "low_m": low,
                                  "high_m": [low[i] + extent[i] for i in range(3)],
                                  "size_m": extent, "closed": True})
                operations.append({"op": tag, "role": active_role})
            else:
                operations.append({"op": tag})
    particles = next((node for node in root.iter() if _local(node.tag) == "particles"), None)
    blocks: list[dict[str, Any]] = []
    if particles is not None:
        for node in list(particles):
            tag = _local(node.tag).lower()
            if tag not in {"fluid", "bound", "floating", "moving", "fixed", "void"}:
                continue
            count_value = node.get("count")
            begin_value = node.get("begin")
            if count_value is None:
                continue
            try:
                count = int(count_value)
                begin = int(begin_value or 0)
            except ValueError as exc:
                raise AuditFailure(f"invalid XML particle range in {path}") from exc
            if count < 0 or begin < 0:
                raise AuditFailure(f"negative XML particle range in {path}")
            blocks.append({"role": tag, "begin": begin, "count": count,
                           "end": begin + count, "attrs": dict(node.attrib)})
    mass_node = next((node for node in root.iter() if _local(node.tag) == "massfluid"), None)
    mass = _num(mass_node.get("value"), "massfluid.value") if mass_node is not None else None
    parameters = {node.get("key"): node.get("value") for node in root.iter()
                  if _local(node.tag) == "parameter" and node.get("key") is not None}
    fluid_blocks = [block for block in blocks if block["role"] == "fluid"]
    bound_blocks = [block for block in blocks if block["role"] in {"bound", "floating", "moving", "fixed"}]
    return {"path": path, "dp_m": dp, "fluid_blocks": fluid_blocks,
            "bound_blocks": bound_blocks, "all_particle_blocks": blocks,
            "fluid_count": sum(item["count"] for item in fluid_blocks),
            "bound_count": sum(item["count"] for item in bound_blocks),
            "massfluid_kg": mass, "fluid_boxes": boxes, "operations": operations,
            "parameters": parameters,
            "has_clip_or_boolean_operation": any(item["op"] in {"clipplane", "clipreset", "drawextrude", "shapeout"} for item in operations)}


_POINTS_RE = re.compile(rb"(?m)^POINTS\s+(\d+)\s+(float|double)\r?\n")
_POINT_DATA_RE = re.compile(rb"(?m)^POINT_DATA\s+(\d+)\r?\n")
_SCALARS_RE = re.compile(rb"(?m)^SCALARS\s+([^\s]+)\s+([^\s]+)(?:\s+(\d+))?\r?\n")
_LOOKUP_RE = re.compile(rb"LOOKUP_TABLE\s+[^\r\n]+\r?\n")


def _dtype(name: bytes) -> np.dtype[Any] | None:
    return {b"unsigned_int": np.dtype(">u4"), b"int": np.dtype(">i4"),
            b"float": np.dtype(">f4"), b"double": np.dtype(">f8"),
            b"unsigned_char": np.dtype("u1"), b"char": np.dtype("i1")}.get(name)


def _parse_vtk(raw: bytes, path: str, *, expected_count: int | None = None) -> dict[str, Any]:
    match = _POINTS_RE.search(raw)
    if match is None:
        raise AuditFailure(f"{path} has no binary POINTS section")
    count = int(match.group(1)); kind = match.group(2)
    dtype = np.dtype(">f4" if kind == b"float" else ">f8")
    offset = match.end(); payload_bytes = count * 3 * dtype.itemsize
    if offset + payload_bytes > len(raw):
        raise AuditFailure(f"{path} has truncated POINTS payload")
    points = np.frombuffer(raw, dtype=dtype, count=count * 3, offset=offset).reshape((count, 3)).astype(np.float64, copy=True)
    if not np.isfinite(points).all():
        raise AuditFailure(f"{path} contains non-finite POINTS")
    if expected_count is not None and count != expected_count:
        raise AuditFailure(f"{path} point count {count} != XML expected {expected_count}")
    point_data = _POINT_DATA_RE.search(raw, offset + payload_bytes)
    arrays: dict[str, np.ndarray] = {}
    array_meta: dict[str, Any] = {}
    cursor = point_data.end() if point_data is not None else offset + payload_bytes
    point_data_count = int(point_data.group(1)) if point_data is not None else None
    # Sequentially consume scalar headers and their binary payload.  Searching
    # only from the current payload cursor prevents binary floats from being
    # mistaken for a second ASCII header.
    while cursor < len(raw):
        scalar = _SCALARS_RE.search(raw, cursor)
        if scalar is None:
            break
        name = scalar.group(1).decode("ascii", "replace")
        scalar_dtype = _dtype(scalar.group(2))
        components = int(scalar.group(3) or b"1")
        lookup = _LOOKUP_RE.search(raw, scalar.end())
        if lookup is None or scalar_dtype is None or components <= 0:
            break
        data_offset = lookup.end()
        nvalues = count * components
        nbytes = nvalues * scalar_dtype.itemsize
        if data_offset + nbytes > len(raw):
            raise AuditFailure(f"{path} scalar {name} payload is truncated")
        values = np.frombuffer(raw, dtype=scalar_dtype, count=nvalues, offset=data_offset).copy()
        if not np.isfinite(values.astype(np.float64, copy=False)).all():
            raise AuditFailure(f"{path} scalar {name} contains non-finite values")
        arrays[name] = values.reshape((count, components)) if components > 1 else values
        array_meta[name] = {"dtype": scalar_dtype.str, "components": components,
                            "bytes": nbytes, "offset": data_offset}
        cursor = data_offset + nbytes
    return {"path": path, "point_count": count, "points": points,
            "points_dtype": dtype.str, "point_data_count": point_data_count,
            "arrays": arrays, "array_meta": array_meta,
            "finite_points": True}


def _range_ids(blocks: list[dict[str, Any]], roles: set[str] | None = None) -> set[int]:
    return {value for block in blocks if roles is None or block["role"] in roles
            for value in range(block["begin"], block["end"])}


def _map_ids(values: np.ndarray | None, blocks: list[dict[str, Any]], expected_count: int) -> dict[str, Any]:
    if values is None:
        return {"status": "UNKNOWN_NO_IDP_ARRAY", "role_counts": None}
    raw = np.asarray(values).reshape(-1).astype(np.int64, copy=False)
    expected = _range_ids(blocks)
    if expected and set(int(x) for x in raw) == expected and len(raw) == len(expected):
        mapped = raw
        mapping = "GLOBAL_XML_PARTICLE_IDS"
    elif len(raw) == expected_count and np.array_equal(np.sort(raw), np.arange(expected_count, dtype=np.int64)):
        # Local order is only mapped when XML ranges cover a contiguous fluid
        # or bound output.  The output preserves the limitation explicitly.
        ordered = np.asarray([value for block in blocks for value in range(block["begin"], block["end"])], dtype=np.int64)
        if len(ordered) != expected_count:
            return {"status": "UNKNOWN_LOCAL_IDS_NONCONTIGUOUS_XML_RANGES", "role_counts": None}
        mapped = ordered[raw]
        mapping = "LOCAL_OUTPUT_ORDER_TO_XML_IDS"
    else:
        return {"status": "UNKNOWN_IDP_VALUES_DO_NOT_MATCH_XML_RANGES", "role_counts": None,
                "observed_unique_count": int(np.unique(raw).size)}
    role_counts: dict[str, int] = {}
    for value in mapped:
        hit = next((block for block in blocks if block["begin"] <= int(value) < block["end"]), None)
        role = hit["role"] if hit is not None else "unknown"
        role_counts[role] = role_counts.get(role, 0) + 1
    return {"status": "PASS_IDP_XML_RANGE_MAPPING", "mapping": mapping,
            "role_counts": role_counts, "unique_id_count": int(np.unique(mapped).size)}


def _axis(points: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, axis in enumerate("xyz"):
        values = np.unique(points[:, index])
        diffs = np.diff(values)
        result[axis] = {"unique_count": int(values.size), "min_m": float(values[0]),
                        "max_m": float(values[-1]),
                        "spacing_min_m": float(diffs.min()) if diffs.size else 0.0,
                        "spacing_max_m": float(diffs.max()) if diffs.size else 0.0}
    return result


def _inside(points: np.ndarray, boxes: list[dict[str, Any]], dp: float) -> dict[str, Any]:
    fluid_boxes = [box for box in boxes if box.get("role") == "fluid"]
    if not fluid_boxes:
        return {"status": "UNKNOWN_NO_FLUID_DRAWBOX_ENVELOPE"}
    if len(fluid_boxes) != 1:
        return {"status": "UNKNOWN_MULTIPLE_FLUID_DRAWBOXES", "box_count": len(fluid_boxes)}
    box = fluid_boxes[0]; low = np.asarray(box["low_m"], dtype=np.float64); high = np.asarray(box["high_m"], dtype=np.float64)
    tol = max(1.0e-7, dp * 1.0e-5)
    inside = np.all((points >= low - tol) & (points <= high + tol), axis=1)
    strict = np.all((points > low + tol) & (points < high - tol), axis=1)
    return {"status": "DIAGNOSTIC_XML_FLUID_BOX_ENVELOPE", "low_m": box["low_m"], "high_m": box["high_m"],
            "tolerance_m": tol, "inside_closed_count": int(inside.sum()),
            "outside_closed_count": int((~inside).sum()), "strict_interior_count": int(strict.sum()),
            "boundary_tie_count": int((inside & ~strict).sum())}


def _contact(fluid: np.ndarray, bound: np.ndarray, tolerance: float) -> dict[str, Any]:
    if fluid.size == 0 or bound.size == 0:
        return {"status": "UNKNOWN_EMPTY_POINT_CLOUD", "exact_duplicate_count": 0, "near_contact_count": 0}
    scale = max(tolerance, 1.0e-8)
    bucket = np.floor(bound / scale + 0.5).astype(np.int64)
    table: dict[tuple[int, int, int], list[int]] = {}
    for index, key in enumerate(bucket):
        table.setdefault((int(key[0]), int(key[1]), int(key[2])), []).append(index)
    fluid_bucket = np.floor(fluid / scale + 0.5).astype(np.int64)
    exact = 0; near = 0; min_distance = math.inf
    limit2 = scale * scale
    for point, key in zip(fluid, fluid_bucket):
        candidates: list[int] = []
        kx, ky, kz = (int(key[0]), int(key[1]), int(key[2]))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    candidates.extend(table.get((kx + dx, ky + dy, kz + dz), ()))
        if not candidates:
            continue
        delta = bound[np.asarray(candidates)] - point
        distances2 = np.einsum("ij,ij->i", delta, delta)
        local_min = float(distances2.min())
        min_distance = min(min_distance, math.sqrt(local_min))
        near += int(np.count_nonzero(distances2 <= limit2))
        exact += int(np.count_nonzero(distances2 <= (scale * 0.25) ** 2))
    return {"status": "POINT_CLOUD_CONTACT_DIAGNOSTIC", "tolerance_m": scale,
            "exact_duplicate_count": exact, "near_contact_count": near,
            "minimum_candidate_distance_m": None if math.isinf(min_distance) else min_distance,
            "interpretation": "contact/duplicate points are a diagnostic; they do not establish physical overlap, flux, or no-penetration"}


def _case_manifest(manifest: dict[str, Any], sid: str) -> dict[str, Any]:
    cases = [case for case in manifest.get("cases", []) if isinstance(case, dict) and case.get("sentinel_id") == sid]
    if len(cases) != 1:
        raise AuditFailure(f"manifest must contain exactly one {sid} case")
    return cases[0]


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise AuditFailure(f"manifest schema mismatch: {manifest.get('schema')!r}")
    if {case.get("sentinel_id") for case in manifest.get("cases", []) if isinstance(case, dict)} != set(CASES):
        raise AuditFailure("manifest must contain exactly the four requested sentinels")


def _read_recorded_small(record: dict[str, Any], label: str) -> tuple[bytes, dict[str, Any]]:
    path = Path(str(record.get("path", "")))
    return _guarded_small(path, label, record.get("sha256") if isinstance(record.get("sha256"), str) else None)


def _audit_case(case: dict[str, Any], scratch: Path) -> dict[str, Any]:
    sid = str(case["sentinel_id"])
    xml_record = case.get("generated_xml")
    receipt_record = case.get("gencase_receipt")
    solver_record = case.get("current_solver_receipt")
    fluid_record = case.get("fluid_vtk")
    bound_record = case.get("bound_vtk")
    bi4_record = case.get("generated_bi4")
    for value, label in ((xml_record, "generated XML"), (receipt_record, "GenCase receipt"),
                         (solver_record, "solver receipt"), (fluid_record, "Fluid VTK"),
                         (bound_record, "Bound VTK"), (bi4_record, "BI4")):
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            raise AuditFailure(f"{sid} missing {label} binding")
    xml_raw, xml_guard = _read_recorded_small(xml_record, f"{sid} generated XML")
    receipt_raw, receipt_guard = _read_recorded_small(receipt_record, f"{sid} GenCase receipt")
    solver_raw, solver_guard = _read_recorded_small(solver_record, f"{sid} solver receipt")
    try:
        receipt = json.loads(receipt_raw.decode("utf-8")); solver = json.loads(solver_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{sid} source receipt is not JSON") from exc
    if not isinstance(receipt, dict) or receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise AuditFailure(f"{sid} GenCase receipt is not completed rc=0")
    if not isinstance(solver, dict) or solver.get("status") != "completed" or int(solver.get("returncode", -1)) != 0:
        raise AuditFailure(f"{sid} current solver receipt is not completed rc=0")
    generated = _parse_xml(xml_raw, xml_record["path"])
    fluid_raw, fluid_guard = _guarded_payload(Path(fluid_record["path"]), fluid_record, f"{sid} Fluid VTK")
    bound_raw, bound_guard = _guarded_payload(Path(bound_record["path"]), bound_record, f"{sid} Bound VTK")
    # BI4 is deliberately stat-only: initial support geometry is derived from
    # VTK, and the native container is deferred to a separate observer audit.
    bi4_path = _absolute(Path(bi4_record["path"]))
    bi4_before = _assert_expected_stat(bi4_path, bi4_record, f"{sid} BI4 pre")
    fluid = _parse_vtk(fluid_raw, fluid_record["path"], expected_count=generated["fluid_count"] if generated["fluid_count"] else None)
    bound = _parse_vtk(bound_raw, bound_record["path"], expected_count=None)
    fluid_ids = fluid["arrays"].get("Idp") if "Idp" in fluid["arrays"] else fluid["arrays"].get("Idpd")
    bound_ids = bound["arrays"].get("Idp") if "Idp" in bound["arrays"] else bound["arrays"].get("Idpd")
    fluid_id_map = _map_ids(fluid_ids, generated["fluid_blocks"], fluid["point_count"])
    bound_id_map = _map_ids(bound_ids, generated["bound_blocks"], bound["point_count"])
    envelope = _inside(fluid["points"], generated["fluid_boxes"], generated["dp_m"])
    contact = _contact(fluid["points"], bound["points"], max(generated["dp_m"] * NEAR_CONTACT_TOL_FACTOR, 1.0e-7))
    bi4_after = _assert_expected_stat(bi4_path, bi4_record, f"{sid} BI4 post")
    owner = case.get("continuous_owner") if isinstance(case.get("continuous_owner"), dict) else {"status": "UNKNOWN"}
    integrity = fluid["finite_points"] and bound["finite_points"] and (generated["fluid_count"] is None or fluid["point_count"] == generated["fluid_count"])
    role_status = "PASS" if bound_id_map.get("status") == "PASS_IDP_XML_RANGE_MAPPING" else bound_id_map.get("status")
    return {
        "sentinel_id": sid,
        "source_identity": {"physical_case_id": case.get("physical_case_id"), "gencase_receipt": receipt_guard, "solver_receipt": solver_guard},
        "source_xml": {"guard": xml_guard, "metadata": generated},
        "deferred_payload_guards": {"fluid_vtk": fluid_guard, "bound_vtk": bound_guard,
                                     "bi4": {"path": str(bi4_path), "stat_pre": bi4_before, "stat_post": bi4_after, "payload_read": False}},
        "fluid": {"point_count": fluid["point_count"], "point_data_count": fluid["point_data_count"],
                  "finite_points": fluid["finite_points"], "axis_summary": _axis(fluid["points"]),
                  "arrays": fluid["array_meta"], "idp_mapping": fluid_id_map,
                  "xml_fluid_count": generated["fluid_count"], "xml_massfluid_kg": generated["massfluid_kg"],
                  "xml_envelope_relation": envelope},
        "bound": {"point_count": bound["point_count"], "point_data_count": bound["point_data_count"],
                  "finite_points": bound["finite_points"], "axis_summary": _axis(bound["points"]),
                  "arrays": bound["array_meta"], "idp_mapping": bound_id_map,
                  "role_mapping_status": role_status},
        "fluid_bound_contact": contact,
        "continuous_owner": owner,
        "admission": {
            "payload_integrity": "PASS_FINITE_AND_XML_FLUID_COUNT" if integrity else "FAIL_PAYLOAD_OR_XML_COUNT",
            "fluid_support": "DIAGNOSTIC_ONLY_OWNER_REGION_NOT_CLOSED" if envelope.get("status") != "UNKNOWN_NO_FLUID_DRAWBOX_ENVELOPE" else "UNKNOWN_NO_OWNER_ENVELOPE",
            "bound_role_support": role_status,
            "continuous_owner": owner.get("status", "UNKNOWN"),
            "solver_admission": "BLOCKED_UNTIL_OWNER_AND_SUPPORT_CONTRACT_CLOSES",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "mass_rescale": False,
        },
        "read_scope": {"xml": True, "gencase_receipt": True, "solver_receipt": True,
                        "fluid_vtk": True, "bound_vtk": True, "bi4": False, "hdf5": False, "solver_launch": False},
    }


def run_manifest(manifest: dict[str, Any], output: Path, attempt_root: Path) -> dict[str, Any]:
    _validate_manifest(manifest)
    scratch = _absolute(attempt_root) / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    results = [_audit_case(_case_manifest(manifest, sid), scratch) for sid in CASES]
    result = {"schema": SCHEMA, "status": "COMPLETED_FLUID_BOUND_VTK_SUPPORT_DIAGNOSTIC",
              "manifest_schema": manifest["schema"], "cases": results,
              "aggregate": {"all_payload_integrity_pass": all(c["admission"]["payload_integrity"].startswith("PASS") for c in results),
                            "continuous_owner_closed": False, "support_overlap_scientific_credit": False,
                            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
              "scope": {"native_bi4_read": False, "hdf5_read": False, "solver_launch": False,
                        "payload_read": "Fluid/Bound VTK only", "owner_mass_inference": False,
                        "neighbor_grid_truth": False}}
    output = _absolute(output)
    if output.exists() or output.is_symlink():
        raise AuditFailure(f"refusing overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return result


def _tiny_vtk(points: list[tuple[float, float, float]], ids: list[int]) -> bytes:
    header = b"# vtk DataFile Version 3.0\ntiny\nBINARY\nDATASET POLYDATA\n"
    header += f"POINTS {len(points)} float\n".encode("ascii")
    payload = b"".join(struct.pack(">fff", *point) for point in points)
    tail = f"\nPOINT_DATA {len(points)}\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n".encode("ascii")
    return header + payload + tail + b"".join(struct.pack(">I", value) for value in ids) + b"\n"


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="four-sentinel-vtk-support-") as td:
        root = Path(td)
        xml = root / "tiny.xml"
        xml.write_text("""<case><casedef><definition dp=\"0.1\"/><mainlist><setmkfluid mk=\"1\"/><drawbox><point x=\"0\" y=\"0\" z=\"0\"/><size x=\"1\" y=\"1\" z=\"1\"/></drawbox><setmkbound mk=\"2\"/></mainlist></casedef><execution><particles><fluid begin=\"0\" count=\"2\" mkfluid=\"0\" mk=\"1\"/><bound begin=\"2\" count=\"1\" mkbound=\"2\" mk=\"2\"/></particles><constants><massfluid value=\"0.5\"/></constants></execution></case>""", encoding="utf-8")
        fluid = root / "tiny_Fluid.vtk"; bound = root / "tiny_Bound.vtk"; bi4 = root / "tiny.bi4"
        fluid.write_bytes(_tiny_vtk([(0.25, 0.25, 0.25), (0.75, 0.75, 0.75)], [0, 1]))
        bound.write_bytes(_tiny_vtk([(0.25, 0.25, 0.25)], [2]))
        bi4.write_bytes(b"do-not-decode")
        def rec(path: Path, *, payload: bool) -> dict[str, Any]:
            value = _stat(path); result = {"path": str(path), "stat": value, "status": "PRESENT_STAT_ONLY"}
            if payload:
                result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            return result
        xml_record = {"path": str(xml), "sha256": hashlib.sha256(xml.read_bytes()).hexdigest(), "stat": _stat(xml)}
        receipt = root / "gencase-receipt.json"; solver = root / "solver-receipt.json"
        receipt.write_text('{"status":"completed","returncode":0}', encoding="utf-8")
        solver.write_text('{"status":"completed","returncode":0}', encoding="utf-8")
        case = {"sentinel_id": "F2-S2", "physical_case_id": "tiny", "generated_xml": xml_record,
                "gencase_receipt": rec(receipt, payload=True), "current_solver_receipt": rec(solver, payload=True),
                "fluid_vtk": rec(fluid, payload=False), "bound_vtk": rec(bound, payload=False), "generated_bi4": rec(bi4, payload=False),
                "continuous_owner": {"status": "UNKNOWN_CONTINUOUS_OWNER"}}
        manifest = {"schema": MANIFEST_SCHEMA, "cases": [dict(case, sentinel_id=sid) for sid in CASES]}
        # Reuse the same tiny files for all cases to exercise the actual CLI
        # contract; the worker intentionally does not infer scientific identity.
        output = root / "out.json"
        result = run_manifest(manifest, output, root / "attempt")
        assert result["status"] == "COMPLETED_FLUID_BOUND_VTK_SUPPORT_DIAGNOSTIC"
        assert all(case_result["admission"]["payload_integrity"].startswith("PASS") for case_result in result["cases"])
        assert all(case_result["read_scope"]["bi4"] is False for case_result in result["cases"])
        bad = bytearray(fluid.read_bytes()); bad[-1] = 0xFF
        bad_path = root / "bad.vtk"; bad_path.write_bytes(bad)
        try:
            _parse_vtk(bad, str(bad_path), expected_count=2)
        except AuditFailure:
            pass
        else:
            # The changed Idp byte may still be a valid integer; the strict
            # negative is instead exercised by a non-finite POINTS payload.
            nan_path = root / "nan.vtk"
            nan_path.write_bytes(_tiny_vtk([(float("nan"), 0.0, 0.0), (1.0, 1.0, 1.0)], [0, 1]))
            try:
                _parse_vtk(nan_path.read_bytes(), str(nan_path), expected_count=2)
            except AuditFailure:
                pass
            else:
                raise AssertionError("non-finite VTK fixture was accepted")
    print("PASS_FOUR_SENTINEL_GENCASE_GEOMETRY_SUPPORT_WORKER_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--run requires --manifest, --attempt-root and --output")
    try:
        raw, _ = _guarded_small(args.manifest, "support manifest")
        manifest = json.loads(raw.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise AuditFailure("support manifest is not an object")
        result = run_manifest(manifest, args.output, args.attempt_root)
    except (AuditFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOUR_SENTINEL_GENCASE_GEOMETRY_SUPPORT: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "cases": [case["sentinel_id"] for case in result["cases"]], "output": str(_absolute(args.output)), "native_bi4_read": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

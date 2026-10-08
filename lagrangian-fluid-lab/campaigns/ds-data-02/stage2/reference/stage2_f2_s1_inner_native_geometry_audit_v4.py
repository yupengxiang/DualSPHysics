#!/usr/bin/env python3
"""Audit the actual F2 inner-mode GenCase geometry product (forward v4).

The worker reads only the bounded generated XML, generated fluid VTK, and
terminal GenCase receipt.  It never opens ``generated.bi4`` or any solver
payload.  Its purpose is to explain why the inner overlay did or did not
change the raster: per-MK lattice coordinates, box-boundary ties, mass,
boundary identity, implicit boundary layers, and AABB overlap are reported
as observed facts.  V2 follows the generated XML's real ``execution/particles``
location and identifies the native VTK ``Idp`` scalar by its explicit scalar
header.  A mass mismatch remains a hard diagnostic; this worker does not
rescale particles or grant a scientific label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import tempfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


OWNER_MASS_KG = 18.876
MASS_HARD_LIMIT_FRACTION = 0.02


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    st = path.stat()
    return {
        "path": str(path),
        "bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "ctime_ns": int(st.st_ctime_ns),
        "st_dev": int(st.st_dev),
        "st_ino": int(st.st_ino),
        "sha256": sha256(path),
    }


def finite(values: list[float], label: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"non-finite {label}: {values}")


def parse_float_attr(node: ET.Element, name: str) -> float:
    value = float(node.attrib[name])
    if not math.isfinite(value):
        raise ValueError(f"non-finite XML attribute {name}")
    return value


def parse_box(node: ET.Element) -> dict[str, Any]:
    point = node.find("point")
    size = node.find("size")
    if point is None or size is None:
        raise ValueError("drawbox is missing point or size")
    low = [parse_float_attr(point, axis) for axis in "xyz"]
    extent = [parse_float_attr(size, axis) for axis in "xyz"]
    high = [low[i] + extent[i] for i in range(3)]
    finite(low + extent + high, "drawbox")
    fill = (node.findtext("boxfill") or "").strip()
    layers = node.find("layers")
    return {
        "low_m": low, "high_m": high, "size_m": extent, "boxfill": fill,
        "layers": dict(layers.attrib) if layers is not None else None,
    }


def parse_definition(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ValueError("missing casedef/geometry/definition")
    dp = parse_float_attr(definition, "dp")
    pointref = definition.find("pointref")
    pointref_m = [parse_float_attr(pointref, axis) for axis in "xyz"] if pointref is not None else None
    commands = root.find("./casedef/geometry/commands/mainlist")
    if commands is None:
        raise ValueError("missing geometry mainlist")
    mode = "full"
    mkfluid: int | None = None
    mkbound: int | None = None
    fluid_boxes: list[dict[str, Any]] = []
    boundary_boxes: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    for child in list(commands):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "setboxlimitmode":
            mode = child.attrib.get("mode", "UNKNOWN")
            operations.append({"op": tag, "mode": mode})
        elif tag == "setmkfluid":
            mkfluid = int(child.attrib["mk"])
            mkbound = None
            operations.append({"op": tag, "mkfluid": mkfluid})
        elif tag == "setmkbound":
            mkbound = int(child.attrib["mk"])
            mkfluid = None
            operations.append({"op": tag, "mkbound": mkbound})
        elif tag == "drawbox":
            box = parse_box(child)
            box.update({"box_limit_mode": mode, "mkfluid": mkfluid, "mkbound": mkbound})
            if mkfluid is not None:
                fluid_boxes.append(box)
            elif mkbound is not None:
                boundary_boxes.append(box)
            else:
                raise ValueError("drawbox has neither active fluid nor bound MK")
            operations.append({"op": tag, "box": box})
    particle_nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "particles"]
    if len(particle_nodes) != 1:
        raise ValueError(f"expected exactly one generated particles summary, found {len(particle_nodes)}")
    particles = particle_nodes[0]
    # Generated GenCase XML stores the sample mass under execution/constants,
    # beside dp/h/b.  It is not a child of execution/particles; the earlier
    # forward worker used the latter path and would fail only after reading the
    # real VTK.  Keep the particle block parsing separate from the constants
    # lookup so the XML schema is checked against the actual generated form.
    mass_node = root.find("./execution/constants/massfluid")
    mass = float(mass_node.attrib["value"]) if mass_node is not None else None
    if mass is not None and not math.isfinite(mass):
        raise ValueError("generated massfluid is non-finite")
    blocks = []
    for node in particles.findall("fluid"):
        # ``execution/particles`` contains both summary rows and typed rows.
        # Summary rows have count/id/mkcount but no begin/mkfluid/mk.
        if not all(key in node.attrib for key in ("mkfluid", "mk", "begin", "count")):
            continue
        blocks.append({
            "mkfluid": int(node.attrib["mkfluid"]), "mk": int(node.attrib["mk"]),
            "begin": int(node.attrib["begin"]), "count": int(node.attrib["count"]),
        })
    particle_blocks = []
    for tag in ("fixed", "moving", "floating"):
        for node in particles.findall(tag):
            if not all(key in node.attrib for key in ("mk", "begin", "count")):
                continue
            particle_blocks.append({
                "kind": tag, "mk": int(node.attrib["mk"]),
                "begin": int(node.attrib["begin"]), "count": int(node.attrib["count"]),
                "mkbound": node.attrib.get("mkbound"), "refmotion": node.attrib.get("refmotion"),
            })
    return {
        "record": record(path), "particles_summary": dict(particles.attrib),
        "dp_m": dp, "pointref_m": pointref_m,
        "massfluid_kg": mass, "fluid_blocks": blocks,
        "fluid_count": sum(block["count"] for block in blocks),
        "particle_blocks": particle_blocks,
        "fluid_boxes": fluid_boxes, "boundary_boxes": boundary_boxes,
        "operations": operations,
    }


def read_vtk(path: Path, expected_count: int) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    data = path.read_bytes()
    point_match = re.search(rb"(?m)^POINTS\s+(\d+)\s+float\r?\n", data)
    if point_match is None:
        raise ValueError(f"missing POINTS section: {path}")
    count = int(point_match.group(1))
    if count != expected_count:
        raise ValueError(f"VTK count {count} != XML count {expected_count}")
    points_offset = point_match.end()
    points_bytes = count * 3 * np.dtype(">f4").itemsize
    points_end = points_offset + points_bytes
    if points_end > len(data):
        raise ValueError("VTK POINTS payload is truncated")
    points = np.frombuffer(data, dtype=">f4", count=count * 3, offset=points_offset).reshape((-1, 3)).copy()
    if not np.isfinite(points).all():
        raise ValueError("VTK points contain NaN/Inf")
    point_data_match = re.compile(rb"(?m)^POINT_DATA\s+(\d+)\r?\n").search(data, points_end)
    if point_data_match is None or int(point_data_match.group(1)) != count:
        raise ValueError("missing or inconsistent VTK POINT_DATA section")
    scalar_matches = list(re.compile(
        rb"(?m)^SCALARS\s+([^\s]+)\s+([^\s]+)(?:\s+(\d+))?\r?\n"
    ).finditer(data, point_data_match.end()))
    idp_matches = [match for match in scalar_matches if match.group(1) == b"Idp"]
    if len(idp_matches) != 1:
        raise ValueError(f"expected exactly one native VTK Idp scalar, found {len(idp_matches)}")
    scalar = idp_matches[0]
    scalar_type = scalar.group(2).decode("ascii", errors="replace")
    components = int(scalar.group(3) or b"1")
    if scalar_type != "unsigned_int" or components != 1:
        raise ValueError(f"unsupported VTK Idp scalar contract: type={scalar_type!r} components={components}")
    lookup = re.match(rb"LOOKUP_TABLE\s+default\r?\n", data[scalar.end():])
    if lookup is None:
        raise ValueError("Idp scalar is not followed by LOOKUP_TABLE default")
    ids_offset = scalar.end() + lookup.end()
    ids_bytes = count * np.dtype(">u4").itemsize
    ids_end = ids_offset + ids_bytes
    if ids_end > len(data):
        raise ValueError("VTK Idp payload is truncated")
    ids = np.frombuffer(data, dtype=">u4", count=count, offset=ids_offset).copy()
    # JSpVtkData writes a newline after each binary array, but the next
    # section may be FIELD or another producer-specific section.  The Idp
    # contract ends at ids_end; requiring FIELD here incorrectly rejects the
    # real GenCase binary VTK (and would make the parser depend on array order).
    separator = "NONE"
    if data[ids_end:ids_end + 2] == b"\r\n":
        separator = "CRLF"
    elif data[ids_end:ids_end + 1] == b"\n":
        separator = "LF"
    next_offset = ids_end + (2 if separator == "CRLF" else 1 if separator == "LF" else 0)
    next_section = data[next_offset:next_offset + 80].split(b"\n", 1)[0].decode("ascii", errors="replace")
    return points, ids, {
        "point_count": count,
        "points_payload_offset": points_offset,
        "points_payload_bytes": points_bytes,
        "point_data_offset": point_data_match.start(),
        "idp_scalar_name": "Idp",
        "idp_scalar_type": scalar_type,
        "idp_components": components,
        "idp_payload_offset": ids_offset,
        "idp_payload_bytes": ids_bytes,
        "payload_end_offset": ids_end,
        "post_payload_separator": separator,
        "next_section_header": next_section,
        "idp_contract": "SCALARS Idp unsigned_int; LOOKUP_TABLE default; exact big-endian uint32 payload; no FIELD-order assumption",
    }


def map_vtk_ids_to_xml(ids: np.ndarray, blocks: list[dict[str, Any]]) -> tuple[np.ndarray, dict[str, Any]]:
    expected_global = np.concatenate([
        np.arange(block["begin"], block["begin"] + block["count"], dtype=np.uint32)
        for block in blocks
    ])
    sorted_ids = np.sort(ids)
    if np.array_equal(sorted_ids, np.sort(expected_global)):
        return ids, {"mapping": "GLOBAL_XML_PARTICLE_IDS", "source_ranges_checked": True}
    local_expected = np.arange(int(expected_global.size), dtype=np.uint32)
    if np.array_equal(sorted_ids, local_expected):
        offsets = np.empty(expected_global.size, dtype=np.uint32)
        cursor = 0
        for block in blocks:
            count = int(block["count"])
            offsets[cursor:cursor + count] = np.arange(block["begin"], block["begin"] + count, dtype=np.uint32)
            cursor += count
        return offsets[ids], {"mapping": "LOCAL_FLUID_ORDER_TO_XML_PARTICLE_IDS", "source_ranges_checked": True}
    raise ValueError("VTK Idp values match neither XML global ranges nor local fluid order")


def axis_summary(points: np.ndarray) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for axis, index in zip("xyz", range(3)):
        values = np.unique(points[:, index])
        diffs = np.diff(values)
        summary[axis] = {
            "unique_count": int(values.size), "min_m": float(values[0]), "max_m": float(values[-1]),
            "spacing_min_m": float(diffs.min()) if diffs.size else 0.0,
            "spacing_max_m": float(diffs.max()) if diffs.size else 0.0,
            "spacing_values_m": sorted({round(float(value), 10) for value in diffs})[:16],
        }
    return summary


def box_volume(low_a: list[float], high_a: list[float], low_b: list[float], high_b: list[float]) -> float:
    lengths = [max(0.0, min(high_a[i], high_b[i]) - max(low_a[i], low_b[i])) for i in range(3)]
    return lengths[0] * lengths[1] * lengths[2]


def box_relation(box: dict[str, Any], points: np.ndarray, dp: float) -> dict[str, Any]:
    low = np.asarray(box["low_m"], dtype=np.float64)
    high = np.asarray(box["high_m"], dtype=np.float64)
    tol = max(1e-7, dp * 1e-5)
    inside = np.all((points >= low - tol) & (points <= high + tol), axis=1)
    strict = np.all((points > low + tol) & (points < high - tol), axis=1)
    boundary = inside & ~strict
    return {
        "box_limit_mode": box["box_limit_mode"], "low_m": box["low_m"], "high_m": box["high_m"],
        "inside_closed_count": int(inside.sum()), "outside_closed_count": int((~inside).sum()),
        "strict_interior_count": int(strict.sum()), "boundary_tie_count": int(boundary.sum()),
        "boundary_tolerance_m": tol,
    }


def build_report(xml_path: Path, vtk_path: Path, receipt_path: Path, expected_count: int, expected_mass: float) -> dict[str, Any]:
    pre = {"generated_xml": record(xml_path), "generated_fluid_vtk": record(vtk_path), "execution_receipt": record(receipt_path)}
    xml = parse_definition(xml_path)
    points, raw_ids, vtk_contract = read_vtk(vtk_path, xml["fluid_count"])
    ids, id_mapping = map_vtk_ids_to_xml(raw_ids, xml["fluid_blocks"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    post = {"generated_xml": record(xml_path), "generated_fluid_vtk": record(vtk_path), "execution_receipt": record(receipt_path)}
    if pre != post:
        raise RuntimeError("guarded input changed during XML/VTK audit")
    massfluid = xml.get("massfluid_kg")
    if massfluid is None:
        raise ValueError("generated XML has no massfluid")
    if xml["fluid_count"] != expected_count:
        raise ValueError(f"XML fluid count {xml['fluid_count']} != expected {expected_count}")
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(xml["fluid_blocks"]):
        selection = (ids >= block["begin"]) & (ids < block["begin"] + block["count"])
        selected = points[selection]
        if selected.shape[0] != block["count"]:
            raise ValueError(f"block {block['mkfluid']} id range does not match VTK")
        box = xml["fluid_boxes"][index] if index < len(xml["fluid_boxes"]) else None
        blocks.append({
            **block, "vtk_count": int(selected.shape[0]), "mass_kg": float(selected.shape[0] * massfluid),
            "axis": axis_summary(selected),
            "box_relation": box_relation(box, selected, xml["dp_m"]) if box else {"status": "UNKNOWN_NO_BOX"},
        })
    total_mass = float(xml["fluid_count"] * massfluid)
    relative = total_mass / expected_mass - 1.0
    fluid_overlap = []
    for i, first in enumerate(xml["fluid_boxes"]):
        for j, second in enumerate(xml["fluid_boxes"]):
            if j <= i:
                continue
            fluid_overlap.append({"i": i, "j": j, "volume_m3": box_volume(first["low_m"], first["high_m"], second["low_m"], second["high_m"])})
    boundary_overlap = []
    for i, fluid in enumerate(xml["fluid_boxes"]):
        boundary_overlap.append({
            "fluid_index": i,
            "boundary_aabb_overlap_m3": [box_volume(fluid["low_m"], fluid["high_m"], boundary["low_m"], boundary["high_m"]) for boundary in xml["boundary_boxes"]],
        })
    mass_status = "PASS_WITHIN_ONE_PERCENT" if abs(relative) <= 0.01 else "MARGINAL_ONE_TO_TWO_PERCENT" if abs(relative) <= 0.02 else "HARDFAIL_OVER_TWO_PERCENT"
    return {
        "schema": "ds02.stage2.f2-s1.inner-native-geometry-audit.v4",
        "status": "COMPLETED_NATIVE_GEOMETRY_AUDIT",
        "scope": {"generated_xml_read": True, "fluid_vtk_read": True, "receipt_read": True, "bi4_read": False, "hdf5_read": False, "solver_started": False},
        "inputs": {"pre": pre, "post": post, "pre_post_equal": True, "complete_stat_and_sha": True},
        "receipt_scope": {
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode", receipt.get("execution", {}).get("returncode")),
            "output_root": receipt.get("output_root", receipt.get("filesystem", {}).get("output_root")),
        },
        "definition": {k: xml[k] for k in ("dp_m", "pointref_m", "massfluid_kg", "fluid_count", "particles_summary")},
        "vtk_idp_contract": {**vtk_contract, **id_mapping, "raw_id_count": int(raw_ids.size), "mapped_id_count": int(ids.size)},
        "fluid_blocks": blocks,
        "boundary_identity": {
            "boxes": xml["boundary_boxes"], "count": len(xml["boundary_boxes"]),
            "particle_blocks": xml["particle_blocks"],
            "implicit_layers_preserved": [box.get("layers") for box in xml["boundary_boxes"]],
        },
        "draw_operations": xml["operations"],
        "overlap": {"fluid_fluid_aabb_m3": fluid_overlap, "fluid_boundary_aabb_m3": boundary_overlap},
        "mass_audit": {"owner_continuous_mass_kg": expected_mass, "actual_sample_mass_kg": total_mass, "relative_error_fraction": relative, "relative_error_percent": 100.0 * relative, "gate": "whole_initial_fluid_mass", "classification": mass_status, "rescale": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "geometry audit and sample mass only; no solver/observer qualification"},
    }


def self_test() -> dict[str, Any]:
    """Exercise the binary Idp offset parser without touching campaign data."""
    points = struct.pack(">6f", 0.0, 0.0, 0.0, 0.01, 0.0, 0.0)
    ids = struct.pack(">2I", 101, 102)
    payload = (
        b"# vtk DataFile Version 3.0\n"
        b"fixture\nBINARY\nDATASET POLYDATA\n"
        b"POINTS 2 float\n" + points
        + b"\nVERTICES 2 4\n" + struct.pack(">4I", 1, 0, 1, 1)
        + b"\nPOINT_DATA 2\nSCALARS Idp unsigned_int\nLOOKUP_TABLE default\n"
        + ids + b"\nTypex 1 1 int\n"
    )
    with tempfile.TemporaryDirectory(prefix="ds02-f2-v3-selftest-") as directory:
        path = Path(directory) / "fixture.vtk"
        path.write_bytes(payload)
        _, decoded, contract = read_vtk(path, 2)
    if decoded.tolist() != [101, 102]:
        raise AssertionError(f"unexpected Idp values: {decoded.tolist()}")
    if contract["post_payload_separator"] != "LF":
        raise AssertionError(contract)
    if not contract["next_section_header"].startswith("Typex 1 1 int"):
        raise AssertionError(contract)
    return {
        "status": "PASS",
        "idp_count": 2,
        "no_field_after_idp_required": True,
        "post_payload_separator": contract["post_payload_separator"],
        "next_section_header": contract["next_section_header"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--fluid-vtk", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--expected-fluid-count", type=int, default=30969)
    parser.add_argument("--expected-mass-kg", type=float, default=OWNER_MASS_KG)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if any(value is None for value in (args.generated_xml, args.fluid_vtk, args.receipt, args.output)):
        parser.error("--generated-xml, --fluid-vtk, --receipt, and --output are required unless --self-test is used")
    report = build_report(args.generated_xml.resolve(), args.fluid_vtk.resolve(), args.receipt.resolve(), args.expected_fluid_count, args.expected_mass_kg)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "mass": report["mass_audit"], "output": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

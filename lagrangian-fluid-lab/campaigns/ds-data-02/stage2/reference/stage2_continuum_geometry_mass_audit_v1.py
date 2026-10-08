#!/usr/bin/env python3
"""Audit declared continuous geometry against particle initialization mass.

This is an XML/source audit only.  It reads the exact source rows and their
generated XML, sums ``solid`` drawboxes while each ``setmkfluid`` is active,
and reports the resulting declared volume target separately from the actual
particle sample mass.  The primitive sum does not prove that GenCase used the
same volume after overlaps, voids, boundaries, or cell-centre cropping; those
semantic gaps remain explicit ``UNKNOWN`` fields.  Floating-body sample mass
is never substituted for its physical rigid-body mass, inertia, or center.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.continuum-geometry-mass-audit.v1"
DEFAULT_QUALITY = Path(__file__).with_name("stage2_reference_quality_cost_v2.json")
DEFAULT_OUTPUT = Path(__file__).with_name("stage2_continuum_geometry_mass_audit_v1.json")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_binding(path: Path) -> dict[str, Any]:
    path = path.resolve()
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def number(value: str | None, *, label: str) -> float:
    if value is None:
        raise ValueError(f"missing numeric {label}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric {label}")
    return result


def child(element: ET.Element, name: str) -> ET.Element | None:
    return next((node for node in element if local_name(node.tag) == name), None)


def attr_vector(element: ET.Element | None, names: tuple[str, ...]) -> list[float] | None:
    if element is None or any(name not in element.attrib for name in names):
        return None
    return [number(element.attrib[name], label=name) for name in names]


def parse_rigid_declarations(root: ET.Element) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for node in root.iter():
        if local_name(node.tag) != "floating":
            continue
        mass = child(node, "massbody")
        center = child(node, "center")
        inertia = child(node, "inertia")
        masspart = child(node, "masspart")
        if mass is None and center is None and inertia is None:
            continue
        records.append({
            "mkbound": node.attrib.get("mkbound"),
            "mk": node.attrib.get("mk"),
            "count": node.attrib.get("count"),
            "begin": node.attrib.get("begin"),
            "massbody_kg": number(mass.attrib.get("value"), label="massbody") if mass is not None else None,
            "masspart_kg": number(masspart.attrib.get("value"), label="masspart") if masspart is not None else None,
            "center_m": attr_vector(center, ("x", "y", "z")),
            "inertia_kg_m2": attr_vector(inertia, ("x", "y", "z")),
            "declaration_role": "positions_or_floatings_unknown",
        })
    return records


def parse_source_row(row: dict[str, Any]) -> dict[str, Any]:
    source_xml = row.get("source_xml")
    if not isinstance(source_xml, dict) or not isinstance(source_xml.get("path"), str):
        raise ValueError(f"source row lacks source_xml.path: {row.get('sentinel_id')}")
    xml_path = Path(source_xml["path"]).expanduser().resolve()
    if not xml_path.is_file():
        raise FileNotFoundError(xml_path)
    root = ET.parse(xml_path).getroot()
    rhop0_values = [number(node.attrib.get("value"), label="rhop0")
                    for node in root.iter() if local_name(node.tag) == "rhop0"]
    if not rhop0_values:
        rhop0_values = []
    if len({round(value, 12) for value in rhop0_values}) > 1:
        rhop0_status = "UNKNOWN_INCONSISTENT_SOURCE_XML_VALUES"
    elif rhop0_values:
        rhop0_status = "DECLARED_SOURCE_XML_VALUE"
    else:
        rhop0_status = "UNKNOWN_MISSING_SOURCE_XML_VALUE"
    rhop0 = rhop0_values[0] if rhop0_values else None

    regions: list[dict[str, Any]] = []
    active_mkfluid: str | None = None
    for node in root.iter():
        tag = local_name(node.tag)
        if tag == "setmkfluid":
            active_mkfluid = node.attrib.get("mk")
            continue
        if tag in {"setmkbound", "setmkvoid"}:
            active_mkfluid = None
            continue
        if tag != "drawbox" or active_mkfluid is None:
            continue
        boxfill = child(node, "boxfill")
        if boxfill is None or (boxfill.text or "").strip().lower() != "solid":
            continue
        point = child(node, "point")
        size = child(node, "size")
        point_m = attr_vector(point, ("x", "y", "z"))
        size_m = attr_vector(size, ("x", "y", "z"))
        if size_m is None or point_m is None or any(value <= 0 for value in size_m):
            raise ValueError(f"invalid fluid drawbox geometry in {xml_path}")
        volume = size_m[0] * size_m[1] * size_m[2]
        regions.append({
            "mkfluid_relative": active_mkfluid,
            "point_m": point_m,
            "size_m": size_m,
            "volume_m3": volume,
            "declared_mass_kg": volume * rhop0 if rhop0 is not None else None,
            "comment": node.attrib.get("cmt"),
            "boxfill": "solid",
        })

    blocks = source_xml.get("fluid_blocks", [])
    if not isinstance(blocks, list):
        blocks = []
    mass_values = source_xml.get("massfluid_values_kg", [])
    if not isinstance(mass_values, list):
        mass_values = []
    sample_by_mk: dict[str, dict[str, Any]] = {}
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        count = block.get("count")
        if not isinstance(count, int):
            count = int(count) if isinstance(count, str) and count.isdigit() else None
        massfluid = mass_values[index] if index < len(mass_values) else (mass_values[0] if len(mass_values) == 1 else None)
        if not isinstance(massfluid, (int, float)) or not math.isfinite(float(massfluid)):
            massfluid = None
        key = str(block.get("mkfluid", "UNKNOWN"))
        sample_by_mk[key] = {
            "mkfluid_relative": block.get("mkfluid"),
            "mk_absolute": block.get("mk"),
            "particle_count": count,
            "massfluid_kg": massfluid,
            "sample_mass_kg": count * massfluid if count is not None and massfluid is not None else None,
        }

    by_mk: dict[str, dict[str, Any]] = {}
    for region in regions:
        key = str(region["mkfluid_relative"])
        item = by_mk.setdefault(key, {"mkfluid_relative": region["mkfluid_relative"], "regions": [], "volume_m3": 0.0})
        item["regions"].append(region)
        item["volume_m3"] += region["volume_m3"]
    per_mk: list[dict[str, Any]] = []
    for key, item in by_mk.items():
        volume = item["volume_m3"]
        continuum_mass = volume * rhop0 if rhop0 is not None else None
        sample = sample_by_mk.get(key, {})
        per_mk.append({
            "mkfluid_relative": item["mkfluid_relative"],
            "mk_absolute": sample.get("mk_absolute"),
            "declared_regions": item["regions"],
            "declared_volume_m3": volume,
            "declared_continuum_mass_kg": continuum_mass,
            "particle_count": sample.get("particle_count"),
            "massfluid_kg": sample.get("massfluid_kg"),
            "reference_particle_sample_mass_kg": sample.get("sample_mass_kg"),
            "sample_minus_declared_kg": (
                sample.get("sample_mass_kg") - continuum_mass
                if sample.get("sample_mass_kg") is not None and continuum_mass is not None else None
            ),
        })

    declared_volume = sum(item["volume_m3"] for item in regions)
    declared_mass = declared_volume * rhop0 if rhop0 is not None else None
    sample_mass = source_xml.get("sample_mass_kg")
    source_binding = file_binding(xml_path)
    return {
        "sentinel_id": row.get("sentinel_id"),
        "family_id": row.get("family_id"),
        "physical_case_id": row.get("physical_case_id"),
        "source_xml": source_binding,
        "declared_source": {
            "rhop0_kg_m3": rhop0,
            "rhop0_values_seen": rhop0_values,
            "rhop0_status": rhop0_status,
            "solid_fluid_drawbox_count": len(regions),
            "declared_volume_m3": declared_volume,
            "declared_continuum_geometry_target_mass_kg": declared_mass,
            "per_mk": per_mk,
            "semantics": {
                "volume_method": "sum solid drawbox primitives while setmkfluid is active",
                "overlap_between_primitives": "UNKNOWN",
                "void_and_boundary_subtraction": "UNKNOWN",
                "cell_center_crop_or_fill_semantics": "UNKNOWN",
                "effective_continuum_mass": "UNKNOWN_UNTIL_SOURCE_GEOMETRY_SEMANTICS_CLOSED",
            },
        },
        "reference_particle_initialization": {
            "fluid_blocks": blocks,
            "source_massfluid_values_kg": mass_values,
            "reference_particle_sample_mass_target_kg": sample_mass,
            "role": "initialization diagnostic only; not a continuum geometry truth target",
            "sample_mass_minus_declared_geometry_mass_kg": (
                sample_mass - declared_mass if isinstance(sample_mass, (int, float)) and declared_mass is not None else None
            ),
        },
        "rigid_body_physical_target": {
            "source_quality_massbody_kg": source_xml.get("rigid_body_massbody_kg"),
            "source_quality_inertia_kg_m2": source_xml.get("rigid_body_inertia"),
            "xml_declarations": parse_rigid_declarations(root),
            "sample_particle_mass_is_not_body_mass": True,
            "qualification": "UNKNOWN_UNTIL_BODY_MASS_INERTIA_COM_AND_GENERATED_STATE_MATCH",
        },
    }


def build_report(quality_path: Path, output_path: Path) -> dict[str, Any]:
    quality_path = quality_path.resolve()
    if not quality_path.is_file():
        raise FileNotFoundError(quality_path)
    if output_path.exists():
        raise FileExistsError(f"refuse to overwrite immutable report: {output_path}")
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    rows = quality.get("sources")
    if not isinstance(rows, list) or len(rows) != 14:
        raise ValueError("quality input must contain exactly 14 source rows")
    entries = [parse_source_row(row) for row in rows]
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS_DECLARED_GEOMETRY_AUDIT_SCIENTIFIC_QUALIFICATION_UNKNOWN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_scope": {
            "source_rows": 14,
            "bi4_read": False,
            "hdf5_read": False,
            "solver_launch": False,
            "continuous_mass_is_declared_primitive_sum": True,
            "particle_sample_mass_is_not_continuum_truth": True,
            "rigid_body_mass_inertia_com_separate_from_floating_sample_mass": True,
        },
        "quality_input": file_binding(quality_path),
        "frozen_error_budget_reference": {
            "initial_whole_fluid_mass_target": "quality contract target remains authoritative; this audit does not widen it",
            "spatial_position_relative_tolerance": "2% L",
            "event_position_relative_tolerance": "5% L",
            "velocity_or_ke_tolerance": "5% nonzero scale",
            "event_time_tolerance": "1% characteristic time",
            "time_and_output_budget": "each <= one quarter of total gate; exact consumer calibration still required",
        },
        "sources": entries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = output_path.with_name(output_path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_bytes(encoded)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", type=Path, default=DEFAULT_QUALITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.quality, args.output)
    print(json.dumps({
        "status": report["status"],
        "output": str(args.output.resolve()),
        "sources": len(report["sources"]),
        "bi4_read": report["audit_scope"]["bi4_read"],
        "hdf5_read": report["audit_scope"]["hdf5_read"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

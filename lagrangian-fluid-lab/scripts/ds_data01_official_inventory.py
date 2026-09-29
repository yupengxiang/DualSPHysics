#!/usr/bin/env python3
"""Inventory every case directory in the bundled DualSPHysics examples.

This is a source scan only. It hashes official inputs and inspects XML/text
metadata; it never invokes GenCase, a solver, PartVTK, or any learner.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


LAB_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_ROOT = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4"
EXAMPLES_ROOT = OFFICIAL_ROOT / "examples"
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01"

CORE_GROUPS = {"main", "mdbc", "shiftingadv", "inletmesh", "inletoutlet", "vresolution"}
EXTENSION_GROUPS = {
    "chrono",
    "flexstruc",
    "moordynplus",
    "mphase_liquidgas",
    "mphase_nnewtonian",
    "wavecoupling",
}
UTILITY_GROUPS = {"motion", "others"}

PHYSICS_BY_GROUP = {
    "main": "single-phase free-surface, gravity/inertia, waves, sloshing, floating bodies, flow and damping examples",
    "mdbc": "single-phase free-surface and internal-flow examples using modified dynamic boundary conditions",
    "shiftingadv": "free-surface waves/dam-break with advanced particle shifting",
    "inletmesh": "open/inlet mesh flow and dam-break/wave examples",
    "inletoutlet": "open inlet/outlet flow, waves, jets and hull examples",
    "vresolution": "variable-resolution flow, dam-break, wedge and floating-body examples",
    "chrono": "fluid–rigid/flexible-body coupling examples using Chrono",
    "flexstruc": "fluid–flexible-structure coupling examples",
    "moordynplus": "fluid–mooring and connected-body coupling examples",
    "mphase_liquidgas": "multiphase liquid–gas examples",
    "mphase_nnewtonian": "non-Newtonian/multiphase examples",
    "wavecoupling": "external wave-coupling examples",
    "motion": "motion-file and prescribed-boundary utility material",
    "others": "format, restart, gauge, variable and utility demonstrations",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(OFFICIAL_ROOT).as_posix()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def xml_summary(xml_files: list[Path]) -> dict[str, Any]:
    tags: set[str] = set()
    parameters: dict[str, str] = {}
    mkconfig: list[dict[str, str]] = []
    dp_values: list[str] = []
    xml_text = "\n".join(read_text(path) for path in xml_files)
    for path in xml_files:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        for element in root.iter():
            tags.add(element.tag.rsplit("}", 1)[-1])
            if element.tag.rsplit("}", 1)[-1].lower() == "parameter":
                key = element.attrib.get("key")
                if key:
                    parameters[key] = element.attrib.get("value", "")
            if element.tag.rsplit("}", 1)[-1].lower() == "mkconfig":
                mkconfig.append(dict(element.attrib))
            if element.tag.rsplit("}", 1)[-1].lower() == "definition":
                dp = element.attrib.get("dp")
                if dp:
                    dp_values.append(dp)
    if not tags and xml_text:
        tags.update(re.findall(r"<([A-Za-z_][A-Za-z0-9_.-]*)", xml_text))
    return {
        "xml_count": len(xml_files),
        "xml_paths": [rel(path) for path in xml_files],
        "tags": sorted(tags),
        "parameters": dict(sorted(parameters.items())),
        "mkconfig": mkconfig,
        "declared_dp_values": sorted(set(dp_values)),
    }


def dimension_assessment(case_dir: Path, xml_text: str) -> dict[str, Any]:
    lower_path = case_dir.relative_to(EXAMPLES_ROOT).as_posix().lower()
    explicit_2d = bool(re.search(r"(^|[^a-z0-9])2d([^a-z0-9]|$)|val2d|2dvres", lower_path))
    explicit_3d = bool(re.search(r"(^|[^a-z0-9])3d([^a-z0-9]|$)", lower_path))
    y_extents: list[tuple[float, float]] = []
    for match in re.finditer(
        r"<(?:pointmin|pointmax)\b[^>]*\by=\"([-+0-9.eE]+)\"", xml_text
    ):
        value = float(match.group(1))
        y_extents.append((value, value))
    for match in re.finditer(
        r"<definition\b[^>]*>.*?</definition>", xml_text, flags=re.DOTALL
    ):
        for pair in re.finditer(
            r"<(?:point|min|max)\w*\b[^>]*\by=\"([-+0-9.eE]+)\"", match.group(0)
        ):
            value = float(pair.group(1))
            y_extents.append((value, value))
    zero_y = bool(y_extents) and all(abs(lo) < 1e-12 and abs(hi) < 1e-12 for lo, hi in y_extents)
    nonzero_y = bool(y_extents) and any(abs(value) > 1e-12 for pair in y_extents for value in pair)
    if explicit_2d or zero_y:
        value = "2D"
        confidence = "explicit_path" if explicit_2d else "source_geometry_y_zero"
    elif explicit_3d or nonzero_y:
        value = "3D"
        confidence = "explicit_path" if explicit_3d else "source_geometry_y_nonzero"
    else:
        value = "unspecified"
        confidence = "requires_generated_geometry_or_native_case_audit"
    return {
        "dimension": value,
        "confidence": confidence,
        "criterion": "explicit 2D/3D path token, otherwise source XML y-extent; unresolved cases require generated geometry audit",
        "source_geometry_y_values": sorted({value for pair in y_extents for value in pair}),
    }


def infer_metadata(group: str, case_name: str, text: str, tags: set[str]) -> dict[str, Any]:
    lower = f"{group}/{case_name} {text}".lower()
    module_terms = {
        "mdbc": "mdbc",
        "inlet": "inlet/outlet",
        "outlet": "inlet/outlet",
        "vres": "variable_resolution",
        "shifting": "particle_shifting",
        "shift": "particle_shifting",
        "chrono": "chrono_rigid_or_flexible_coupling",
        "moordyn": "mooring_coupling",
        "floating": "floating_rigid_body",
        "wave": "wave_generation_or_propagation",
        "piston": "prescribed_piston",
        "flap": "prescribed_flap",
        "periodic": "periodic_boundary",
        "gauge": "gauges",
        "forcing": "external_forcing",
        "accinput": "external_forcing",
    }
    modules = sorted({value for term, value in module_terms.items() if term in lower})
    boundary = []
    if "mdbc" in lower or "mdbc" in group:
        boundary.append("modified_dynamic_boundary")
    if "inlet" in lower or "outlet" in lower:
        boundary.append("open_inlet_outlet")
    if "periodic" in lower:
        boundary.append("periodic")
    if "drawbox" in lower or "drawfilestl" in lower or "mkbound" in tags:
        boundary.append("fixed_or_geometry_boundary")
    if "objreal" in lower or "floating" in lower or "chrono" in lower:
        boundary.append("moving_or_free_body_boundary")
    driving = []
    if any(term in lower for term in ("accinput", "externalforces", "forces")):
        driving.append("external_acceleration_or_force")
    if any(term in lower for term in ("motion", "mvrot", "mvlin", "piston", "flap")):
        driving.append("prescribed_motion")
    if any(term in lower for term in ("wave", "solitary", "wavemaker")):
        driving.append("wave_generator_or_wave_input")
    if "inlet" in lower or "flow" in lower or "pump" in lower:
        driving.append("flow_or_inlet_condition")
    if "gravity" in lower:
        driving.append("gravity")
    open_system = any(term in lower for term in ("inlet", "outlet", "openchannel", "reverseflow"))
    fixed_system = bool(boundary and "fixed_or_geometry_boundary" in boundary)
    rigid_response = any(term in lower for term in ("floating", "chrono", "moordyn", "rigid"))
    post = []
    if any(term in lower for term in ("gauge", "swl", "measure")):
        post.append("gauges_or_measurements")
    if "force" in lower or "torque" in lower:
        post.append("force_or_torque_output")
    if "vtk" in lower or "savevtk" in lower:
        post.append("vtk_output")
    if ".csv" in lower or "output" in lower:
        post.append("csv_or_scalar_output")
    return {
        "physics_content": PHYSICS_BY_GROUP.get(group, "official example material"),
        "modules": modules,
        "boundary_types": sorted(set(boundary)),
        "driving": sorted(set(driving)),
        "system_semantics": {
            "fixed_boundaries_present": fixed_system,
            "open_system_or_lifecycle": open_system,
            "moving_or_rigid_response": rigid_response,
        },
        "postprocessing_signals": sorted(set(post)),
    }


def initial_classification(group: str, case_name: str) -> tuple[str, str]:
    lower = f"{group}/{case_name}".lower()
    if "dem" in lower:
        return "exclude_from_core", "DEM or granular mechanics is outside single-phase fluid core"
    if group in UTILITY_GROUPS:
        return "calibration_or_utility", "utility/format/control material; not automatically a core mechanism"
    if group in EXTENSION_GROUPS:
        return "extension_candidate", "coupled, multiphase, non-Newtonian, adaptive, or external-coupling track"
    if group in CORE_GROUPS:
        return "core_candidate", "single-phase fluid candidate; verify actual dimension, mechanism, and recipe"
    return "review_required", "no automatic family assignment"


def source_files(case_dir: Path) -> list[dict[str, Any]]:
    assets = []
    for path in sorted(case_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            assets.append({"path": rel(path), "size_bytes": path.stat().st_size, "sha256": digest(path)})
        except OSError as exc:
            assets.append({"path": rel(path), "error": str(exc)})
    return assets


def case_directories() -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    for group_dir in sorted(path for path in EXAMPLES_ROOT.iterdir() if path.is_dir()):
        children = sorted(path for path in group_dir.iterdir() if path.is_dir())
        if children:
            candidates.extend((group_dir.name, child) for child in children)
        elif any(path.is_file() for path in group_dir.iterdir()):
            candidates.append((group_dir.name, group_dir))
    return candidates


def build_inventory() -> dict[str, Any]:
    records = []
    for group, case_dir in case_directories():
        files = source_files(case_dir)
        xml_files = sorted(case_dir.rglob("*.xml"))
        xml_text = "\n".join(read_text(path) for path in xml_files)
        summary = xml_summary(xml_files)
        tags = set(summary["tags"])
        metadata = infer_metadata(group, case_dir.name, xml_text, tags)
        classification, reason = initial_classification(group, case_dir.name)
        records.append(
            {
                "case_id": f"official::{group}::{case_dir.name}",
                "group": group,
                "case_name": case_dir.name,
                "path": rel(case_dir),
                "source_assets": files,
                "source_asset_count": len(files),
                "xml": summary,
                "dimension_assessment": dimension_assessment(case_dir, xml_text),
                "declared_particle_count": {
                    "status": "not_declared_in_source_xml",
                    "note": "mkconfig boundcount/fluidcount are material-kind counts, not generated particle counts; obtain particles only after GenCase and record separately",
                },
                **metadata,
                "initial_scope_class": classification,
                "initial_scope_reason": reason,
                "reference_and_license": {
                    "package_license": "LICENSE",
                    "documentation_pdf": f"examples/Examples_{group}.pdf" if (EXAMPLES_ROOT / f"Examples_{group}.pdf").exists() else None,
                    "reference_named_assets": [
                        item["path"]
                        for item in files
                        if re.search(r"(^|/)(exp|reference|.*_exp|.*reference).*", item["path"].lower())
                        or item["path"].lower().endswith((".ods", ".pdf"))
                    ],
                },
                "reproduction_status": "source_inventory_only",
                "scientific_acceptance": "not_assessed",
            }
        )
    pdfs = []
    for path in sorted(EXAMPLES_ROOT.rglob("*.pdf")):
        pdfs.append({"path": rel(path), "size_bytes": path.stat().st_size, "sha256": digest(path)})
    return {
        "schema": "ds-data-01.official-examples-inventory.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(OFFICIAL_ROOT),
        "package_version_file": "bin/linux/VERSION_INFO.txt",
        "package_license": "LICENSE",
        "inventory_method": {
            "case_rule": "each direct child of an example group is a case; a group with no child directory is itself a utility case",
            "dimension_rule": "path tokens and source XML y-extent are recorded as evidence; unresolved cases require generated-geometry audit",
            "particle_rule": "source XML is not treated as a particle-count receipt",
            "acceptance_rule": "this inventory is a candidate selector, not reproduction or quality acceptance",
        },
        "example_group_count": len({group for group, _ in case_directories()}),
        "case_count": len(records),
        "documentation_pdfs": pdfs,
        "cases": records,
    }


def write_csv(records: list[dict[str, Any]], output: Path) -> None:
    fields = [
        "case_id",
        "group",
        "case_name",
        "path",
        "initial_scope_class",
        "dimension",
        "dimension_confidence",
        "physics_content",
        "modules",
        "boundary_types",
        "driving",
        "fixed_boundaries_present",
        "open_system_or_lifecycle",
        "moving_or_rigid_response",
        "declared_dp_values",
        "parameter_keys",
        "source_asset_count",
        "reproduction_status",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for record in records:
            row = {
                "case_id": record["case_id"],
                "group": record["group"],
                "case_name": record["case_name"],
                "path": record["path"],
                "initial_scope_class": record["initial_scope_class"],
                "dimension": record["dimension_assessment"]["dimension"],
                "dimension_confidence": record["dimension_assessment"]["confidence"],
                "physics_content": record["physics_content"],
                "modules": ";".join(record["modules"]),
                "boundary_types": ";".join(record["boundary_types"]),
                "driving": ";".join(record["driving"]),
                "fixed_boundaries_present": record["system_semantics"]["fixed_boundaries_present"],
                "open_system_or_lifecycle": record["system_semantics"]["open_system_or_lifecycle"],
                "moving_or_rigid_response": record["system_semantics"]["moving_or_rigid_response"],
                "declared_dp_values": ";".join(record["xml"]["declared_dp_values"]),
                "parameter_keys": ";".join(record["xml"]["parameters"]),
                "source_asset_count": record["source_asset_count"],
                "reproduction_status": record["reproduction_status"],
            }
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", type=Path, default=CAMPAIGN_ROOT / "OFFICIAL_EXAMPLES_INVENTORY.json")
    parser.add_argument("--csv-output", type=Path, default=CAMPAIGN_ROOT / "OFFICIAL_EXAMPLES_INVENTORY.csv")
    args = parser.parse_args()
    inventory = build_inventory()
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.json_output.with_suffix(args.json_output.suffix + ".tmp")
    temporary.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.json_output)
    write_csv(inventory["cases"], args.csv_output)
    print(json.dumps({"case_count": inventory["case_count"], "example_group_count": inventory["example_group_count"], "json": str(args.json_output), "csv": str(args.csv_output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare and audit a matched RV4 F2 three-spacing initial-state family.

The RV4 physical mother is frozen at a three-source fluid region
``0.32 x 0.24 x 0.32 m`` (24.576 kg at rho0=1000 kg/m3), with the finite cup,
receiver, tray, motion curve, controls, four-second window, and padded domain
copied from the completed RV4 baseline.  This module only creates additive
GenCase sources and bounded CPU requests; it never starts GenCase, PartVTK, a
solver, or a GPU job.

The requested medium spacing ``0.0064 m`` is audited explicitly.  Its y-span
and each source-band width are half-integer cell counts, and no rectangular
integer lattice with the exact 24.576 kg population fits inside the frozen cup
at that spacing.  The module therefore does not silently alter the fluid
domain.  It registers ``dp=0.008 m`` as a lawful same-mother medium fallback:
all three frozen dimensions and all three 0.08 m source bands are integral,
so the coarse ``dp=0.01`` and medium ``dp=0.008`` definitions can be checked
by actual CPU GenCase before any root-owned GPU request.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_RV4_MATCHED_THREE_DP_INIT_20261003"
SCHEMA = "ds-data-02.f2.rv4-matched-three-dp-init.v1"
FAMILY_ROOT = Path(__file__).resolve().parents[2]
WORKTREE_ROOT = FAMILY_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
RV4_ROOT = INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs"

RV4 = {
    "CENTER": {
        "mechanism_id": "center_catch",
        "physical_case_id": "F2H10V2_CENTER_V1",
        "source_case": "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001",
        "physical_condition_hash": "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43",
        "geometry_family_id": "F2_GEOM_GEM_CUP_RECEIVER_CENTER_CATCH_V2",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_GEM_V2",
        "conversion_report": DATA_ROOT / "families/F2/F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001/conversion-f2h10v2_center_v1_medium_rv4d1_baseline_save001-fullstate-v5-002/conversion-report.json",
    },
    "OFFSET": {
        "mechanism_id": "offset_spill",
        "physical_case_id": "F2H10V2_OFFSET_V1",
        "source_case": "F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001",
        "physical_condition_hash": "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef",
        "geometry_family_id": "F2_GEOM_GEM_CUP_RECEIVER_OFFSET_SPILL_V2",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_GEM_V2",
        "conversion_report": DATA_ROOT / "families/F2/F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001/conversion-f2h10v2_offset_v1_medium_rv4d1_baseline_save001-fullstate-v5-002/conversion-report.json",
    },
}

# Decimal strings keep the frozen physical definition independent of binary
# display rounding.  These are the values recovered from the RV4 reports.
RHO0 = Decimal("1000")
FLUID_LOW = tuple(Decimal(value) for value in ("0.0525", "-0.12", "0.70"))
FLUID_SIZE = tuple(Decimal(value) for value in ("0.32", "0.24", "0.32"))
SOURCE_BANDS = 3
SOURCE_BAND_WIDTH = Decimal("0.08")
CONTINUOUS_VOLUME = FLUID_SIZE[0] * FLUID_SIZE[1] * FLUID_SIZE[2]
CONTINUOUS_MASS = RHO0 * CONTINUOUS_VOLUME
GRID_ORIGIN = ("-1.42", "-1.2225", "-0.5625")

# Only these two definitions are materialised.  The requested .0064 candidate
# is retained as an explicit blocked feasibility record below.
VALID_CANDIDATES = {
    "COARSE_DP010": {"resolution": "COARSE", "dp": Decimal("0.01"), "role": "matched_same_mother"},
    "MEDIUM_DP008": {"resolution": "MEDIUM", "dp": Decimal("0.008"), "role": "matched_same_mother_lawful_fallback"},
}
REQUESTED_MEDIUM_DP = Decimal("0.0064")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def decimal_text(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".") or "0"


def q(value: Decimal | float | str) -> str:
    return decimal_text(Decimal(str(value)))


def rv4_paths(background: str) -> tuple[Path, Path]:
    info = RV4[background]
    directory = (RV4_ROOT / info["source_case"]).resolve()
    xml = require(directory / f"{info['source_case']}.xml", f"RV4 {background} XML")
    motion = require(directory / f"F2H10V2_{background}_V1_MEDIUM_motion.dat", f"RV4 {background} motion")
    return xml, motion


def _attrs(node: ET.Element | None, keys: Iterable[str]) -> dict[str, str] | None:
    if node is None:
        return None
    return {key: node.attrib.get(key, "") for key in keys}


def declared_bound_boxes(xml_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(xml_path).getroot()
    mainlist = root.find(".//casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError(f"missing geometry mainlist: {xml_path}")
    current_mk: int | None = None
    boxes: list[dict[str, Any]] = []
    for node in mainlist:
        if node.tag == "setmkbound":
            current_mk = int(node.attrib["mk"])
        elif node.tag == "setmkfluid":
            current_mk = None
        elif node.tag == "drawbox" and current_mk is not None:
            point = node.find("point")
            size = node.find("size")
            if point is None or size is None:
                raise ValueError(f"bound drawbox lacks point/size: {xml_path}")
            boxes.append({
                "mk": current_mk,
                "boxfill": node.findtext("boxfill", default="").strip(),
                "low_m": [float(point.attrib[key]) for key in "xyz"],
                "size_m": [float(size.attrib[key]) for key in "xyz"],
            })
    if len(boxes) != 3:
        raise ValueError(f"expected three finite bound boxes, got {len(boxes)}")
    return boxes


def physical_projection(xml_path: Path, motion_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    constants = root.find(".//casedef/constantsdef")
    if constants is None:
        raise ValueError(f"missing constantsdef: {xml_path}")
    motion = root.find("./casedef/motion/objreal")
    if motion is None:
        raise ValueError(f"missing motion: {xml_path}")
    begin = motion.find("begin")
    mvrot = motion.find("mvrotfile")
    axis1 = mvrot.find("axisp1") if mvrot is not None else None
    axis2 = mvrot.find("axisp2") if mvrot is not None else None
    params = root.findall(".//execution/parameters/parameter")
    parameter_projection = sorted((node.attrib.get("key", ""), node.attrib.get("value", "")) for node in params)
    domain = root.find(".//execution/parameters/simulationdomain")
    if domain is None:
        raise ValueError(f"missing simulationdomain: {xml_path}")
    definition = root.find(".//casedef/geometry/definition")
    return {
        "bound_boxes": declared_bound_boxes(xml_path),
        "constantsdef": [(node.tag, tuple(sorted(node.attrib.items()))) for node in constants],
        "motion": {
            "begin": _attrs(begin, ("mov", "start", "finish")),
            "mvrotfile": _attrs(mvrot, ("id", "duration", "anglesunits")),
            "axis1": _attrs(axis1, ("x", "y", "z")),
            "axis2": _attrs(axis2, ("x", "y", "z")),
            "file_sha256": sha256(motion_path),
        },
        "execution_parameters": parameter_projection,
        "time_window_s": {
            "time_max": next((float(value) for key, value in parameter_projection if key == "TimeMax"), None),
            "time_out": next((float(value) for key, value in parameter_projection if key == "TimeOut"), None),
        },
        "simulationdomain": {
            "posmin": _attrs(domain.find("posmin"), ("x", "y", "z")),
            "posmax": _attrs(domain.find("posmax"), ("x", "y", "z")),
        },
        "definition_dp": definition.attrib.get("dp") if definition is not None else None,
    }


def frozen_geometry_projection() -> dict[str, Any]:
    return {
        "continuous_fluid_low_m": [float(value) for value in FLUID_LOW],
        "continuous_fluid_size_m": [float(value) for value in FLUID_SIZE],
        "continuous_fluid_volume_m3": float(CONTINUOUS_VOLUME),
        "continuous_mass_kg": float(CONTINUOUS_MASS),
        "source_band_count": SOURCE_BANDS,
        "source_band_width_m": float(SOURCE_BAND_WIDTH),
        "source_band_bounds_y_m": [[float(FLUID_LOW[1] + index * SOURCE_BAND_WIDTH), float(FLUID_LOW[1] + (index + 1) * SOURCE_BAND_WIDTH)] for index in range(SOURCE_BANDS)],
        "source_axis": "y",
    }


def integer_ratio(value: Decimal, divisor: Decimal) -> tuple[Decimal, bool]:
    ratio = value / divisor
    return ratio, ratio == ratio.to_integral_value()


def factor_triples(target: int, limits: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    triples: list[tuple[int, int, int]] = []
    for nx in range(1, limits[0] + 1):
        for ny in range(1, limits[1] + 1):
            product = nx * ny
            if product == 0 or target % product:
                continue
            nz = target // product
            if nz <= limits[2]:
                triples.append((nx, ny, nz))
    return triples


def feasibility(dp: Decimal) -> dict[str, Any]:
    axis_ratios = [integer_ratio(value, dp) for value in FLUID_SIZE]
    band_ratios = [integer_ratio(value, dp) for value in (FLUID_SIZE[0], SOURCE_BAND_WIDTH, FLUID_SIZE[2])]
    target_decimal = CONTINUOUS_VOLUME / (dp ** 3)
    target_is_integer = target_decimal == target_decimal.to_integral_value()
    target_count = int(target_decimal) if target_is_integer else None
    cup_limits = (Decimal("0.425"), Decimal("0.30"), Decimal("0.45"))
    limits = tuple(int(value // dp) for value in cup_limits)
    triples = factor_triples(target_count, limits) if target_count is not None else []
    same_box = all(item[1] for item in axis_ratios)
    same_bands = all(item[1] for item in band_ratios)
    return {
        "dp_m": float(dp),
        "axis_cell_ratios": {axis: {"ratio": str(ratio), "integer": integer} for axis, (ratio, integer) in zip("xyz", axis_ratios)},
        "source_band_cell_ratios_xyz": {axis: {"ratio": str(ratio), "integer": integer} for axis, (ratio, integer) in zip("xyz", band_ratios)},
        "target_particle_count_for_exact_continuum_volume": target_count,
        "target_count_is_integer": target_is_integer,
        "cup_cell_limits_xyz": list(limits),
        "exact_rectangular_population_triples_inside_cup": [list(item) for item in triples],
        "same_continuous_box_integer_lattice": same_box,
        "same_three_source_band_integer_lattice": same_bands,
        "same_mother_valid": same_box and same_bands and target_is_integer,
        "blocking_reasons": ([
            "frozen fluid y span is not an integer number of dp=0.0064 cells",
            "each frozen 0.08 m source band is not an integer number of dp=0.0064 cells",
            "no exact-volume rectangular integer lattice fits within the frozen cup extents at dp=0.0064",
        ] if not (same_box and same_bands and target_is_integer and triples) else []),
    }


def expected_population(dp: Decimal) -> dict[str, Any]:
    cells = [int(value / dp) for value in FLUID_SIZE]
    band_cells = [int(FLUID_SIZE[0] / dp), int(SOURCE_BAND_WIDTH / dp), int(FLUID_SIZE[2] / dp)]
    per_band = band_cells[0] * band_cells[1] * band_cells[2]
    count = per_band * SOURCE_BANDS
    particle_mass = RHO0 * dp ** 3
    lattice_mass = particle_mass * count
    return {
        "cells_xyz": cells,
        "source_band_cells_xyz": band_cells,
        "source_band_count": SOURCE_BANDS,
        "source_band_particle_count": per_band,
        "total_particle_count": count,
        "continuous_volume_m3": float(CONTINUOUS_VOLUME),
        "continuous_mass_kg": float(CONTINUOUS_MASS),
        "expected_particle_mass_kg": float(particle_mass),
        "expected_lattice_mass_kg": float(lattice_mass),
        "relative_mass_error": float(lattice_mass / CONTINUOUS_MASS - Decimal("1")),
        "decimal_values": {
            "dp_m": decimal_text(dp),
            "particle_mass_kg": decimal_text(particle_mass),
            "lattice_mass_kg": decimal_text(lattice_mass),
            "continuous_mass_kg": decimal_text(CONTINUOUS_MASS),
        },
    }


def same_physical_projection(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("bound_boxes", "constantsdef", "motion", "execution_parameters", "time_window_s", "simulationdomain")
    differences = {key: {"rv4": before[key], "candidate": after[key]} for key in keys if before[key] != after[key]}
    return {
        "compared_keys": list(keys),
        "differences": differences,
        "physical_solids_controls_window_equal": not differences,
        "allowed_changes": ["definition dp", "definition pointmin numerical grid phase", "three fluid source blocks", "motion file reference name"],
    }


def build_source_xml(background: str, source_xml: Path, source_motion: Path, candidate: Mapping[str, Any], motion_name: str) -> tuple[str, dict[str, Any]]:
    root = ET.parse(source_xml).getroot()
    execution = root.find("execution")
    if execution is None:
        raise ValueError(f"RV4 source lacks execution: {source_xml}")
    for child in list(execution):
        if child.tag in {"particles", "constants", "uservars", "motion", "vtkout"}:
            execution.remove(child)
    definition = root.find(".//casedef/geometry/definition")
    if definition is None:
        raise ValueError(f"RV4 source lacks definition: {source_xml}")
    dp = Decimal(str(candidate["dp"]))
    definition.set("dp", q(dp))
    pointmin = definition.find("pointmin")
    if pointmin is None:
        raise ValueError("definition lacks pointmin")
    for axis, value in zip("xyz", GRID_ORIGIN):
        pointmin.set(axis, value)

    mainlist = root.find(".//casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError("RV4 source lacks geometry mainlist")
    active_fluid: int | None = None
    fluid_boxes = 0
    for node in mainlist:
        if node.tag == "setmkfluid":
            active_fluid = int(node.attrib["mk"])
        elif node.tag == "setmkbound":
            active_fluid = None
        elif node.tag == "drawbox" and active_fluid is not None:
            if active_fluid >= SOURCE_BANDS:
                raise ValueError(f"unexpected source mkfluid {active_fluid}")
            point = node.find("point")
            size = node.find("size")
            if point is None or size is None:
                raise ValueError("fluid drawbox lacks point or size")
            low = (FLUID_LOW[0], FLUID_LOW[1] + active_fluid * SOURCE_BAND_WIDTH, FLUID_LOW[2])
            center = tuple(value + dp / 2 for value in low)
            extent = (FLUID_SIZE[0] - dp, SOURCE_BAND_WIDTH - dp, FLUID_SIZE[2] - dp)
            for axis, value in zip("xyz", center):
                point.set(axis, q(value))
            for axis, value in zip("xyz", extent):
                size.set(axis, q(value))
            fluid_boxes += 1
    if fluid_boxes != SOURCE_BANDS:
        raise ValueError(f"expected three fluid source blocks, got {fluid_boxes}")
    motion_files = root.findall("./casedef/motion//file")
    if len(motion_files) != 1:
        raise ValueError(f"expected one motion file reference, got {len(motion_files)}")
    motion_files[0].set("name", motion_name)
    root.insert(0, ET.Comment(f" F2 matched RV4 same-mother candidate; background={background}; dp={q(dp)}; scope={SCOPE_ID}; "))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True), physical_projection(source_xml, source_motion)


def materialize_case(background: str, candidate_name: str, candidate: Mapping[str, Any], output_root: Path) -> dict[str, Any]:
    info = RV4[background]
    source_xml, source_motion = rv4_paths(background)
    conversion_report = require(info["conversion_report"], f"{background} RV4 conversion report")
    report = json.loads(conversion_report.read_text(encoding="utf-8"))
    actual_physical_hash = report["hash_scopes"]["physical_condition_sha256"]
    if actual_physical_hash != info["physical_condition_hash"]:
        raise ValueError(f"{background}: actual RV4 physical hash changed")
    case_id = f"F2_RV4EQ_MATCHED_{background}_V1_{candidate_name}"
    case_dir = output_root / "definitions" / case_id
    case_dir.mkdir(parents=True, exist_ok=False)
    motion_name = f"{case_id}_motion.dat"
    xml_text, before_projection = build_source_xml(background, source_xml, source_motion, candidate, motion_name)
    xml_path = case_dir / f"{case_id}_Def.xml"
    motion_path = case_dir / motion_name
    xml_path.write_text(xml_text, encoding="utf-8")
    shutil.copyfile(source_motion, motion_path)
    after_projection = physical_projection(xml_path, motion_path)
    equality = same_physical_projection(before_projection, after_projection)
    if not equality["physical_solids_controls_window_equal"]:
        raise ValueError(f"{case_id}: physical projection changed: {equality['differences']}")
    dp = Decimal(str(candidate["dp"]))
    population = expected_population(dp)
    recipe_fields = {
        "candidate_name": candidate_name,
        "resolution": candidate["resolution"],
        "dp_m": decimal_text(dp),
        "grid_origin_m": list(GRID_ORIGIN),
        "fluid_low_m": [decimal_text(value) for value in FLUID_LOW],
        "fluid_size_m": [decimal_text(value) for value in FLUID_SIZE],
        "source_band_width_m": decimal_text(SOURCE_BAND_WIDTH),
        "source_band_count": SOURCE_BANDS,
        "time_max_s": "4",
        "time_out_s": "0.001",
    }
    metadata_path = case_dir / f"{case_id}.metadata.json"
    metadata = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "scope_id": SCOPE_ID,
        "status": "new_same_mother_definition_pending_cpu_gencase",
        "qualification_claim": "none",
        "production_claim": "none",
        "registry_role": "new_same_physical_mother_numeric_reference_outside_original_48_registry",
        "background": background,
        "mechanism_id": info["mechanism_id"],
        "case_id": case_id,
        "physical_case_id": info["physical_case_id"],
        "candidate_name": candidate_name,
        "resolution": candidate["resolution"],
        "candidate_role": candidate["role"],
        "rv4_binding": {
            "staged_xml": {"path": str(source_xml), "sha256": sha256(source_xml)},
            "staged_motion": {"path": str(source_motion), "sha256": sha256(source_motion)},
            "conversion_report": {"path": str(conversion_report), "sha256": sha256(conversion_report)},
            "physical_condition_hash": info["physical_condition_hash"],
            "geometry_family_id": info["geometry_family_id"],
            "control_family_id": info["control_family_id"],
            "physical_projection_sha256": canonical_hash({key: before_projection[key] for key in ("bound_boxes", "constantsdef", "motion", "execution_parameters", "time_window_s", "simulationdomain")}),
            "physical_projection_equality": equality,
        },
        "definition": {"path": str(xml_path.resolve()), "sha256": sha256(xml_path)},
        "motion": {"path": str(motion_path.resolve()), "sha256": sha256(motion_path)},
        "physical_geometry": frozen_geometry_projection(),
        "physical_geometry_is_unchanged": True,
        "finite_solids": before_projection["bound_boxes"],
        "simulationdomain": before_projection["simulationdomain"],
        "motion_and_control": {
            "curve_copied_byte_for_byte": sha256(source_motion) == sha256(motion_path),
            "source_motion_sha256": sha256(source_motion),
            "source_execution_parameters": before_projection["execution_parameters"],
            "source_time_window_s": before_projection["time_window_s"],
        },
        "population_construction": {
            "mode": "three_disjoint cell-centre source blocks",
            "source_mk_values": [1, 2, 3],
            "source_band_bounds_y_m": frozen_geometry_projection()["source_band_bounds_y_m"],
            "center_rule": "point=low+dp/2; size=physical_extent-dp; centres stop at high-dp/2",
            "initial_particles_are_not_renormalized": True,
        },
        "dp_m": float(dp),
        "grid_origin_m": list(GRID_ORIGIN),
        "expected_population": population,
        "mass_budget": {
            "continuous_mass_kg": decimal_text(CONTINUOUS_MASS),
            "native_mass_authority": "generated XML MassFluid and BI4 header after actual GenCase; CSV display is secondary",
            "strict_cell_center_exact_budget_fraction": "1e-12",
            "continuous_geometry_not_rescaled": True,
        },
        "numerical_recipe": recipe_fields,
        "numerical_recipe_hash": canonical_hash(recipe_fields),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    write_json(metadata_path, metadata)
    metadata["metadata"] = {"path": str(metadata_path.resolve()), "sha256": sha256(metadata_path)}
    write_json(metadata_path, metadata)
    metadata["metadata"]["sha256"] = sha256(metadata_path)
    return metadata


def make_gencase_request(metadata: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(metadata["case_id"])
    definition = Path(metadata["definition"]["path"]).resolve()
    motion = Path(metadata["motion"]["path"]).resolve()
    metadata_path = Path(metadata["metadata"]["path"]).resolve()
    source_xml = Path(metadata["rv4_binding"]["staged_xml"]["path"]).resolve()
    source_motion = Path(metadata["rv4_binding"]["staged_motion"]["path"]).resolve()
    conversion_report = Path(metadata["rv4_binding"]["conversion_report"]["path"]).resolve()
    attempt_id = f"gencase-{case_id.lower()}-20261003-001"
    inputs = [Path(__file__).resolve(), RUNTIME_V2.resolve(), GENCASE.resolve(), source_xml, source_motion, definition, motion, metadata_path, conversion_report]
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 4,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "command": [str(GENCASE), str(definition.with_suffix("")), f"{{attempt_root}}/{case_id}", "-save:all"],
        "cwd": str(definition.parent),
        "raw_output_root": str((DATA_ROOT / "families/F2" / case_id).resolve()),
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "solver_launch_forbidden": True,
        "scope_id": SCOPE_ID,
        "physical_condition_hash": metadata["rv4_binding"]["physical_condition_hash"],
        "physical_geometry_control_hash": metadata["rv4_binding"]["physical_condition_hash"],
        "numerical_recipe_hash": metadata["numerical_recipe_hash"],
        "input_files": [str(path) for path in inputs],
        "input_sha256": {str(path): sha256(path) for path in inputs},
        "expected_population": metadata["expected_population"],
        "generation_status": "new_same_mother_gencase_request_registered_not_run",
        "registry_role": "new_same_physical_mother_numeric_reference_outside_original_48_registry",
        "request_note": "CPU GenCase only through shared runtime v2; root owns any solver/GPU. dp=.0064 was rejected by explicit same-mother integer-grid feasibility audit; this request is dp=.01 or lawful dp=.008 fallback.",
    }


def blocked_medium_record() -> dict[str, Any]:
    result = feasibility(REQUESTED_MEDIUM_DP)
    result.update({
        "candidate_name": "MEDIUM_DP0064_REQUESTED",
        "resolution": "MEDIUM",
        "status": "blocked_same_mother_integer_grid_incompatible",
        "physical_geometry_preserved": False,
        "request_registered": False,
        "reason": "Do not shrink/rescale the frozen .32 x .24 x .32 source domain or silently change the 24.576 kg denominator.",
    })
    return result


def design(output_root: Path | None = None) -> dict[str, Any]:
    output_root = (output_root or Path(__file__).resolve().parent / "artifacts").resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"design output must be fresh: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for candidate_name, candidate in VALID_CANDIDATES.items():
        for background in ("CENTER", "OFFSET"):
            metadata = materialize_case(background, candidate_name, candidate, output_root)
            request = make_gencase_request(metadata)
            request_path = output_root / "requests" / f"{metadata['case_id']}_gencase_request.json"
            write_json(request_path, request)
            records.append({
                "background": background,
                "candidate_name": candidate_name,
                "case_id": metadata["case_id"],
                "physical_case_id": metadata["physical_case_id"],
                "mechanism_id": metadata["mechanism_id"],
                "dp_m": metadata["dp_m"],
                "definition": metadata["definition"],
                "motion": metadata["motion"],
                "metadata": metadata["metadata"],
                "request": {"path": str(request_path.resolve()), "sha256": sha256(request_path), "attempt_id": request["attempt_id"]},
                "expected_population": metadata["expected_population"],
            })
    manifest = {
        "schema": f"{SCHEMA}.manifest",
        "family_id": FAMILY_ID,
        "scope_id": SCOPE_ID,
        "status": "same_mother_cpu_gencase_requests_registered_not_run",
        "qualification_claim": "none",
        "production_claim": "none",
        "registry_role": "new_same_physical_mother_numeric_reference_outside_original_48_registry",
        "physical_mother": {
            **frozen_geometry_projection(),
            "mass_authority": "continuous geometry is frozen; generated XML/BI4 native MassFluid is checked independently after GenCase",
            "finite_solids_and_controls": "copied from each RV4 background by source XML and motion hashes",
            "motion_window_s": 4.0,
            "save_interval_s": 0.001,
        },
        "candidate_resolution_plan": {
            "COARSE_DP010": {"dp_m": 0.01, "same_mother": feasibility(Decimal("0.01")), "request_count": 2},
            "MEDIUM_DP008": {"dp_m": 0.008, "same_mother": feasibility(Decimal("0.008")), "request_count": 2},
            "MEDIUM_DP0064_REQUESTED": blocked_medium_record(),
            "fine_reference": {"dp_m": 0.005, "source": "existing additive F2_RV4EQ_DP005 scope; not rewritten here", "same_mother": True},
        },
        "cases": records,
        "source_code": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "next_gate": "parent reviews .0064 blocker and terminal CPU GenCase plus independent initial PartVTK evidence; no GPU request is implied",
    }
    manifest_path = output_root / "rv4-matched-three-dp-init-manifest.json"
    write_json(manifest_path, manifest)
    return {"manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "case_count": len(records), "blocked_medium": manifest["candidate_resolution_plan"]["MEDIUM_DP0064_REQUESTED"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", action="store_true", help="materialise additive definitions and CPU requests")
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if not args.design:
        parser.error("--design is required; this module never runs GenCase directly")
    result = design(args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

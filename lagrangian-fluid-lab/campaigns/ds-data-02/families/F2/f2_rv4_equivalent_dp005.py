#!/usr/bin/env python3
"""Materialise and audit an RV4-equivalent F2 ``dp=0.005`` mother.

The historical COMM4 ``dp=.005`` outputs are retained as negative evidence:
their receiver/tray/motion inputs are different from RV4.  This module starts
from the immutable RV4 generated XML for each background and changes only the
numerical particle spacing, numerical grid phase, and the three explicit
cell-centred fluid source blocks.  The cup, receiver, tray, motion curve,
four-second window, solver controls, and padded simulation domain are copied
from RV4 and are hash-bound in the resulting manifest.

``design`` writes two new-scope definitions and bounded GenCase requests.  A
request is submitted by the parent process through ``ds_data02_runtime_v2``;
this module never starts GenCase directly.  After both receipts are terminal,
``make-audit-request`` registers an independent CPU PartVTK initial-frame
audit.  The audit checks the actual generated XML/BI4, source-band counts and
lattice, native mass authority, finite face coverage, fluid/wall overlap, and
the copied motion/control binding.  It makes no solver, Q-I, Q-N, or
production claim.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import struct
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002"
SCHEMA = "ds-data-02.f2.rv4-equivalent-dp005.v1"
FAMILY_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = FAMILY_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")

RV4_ROOT = INTEGRATION_LAB / "campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs"
RV4 = {
    "CENTER": {
        "mechanism": "center_catch",
        "physical_case_id": "F2H10V2_CENTER_V1",
        "source_case": "F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001",
        "physical_condition_hash": "45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43",
        "geometry_family_id": "F2_GEOM_GEM_CUP_RECEIVER_CENTER_CATCH_V2",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_GEM_V2",
        "conversion_report": DATA_ROOT / "families/F2/F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001/conversion-f2h10v2_center_v1_medium_rv4d1_baseline_save001-fullstate-v5-002/conversion-report.json",
    },
    "OFFSET": {
        "mechanism": "offset_spill",
        "physical_case_id": "F2H10V2_OFFSET_V1",
        "source_case": "F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001",
        "physical_condition_hash": "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef",
        "geometry_family_id": "F2_GEOM_GEM_CUP_RECEIVER_OFFSET_SPILL_V2",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_GEM_V2",
        "conversion_report": DATA_ROOT / "families/F2/F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001/conversion-f2h10v2_offset_v1_medium_rv4d1_baseline_save001-fullstate-v5-002/conversion-report.json",
    },
}

# The pointmin is a numerical lattice phase, not a physical wall.  It makes
# all three fluid source blocks land exactly on the dp=.005 grid while keeping
# the RV4 simulationdomain unchanged.
DP = 0.005
GRID_ORIGIN = (-1.4200, -1.2225, -0.5625)
FLUID_LOW = (0.0525, -0.12, 0.70)
FLUID_SIZE = (0.32, 0.24, 0.32)
SOURCE_BANDS = 3
SOURCE_BAND_WIDTH = 0.08
RHO0 = 1000.0
CONTINUOUS_VOLUME = FLUID_SIZE[0] * FLUID_SIZE[1] * FLUID_SIZE[2]
CONTINUOUS_MASS = CONTINUOUS_VOLUME * RHO0
CELLS_XYZ = tuple(round(value / DP) for value in FLUID_SIZE)
CELLS_PER_BAND = (CELLS_XYZ[0], round(SOURCE_BAND_WIDTH / DP), CELLS_XYZ[2])
FLUID_COUNT_PER_BAND = CELLS_PER_BAND[0] * CELLS_PER_BAND[1] * CELLS_PER_BAND[2]
FLUID_COUNT = FLUID_COUNT_PER_BAND * SOURCE_BANDS
MASS_FLUID_EXACT = RHO0 * DP**3


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


def q(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".") or "0"


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def rv4_paths(background: str) -> tuple[Path, Path]:
    if background not in RV4:
        raise ValueError(f"unknown background: {background}")
    case = RV4[background]["source_case"]
    directory = (RV4_ROOT / case).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"RV4 staging directory for {background} missing: {directory}")
    return require(directory / f"{case}.xml", "RV4 XML"), require(directory / f"F2H10V2_{background}_V1_MEDIUM_motion.dat", "RV4 motion")


def parse_motion_samples(path: Path) -> dict[str, Any]:
    """Record the actual copied curve bytes and basic time/sample facts."""
    text = path.read_text(encoding="utf-8", errors="replace")
    numeric_rows: list[tuple[float, ...]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
            continue
        fields = stripped.replace(",", " ").split()
        try:
            values = tuple(float(item) for item in fields)
        except ValueError:
            continue
        if len(values) >= 2:
            numeric_rows.append(values)
    times = [row[0] for row in numeric_rows]
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "numeric_row_count": len(numeric_rows),
        "time_start_s": min(times) if times else None,
        "time_end_s": max(times) if times else None,
        "curve_bytes_unchanged": True,
    }


def _attrs(node: ET.Element | None, keys: Iterable[str]) -> dict[str, str] | None:
    if node is None:
        return None
    return {key: node.attrib.get(key, "") for key in keys}


def declared_bound_boxes(xml_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(xml_path).getroot()
    mainlist = root.find(".//casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError(f"no casedef mainlist in {xml_path}")
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
                raise ValueError(f"bound drawbox lacks point/size in {xml_path}")
            boxes.append({
                "mk": current_mk,
                "boxfill": node.findtext("boxfill", default="").strip(),
                "low_m": [float(point.attrib[key]) for key in "xyz"],
                "size_m": [float(size.attrib[key]) for key in "xyz"],
            })
    if len(boxes) != 3:
        raise ValueError(f"expected cup/receiver/tray bound boxes, got {len(boxes)} in {xml_path}")
    return boxes


def source_projection(xml_path: Path, motion_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    constants = root.find(".//casedef/constantsdef")
    if constants is None:
        raise ValueError(f"missing constantsdef: {xml_path}")
    constants_projection = [
        (node.tag, tuple(sorted(node.attrib.items()))) for node in constants
    ]
    motion = root.find("./casedef/motion/objreal")
    if motion is None:
        raise ValueError(f"missing casedef motion: {xml_path}")
    begin = motion.find("begin")
    mvrot = motion.find("mvrotfile")
    if begin is None or mvrot is None:
        raise ValueError(f"incomplete motion control: {xml_path}")
    axis1 = mvrot.find("axisp1")
    axis2 = mvrot.find("axisp2")
    parameters = root.findall(".//execution/parameters/parameter")
    parameter_projection = sorted((node.attrib.get("key", ""), node.attrib.get("value", "")) for node in parameters)
    simulationdomain = root.find(".//execution/parameters/simulationdomain")
    if simulationdomain is None:
        raise ValueError(f"missing simulationdomain: {xml_path}")
    posmin = simulationdomain.find("posmin")
    posmax = simulationdomain.find("posmax")
    definition = root.find(".//casedef/geometry/definition")
    return {
        "bound_boxes": declared_bound_boxes(xml_path),
        "constantsdef": constants_projection,
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
            "posmin": _attrs(posmin, ("x", "y", "z")),
            "posmax": _attrs(posmax, ("x", "y", "z")),
        },
        "definition_dp": definition.attrib.get("dp") if definition is not None else None,
    }


def build_source_xml(background: str, source_xml: Path, motion_name: str) -> tuple[str, dict[str, Any]]:
    """Return a GenCase source with only the registered dp/grid/fluid edits."""
    root = ET.parse(source_xml).getroot()
    execution = root.find("execution")
    if execution is None:
        raise ValueError(f"RV4 XML has no execution node: {source_xml}")
    # Generated RV4 XML contains solver-output sections.  They are removed
    # because this file is a new GenCase source; the casedef physical/control
    # contract remains byte-bound to the staged RV4 source below.
    for child in list(execution):
        if child.tag in {"particles", "constants", "uservars", "motion", "vtkout"}:
            execution.remove(child)
    definition = root.find(".//casedef/geometry/definition")
    if definition is None:
        raise ValueError(f"missing geometry definition: {source_xml}")
    definition.set("dp", q(DP))
    for axis, value in zip("xyz", GRID_ORIGIN):
        definition.find("pointmin").set(axis, q(value))

    mainlist = root.find(".//casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError(f"missing geometry mainlist: {source_xml}")
    active_fluid: int | None = None
    fluid_boxes = 0
    for node in mainlist:
        if node.tag == "setmkfluid":
            active_fluid = int(node.attrib["mk"])
        elif node.tag == "setmkbound":
            active_fluid = None
        elif node.tag == "drawbox" and active_fluid is not None:
            if active_fluid >= SOURCE_BANDS:
                raise ValueError(f"unexpected fluid material index {active_fluid}")
            point = node.find("point")
            size = node.find("size")
            if point is None or size is None:
                raise ValueError("fluid drawbox lacks point/size")
            low = (FLUID_LOW[0], FLUID_LOW[1] + active_fluid * SOURCE_BAND_WIDTH, FLUID_LOW[2])
            center = tuple(low[index] + DP / 2 for index in range(3))
            extent = (FLUID_SIZE[0] - DP, SOURCE_BAND_WIDTH - DP, FLUID_SIZE[2] - DP)
            for axis, value in zip("xyz", center):
                point.set(axis, q(value))
            for axis, value in zip("xyz", extent):
                size.set(axis, q(value))
            fluid_boxes += 1
    if fluid_boxes != SOURCE_BANDS:
        raise ValueError(f"expected {SOURCE_BANDS} RV4 fluid source boxes, got {fluid_boxes}")
    motion_files = root.findall("./casedef/motion//file")
    if len(motion_files) != 1:
        raise ValueError(f"expected one casedef motion file, got {len(motion_files)}")
    motion_files[0].set("name", motion_name)

    # Replacing the comment is deliberately separate from physical content;
    # generated XML comments are not used in the physical hash.
    root.insert(0, ET.Comment(
        f" F2 RV4-equivalent dp005 source; background={background}; "
        f"scope={SCOPE_ID}; old COMM4 DP005 is a negative, non-equivalent scope. "
    ))
    ET.indent(root, space="  ")
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    projection = source_projection(source_xml, rv4_paths(background)[1])
    return xml_bytes.decode("utf-8"), projection


def expected_population() -> dict[str, Any]:
    return {
        "cells_xyz": list(CELLS_XYZ),
        "source_band_cells_xyz": list(CELLS_PER_BAND),
        "source_band_particle_count": FLUID_COUNT_PER_BAND,
        "source_band_count": SOURCE_BANDS,
        "total_particle_count": FLUID_COUNT,
        "continuous_volume_m3": CONTINUOUS_VOLUME,
        "continuous_mass_kg": CONTINUOUS_MASS,
        "expected_particle_mass_kg": MASS_FLUID_EXACT,
        "expected_lattice_mass_kg": FLUID_COUNT * MASS_FLUID_EXACT,
        "relative_mass_error": FLUID_COUNT * DP**3 / CONTINUOUS_VOLUME - 1.0,
    }


def equal_physical_contract(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the physical projection while allowing dp/grid/fluid edits."""
    keys = ("bound_boxes", "constantsdef", "motion", "execution_parameters", "time_window_s", "simulationdomain")
    differences: dict[str, Any] = {}
    for key in keys:
        if before[key] != after[key]:
            differences[key] = {"rv4": before[key], "dp005": after[key]}
    return {
        "compared_keys": list(keys),
        "differences": differences,
        "physical_solids_controls_window_equal": not differences,
        "allowed_numerical_changes": {"definition_dp": {"rv4": before["definition_dp"], "dp005": q(DP)}, "grid_origin_m": list(GRID_ORIGIN), "fluid_blocks": "three explicit cell-centred blocks"},
    }


def source_paths_for_metadata(background: str) -> tuple[Path, Path, Path]:
    source_xml, source_motion = rv4_paths(background)
    return source_xml, source_motion, require(RV4[background]["conversion_report"], "RV4 conversion report")


def materialize_case(background: str, output_root: Path) -> dict[str, Any]:
    info = RV4[background]
    source_xml, source_motion, conversion_report = source_paths_for_metadata(background)
    case_id = f"F2_RV4EQ_DP005_{background}_V1"
    case_dir = output_root / "definitions" / case_id
    case_dir.mkdir(parents=True, exist_ok=False)
    motion_name = f"{case_id}_motion.dat"
    xml_text, rv4_projection = build_source_xml(background, source_xml, motion_name)
    xml_path = case_dir / f"{case_id}_Def.xml"
    motion_path = case_dir / motion_name
    xml_path.write_text(xml_text, encoding="utf-8")
    shutil.copyfile(source_motion, motion_path)
    after_projection = source_projection(xml_path, motion_path)
    equality = equal_physical_contract(rv4_projection, after_projection)
    if not equality["physical_solids_controls_window_equal"]:
        raise ValueError(f"{case_id}: RV4 physical contract changed: {equality['differences']}")
    report = json.loads(conversion_report.read_text(encoding="utf-8"))
    actual_hash = report["hash_scopes"]["physical_condition_sha256"]
    if actual_hash != info["physical_condition_hash"]:
        raise ValueError(f"{case_id}: configured RV4 physical hash differs from actual report")
    projection_hash = canonical_hash({key: rv4_projection[key] for key in ("bound_boxes", "constantsdef", "motion", "execution_parameters", "time_window_s", "simulationdomain")})
    numerical_fields = {
        "case_id": case_id,
        "physical_case_id": info["physical_case_id"],
        "dp_m": DP,
        "grid_origin_m": list(GRID_ORIGIN),
        "fluid_low_m": list(FLUID_LOW),
        "fluid_size_m": list(FLUID_SIZE),
        "source_band_width_m": SOURCE_BAND_WIDTH,
        "time_max_s": 4.0,
        "save_interval_s": 0.001,
        "rv4_domain_repair": "unchanged padded simulationdomain from RV4",
    }
    metadata = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "scope_id": SCOPE_ID,
        "status": "new_scope_definition_only_pending_gencase",
        "qualification_claim": "none",
        "production_claim": "none",
        "registry_role": "new_RV4_equivalent_finer_reference_outside_original_48_registry",
        "background": background,
        "mechanism_id": info["mechanism"],
        "case_id": case_id,
        "physical_case_id": info["physical_case_id"],
        "numerical_view_role": "candidate_finer_reference_same_RV4_physical_mother",
        "negative_scope_separation": {
            "old_comm4_dp005_is_not_reused": True,
            "reason": "old COMM4 DP005 finite solids and motion/control hashes differ from RV4",
            "old_scope": "F2_COMM4_DP005_REPAIR01_NATIVE_EXCLUSION_DIAGNOSTIC",
        },
        "rv4_binding": {
            "staged_xml": {"path": str(source_xml), "sha256": sha256(source_xml)},
            "staged_motion": {"path": str(source_motion), "sha256": sha256(source_motion)},
            "conversion_report": {"path": str(conversion_report), "sha256": sha256(conversion_report)},
            "physical_condition_hash": info["physical_condition_hash"],
            "geometry_family_id": info["geometry_family_id"],
            "control_family_id": info["control_family_id"],
            "physical_projection_sha256": projection_hash,
            "physical_projection_equality": equality,
            "motion_curve": parse_motion_samples(source_motion),
        },
        "definition": {"path": str(xml_path.resolve()), "sha256": sha256(xml_path)},
        "motion": {"path": str(motion_path.resolve()), "sha256": sha256(motion_path)},
        "dp_m": DP,
        "grid_origin_m": list(GRID_ORIGIN),
        "geometry": {
            "continuous_fluid_low_m": list(FLUID_LOW),
            "continuous_fluid_size_m": list(FLUID_SIZE),
            "continuous_fluid_volume_m3": CONTINUOUS_VOLUME,
            "continuous_mass_kg": CONTINUOUS_MASS,
            "source_axis": "y",
            "source_band_count": SOURCE_BANDS,
            "source_band_width_m": SOURCE_BAND_WIDTH,
            "source_band_bounds_y_m": [[FLUID_LOW[1] + i * SOURCE_BAND_WIDTH, FLUID_LOW[1] + (i + 1) * SOURCE_BAND_WIDTH] for i in range(SOURCE_BANDS)],
            "cell_center_rule": "each source band point=low+dp/2; size=extent-dp; centres stop at high-dp/2",
            "finite_solids": rv4_projection["bound_boxes"],
            "simulationdomain_copied_from_rv4": rv4_projection["simulationdomain"],
        },
        "motion_and_control": {
            "curve_file_copied_byte_for_byte": True,
            "axis_and_window_copied_from_rv4": rv4_projection["motion"],
            "solver_execution_parameters_copied_from_rv4": True,
            "physical_condition_hash_excludes_dp_grid_and_fluid_population": True,
        },
        "population_construction": {
            "mode": "three_disjoint_drawbox_cell_center_sources",
            "source_mk_values": [1, 2, 3],
            "source_band_particle_count": FLUID_COUNT_PER_BAND,
            "expected_particle_count": FLUID_COUNT,
            "initial_particles_are_not_renormalized": True,
        },
        "expected_population": expected_population(),
        "mass_budget": {
            "continuous_mass_kg": CONTINUOUS_MASS,
            "native_mass_authority": "generated XML massfluid decimal × actual native fluid count; BI4 header checked independently",
            "relative_budget_fraction": 1.0e-12,
            "csv_display_rounding_is_not_authority": True,
        },
        "numerical_fields": numerical_fields,
        "numerical_recipe_hash": canonical_hash(numerical_fields),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    metadata_path = case_dir / f"{case_id}.metadata.json"
    write_json(metadata_path, metadata)
    metadata["metadata"] = {"path": str(metadata_path.resolve()), "sha256": sha256(metadata_path)}
    write_json(metadata_path, metadata)
    metadata["metadata"]["sha256"] = sha256(metadata_path)
    return metadata


def make_gencase_request(metadata: Mapping[str, Any], output_root: Path, request_root: Path) -> dict[str, Any]:
    case_id = str(metadata["case_id"])
    definition = Path(metadata["definition"]["path"]).resolve()
    motion = Path(metadata["motion"]["path"]).resolve()
    metadata_path = Path(metadata["metadata"]["path"]).resolve()
    source_xml = Path(metadata["rv4_binding"]["staged_xml"]["path"]).resolve()
    source_motion = Path(metadata["rv4_binding"]["staged_motion"]["path"]).resolve()
    attempt_id = f"gencase-{case_id.lower()}-20261002-001"
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
        "raw_output_root": str((output_root / case_id).resolve()),
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "solver_launch_forbidden": True,
        "scope_id": SCOPE_ID,
        "physical_condition_hash": metadata["rv4_binding"]["physical_condition_hash"],
        "physical_geometry_control_hash": metadata["rv4_binding"]["physical_condition_hash"],
        "numerical_recipe_hash": metadata["numerical_recipe_hash"],
        "input_files": [str(Path(__file__).resolve()), str(RUNTIME_V2.resolve()), str(GENCASE.resolve()), str(source_xml), str(source_motion), str(definition), str(motion), str(metadata_path), str(metadata["rv4_binding"]["conversion_report"]["path"])],
        "input_sha256": {str(path): sha256(Path(path)) for path in [Path(__file__).resolve(), RUNTIME_V2.resolve(), GENCASE.resolve(), source_xml, source_motion, definition, motion, metadata_path, Path(metadata["rv4_binding"]["conversion_report"]["path"]).resolve()]},
        "expected_population": metadata["expected_population"],
        "generation_status": "new_RV4_equivalent_dp005_definition_registered_not_run",
        "registry_role": "new_scope_new_finer_reference_outside_original_48_registry",
        "request_note": "CPU GenCase only through shared v2 runner; no solver/GPU/Q-I/Q-N/production claim. Old COMM4 DP005 remains a separate negative scope.",
    }


def design(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    design_root = FAMILY_ROOT / "rv4_equivalent_dp005"
    if design_root.exists() and any(design_root.iterdir()):
        raise ValueError(f"design output must be fresh: {design_root}")
    design_root.mkdir(parents=True, exist_ok=True)
    requests_dir = design_root / "requests"
    requests_dir.mkdir()
    records: list[dict[str, Any]] = []
    for background in ("CENTER", "OFFSET"):
        metadata = materialize_case(background, design_root)
        request = make_gencase_request(metadata, output_root, requests_dir)
        request_path = requests_dir / f"{metadata['case_id']}_gencase_request.json"
        write_json(request_path, request)
        records.append({
            "background": background,
            "case_id": metadata["case_id"],
            "physical_case_id": metadata["physical_case_id"],
            "mechanism_id": metadata["mechanism_id"],
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
        "status": "new_scope_gencase_requests_registered_not_run",
        "qualification_claim": "none",
        "production_claim": "none",
        "registry_role": "new_RV4_equivalent_finer_reference_outside_original_48_registry",
        "rv4_equivalence": "same finite cup/receiver/tray boxes, motion bytes, axis, four-second window, execution controls, and padded simulationdomain; only dp, numerical grid phase, and explicit fluid cell-centre blocks differ",
        "continuous_fluid": {"low_m": list(FLUID_LOW), "size_m": list(FLUID_SIZE), "volume_m3": CONTINUOUS_VOLUME, "mass_kg": CONTINUOUS_MASS, "source_bands": SOURCE_BANDS},
        "dp_m": DP,
        "grid_origin_m": list(GRID_ORIGIN),
        "expected_population": expected_population(),
        "cases": records,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_code": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
        "next_gate": "parent reviews terminal CPU GenCase and independent initial PartVTK audit before any GPU request",
    }
    manifest_path = design_root / "manifest.json"
    write_json(manifest_path, manifest)
    return {"manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "case_count": len(records), "cases": records}


def parse_csv(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Pos.x [m]")), None)
    if header_index is None:
        raise ValueError(f"PartVTK header missing: {path}")
    header = [item.strip() for item in lines[header_index].split(",") if item.strip()]
    required = {"Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk", "Mass [kg]"}
    missing = required.difference(header)
    if missing:
        raise ValueError(f"PartVTK fields missing {sorted(missing)}: {path}")
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 1 :]:
        if not line.strip():
            continue
        fields = [item.strip() for item in line.split(",")]
        if len(fields) >= len(header):
            rows.append(dict(zip(header, fields)))
    if not rows:
        raise ValueError(f"PartVTK has no rows: {path}")
    return rows


def run_partvtk(data_dir: Path, report_dir: Path, case_id: str) -> tuple[Path, dict[str, Any]]:
    report_dir.mkdir(parents=True, exist_ok=True)
    prefix = report_dir / "initial"
    xml = require(data_dir / f"{case_id}.xml", "generated XML")
    bi4 = require(data_dir / f"{case_id}.bi4", "generated BI4")
    command = [str(PARTVTK), "-filedata", str(bi4), "-filexml", str(xml), "-first:0", "-last:0", "-threads:4", "-savecsv", str(prefix), "-onlytype:+all", "-vars:-all,+idp,+vel,+rhop,+type,+mk,+mass,+zone", "-csvsep:1"]
    result = subprocess.run(command, cwd=report_dir, capture_output=True, text=True, check=False, timeout=600)
    log = report_dir / "partvtk.stdout.log"
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    csvs = [path for path in sorted(report_dir.glob("initial_*.csv")) if not path.name.endswith("_stats.csv")]
    if not csvs and (report_dir / "initial.csv").is_file():
        csvs = [report_dir / "initial.csv"]
    if result.returncode != 0 or not csvs:
        raise RuntimeError(f"PartVTK failed for {case_id}; see {log}")
    return csvs[0], {"command": command, "returncode": result.returncode, "csv": {"path": str(csvs[0]), "sha256": sha256(csvs[0]), "bytes": csvs[0].stat().st_size}, "log": {"path": str(log), "sha256": sha256(log), "bytes": log.stat().st_size}, "binary": {"path": str(PARTVTK), "sha256": sha256(PARTVTK)}}


def row_float(row: Mapping[str, str], key: str) -> float:
    return float(row[key])


def row_int(row: Mapping[str, str], key: str) -> int:
    return int(float(row[key]))


def face_names(boxfill: str) -> tuple[str, ...]:
    return tuple({"bottom": "z-", "top": "z+", "left": "x-", "right": "x+", "front": "y-", "back": "y+"}[part.strip()] for part in boxfill.split("|") if part.strip() in {"bottom", "top", "left", "right", "front", "back"})


def finite_face_audit(rows: list[dict[str, str]], boxes: list[dict[str, Any]], dp: float) -> dict[str, Any]:
    tolerance = max(2.25 * dp, 1e-6)
    by_mk: dict[int, list[tuple[float, float, float]]] = {}
    for row in rows:
        if row_int(row, "Type") not in (0, 1):
            continue
        by_mk.setdefault(row_int(row, "Mk"), []).append(tuple(row_float(row, f"Pos.{axis} [m]") for axis in "xyz"))
    result: dict[str, Any] = {}
    all_pass = True
    axes = {"x": 0, "y": 1, "z": 2}
    for box in boxes:
        points = by_mk.get({0: 17, 1: 18, 2: 19}[box["mk"]], [])
        low = box["low_m"]
        high = [a + b for a, b in zip(low, box["size_m"])]
        faces: dict[str, Any] = {}
        for face in face_names(box["boxfill"]):
            axis = axes[face[0]]
            target = low[axis] if face[1] == "-" else high[axis]
            selected = [point for point in points if abs(point[axis] - target) <= tolerance]
            tangential = [index for index in range(3) if index != axis]
            spans = []
            for index in tangential:
                values = [point[index] for point in selected]
                spans.append((max(values) - min(values)) / max(box["size_m"][index], 1e-12) if values else 0.0)
            span = min(spans) if spans else 0.0
            passed = bool(selected) and span >= 0.85
            all_pass = all_pass and passed
            faces[face] = {"count": len(selected), "span_fraction": span, "coordinate_target_m": target, "tolerance_m": tolerance, "pass": passed}
        result[str(box["mk"])] = {"boxfill": box["boxfill"], "native_mk": {0: 17, 1: 18, 2: 19}[box["mk"]], "faces": faces, "pass": all(item["pass"] for item in faces.values())}
    return {"boxes": result, "all_finite_faces_covered": all_pass}


def audit_case(record: Mapping[str, Any], report_root: Path) -> dict[str, Any]:
    request_path = Path(record["request"]["path"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    receipt_path = DATA_ROOT / "families" / FAMILY_ID / str(record["case_id"]) / str(request["attempt_id"]) / "execution-receipt.json"
    receipt = json.loads(require(receipt_path, "GenCase execution receipt").read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"GenCase receipt is not successful: {receipt_path}")
    expected = record["expected_population"]
    generated_dir = Path(receipt["output_root"])
    case_id = str(record["case_id"])
    xml = require(generated_dir / f"{case_id}.xml", "generated output XML")
    bi4 = require(generated_dir / f"{case_id}.bi4", "generated output BI4")
    generated_motion = require(generated_dir / f"{case_id}_motion.dat", "generated copied motion")
    generated_root = ET.parse(xml).getroot()
    constants = generated_root.find(".//execution/constants")
    particles = generated_root.find(".//execution/particles")
    if constants is None or particles is None:
        raise ValueError(f"GenCase output lacks constants/particles: {xml}")
    data2d = constants.find("data2d")
    mass_node = constants.find("massfluid")
    dp_node = constants.find("dp")
    fluid_summary = particles.find("_summary/fluid")
    if data2d is None or mass_node is None or dp_node is None or fluid_summary is None:
        raise ValueError(f"GenCase output lacks required mass/3-D summary: {xml}")
    actual_fluid_count = int(fluid_summary.attrib["count"])
    source_counts = [int(node.attrib["count"]) for node in particles.findall("fluid")]
    generated_massfluid = Decimal(mass_node.attrib["value"])
    authoritative_mass = generated_massfluid * actual_fluid_count
    relative_mass_error = float(authoritative_mass / Decimal(str(CONTINUOUS_MASS)) - Decimal(1))
    source_xml = Path(record["metadata"]["path"]).with_name(f"{case_id}_Def.xml")
    source_motion = Path(record["motion"]["path"])
    source_projection_data = source_projection(source_xml, source_motion)
    output_projection = source_projection(xml, generated_motion)
    physical_equal = equal_physical_contract(source_projection_data, output_projection)
    csv_path, partvtk = run_partvtk(generated_dir, report_root / case_id / "partvtk", case_id)
    rows = parse_csv(csv_path)
    fluid_rows = [row for row in rows if row_int(row, "Type") == 3]
    points = [(row_float(row, "Pos.x [m]"), row_float(row, "Pos.y [m]"), row_float(row, "Pos.z [m]")) for row in fluid_rows]
    typed_ids = [(row_int(row, "Zone"), row_int(row, "Idp")) for row in rows]
    axis_expected = [[FLUID_LOW[index] + DP / 2 + n * DP for n in range(CELLS_XYZ[index])] for index in range(3)]
    axis_actual = [sorted({round(point[index], 8) for point in points}) for index in range(3)]
    axis_checks = []
    for actual, expected_axis in zip(axis_actual, axis_expected):
        errors = [min(abs(value - target) for target in expected_axis) for value in actual]
        axis_checks.append({"actual_count": len(actual), "expected_count": len(expected_axis), "first_m": actual[0] if actual else None, "last_m": actual[-1] if actual else None, "max_nearest_error_m": max(errors, default=float("inf")), "pass": len(actual) == len(expected_axis) and max(errors, default=float("inf")) <= 2.0e-7})
    source_mks = sorted({row_int(row, "Mk") for row in fluid_rows})
    per_source = {str(mk): sum(row_int(row, "Mk") == mk for row in fluid_rows) for mk in source_mks}
    boxes = declared_bound_boxes(source_xml)
    receiver = next(box for box in boxes if box["mk"] == 1)
    tray = next(box for box in boxes if box["mk"] == 2)
    def inside(point: tuple[float, float, float], box: Mapping[str, Any]) -> bool:
        high = [a + b for a, b in zip(box["low_m"], box["size_m"])]
        return all(low - 1e-12 <= value <= top + 1e-12 for value, low, top in zip(point, box["low_m"], high))
    receiver_overlap = sum(inside(point, receiver) for point in points)
    tray_overlap = sum(inside(point, tray) for point in points)
    moving_rows = [row for row in rows if row_int(row, "Type") == 1 and row_int(row, "Mk") == 17]
    report = {
        "schema": f"{SCHEMA}.initial-audit",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": case_id,
        "background": record["background"],
        "scope_id": SCOPE_ID,
        "qualification_claim": "none; independent GenCase/PartVTK initial evidence only",
        "production_claim": "none",
        "gencase": {"receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)}, "output_root": str(generated_dir), "xml": {"path": str(xml), "sha256": sha256(xml)}, "bi4": {"path": str(bi4), "sha256": sha256(bi4)}, "motion": {"path": str(generated_motion), "sha256": sha256(generated_motion)}, "reported_dimension": receipt.get("solver_dimension_from_gencase"), "reported_total_particles": receipt.get("total_particles"), "reported_fluid_particles": receipt.get("fluid_particles")},
        "rv4_binding": {"metadata_path": str(record["metadata"]["path"]), "metadata_sha256": record["metadata"]["sha256"], "physical_condition_hash": request["physical_condition_hash"], "physical_contract_equal_after_gencase": physical_equal, "source_motion_sha256": sha256(source_motion), "generated_motion_sha256": sha256(generated_motion), "motion_bytes_equal": sha256(source_motion) == sha256(generated_motion), "motion_control": source_projection_data["motion"]},
        "native_xml_mass": {"data2d_value": data2d.attrib.get("value"), "dp_m": float(dp_node.attrib["value"]), "massfluid_decimal_kg": str(generated_massfluid), "native_fluid_count": actual_fluid_count, "authoritative_mass_kg": str(authoritative_mass), "continuous_mass_kg": str(Decimal(str(CONTINUOUS_MASS))), "relative_error": relative_mass_error, "budget_fraction": 1.0e-12, "pass": abs(relative_mass_error) <= 1.0e-12},
        "native_initial_population": {"csv": partvtk["csv"], "row_count": len(rows), "fluid_count": len(fluid_rows), "source_mk_values": source_mks, "source_counts": per_source, "expected_source_count": FLUID_COUNT_PER_BAND, "typed_id_duplicate_count": len(typed_ids) - len(set(typed_ids)), "moving_type1_mk17_count": len(moving_rows), "axis_lattice": axis_checks, "grid_origin_m": list(GRID_ORIGIN)},
        "finite_geometry": finite_face_audit(rows, boxes, DP),
        "initial_fluid_overlap": {"receiver_particle_count": receiver_overlap, "tray_particle_count": tray_overlap, "fluid_is_strictly_inside_cup_contract": receiver_overlap == 0 and tray_overlap == 0, "interpretation": "receiver/tray overlap is checked from actual initial PartVTK positions; cup interior/finite faces are separately audited"},
        "checks": {
            "actual_3d": data2d.attrib.get("value") in {"0", "false", "False"},
            "nonzero_fluid": actual_fluid_count == FLUID_COUNT,
            "three_source_counts": source_mks == [1, 2, 3] and source_counts == [FLUID_COUNT_PER_BAND] * 3,
            "typed_ids_unique": len(typed_ids) == len(set(typed_ids)),
            "lattice_axes": all(item["pass"] for item in axis_checks),
            "finite_faces": finite_face_audit(rows, boxes, DP)["all_finite_faces_covered"],
            "no_receiver_or_tray_overlap": receiver_overlap == 0 and tray_overlap == 0,
            "physical_controls_unchanged": physical_equal["physical_solids_controls_window_equal"],
            "motion_bytes_equal": sha256(source_motion) == sha256(generated_motion),
            "authoritative_mass_budget": abs(relative_mass_error) <= 1.0e-12,
        },
        "next_gate": "parent reviews both terminal CPU audits; no GPU request is generated by this module",
    }
    report["all_initial_checks_pass"] = all(report["checks"].values())
    output = report_root / case_id / "rv4-equivalent-dp005-initial-audit.json"
    write_json(output, report)
    return {"case_id": case_id, "report": str(output), "report_sha256": sha256(output), "all_initial_checks_pass": report["all_initial_checks_pass"], "checks": report["checks"], "native_counts": {"fluid": actual_fluid_count, "sources": per_source}, "mass": report["native_xml_mass"]}


def make_audit_request(manifest_path: Path, request_path: Path, attempt_id: str) -> dict[str, Any]:
    manifest = json.loads(require(manifest_path, "manifest").read_text(encoding="utf-8"))
    if len(manifest.get("cases", [])) != 2:
        raise ValueError("audit request requires the two new RV4-equivalent cases")
    input_files: list[Path] = [Path(__file__).resolve(), RUNTIME_V2.resolve(), PARTVTK.resolve(), manifest_path.resolve()]
    for record in manifest["cases"]:
        input_files.extend([Path(record["request"]["path"]), Path(record["definition"]["path"]), Path(record["motion"]["path"]), Path(record["metadata"]["path"])])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in input_files:
        path = require(path, "audit input")
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": "F2_RV4EQ_DP005_INITIAL_AUDIT",
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 8 * 1024 * 1024 * 1024,
        "command": ["/usr/bin/env", "bash", "-lc", f"exec /home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python {Path(__file__).resolve()} audit --manifest {manifest_path.resolve()} --report-root {{attempt_root}}/reports"],
        "cwd": str(FAMILY_ROOT.resolve()),
        "raw_output_root": str((DATA_ROOT / "families/F2/F2_RV4EQ_DP005_INITIAL_AUDIT").resolve()),
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "solver_launch_forbidden": True,
        "scope_id": SCOPE_ID,
        "input_files": [str(path) for path in unique],
        "input_sha256": {str(path): sha256(path) for path in unique},
        "request_note": "CPU PartVTK initial-frame audit of two completed GenCase artefacts only; no solver/GPU/Q-I/Q-N/production claim.",
    }
    write_json(request_path, request)
    return request


def audit_manifest(manifest_path: Path, report_root: Path) -> dict[str, Any]:
    manifest = json.loads(require(manifest_path, "manifest").read_text(encoding="utf-8"))
    rows = [audit_case(record, report_root) for record in manifest["cases"]]
    result = {"schema": f"{SCHEMA}.audit-manifest", "manifest": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)}, "scope_id": SCOPE_ID, "cases": rows, "all_initial_checks_pass": all(row["all_initial_checks_pass"] for row in rows), "qualification_claim": "none", "production_claim": "none"}
    output = report_root / "rv4-equivalent-dp005-initial-audit-manifest.json"
    write_json(output, result)
    result["report"] = {"path": str(output), "sha256": sha256(output)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_design = sub.add_parser("design")
    p_design.add_argument("--output-root", type=Path, default=DATA_ROOT / "families/F2/F2_RV4EQ_DP005")
    p_audit_request = sub.add_parser("make-audit-request")
    p_audit_request.add_argument("--manifest", type=Path, required=True)
    p_audit_request.add_argument("--request", type=Path, required=True)
    p_audit_request.add_argument("--attempt-id", default="audit-f2-rv4eq-dp005-initial-20261002-001")
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("--manifest", type=Path, required=True)
    p_audit.add_argument("--report-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "design":
        print(json.dumps({"status": "designed", **design(args.output_root)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "make-audit-request":
        request = make_audit_request(args.manifest.resolve(), args.request.resolve(), args.attempt_id)
        print(json.dumps({"status": "written", "request": str(args.request.resolve()), "input_count": len(request["input_files"])}, ensure_ascii=False, indent=2))
        return 0
    result = audit_manifest(args.manifest.resolve(), args.report_root.resolve())
    return 0 if result["all_initial_checks_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

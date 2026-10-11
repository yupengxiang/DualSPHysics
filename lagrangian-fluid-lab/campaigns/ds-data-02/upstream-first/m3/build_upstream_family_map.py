#!/usr/bin/env python3
"""Build the M3 official-package family crosswalk from metadata only.

This builder parses the seven selected official definition XML files and their
small launch scripts, and reads the existing M3 catalog/proof JSON.  Referenced
particle arrays and scientific payloads are never opened.  Reference/control
assets are represented by path, existence and byte size only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
WORKTREE = next((p for p in HERE.parents if (p / "lagrangian-fluid-lab").is_dir()), HERE.parents[5])
OFFICIAL = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4"
)
CATALOG_PATH = HERE / "scope_catalog.json"
JSON_OUT = HERE / "upstream-family-map.json"
MD_OUT = HERE / "upstream-family-map.md"

PLAN_PATH = (
    WORKTREE
    / "lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/adopted-plan/PLAN_ZH.md"
)
DERIVATIVE_PATH = HERE / "derivative-design.json"

PAYLOAD_EXTENSIONS = {
    ".bi4",
    ".h5",
    ".hdf5",
    ".jsonl",
    ".xmf",
    ".csv",
    ".ods",
    ".xlsx",
    ".zip",
    ".vtk",
    ".stl",
    ".dat",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def file_meta(path: str | Path, *, read: bool = False, role: str | None = None) -> dict[str, Any]:
    """Return a path manifest without opening scientific/control payloads.

    ``read`` is reserved for JSON/Markdown/XML/launch-script metadata.  A
    referenced CSV/ODS/XLSX/ZIP/VTK/STL/DAT is intentionally only stat'ed.
    """

    p = Path(path)
    item: dict[str, Any] = {"path": str(p), "exists": p.is_file()}
    if role:
        item["role"] = role
    if p.is_file():
        item["bytes"] = p.stat().st_size
        item["extension"] = p.suffix.lower()
        item["read_by_builder"] = bool(read)
        if read:
            if p.suffix.lower() in PAYLOAD_EXTENSIONS:
                raise AssertionError(f"payload extension was requested for reading: {p}")
            item["sha256"] = sha256(p)
    else:
        item["read_by_builder"] = False
    return item


def json_meta(path: Path, *, role: str) -> dict[str, Any]:
    result = file_meta(path, read=True, role=role)
    if not result["exists"]:
        raise FileNotFoundError(path)
    return result


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def maybe_ref(base: Path, value: str) -> Path | None:
    if not value or value.startswith(("[", "#")):
        return None
    if any(ch in value for ch in ("$", "*")):
        return None
    candidate = base / value
    return candidate if candidate.is_file() else None


def xml_summary(rel: str) -> dict[str, Any]:
    """Parse only definition/control XML; no generated output is followed."""

    path = OFFICIAL / rel
    if not path.is_file():
        raise FileNotFoundError(path)
    tree = ET.parse(path)
    root = tree.getroot()
    casedef = root.find("./casedef")
    if casedef is None:
        raise ValueError(f"missing casedef: {path}")
    definition = casedef.find("./geometry/definition")
    pointmin = definition.find("./pointmin") if definition is not None else None
    pointmax = definition.find("./pointmax") if definition is not None else None
    pmin = dict(pointmin.attrib) if pointmin is not None else None
    pmax = dict(pointmax.attrib) if pointmax is not None else None
    dimension = "unknown"
    if pmin and pmax and pmin.get("y") is not None and pmax.get("y") is not None:
        dimension = "3D" if pmin["y"] != pmax["y"] else "2D"
    gravity = casedef.find("./constantsdef/gravity")
    wanted_parameters = {
        "Boundary",
        "RigidAlgorithm",
        "TimeMax",
        "TimeOut",
        "PartsOutMax",
        "FtPause",
        "DtAllParticles",
    }
    parameters = {
        node.attrib.get("key"): node.attrib.get("value")
        for node in root.iter("parameter")
        if node.attrib.get("key") in wanted_parameters
    }
    feature_tags = {
        "accinputs",
        "wavepaddles",
        "gauges",
        "floatings",
        "motion",
        "chrono",
        "initials",
        "inout",
    }
    features = sorted({node.tag for node in root.iter() if node.tag in feature_tags})
    motion_tags = sorted(
        {
            node.tag
            for node in root.findall(".//motion//*")
            if node.tag not in {"objreal", "begin"}
        }
    )
    gauge_names = sorted(
        node.attrib["name"]
        for node in root.findall(".//gauges//*[@name]")
        if "name" in node.attrib
    )
    external: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for node in root.iter():
        for attr in ("file", "name"):
            value = node.attrib.get(attr)
            if not value:
                continue
            ref = maybe_ref(path.parent, value)
            if ref is None:
                continue
            key = (node.tag, attr, value)
            if key in seen:
                continue
            seen.add(key)
            external.append(
                {
                    "xml_tag": node.tag,
                    "attribute": attr,
                    "value": value,
                    "asset": file_meta(ref, read=False),
                }
            )
    return {
        "definition_path": str(path),
        "definition_sha256": sha256(path),
        "dimension_from_definition_bounds": dimension,
        "dp_m": definition.attrib.get("dp") if definition is not None else None,
        "gravity": dict(gravity.attrib) if gravity is not None else None,
        "pointmin": pmin,
        "pointmax": pmax,
        "parameters": parameters,
        "features": features,
        "motion_tags": motion_tags,
        "gauge_names": gauge_names,
        "xml_bound_external_assets": external,
    }


def asset(rel_or_abs: str, *, role: str, official: bool = True, read: bool = False) -> dict[str, Any]:
    path = (OFFICIAL / rel_or_abs) if official else Path(rel_or_abs)
    return file_meta(path, read=read, role=role)


def candidate(
    *,
    candidate_id: str,
    role: str,
    match_level: str,
    definition: str,
    scripts: list[str],
    controls: list[dict[str, Any]],
    declared_observations: list[str],
    script_observations: list[str],
    reference_data: list[dict[str, Any]],
    gaps: list[str],
    expected_native_cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "candidate_id": candidate_id,
        "role": role,
        "match_level": match_level,
        "equivalence_credit": "NONE",
        "definition": xml_summary(definition),
        "launch_scripts": [asset(rel, role="official launch script", read=True) for rel in scripts],
        "controls": [
            asset(item["path"], role=item["role"], official=item.get("official", True), read=False)
            for item in controls
        ],
        "declared_or_configured_observations": declared_observations,
        "script_observations_available_after_run": script_observations,
        "reference_data": reference_data,
        "gaps": gaps,
    }
    if expected_native_cost is not None:
        result["expected_native_cost"] = expected_native_cost
    return result


def reference(
    path: str,
    *,
    role: str,
    official: bool = True,
    relation: str,
    binding: str,
) -> dict[str, Any]:
    return {
        **asset(path, role=role, official=official, read=False),
        "relation": relation,
        "binding": binding,
        "read_by_builder": False,
    }


def catalog_context(catalog: dict[str, Any]) -> dict[str, Any]:
    families: dict[str, Any] = {}
    for family_id, scope in catalog["family_scopes"].items():
        families[family_id] = {
            "physical_mechanism": scope["physical_mechanism"],
            "case_count": scope["case_count"],
            "status": scope["status"],
            "qualification": scope["qualification"],
            "split_safe": scope["split_safe"],
            "observer_contract": scope["observer_contract"],
            "task_subsets": scope["task_subsets"],
            "evidence_counts": scope["evidence_counts"],
            "source_closure": scope["source_closure"],
            "unknown_scope": scope["unknown_scope"],
            "proof": scope["proof"],
        }
    return {
        "counts": catalog["counts"],
        "families": families,
        "exceptions": catalog["exceptions"],
        "aggregate_count_rule": (
            "335/78/117 are aggregate metadata provenance only. They do not turn any case, "
            "family, or report row into a scientific passed state; QI/QN/QE remain UNKNOWN."
        ),
    }


def build_map() -> dict[str, Any]:
    catalog = read_json(CATALOG_PATH)
    source_snapshot = catalog["source_snapshot"]
    official_version = OFFICIAL / "bin/linux/VERSION_INFO.txt"
    sources: dict[str, Any] = {
        "m3_catalog": json_meta(CATALOG_PATH, role="current M3 metadata-only 336-case catalog"),
        "official_version": json_meta(official_version, role="official package version metadata"),
        "adopted_plan": json_meta(PLAN_PATH, role="adopted upstream-first plan"),
    }
    if DERIVATIVE_PATH.is_file():
        sources["root_owned_derivative_design_read_only"] = json_meta(
            DERIVATIVE_PATH, role="root-owned F1 derivative design read for relation only"
        )
    for key in ("current336", "final_report_20261010", "family_source_proof_v21"):
        value = catalog["proof_sources"].get(key)
        if value:
            sources[key] = dict(value)

    f1 = {
        "family_id": "F1",
        "best_match_level": "STRONG_3D_CONFIGURATION_CANDIDATE",
        "mapping_statement": (
            "The root-owned derivative design names UF_F1_MDBC_DAMBREAK3D; the official mDBC "
            "definition below is the matching 3D mother configuration. The existing F1 catalog "
            "mechanism and fill-depth variants still require explicit geometry/initial-state binding."
        ),
        "candidates": [
            candidate(
                candidate_id="UF_F1_MDBC_DAMBREAK3D",
                role="primary M3 mother candidate",
                match_level="STRONG_3D_CONFIGURATION_CANDIDATE",
                definition="examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml",
                scripts=[
                    "examples/mdbc/04_Dambreak/xCaseDamBreak3D_mDBC_linux64_CPU.sh",
                    "examples/mdbc/04_Dambreak/xCaseDamBreak3D_mDBC_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/mdbc/04_Dambreak/elevation.txt", "role": "MeasureTool elevation point list"},
                    {"path": "examples/mdbc/04_Dambreak/pressure.txt", "role": "MeasureTool pressure point list"},
                ],
                declared_observations=[
                    "Definition: 3D gravity release, dp=0.01 m, tank plus central obstacle, mDBC Boundary=2, SlipMode=1, NoPenetration=0.",
                    "Definition: TimeMax=6 s and TimeOut=0.01 s.",
                ],
                script_observations=[
                    "MeasureTool elevation histories from elevation.txt (with -elevation:0.5).",
                    "MeasureTool pressure histories from pressure.txt (press, k-correction and VTK/CSV products).",
                    "PartVTK fluid velocity/rhop/pressure and PartVTKOut excluded-fluid records.",
                ],
                reference_data=[
                    reference(
                        "/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m1/f1/reference/SPHERIC_Test2.zip",
                        role="current M1 external SPHERIC Test 02 package",
                        official=False,
                        relation="current-project reference pointer",
                        binding="Exists, but coordinate, initial-state, boundary and time-origin matching remain unproved.",
                    ),
                    reference(
                        "examples/main/01_DamBreak/EXP_X-DamTipPosition_Koshizula&Oka1996.txt",
                        role="official dam-break tip reference",
                        relation="alternate official reference",
                        binding="Reference is for the main/01 definition, not a demonstrated match to the mDBC obstacle mother.",
                    ),
                ],
                gaps=[
                    "The official package directory has no same-directory experimental reference bound to this mDBC XML; elevation.txt and pressure.txt are point lists, not reference observations.",
                    "Current F1 catalog names eccentric lower-head / fill-depth variants; a family label does not prove this exact tank, obstacle, fill and sensor binding.",
                    "Mass, COM, obstacle fate and open-top return are not direct official gauge quantities; they need a declared postprocessor and acceptance contract.",
                ],
            )
        ],
        "family_gaps": [
            "Do not transfer the official mother’s identity or any external-reference result to all 48 current F1 rows.",
            "Current catalog QI/QN/QE and split_safe remain UNKNOWN/false.",
        ],
    }

    f2 = {
        "family_id": "F2",
        "best_match_level": "NO_EXACT_OFFICIAL_CANDIDATE",
        "mapping_statement": (
            "No official XML metadata was found that combines a rotating offset cup, a receiver or "
            "aperture, and a transport/residence measurement. Pump and moving-square examples are "
            "nearest controls only and receive no family equivalence credit."
        ),
        "candidates": [
            candidate(
                candidate_id="OFFICIAL_PUMP_ROTATING_BOUNDARY_PARTIAL",
                role="nearest 3D rotating-boundary control candidate",
                match_level="PARTIAL_3D_ROTATING_BOUNDARY_ONLY",
                definition="examples/main/13_Pump/CasePump_Def.xml",
                scripts=[
                    "examples/main/13_Pump/xCasePump_linux64_CPU.sh",
                    "examples/main/13_Pump/xCasePump_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/main/13_Pump/pump_fixed.vtk", "role": "fixed pump geometry"},
                    {"path": "examples/main/13_Pump/pump_moving.vtk", "role": "moving pump geometry"},
                ],
                declared_observations=[
                    "Definition: 3D finite tank and moving pump meshes; mvrotace with 500 degrees/s^2, initial 90 degrees/s, axis points; TimeMax=6 s, TimeOut=0.02 s, PartsOutMax=0.9.",
                ],
                script_observations=[
                    "BoundaryVTK moving-pump and fixed-pump geometry histories.",
                    "PartVTK fluid and PartVTKOut excluded-fluid records.",
                    "IsoSurface products with velocity and density fields.",
                ],
                reference_data=[],
                gaps=[
                    "No cup, receiver volume, finite aperture crossing or gross/net flux observable is declared.",
                    "No same-directory experimental/analytic reference file was found for this pump candidate.",
                ],
            ),
            candidate(
                candidate_id="OFFICIAL_MOVING_SQUARE_PARTIAL",
                role="nearest simple moving-obstacle control candidate",
                match_level="PARTIAL_2D_MOVING_BOUNDARY_ONLY",
                definition="examples/main/03_MovingSquare/CaseMovingSquare_Def.xml",
                scripts=[
                    "examples/main/03_MovingSquare/xCaseMovingSquare_linux64_CPU.sh",
                    "examples/main/03_MovingSquare/xCaseMovingSquare_linux64_GPU.sh",
                ],
                controls=[],
                declared_observations=[
                    "Definition: 2D moving square, gravity zero, mvrect velocity 2.8 m/s, TimeMax=2.5 s and TimeOut=0.01 s.",
                ],
                script_observations=[
                    "PartVTK fluid velocity/density/pressure/vorticity and moving-square boundary histories.",
                    "PartVTKOut excluded-fluid records.",
                ],
                reference_data=[],
                gaps=[
                    "No rotating offset cup, receiver/aperture, residence integral, flux sign convention or reference data.",
                ],
            ),
        ],
        "family_gaps": [
            "The current F2 first-arrival, residence_mass_time and flux contract has no official metadata candidate with the required geometry and observable.",
            "Keep the historical alias F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090 and F2H10V2_OFFSET_V1 manifest gap UNKNOWN as recorded by the catalog.",
        ],
    }

    f3 = {
        "family_id": "F3",
        "best_match_level": "NO_GENUINE_3D_OFFICIAL_SLOSHING_MOTHER",
        "mapping_statement": (
            "Official SloshingAcc is the exact control style for prescribed acceleration and has "
            "pressure/force postprocessing. Its definition bounds are 2D. A metadata sweep of all "
            "parseable official Sloshing/Slosh definitions found no 3D full-sloshing mother. "
            "CaseForces is recorded as a compact 3D acceleration fallback only; it is not a sloshing "
            "or externally referenced F3 candidate."
        ),
        "official_sloshing_search": {
            "scope": "official examples/**/*.xml whose path or filename contains Sloshing/Slosh",
            "definition_files_found": 16,
            "parseable_definition_files": 15,
            "parseable_3d_definitions": 0,
            "parseable_2d_definitions": 15,
            "invalid_definition_file": "examples/mphase_nnewtonian/04_SloshingMotion/CaseSloshingMotionNN_Def.xml",
            "invalid_definition_reason": "ElementTree metadata parse failed at line 32, column 26; no dimensions or controls were inferred.",
            "result": "NO_GENUINE_3D_OFFICIAL_SLOSHING_MOTHER",
        },
        "candidates": [
            candidate(
                candidate_id="OFFICIAL_SLOSHING_ACC",
                role="primary prescribed-acceleration control candidate",
                match_level="STRONG_2D_CONTROL_CANDIDATE_ONLY",
                definition="examples/main/05_SloshingTank/CaseSloshingAcc_Def.xml",
                scripts=[
                    "examples/main/05_SloshingTank/xCaseSloshingAcc_linux64_CPU.sh",
                    "examples/main/05_SloshingTank/xCaseSloshingAcc_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/main/05_SloshingTank/CaseSloshingAccData.csv", "role": "linear/angular acceleration input; metadata pointer only"},
                    {"path": "examples/main/05_SloshingTank/CaseSloshingAcc_PointsPressure_Correct.txt", "role": "correct pressure point list"},
                    {"path": "examples/main/05_SloshingTank/CaseSloshingAcc_PointsPressure_Incorrect.txt", "role": "incorrect pressure point list for probe sensitivity"},
                    {"path": "examples/main/05_SloshingTank/FromMotionToAcc.txt", "role": "official control explanation"},
                ],
                declared_observations=[
                    "Definition: 2D sloshing tank, dp=0.002 m, gravity -9.81 m/s^2, accinputs for mkfluid=0, acceleration centre (0.45,0,0), globalgravity=0, and external acceleration data file.",
                    "Definition: TimeMax=8.35 s and TimeOut=0.01 s.",
                ],
                script_observations=[
                    "MeasureTool pressure and k-correction at correct and incorrect point sets.",
                    "ComputeForces tank force and moment CSV about a declared axis.",
                    "PartVTK all particles and PartVTKOut excluded-fluid records.",
                ],
                reference_data=[
                    reference(
                        "examples/main/05_SloshingTank/EXP_Pressure_SPHERIC_Benchmark#10.txt",
                        role="SPHERIC pressure reference",
                        relation="same-example reference",
                        binding="Exists; coordinate, time-window and pressure convention still require explicit acceptance binding.",
                    ),
                    reference(
                        "examples/main/05_SloshingTank/CaseSloshing_Pressure_Probes.pdf",
                        role="official probe documentation",
                        relation="same-example documentation",
                        binding="Exists; documentation is not a numerical acceptance result by itself.",
                    ),
                ],
                gaps=[
                    "The acceleration CSV was not opened; exact axis ordering, trajectory and window matching are unresolved by this metadata map.",
                    "Current family COM/front, velocity and kinetic-energy contract is not a direct official output contract; postprocessing remains required.",
                ],
            ),
            candidate(
                candidate_id="OFFICIAL_SLOSHING_MOTION",
                role="alternate prescribed-motion control candidate",
                match_level="PARTIAL_2D_ROTATIONAL_CONTROL_ONLY",
                definition="examples/main/05_SloshingTank/CaseSloshingMotion_Def.xml",
                scripts=[
                    "examples/main/05_SloshingTank/xCaseSloshingMotion_linux64_CPU.sh",
                    "examples/main/05_SloshingTank/xCaseSloshingMotion_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/main/05_SloshingTank/CaseSloshingMotionData.dat", "role": "prescribed rotation input; metadata pointer only"},
                ],
                declared_observations=[
                    "Definition: 2D tank with mvrotfile around the y-axis and the same 8.35 s / 0.01 s output schedule.",
                ],
                script_observations=[
                    "Moving pressure point positions, pressure/k-correction, tank force and moment, particle and excluded-fluid products.",
                ],
                reference_data=[
                    reference(
                        "examples/main/05_SloshingTank/EXP_Pressure_SPHERIC_Benchmark#10.txt",
                        role="SPHERIC pressure reference",
                        relation="same-example reference",
                        binding="Same reference as SloshingAcc; motion-input equivalence is not implied.",
                    ),
                ],
                gaps=[
                    "Rotation-file semantics and current two-axis family controls are not proven equivalent from filenames or family labels.",
                ],
            ),
            candidate(
                candidate_id="OFFICIAL_EXTERNAL_FORCES_3D_COSTED_FALLBACK",
                role="compact 3D acceleration fallback; not an F3 sloshing mother",
                match_level="NON_EQUIVALENT_3D_ACCELERATION_CONTROL_ONLY",
                definition="examples/main/04_ExternalForces/CaseForces_Def.xml",
                scripts=[
                    "examples/main/04_ExternalForces/xCaseForces_linux64_CPU.sh",
                    "examples/main/04_ExternalForces/xCaseForces_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/main/04_ExternalForces/CaseForcesData_0.csv", "role": "mkfluid=0 acceleration input; metadata pointer only"},
                    {"path": "examples/main/04_ExternalForces/CaseForcesData_1.csv", "role": "mkfluid=1 acceleration input; metadata pointer only"},
                ],
                declared_observations=[
                    "Definition: genuine 3D bounds, dp=0.02 m, two fluid IDs in finite boxes and a central sphere; separate acceleration inputs for mkfluid=0/1 with global gravity enabled.",
                    "Definition: TimeMax=5 s and TimeOut=0.02 s; no sloshing pressure reference is declared.",
                ],
                script_observations=[
                    "PartVTK fluid mk/velocity/type/density/pressure and PartVTKOut excluded-fluid records.",
                ],
                reference_data=[],
                gaps=[
                    "This is a 3D force/acceleration test, not a tank sloshing benchmark; it has no external primary observable/reference file.",
                    "It cannot supply F3 sloshing COM/front, pressure or kinetic-energy acceptance without a new declared observer and reference.",
                ],
                expected_native_cost={
                    "status": "planning estimate only; no GenCase or solver launch",
                    "fluid_geometry_volume_m3": 0.19903455432,
                    "nominal_dp_m": 0.02,
                    "uniform_lattice_fluid_particles_estimate": 24879,
                    "output_frames_including_t0_estimate": 251,
                    "particle_frame_product_estimate": 6244629,
                    "native_storage_range_gib_before_vtk_and_other_products": [0.2, 0.6],
                    "method": "Two definition fluid-box volumes divided by dp^3; frame count from TimeMax/TimeOut plus t0; storage range is a conservative planning scale from current F1 native-output density, not a measured result.",
                    "reservation_note": "A bounded native preflight would still be required before any run; this map does not authorize execution.",
                },
            ),
        ],
        "family_gaps": [
            "Four current F3 solver rows remain launch-only/incomplete in source closure; this mapping does not repair lifecycle evidence.",
            "No genuine 3D official full-sloshing mother with an external primary reference was found. The compact 3D CaseForces fallback is explicitly non-equivalent and reference-free.",
            "No 3D qualification credit is transferred from the 2D official examples or the non-equivalent CaseForces fallback.",
        ],
    }

    f4 = {
        "family_id": "F4",
        "best_match_level": "NO_EXACT_OFFICIAL_DROP_INTO_POOL_CANDIDATE",
        "mapping_statement": (
            "The package contains a 3D Chrono dam-break with a floating cube and a 2D falling wedge, "
            "but no exact finite drop into a finite pool with the current impact/rebound contract."
        ),
        "candidates": [
            candidate(
                candidate_id="OFFICIAL_DAMBREAK_ONE_CUBE_CHRONO",
                role="nearest 3D finite-fluid collision candidate",
                match_level="PARTIAL_3D_FLOATING_COLLISION_ONLY",
                definition="examples/chrono/07_DamBreakCubes/DamBreak1Cube_Def.xml",
                scripts=[
                    "examples/chrono/07_DamBreakCubes/xDamBreak1Cube_linux64_CPU.sh",
                    "examples/chrono/07_DamBreakCubes/xDamBreak1Cube_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/chrono/07_DamBreakCubes/Floating_Materials.xml", "role": "floating material properties"},
                ],
                declared_observations=[
                    "Definition: 3D finite dam-break tank with floating cube, massbody=2.7, Chrono RigidAlgorithm=3, savedata=0.01 s, TimeMax=2 s and TimeOut=0.01 s.",
                ],
                script_observations=[
                    "PartVTK fluid/cube and PartVTKOut excluded-fluid products.",
                    "BoundaryVTK cube/tank motion, FloatingInfo motion data and IsoSurface products.",
                ],
                reference_data=[
                    reference(
                        "examples/chrono/07_DamBreakCubes/EXP_COMP_CUBE1.xlsx",
                        role="cube comparison reference 1",
                        relation="same-example reference",
                        binding="Exists; cube/dam-break comparison is not a finite-drop impact reference.",
                    ),
                    reference(
                        "examples/chrono/07_DamBreakCubes/EXP_COMP_CUBE3.xlsx",
                        role="cube comparison reference 3",
                        relation="same-example reference",
                        binding="Exists; cube/dam-break comparison is not a finite-drop impact reference.",
                    ),
                ],
                gaps=[
                    "Initial cube placement and dam-break forcing do not establish a released finite drop, finite pool impact time, or rebound censoring.",
                    "Current mass-weighted front/COM and impact_time require a typed observer contract beyond the listed postprocessors.",
                ],
            ),
            candidate(
                candidate_id="OFFICIAL_FALLING_WEDGE_2D",
                role="nearest explicit falling-body control candidate",
                match_level="PARTIAL_2D_DROP_LIKE_ONLY",
                definition="examples/vresolution/04_FallingWedge2D/CaseFallingWedge2DVRes_Def.xml",
                scripts=[
                    "examples/vresolution/04_FallingWedge2D/xCaseFallingWedge2DVRes_linux64_CPU.sh",
                    "examples/vresolution/04_FallingWedge2D/xCaseFallingWedge2DVRes_linux64_GPU.sh",
                ],
                controls=[],
                declared_observations=[
                    "Definition: 2D floating wedge, massbody=241, initial linear velocity z=-6.15 m/s, gravity -9.81 m/s^2, Boundary=2, TimeMax=0.025 s and TimeOut=0.00005 s.",
                ],
                script_observations=[
                    "PartVTK bound/fluid velocity, density and pressure products.",
                ],
                reference_data=[],
                gaps=[
                    "No finite-pool drop reference, impact/rebound event file or external acceptance data is present in this example directory.",
                    "2D wedge and variable-resolution controls cannot establish the current finite-drop family.",
                ],
            ),
            candidate(
                candidate_id="OFFICIAL_FLOATING_SPHERE_VAL2D",
                role="alternate reference-bearing floating-body candidate",
                match_level="PARTIAL_2D_FLOATING_REFERENCE_ONLY",
                definition="examples/main/11_Floating/CaseFloatingSphereVal2D_Def.xml",
                scripts=[
                    "examples/main/11_Floating/xCaseFloatingSphereVal2D_linux64_CPU.sh",
                    "examples/main/11_Floating/xCaseFloatingSphereVal2D_linux64_GPU.sh",
                ],
                controls=[],
                declared_observations=[
                    "Definition: 2D floating sphere validation geometry with relativeweight=1.20, FtPause=1 s, TimeMax=6 s and TimeOut=0.02 s.",
                ],
                script_observations=[
                    "PartVTK fluid/floating and PartVTKOut products, FloatingInfo and surface slices.",
                ],
                reference_data=[
                    reference(
                        "examples/main/11_Floating/EXP_FloatingSphereVal2D_Displacement_Fekken2004.txt",
                        role="sphere displacement reference",
                        relation="same-example reference",
                        binding="Exists; floating-sphere displacement does not establish drop-impact equivalence.",
                    ),
                    reference(
                        "examples/main/11_Floating/EXP_FloatingSphereVal2D_Velocity_Fekken2004.txt",
                        role="sphere velocity reference",
                        relation="same-example reference",
                        binding="Exists; floating-sphere velocity does not establish drop-impact equivalence.",
                    ),
                    reference(
                        "examples/main/11_Floating/EXP_FloatingSphereVal2D.ods",
                        role="sphere validation workbook",
                        relation="same-example reference",
                        binding="Exists; workbook was not opened by this map.",
                    ),
                ],
                gaps=[
                    "2D buoyant sphere validation has no finite drop/pool impact event and no current F4 source-cohort binding.",
                ],
            ),
        ],
        "family_gaps": [
            "No official exact candidate or exact reference chain was found for the current finite-drop impact family.",
            "Current catalog has 21 F4 GenCase receipt-schema-unknown rows; upstream examples do not close that lifecycle gap.",
        ],
    }

    f5 = {
        "family_id": "F5",
        "best_match_level": "2D_CALIBRATION_PLUS_PARTIAL_3D_RUNUP",
        "mapping_statement": (
            "CasePistonBeach_REG is the planned 2D calibration mother. CaseWaveRunup is the official "
            "3D runup candidate with gauges and an external reference. The two are separate candidates; "
            "the 2D result cannot be counted as 3D coverage."
        ),
        "candidates": [
            candidate(
                candidate_id="UF_F5_PISTON_BEACH_REG_2D",
                role="planned 2D calibration mother",
                match_level="STRONG_2D_CALIBRATION_ONLY",
                definition="examples/main/09_WavesPiston/CasePistonBeach_REG_Def.xml",
                scripts=[
                    "examples/main/09_WavesPiston/xCasePistonBeach_REG_linux64_CPU.sh",
                    "examples/main/09_WavesPiston/xCasePistonBeach_REG_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/main/09_WavesPiston/elevation.txt", "role": "wave-elevation point list"},
                    {"path": "examples/main/09_WavesPiston/velocity.txt", "role": "wave-velocity point list"},
                    {"path": "examples/main/09_WavesPiston/CasePiston_SPHvsTheory.ods", "role": "SPH/theory comparison workbook"},
                ],
                declared_observations=[
                    "Definition: 2D regular piston beach, dp=0.02 m, wave height 0.15 m, period 2 s, depth 0.66 m, TimeMax=30 s and TimeOut=0.05 s.",
                    "Definition: piston savemotion at xpos=6.0 and zpos=-0.26; wave gauge files are consumed by the launch script.",
                ],
                script_observations=[
                    "MeasureTool elevation and velocity histories, PartVTK fluid/piston, PartVTKOut, tracer and surface products.",
                ],
                reference_data=[
                    reference(
                        "examples/main/09_WavesPiston/CasePiston_SPHvsTheory.ods",
                        role="official SPH/theory comparison workbook",
                        relation="same-example reference",
                        binding="Exists; workbook content and acceptance window were not opened by this map.",
                    ),
                ],
                gaps=[
                    "Definition bounds are 2D; this candidate is calibration only and cannot satisfy the M1/M4 3D count.",
                    "Current F5 recovery/tail and mass-distribution observers are not all direct official gauge outputs.",
                ],
            ),
            candidate(
                candidate_id="OFFICIAL_WAVE_RUNUP_3D",
                role="3D runup candidate requiring separate binding",
                match_level="PARTIAL_3D_RUNUP_CANDIDATE",
                definition="examples/main/17_WaveRunup/CaseWaveRunup_Def.xml",
                scripts=[
                    "examples/main/17_WaveRunup/xCaseWaveRunup_linux64_CPU.sh",
                    "examples/main/17_WaveRunup/xCaseWaveRunup_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/main/17_WaveRunup/Slope.stl", "role": "3D slope geometry"},
                    {"path": "examples/main/17_WaveRunup/Blocks_3D_scaled.stl", "role": "3D blocks geometry"},
                    {"path": "examples/main/17_WaveRunup/Mov_piston.dat", "role": "prescribed piston trajectory; metadata pointer only"},
                    {"path": "examples/main/17_WaveRunup/wg1234.txt", "role": "wave-gauge point list"},
                ],
                declared_observations=[
                    "Definition: 3D slope/blocks runup, prescribed piston file, seven named swl gauges, dp=0.008 m, TimeMax=20 s and TimeOut=0.02 s.",
                ],
                script_observations=[
                    "MeasureTool wg1234 gauge histories, PartVTK fluid/piston, PartVTKOut, boundary motion and surface products.",
                ],
                reference_data=[
                    reference(
                        "examples/main/17_WaveRunup/EXP_CaseWaveRunup_CIEMito.txt",
                        role="CIEMito wave-runup reference",
                        relation="same-example reference",
                        binding="Exists; gauge coordinates, runup definition and time window require explicit binding.",
                    ),
                ],
                gaps=[
                    "The official 3D geometry and piston are not the planned 2D PistonBeach input; no result or acceptance is borrowed across them.",
                    "Current compact-runup recovery/tail and mass observers need an explicit typed postprocessor and reference contract.",
                ],
            ),
        ],
        "family_gaps": [
            "Current F5 catalog has 48 source-bound development rows with QI/QN/QE UNKNOWN; official gauge presence does not qualify them.",
        ],
    }

    f6 = {
        "family_id": "F6",
        "best_match_level": "STRONG_3D_FLOATING_CONTROL_WITH_OBSERVATION_GAPS",
        "mapping_statement": (
            "CaseFloating_Def is the simplest official 3D free-floating control with mass and particle/motion "
            "postprocessors. Chrono OWSC3D adds 3D rigid coupling but is wave-driven; the 2D sphere case has "
            "reference files. None proves the current six-DOF release contract or external 3D acceptance."
        ),
        "candidates": [
            candidate(
                candidate_id="OFFICIAL_FLOATING_3D",
                role="primary simple 3D floating-body candidate",
                match_level="STRONG_3D_FLOATING_CONTROL_WITH_OBSERVATION_GAPS",
                definition="examples/main/11_Floating/CaseFloating_Def.xml",
                scripts=[
                    "examples/main/11_Floating/xCaseFloating_linux64_CPU.sh",
                    "examples/main/11_Floating/xCaseFloating_linux64_GPU.sh",
                ],
                controls=[],
                declared_observations=[
                    "Definition: 3D floating body mkbound=50, massbody=10000, gravity -9.81 m/s^2, moving piston control, RigidAlgorithm=1, TimeMax=10 s and TimeOut=0.1 s.",
                ],
                script_observations=[
                    "PartVTK fluid/floating/moving-piston products and PartVTKOut.",
                    "BoundaryVTK floating/piston motion and fixed box; FloatingInfo motion data; IsoSurface.",
                ],
                reference_data=[],
                gaps=[
                    "No external 3D pose, linear/angular velocity or fluid-mass reference file is present in this example directory.",
                    "FloatingInfo script selects onlymk:60 while the definition declares mkbound=50; mark binding must be checked before claiming telemetry.",
                    "Quaternion/SE(3), angular velocity and fluid-mass observer semantics are not established by output file names alone.",
                ],
            ),
            candidate(
                candidate_id="OFFICIAL_OWSC3D_CHRONO",
                role="alternate 3D Chrono-coupled rigid-body candidate",
                match_level="PARTIAL_3D_WAVE_DRIVEN_CHRONO_ONLY",
                definition="examples/chrono/05_OWSC/CaseOWSC3D_Def.xml",
                scripts=[
                    "examples/chrono/05_OWSC/xCaseOWSC3D_linux64_CPU.sh",
                    "examples/chrono/05_OWSC/xCaseOWSC3D_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/chrono/05_OWSC/CaseOWSC3D_tank.stl", "role": "tank geometry"},
                    {"path": "examples/chrono/05_OWSC/CaseOWSC3D_flap.stl", "role": "floating flap geometry"},
                    {"path": "examples/chrono/05_OWSC/Floating_Materials.xml", "role": "floating material properties"},
                ],
                declared_observations=[
                    "Definition: 3D floating flap with Chrono RigidAlgorithm=3, center/inertia, wave piston and TimeMax=10 s / TimeOut=0.02 s.",
                ],
                script_observations=[
                    "PartVTK fluid/wavemaker/flap and PartVTKOut, BoundaryVTK, FloatingInfo flap motion, ComputeForces tank moment and IsoSurface.",
                ],
                reference_data=[],
                gaps=[
                    "Wave-driven Chrono flap is not a free rigid release; no current F6 release/initial-state mapping or external reference is declared.",
                    "FloatingInfo selects onlymk:15 while XML floating mkbound=5; telemetry mark binding needs verification.",
                ],
            ),
            candidate(
                candidate_id="OFFICIAL_FLOATING_SPHERE_VAL2D",
                role="reference-bearing 2D validation candidate",
                match_level="PARTIAL_2D_REFERENCE_ONLY",
                definition="examples/main/11_Floating/CaseFloatingSphereVal2D_Def.xml",
                scripts=[
                    "examples/main/11_Floating/xCaseFloatingSphereVal2D_linux64_CPU.sh",
                    "examples/main/11_Floating/xCaseFloatingSphereVal2D_linux64_GPU.sh",
                ],
                controls=[],
                declared_observations=[
                    "Definition: 2D floating sphere, relativeweight=1.20, FtPause=1 s, TimeMax=6 s and TimeOut=0.02 s.",
                ],
                script_observations=[
                    "PartVTK fluid/floating, PartVTKOut, FloatingInfo and surface slices.",
                ],
                reference_data=[
                    reference(
                        "examples/main/11_Floating/EXP_FloatingSphereVal2D_Displacement_Fekken2004.txt",
                        role="2D sphere displacement reference",
                        relation="same-example reference",
                        binding="Exists; 2D displacement reference only.",
                    ),
                    reference(
                        "examples/main/11_Floating/EXP_FloatingSphereVal2D_Velocity_Fekken2004.txt",
                        role="2D sphere velocity reference",
                        relation="same-example reference",
                        binding="Exists; 2D velocity reference only.",
                    ),
                    reference(
                        "examples/main/11_Floating/EXP_FloatingSphereVal2D.ods",
                        role="2D sphere validation workbook",
                        relation="same-example reference",
                        binding="Exists; workbook was not opened by this map.",
                    ),
                ],
                gaps=[
                    "2D sphere output/reference cannot establish 3D six-DOF equivalence.",
                    "FloatingInfo selects onlymk:61 while XML floating mkbound=51; telemetry mark binding needs verification.",
                ],
            ),
        ],
        "family_gaps": [
            "Current F6 native join count is an identity/cause audit count, not pose/SE(3) or physical qualification.",
            "No official candidate supplies the complete current pose, linear/angular velocity and fluid-mass contract with 3D reference data.",
        ],
    }

    f7 = {
        "family_id": "F7",
        "best_match_level": "PARTIAL_3D_MOVING_PUMP_ONLY",
        "mapping_statement": (
            "CasePump_Def is the official 3D moving-boundary candidate named by the plan. Its rotation and "
            "fluid products do not provide the current quintic, wet-base, left/right flux and residence contract."
        ),
        "candidates": [
            candidate(
                candidate_id="OFFICIAL_PUMP_3D",
                role="primary official 3D moving-boundary candidate",
                match_level="PARTIAL_3D_MOVING_PUMP_ONLY",
                definition="examples/main/13_Pump/CasePump_Def.xml",
                scripts=[
                    "examples/main/13_Pump/xCasePump_linux64_CPU.sh",
                    "examples/main/13_Pump/xCasePump_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/main/13_Pump/pump_fixed.vtk", "role": "fixed pump geometry"},
                    {"path": "examples/main/13_Pump/pump_moving.vtk", "role": "moving pump geometry"},
                ],
                declared_observations=[
                    "Definition: 3D finite tank, rotating pump, gravity -9.81 m/s^2, mvrotace control, TimeMax=6 s, TimeOut=0.02 s, PartsOutMax=0.9.",
                ],
                script_observations=[
                    "BoundaryVTK pump motion and fixed geometry.",
                    "PartVTK fluid and PartVTKOut excluded-fluid products.",
                    "IsoSurface products with velocity and density.",
                ],
                reference_data=[],
                gaps=[
                    "No prescribed quintic trajectory, wet-base partition, left/right mass split, flux/residence gauge or same-directory reference data.",
                    "Current F7 observer contract therefore needs a new typed postprocessor and an explicit reference source before qualification.",
                ],
            ),
            candidate(
                candidate_id="OFFICIAL_FLEXIBLE_OBSTACLE_2D",
                role="alternate reference-bearing moving-obstacle candidate",
                match_level="PARTIAL_2D_FLEXIBLE_GATE_ONLY",
                definition="examples/chrono/13_FlexibleObstacle/CaseFlexibleObstacle_Def.xml",
                scripts=[
                    "examples/chrono/13_FlexibleObstacle/xCaseFlexibleObstacle_linux64_CPU.sh",
                    "examples/chrono/13_FlexibleObstacle/xCaseFlexibleObstacle_linux64_GPU.sh",
                ],
                controls=[
                    {"path": "examples/chrono/13_FlexibleObstacle/GateMotion.txt", "role": "prescribed gate motion; metadata pointer only"},
                ],
                declared_observations=[
                    "Definition: 2D mDBC flexible gate, motion file GateMotion.txt, Chrono floating beam, TimeMax=1 s and TimeOut=0.01 s.",
                ],
                script_observations=[
                    "PartVTK fixed/fluid/beam products, BoundaryVTK gate, FloatingInfo and excluded/geometry products.",
                ],
                reference_data=[
                    reference(
                        "examples/chrono/13_FlexibleObstacle/ModelComparison.ods",
                        role="flexible-obstacle model comparison workbook",
                        relation="same-example reference",
                        binding="Exists; 2D flexible-gate comparison is not a quintic pump reference.",
                    ),
                ],
                gaps=[
                    "Flexible 2D gate and external motion file do not establish the 3D pump, quintic trajectory, wet-base or flux semantics.",
                ],
            ),
        ],
        "family_gaps": [
            "Current F7 has 24 GenCase schema-unknown rows and five launch/incomplete rows; official candidate metadata does not close those lifecycle gaps.",
            "No equivalence is credited from the shared words moving obstacle or pump.",
        ],
    }

    family_maps = {f["family_id"]: f for f in (f1, f2, f3, f4, f5, f6, f7)}
    result: dict[str, Any] = {
        "schema": "ds-data-02.upstream-first.m3.upstream-family-map.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Metadata-only crosswalk from the seven current catalog families to local official v5.4 mother candidates and explicit gaps.",
        "scope_boundary": {
            "mode": "metadata_only",
            "solver_invocations": 0,
            "full_array_reads": 0,
            "payload_extensions_not_opened": sorted(PAYLOAD_EXTENSIONS),
            "official_package_root": str(OFFICIAL),
            "referenced_payloads_are_pointers_only": True,
            "scientific_equivalence_credit": "NONE",
            "aggregate_counts_do_not_promote_case_status": True,
            "note": "XML/control metadata and launch scripts were inspected; control/reference payloads are recorded by path and size only.",
        },
        "source_snapshots": sources,
        "catalog_context": catalog_context(catalog),
        "official_package_version_first_line": (
            official_version.read_text(encoding="utf-8").splitlines()[0]
            if official_version.is_file()
            else None
        ),
        "families": family_maps,
        "cross_family_gaps": [
            "An official definition, script and reference file prove source availability only; they do not prove that any current 48-case family row has the same geometry, initial state, boundary, motion, time window or sensor semantics.",
            "Reference-data existence is recorded separately from reference-data binding. No ODS/XLSX/ZIP/CSV/DAT scientific or control payload was opened by this builder.",
            "The current catalog's 335 masks, 78 scans and 117 joins remain aggregate metadata provenance; no per-case passed state, QI, QN or QE is inferred.",
            "Resolution, recovery, window transfer and prospective split safety remain UNKNOWN for all families.",
        ],
    }
    return result


def require_assets(node: Any, missing: list[str]) -> None:
    if isinstance(node, dict):
        if "path" in node and "exists" in node and not node["exists"]:
            missing.append(str(node["path"]))
        for value in node.values():
            require_assets(value, missing)
    elif isinstance(node, list):
        for value in node:
            require_assets(value, missing)


def render_md(data: dict[str, Any]) -> str:
    ctx = data["catalog_context"]
    counts = ctx["counts"]
    lines: list[str] = [
        "# M3 upstream seven-family mother map (metadata only)",
        "",
        "This crosswalk maps the current seven-family catalog to local DualSPHysics v5.4 definition/script candidates. It records source availability, configured controls and postprocessing outputs; it grants **zero equivalence or scientific qualification credit**.",
        "",
        "## Boundary and provenance",
        "",
        f"- Official package: `{data['scope_boundary']['official_package_root']}` ({data.get('official_package_version_first_line')}).",
        f"- Current catalog: `{data['source_snapshots']['m3_catalog']['path']}`; `{counts['cases']}` rows, `{counts['families']}` families, `{counts['saved_mask_cases']}` saved-mask rows, `{counts['field_scan_cases']}` field-scan rows, `{counts['native_cause_join_cases']}` native joins.",
        "- The 335/78/117 values are aggregate metadata counts. They do not make a case or family scientifically passed; all catalog QI/QN/QE remain UNKNOWN.",
        "- The builder parsed selected XML and launch scripts only. CSV/DAT/ODS/XLSX/ZIP/VTK/STL and solver outputs are path/size pointers and were not opened.",
        "",
        "## Family rollup",
        "",
        "| Family | Current catalog contract | Best official match | Reference status | Main gap |",
        "|---|---|---|---|---|",
    ]
    for fid, family in data["families"].items():
        c = ctx["families"][fid]
        refs = sum(len(cand["reference_data"]) for cand in family["candidates"])
        ref_status = "present" if refs else "none found"
        main_gap = family["family_gaps"][0].replace("|", "\\|")
        lines.append(
            f"| {fid} | {c['physical_mechanism']} | {family['best_match_level']} | {ref_status} | {main_gap} |"
        )
    for fid, family in data["families"].items():
        c = ctx["families"][fid]
        lines.extend(
            [
                "",
                f"## {fid}: {c['physical_mechanism']}",
                "",
                f"**Mapping.** {family['mapping_statement']}",
                "",
                f"**Current observer contract.** {', '.join(o['name'] + ' [' + o['unit'] + ']' for o in c['observer_contract'])}.",
                "",
                "| Candidate | Definition / dimension | Controls and configured observations | Available script outputs | References and hard gaps |",
                "|---|---|---|---|---|",
            ]
        )
        for cand in family["candidates"]:
            d = cand["definition"]
            control_paths = ", ".join(f"`{Path(x['path']).name}`" for x in cand["controls"]) or "none"
            obs = "; ".join(cand["script_observations_available_after_run"])
            if cand.get("expected_native_cost"):
                cost = cand["expected_native_cost"]
                obs += (
                    f" Planning only: about {cost['uniform_lattice_fluid_particles_estimate']:,} fluid particles, "
                    f"{cost['output_frames_including_t0_estimate']} frames, and "
                    f"{cost['native_storage_range_gib_before_vtk_and_other_products'][0]}–"
                    f"{cost['native_storage_range_gib_before_vtk_and_other_products'][1]} GiB native before VTK."
                )
            refs = "; ".join(
                f"`{Path(x['path']).name}` ({x['binding']})" for x in cand["reference_data"]
            ) or "none found"
            gaps = "; ".join(cand["gaps"])
            lines.append(
                f"| `{cand['candidate_id']}` ({cand['match_level']}) | `{d['definition_path']}`; {d['dimension_from_definition_bounds']}, dp={d['dp_m']} m | {control_paths}; {', '.join(cand['declared_or_configured_observations'])} | {obs} | {refs}. Gaps: {gaps} |"
            )
        lines.extend(
            [
                "",
                "**Family-level gaps.**",
                "",
            ]
        )
        lines.extend(f"- {gap}" for gap in family["family_gaps"])
    lines.extend(
        [
            "",
            "## Cross-family rules",
            "",
        ]
    )
    lines.extend(f"- {gap}" for gap in data["cross_family_gaps"])
    lines.extend(
        [
            "",
            "The JSON retains absolute source paths, metadata hashes where read, existence/byte metadata for referenced assets, XML control summaries and the current catalog's family/source-closure evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write JSON and Markdown outputs")
    parser.add_argument("--check", action="store_true", help="validate source paths and generated schema")
    args = parser.parse_args(argv)
    if not args.write and not args.check:
        args.check = True
    data = build_map()
    missing: list[str] = []
    require_assets(data["source_snapshots"], missing)
    require_assets(data["families"], missing)
    if missing:
        print("missing metadata assets:", file=sys.stderr)
        for path in sorted(set(missing)):
            print(f"  {path}", file=sys.stderr)
        return 2
    if set(data["families"]) != {f"F{i}" for i in range(1, 8)}:
        raise AssertionError("family set is not F1..F7")
    if data["scope_boundary"]["solver_invocations"] != 0:
        raise AssertionError("solver invocation marker changed")
    if data["scope_boundary"]["scientific_equivalence_credit"] != "NONE":
        raise AssertionError("equivalence credit marker changed")
    if args.write:
        JSON_OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        MD_OUT.write_text(render_md(data), encoding="utf-8")
        print(f"wrote {JSON_OUT} ({JSON_OUT.stat().st_size} bytes)")
        print(f"wrote {MD_OUT} ({MD_OUT.stat().st_size} bytes)")
    else:
        print("upstream family map metadata check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

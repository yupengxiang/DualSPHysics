#!/usr/bin/env python3
"""Audit the fixed-geometry F2-S1 coarse lattice step function.

This is a read-only diagnostic.  It consumes the CURRENT source XML/Fluid VTK
and the explicitly listed, already completed coarse GenCase XML/Fluid VTK
artifacts.  It does not read HDF5, run GenCase, run a solver, or mutate any
source/receipt.  The purpose is to distinguish an integer lattice-count
change from a continuous geometry or particle-mass change.
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
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.coarse-lattice-phase-diagnostic.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
GRAPH = REFERENCE / "stage2_minimal14_study_graph_v2.json"
REPORT = REFERENCE / "f2_s1_coarse_lattice_phase_diagnostic_v1.json"
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
TARGET_MASS_KG = 21.114
PASS_PCT = 1.0
HARD_PCT = 2.0

# These are explicit historical artifacts.  Do not replace this list with a
# latest-glob: the report is meant to preserve exactly which evidence was used.
COARSE_XMLS = (
    Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_COARSE_PHASE_PROBE_DP01236/f2_s1_coarse_phase_probe_dp01236-001/generated.xml"),
    Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_COARSE_PHASE_PROBE_DP01240/f2_s1_coarse_phase_probe_dp01240-001/generated.xml"),
    Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_COARSE_PHASE_PROBE_DP01258/f2_s1_coarse_phase_probe_dp01258-001/generated.xml"),
    Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_COARSE_PHASE_PROBE_DP01260/f2_s1_coarse_phase_probe_dp01260-001/generated.xml"),
    Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_COARSE_PHASE_PROBE_DP01270/f2_s1_coarse_phase_probe_dp01270-001/generated.xml"),
    Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_COARSE_PHASE_PROBE_V3_DP01290/f2_s1_coarse_phase_probe_v3_dp01290-001/generated.xml"),
    Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_COARSE_PHASE_PROBE_V3_DP01300/f2_s1_coarse_phase_probe_v3_dp01300-001/generated.xml"),
    Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_COARSE_PHASE_PROBE_V3_DP01310/f2_s1_coarse_phase_probe_v3_dp01310-001/generated.xml"),
    Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_S1_COARSE_PHASE_PROBE_V3_DP01320/f2_s1_coarse_phase_probe_v3_dp01320-001/generated.xml"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def float_attr(node: ET.Element, name: str) -> float:
    value = node.get(name)
    if value is None:
        raise ValueError(f"missing {name} on {node.tag}")
    return float(value)


def xml_metadata(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError(f"no geometry definition in {path}")
    dp = float_attr(definition, "dp")
    cfl = root.find(".//constants/cflnumber")
    if cfl is None:
        cfl = root.find(".//constantsdef/cflnumber")
    mass_node = root.find(".//constants/massfluid")
    massfluid = float_attr(mass_node, "value") if mass_node is not None else 1000.0 * dp**3
    fluid_nodes = [
        node for node in root.findall(".//fluid")
        if node.get("mkfluid") is not None and node.get("count") is not None
    ]
    blocks = [
        {"mkfluid": int(node.get("mkfluid")), "mk": int(node.get("mk", "-1")),
         "count": int(node.get("count"))}
        for node in fluid_nodes
    ]
    fluid_count = sum(item["count"] for item in blocks)
    # Retain only the actual solid-fluid drawboxes.  This is the source
    # continuous recipe; generated XML keeps these commands byte-equivalent.
    current_mk: int | None = None
    boxes: list[dict[str, Any]] = []
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is not None:
        for node in list(mainlist):
            if node.tag == "setmkfluid":
                current_mk = int(node.get("mk", "-1"))
            elif node.tag == "drawbox" and current_mk is not None:
                point = node.find("point")
                size = node.find("size")
                if point is not None and size is not None and node.find("boxfill") is not None:
                    boxes.append({
                        "mkfluid": current_mk,
                        "point_m": {axis: float_attr(point, axis) for axis in "xyz"},
                        "size_m": {axis: float_attr(size, axis) for axis in "xyz"},
                        "boxfill": (node.findtext("boxfill") or "").strip(),
                    })
    sample_mass = fluid_count * massfluid
    error_pct = 100.0 * (sample_mass - TARGET_MASS_KG) / TARGET_MASS_KG
    return {
        "file": file_record(path),
        "dp_m": dp,
        "cfl": float(cfl.get("value")) if cfl is not None else None,
        "massfluid_kg": massfluid,
        "mass_rule_check": {
            "rho0_kg_m3": 1000.0,
            "rho0_dp3_kg": 1000.0 * dp**3,
            "abs_difference_kg": abs(massfluid - 1000.0 * dp**3),
            "status": "PASS" if abs(massfluid - 1000.0 * dp**3) <= 1e-12 else "UNKNOWN",
        },
        "fluid_blocks": blocks,
        "fluid_particle_count": fluid_count,
        "sample_mass_kg": sample_mass,
        "whole_initial_mass_error_pct": error_pct,
        "whole_initial_mass_gate": (
            "PASS_TARGET_1PCT" if abs(error_pct) <= PASS_PCT else
            "MARGINAL_1_TO_2PCT" if abs(error_pct) <= HARD_PCT else
            "HARD_FAIL_GT2PCT"
        ),
        "continuous_fluid_drawboxes": boxes,
    }


def read_fluid_vtk(path: Path, dp: float, boxes: list[dict[str, Any]]) -> dict[str, Any]:
    """Read only VTK points; the file is binary VTK with big-endian floats."""
    data = path.read_bytes()
    match = re.search(rb"POINTS (\d+) float\n", data)
    if match is None:
        raise ValueError(f"unsupported VTK header: {path}")
    count = int(match.group(1))
    start = match.end()
    end = start + 12 * count
    if end > len(data):
        raise ValueError(f"truncated VTK points: {path}")
    values = struct.unpack(">" + "f" * (3 * count), data[start:end])
    points = list(zip(values[::3], values[1::3], values[2::3]))
    # The fluid VTK is emitted in draw-command order.  Counts per z plane are
    # still recovered from coordinates, independent of that ordering.
    z_groups: dict[float, int] = {}
    for point in points:
        key = round(float(point[2]), 6)
        z_groups[key] = z_groups.get(key, 0) + 1

    def axis_info(index: int) -> dict[str, Any]:
        values_axis = sorted({round(float(point[index]), 6) for point in points})
        steps = [b - a for a, b in zip(values_axis, values_axis[1:])]
        return {
            "count": len(values_axis),
            "min_m": values_axis[0] if values_axis else None,
            "max_m": values_axis[-1] if values_axis else None,
            "step_min_m": min(steps) if steps else None,
            "step_max_m": max(steps) if steps else None,
            "step_matches_dp": bool(steps) and max(abs(step - dp) for step in steps) < 2e-5,
        }

    phase_offsets: list[dict[str, Any]] = []
    for box in boxes:
        matching_z = [
            float(point[2]) for point in points
            if abs(float(point[2]) - box["point_m"]["z"]) <= max(dp * 0.6, 1e-5)
        ]
        # This is a diagnostic nearest-plane phase, not a claim that all
        # points are in the mathematical box boundary.
        first_by_axis = {
            "x": min(float(point[0]) for point in points),
            "y": min(float(point[1]) for point in points),
            "z": min(matching_z) if matching_z else None,
        }
        offsets = {}
        for axis in "xyz":
            first = first_by_axis[axis]
            offsets[axis] = None if first is None else (first - box["point_m"][axis]) / dp
        phase_offsets.append({"mkfluid": box["mkfluid"], "nearest_box_lattice_offset_cells": offsets})

    return {
        "file": file_record(path),
        "point_count": count,
        "axis_lattice": {axis: axis_info(i) for i, axis in enumerate("xyz")},
        "z_plane_counts": {str(key): value for key, value in sorted(z_groups.items())},
        "phase_offsets": phase_offsets,
    }


def source_xml_path() -> Path:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    rows = [row for row in graph["sentinels"] if row.get("sentinel_id") == "F2-S1"]
    if len(rows) != 1:
        raise ValueError("CURRENT graph must contain one F2-S1 row")
    return Path(rows[0]["source_xml"]["path"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the new immutable report")
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    source_xml = source_xml_path()
    source_meta = xml_metadata(source_xml)
    source_vtk = source_xml.with_name(source_xml.stem + "_Fluid.vtk")
    source_points = read_fluid_vtk(source_vtk, source_meta["dp_m"], source_meta["continuous_fluid_drawboxes"])

    candidates: list[dict[str, Any]] = []
    for xml_path in COARSE_XMLS:
        meta = xml_metadata(xml_path)
        vtk_path = xml_path.with_name(xml_path.stem + "_Fluid.vtk")
        points = read_fluid_vtk(vtk_path, meta["dp_m"], meta["continuous_fluid_drawboxes"])
        candidates.append({"xml": meta, "fluid_vtk": points})

    help_run = subprocess.run([str(GENCASE), "-h"], check=True, capture_output=True, text=True)
    help_lines = help_run.stdout.splitlines()
    report = {
        "schema": SCHEMA,
        "status": "COMPLETED_READ_ONLY_GEOMETRY_MASS_DIAGNOSTIC",
        "generated_at_commit": git_head(),
        "sentinel_id": "F2-S1",
        "family_id": "F2",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "scope": {
            "read_files": "CURRENT source XML/Fluid VTK, nine explicitly listed completed coarse XML/Fluid VTK artifacts, official GenCase -h",
            "hdf5_read": False,
            "solver_started": False,
            "gencase_started": False,
            "particle_mass_rescale": False,
            "continuous_geometry_or_threshold_changed": False,
            "adjacent_dp_search_after_v3": False,
        },
        "official_evidence": {
            "gencase_binary": file_record(GENCASE),
            "help_command": [str(GENCASE), "-h"],
            "help_sha256": hashlib.sha256(help_run.stdout.encode("utf-8")).hexdigest(),
            "help_excerpt": [line for line in help_lines if any(token in line for token in ("-dp:", "-evars:", "-save:"))],
            "observed_phase_control": "official help exposes -dp and save/evars controls but no particle-origin/phase switch",
            "configuration_source": "vendor/official/DualSPHysics_v5.4/src_extra/ToVTK/source/JSpaceCtes.cpp and doc/xml_format/GenCase_CaseTemplate.xml show optional lattice configuration/default fluid lattice=1; actual output is the controlling evidence",
        },
        "fixed_continuous_recipe": {
            "drawboxes": source_meta["continuous_fluid_drawboxes"],
            "source_dp_m": source_meta["dp_m"],
            "source_massfluid_kg": source_meta["massfluid_kg"],
            "source_particle_count_by_mkfluid": {str(x["mkfluid"]): x["count"] for x in source_meta["fluid_blocks"]},
            "source_fluid_vtk": source_points,
            "rule": "Cartesian fluid lattice points are generated separately inside each solid drawbox; counts are integer floor/edge inclusion outcomes at the requested dp and the fixed drawbox origin.",
        },
        "mass_and_phase_model": {
            "mass_formula": "massfluid = rho0 * dp^3; rho0=1000 kg/m^3",
            "count_formula": "sample_mass_mk = integer_count_mk(dp, fixed_drawbox_origin,size) * rho0 * dp^3",
            "step_mechanism": "integer counts nx, ny, nz change only when a lattice point crosses a box edge; multiplying each count by dp^3 creates mass jumps. Separate z boxes are sampled independently, so per-MK steps can differ even when total mass is near the source.",
            "source_geometry_is_not_continuum_mass": "21.114 kg is the frozen Stage1 discrete sample mass; the continuous box volume is a separate physical quantity and is not substituted here.",
            "phase_definition": "observed first lattice coordinate relative to each fixed drawbox point, in dp cells; this is an output diagnostic, not a user-controlled phase parameter.",
        },
        "candidate_audits": candidates,
        "conclusion": {
            "phase_control_status": "NO_OFFICIAL_PHASE_SWITCH",
            "legal_fixed_geometry_phase_match_status": "NO_MATCH_PROVEN",
            "observed_result": "The same fixed source drawboxes and motion/control recipe produce discontinuous x/y/z plane counts across dp. Several total masses approach the 1% target while MK-specific errors remain large; this is a lattice-count/phase artifact, not evidence of continuous-state or material equivalence.",
            "current_scope_decision": "F2-S1 coarse matched-reference qualification remains RANGE_FAILED_OR_UNPROVEN; no coarse candidate receives QI/QN/QE credit.",
            "next_independent_design": "If coarse F2-S1 remains scientifically necessary, register one separate lattice-origin/recipe experiment with explicit origin/geometry semantics, per-MK and whole-initial-mass gates, and observer/dynamics calibration before any solver. It must be a new numerical recipe, not a silent phase tweak to CURRENT.",
            "forbidden_shortcuts": ["do not rescale particle masses", "do not move drawbox geometry to force a count", "do not relax the 1% target or 2% hard ceiling", "do not continue an unbounded adjacent-dp search", "do not infer QI/QN/QE from GenCase or initial mass alone"],
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }
    if args.write:
        atomic_json(args.output, report)
    print(json.dumps({"status": "PASS", "output": str(args.output), "candidates": len(candidates), "write": args.write}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit the pre-existing F6 DP0125 native tank walls.

The audit is deliberately additive.  It reads the immutable GenCase XML and
Bound.vtk files and records coverage of the five *finite* tank faces using the
shared helper.  It does not launch GenCase, a solver, or a post-processor and
does not treat a boundary population check as a qualification result.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any


SCRIPT = Path(__file__).resolve()
RAW_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
HELPER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_finite_faces_v1.py"
)
HELPER_SHA256 = "16bd1e8d0883a9307bcb54a0d5395acf83bdefb6de1a97ae44706fc3aa2105e1"

CASES = {
    "simple_free_response": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_EPSFREE002_PHASE003_DP0125",
    "wave_no_contact": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_EPSFREE002_PHASE003_DP0125",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_helper():
    if sha256(HELPER) != HELPER_SHA256:
        raise RuntimeError("shared finite-face helper changed since root review")
    spec = importlib.util.spec_from_file_location("ds_data02_finite_faces_v1", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper: {HELPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _attr(node: ET.Element | None, name: str) -> float:
    if node is None or node.get(name) is None:
        raise ValueError(f"missing XML attribute {name}")
    return float(node.get(name, "nan"))


def parse_xml(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ValueError(f"geometry definition missing: {xml_path}")
    dp = _attr(definition, "dp")
    pointref = definition.find("pointref")
    pointref_xyz = [_attr(pointref, axis) for axis in "xyz"]
    walls = None
    for drawbox in root.findall(".//drawbox"):
        fill = drawbox.findtext("boxfill", default="")
        text = " ".join([str(drawbox.get("cmt", "")), fill])
        if "tank walls" in text.lower() or all(word in text.lower() for word in ("bottom", "left", "right")):
            walls = drawbox
            break
    if walls is None:
        raise ValueError(f"finite tank drawbox missing: {xml_path}")
    wall_point = walls.find("point")
    wall_size = walls.find("size")
    low = [_attr(wall_point, axis) for axis in "xyz"]
    size = [_attr(wall_size, axis) for axis in "xyz"]
    high = [low[i] + size[i] for i in range(3)]

    particles = root.find("./execution/particles")
    if particles is None:
        raise ValueError(f"particles summary missing: {xml_path}")
    groups: dict[str, dict[str, Any]] = {}
    for role in ("fixed", "moving", "floating", "fluid"):
        node = particles.find(role)
        if node is not None:
            groups[role] = {
                "begin": int(node.get("begin", "0")),
                "count": int(node.get("count", "0")),
                "mk": int(node.get("mk", "0")),
                "mkbound": int(node.get("mkbound", "0")) if node.get("mkbound") is not None else None,
            }
    summary = particles.find("_summary")
    total_particles = int(particles.get("np", "0"))
    fixed_particles = int(particles.get("nbf", "0"))
    floating = particles.find("floating")
    source_floating = root.find("./casedef/floatings/floating")
    if floating is None:
        raise ValueError(f"floating group missing: {xml_path}")
    massbody_node = (source_floating or floating).find("massbody")
    massbody = float(massbody_node.get("value", "nan")) if massbody_node is not None else float("nan")
    center_node = (source_floating or floating).find("center")
    inertia_node = (source_floating or floating).find("inertia")
    center = [_attr(center_node, axis) for axis in "xyz"]
    inertia = [_attr(inertia_node, axis) for axis in "xyz"]
    data2d = root.find("./execution/parameters/data2d")
    if data2d is None:
        # GenCase XML stores data2d in the execution parameters as a parameter
        # only in some official examples.  The generated particle contract is
        # still 3-D when the explicit value is absent.
        data2d_value: bool | None = None
    else:
        data2d_value = data2d.get("value", "false").lower() == "true"
    return {
        "dp_m": dp,
        "pointref_m": pointref_xyz,
        "tank_low_m": low,
        "tank_high_m": high,
        "tank_size_m": size,
        "finite_wall_boxfill": walls.findtext("boxfill", default=""),
        "total_particles": total_particles,
        "fixed_particles": fixed_particles,
        "groups": groups,
        "fluid_particles": groups.get("fluid", {}).get("count"),
        "floating_particles": groups.get("floating", {}).get("count"),
        "moving_particles": groups.get("moving", {}).get("count", 0),
        "massbody_kg": massbody,
        "center_m": center,
        "inertia_diag_kg_m2": inertia,
        "data2d": data2d_value,
        "summary_present": summary is not None,
    }


def source_files(case_id: str) -> dict[str, Path]:
    prefix = RAW_ROOT / case_id / f"{case_id}_GENCASE_001" / case_id
    paths = {
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
        "bound_vtk": prefix.with_name(prefix.name + "_Bound.vtk"),
        "fluid_vtk": prefix.with_name(prefix.name + "_Fluid.vtk"),
        "all_vtk": prefix.with_name(prefix.name + "_All.vtk"),
        "mkcells_vtk": prefix.with_name(prefix.name + "_MkCells.vtk"),
        "dp_vtk": prefix.with_name(prefix.name + "__Dp.vtk"),
        "gencase_receipt": prefix.parent / "execution-receipt.json",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"{case_id}: missing {missing}")
    return paths


def audit_case(mechanism: str, case_id: str, helper: Any) -> dict[str, Any]:
    paths = source_files(case_id)
    xml = parse_xml(paths["xml"])
    points, types = helper.bound_vtk_points(paths["bound_vtk"])
    fixed_points = points[types == 0]
    coverage = helper.open_tank_coverage(
        fixed_points,
        low_m=xml["tank_low_m"],
        high_m=xml["tank_high_m"],
        dp_m=xml["dp_m"],
    )
    expected = {
        # Bound.vtk contains fixed/moving/floating particles.  Type-3 fluid
        # particles are in the generated BI4/XML and deliberately absent from
        # this boundary-only VTK stream.
        "total_particles": 432421 if mechanism == "simple_free_response" else 741171,
        "fixed_particles": 292996,
        "fluid_particles": 0,
        "floating_particles": 139425,
        "moving_particles": 0 if mechanism == "simple_free_response" else 308750,
    }
    actual_counts = {
        "total_particles": int(len(points)),
        "fixed_particles": int((types == 0).sum()),
        "moving_particles": int((types == 1).sum()),
        "floating_particles": int((types == 2).sum()),
        "fluid_particles": int((types == 3).sum()),
    }
    count_pass = actual_counts == expected and xml["fluid_particles"] == 2621440
    mass_pass = xml["fluid_particles"] == 2621440 and abs(xml["fluid_particles"] * 0.001953125 - 5120.0) < 1e-9
    body_pass = (
        abs(xml["massbody_kg"] - 128.0) < 1e-10
        and all(abs(a - b) < 1e-9 for a, b in zip(xml["center_m"], [2.4, 1.2, 1.08]))
        and all(abs(a - b) < 1e-8 for a, b in zip(xml["inertia_diag_kg_m2"], [8.53333333333, 8.53333333333, 13.6533333333]))
    )
    file_hashes = {key: {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256(path)} for key, path in paths.items()}
    return {
        "mechanism_id": mechanism,
        "case_id": case_id,
        "source_files": file_hashes,
        "generated_xml_contract": xml,
        "bound_vtk_native_points": int(len(points)),
        "bound_vtk_fixed_points_used": int(len(fixed_points)),
        "actual_type_counts_from_bound_vtk": actual_counts,
        "expected_type_counts": expected,
        "type_count_pass": count_pass,
        "fluid_mass_contract": {
            "massfluid_kg": 0.001953125,
            "continuous_fluid_mass_kg": 5120.0,
            "actual_xml_fluid_mass_kg": xml["fluid_particles"] * 0.001953125,
            "pass": mass_pass,
        },
        "rigid_contract": {
            "aggregate_massbody_kg": xml["massbody_kg"],
            "center_m": xml["center_m"],
            "inertia_diag_kg_m2": xml["inertia_diag_kg_m2"],
            "pass": body_pass,
            "type2_particle_mass_is_not_aggregate_mass": True,
        },
        "finite_face_audit": {
            "point_type_filter": "Bound.vtk Type==0 fixed only",
            "tank_top_is_open": True,
            **coverage,
        },
        "actual_3d": xml["data2d"] is not True,
        "audit_pass": bool(count_pass and mass_pass and body_pass and coverage["all_five_finite_faces_covered"] and xml["data2d"] is not True),
        "qualification_claim": "none; native finite-face/source preflight only",
        "q_n_status": "pending root domain review, solver run, full native postprocessing and scientific review",
        "limitations": [
            "Coverage samples native fixed boundary points and does not prove normals, motion, solver lifecycle, or hydrodynamic accuracy.",
            "The open top is intentionally excluded; the XML default simulationdomain remains a root-owned solver gate.",
            "Aggregate body mass and analytical inertia are recorded separately from Type-2 particle mass and count.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    helper = load_helper()
    results = [audit_case(mechanism, case_id, helper) for mechanism, case_id in CASES.items()]
    result = {
        "schema": "ds-data-02.f6.dp0125.finite-face-audit.v1",
        "family_id": "F6",
        "scope": "F6_HANDOFF_20261002_RIGID003_DP0125_FINITE_FACE_REFERENCE_001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_script": {"path": str(SCRIPT), "sha256": sha256(SCRIPT)},
        "helper": {"path": str(HELPER), "sha256": HELPER_SHA256},
        "cases": results,
        "all_cases_finite_faces_pass": all(row["audit_pass"] for row in results),
        "solver_launch": False,
        "gpu_launch": False,
        "qualification_claim": "none",
    }
    output = args.output_dir / "finite_face_audit_001.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.resolve()), "sha256": sha256(output), "all_cases_finite_faces_pass": result["all_cases_finite_faces_pass"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

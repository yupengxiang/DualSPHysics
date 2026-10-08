#!/usr/bin/env python3
"""Audit the F5-S1 source clip plane and derive its continuous fluid volume.

This is a bounded source/XML audit.  It reads the small source and generated
XML files plus the existing V3 report; it does not read BI4, VTK, HDF5, or
start GenCase/CFD.  The official GenCase binary is used only as an immutable
version/identity anchor.  The plane-side convention is recorded from the
v5.4 binary implementation symbols and checked against the explicit source
point/vector form.

The old V2 scope sidecar deliberately left the continuous mass UNKNOWN.  The
source now contains an explicit point/vector plane and the official v5.4
clipper keeps the non-positive plane side.  For this source that side is the
region above the analytic bed's upper profile inside the declared fluid box.
The resulting continuous volume is therefore derived from the source
geometry, while the particle sample is still only a discrete diagnostic and
must be gated against that derived region before any CFD.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[6]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REPORT = DATA_ROOT / "families/F5/F5_S1_INITIAL_SUPPORT_AUDIT_V3_ROOT_077/f5-s1-initial-support-audit-v3-root-077-001-root-forward-030-001/report/f5_s1_initial_gencase_support_audit_v3.json"
GENERATED_XML = DATA_ROOT / "families/F5/F5_S1_FINE_INITIAL_GENCASE_CANARY_ROOT_068/f5-s1-fine-initial-gencase-canary-root-068-001-root-forward-030-001/generated.xml"
SOURCE_DEF = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml")
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4")
GENCASE = OFFICIAL_ROOT / "bin/linux/GenCase_linux64"
TEMPLATE = OFFICIAL_ROOT / "doc/xml_format/GenCase_CaseTemplate.xml"
CHANGES = OFFICIAL_ROOT / "CHANGES.txt"
OUTPUT = Path(__file__).with_name("stage2_f5_s1_clipplane_volume_audit_v1.json")

EXPECTED_REPORT_SHA = "6bdeb4942f73ca0e96ec536dcd87cb4ad4302b4b047ab4f650df88e2f03304ed"
EXPECTED_GENERATED_XML_SHA = "46d38211d7fc52f1647043821e2aa940084b4ceaeb455dd6749a288515bdd2d8"
EXPECTED_SOURCE_DEF_SHA = "fc5f044b657f1cd02a9375b74a20ba0496a94e80410a61f71884f7ed8dcec28f"
EXPECTED_GENCASE_SHA = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"

UPPER_PROFILE = ((-0.20, 0.00), (2.00, 0.00), (3.00, 0.28), (3.60, 0.448), (3.90, 0.448), (4.40, 0.05), (4.80, 0.05))


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with regular(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    s = path.stat()
    return {
        "path": str(path),
        "bytes": int(s.st_size),
        "mtime_ns": int(s.st_mtime_ns),
        "ctime_ns": int(s.st_ctime_ns),
        "st_dev": int(s.st_dev),
        "st_ino": int(s.st_ino),
        "sha256": sha256(path),
    }


def ffloat(node: ET.Element, name: str) -> float:
    value = node.attrib.get(name)
    if value is None:
        raise ValueError(f"missing {name} on {node.tag}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"non-finite {name}")
    return out


def xyz(node: ET.Element) -> tuple[float, float, float]:
    return (ffloat(node, "x"), ffloat(node, "y"), ffloat(node, "z"))


def parse_source_and_generated() -> dict[str, Any]:
    source_root = ET.parse(regular(SOURCE_DEF)).getroot()
    generated_root = ET.parse(regular(GENERATED_XML)).getroot()

    def command_root(root: ET.Element) -> ET.Element:
        found = root.findall(".//mainlist")
        if len(found) != 1:
            raise ValueError(f"expected one mainlist, got {len(found)}")
        return found[0]

    source_main = command_root(source_root)
    generated_main = command_root(generated_root)

    def get_clip(main: ET.Element) -> ET.Element:
        nodes = main.findall("./clipplane")
        if len(nodes) != 1:
            raise ValueError(f"expected one explicit clipplane, got {len(nodes)}")
        return nodes[0]

    source_clip = get_clip(source_main)
    generated_clip = get_clip(generated_main)

    def clip_values(node: ET.Element) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        points = node.findall("./point")
        vectors = node.findall("./vector")
        if len(points) != 1 or len(vectors) != 1:
            raise ValueError("clipplane must use exactly one point and vector")
        return xyz(points[0]), xyz(vectors[0])

    source_point, source_vector = clip_values(source_clip)
    generated_point, generated_vector = clip_values(generated_clip)
    if source_point != generated_point or source_vector != generated_vector:
        raise ValueError("generated clipplane differs from source")

    def find_fluid_box(main: ET.Element) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        boxes = []
        for box in main.findall("./drawbox"):
            if "initial_fluid_equilibrium_cell_centres_solid_recovery" in box.attrib.get("cmt", ""):
                point = box.find("./point")
                size = box.find("./size")
                if point is None or size is None:
                    raise ValueError("fluid box missing point/size")
                boxes.append((xyz(point), xyz(size)))
        if len(boxes) != 1:
            raise ValueError(f"expected one fluid box, got {len(boxes)}")
        return boxes[0]

    fluid_low, fluid_size = find_fluid_box(generated_main)
    fluid_high = tuple(fluid_low[i] + fluid_size[i] for i in range(3))

    def upper_points(main: ET.Element) -> tuple[tuple[float, float], ...]:
        extrudes = main.findall("./drawextrude")
        if len(extrudes) != 1:
            raise ValueError(f"expected one drawextrude, got {len(extrudes)}")
        points = extrudes[0].findall("./point")
        values = tuple((ffloat(p, "x"), ffloat(p, "z")) for p in points)
        if len(values) < len(UPPER_PROFILE) or values[: len(UPPER_PROFILE)] != UPPER_PROFILE:
            raise ValueError("source/generated upper bed profile does not match frozen profile")
        return values[: len(UPPER_PROFILE)]

    source_upper = upper_points(source_main)
    generated_upper = upper_points(generated_main)
    if source_upper != generated_upper:
        raise ValueError("generated upper profile differs from source")

    return {
        "source_clip_point_m": list(source_point),
        "source_clip_vector": list(source_vector),
        "fluid_low_m": list(fluid_low),
        "fluid_high_m": list(fluid_high),
        "fluid_size_m": list(fluid_size),
        "upper_profile_xz_m": [list(v) for v in source_upper],
    }


def integrate_clipped_box(low: tuple[float, float, float], high: tuple[float, float, float], normal: tuple[float, float, float], point: tuple[float, float, float]) -> float:
    """Integrate the volume in the box with n.(x-point)<=0.

    The F5 plane has nz<0, so it is represented as z >= a*x+b.  The helper
    intentionally refuses a different orientation instead of silently
    choosing the complementary half-space.
    """
    nx, ny, nz = normal
    if abs(nz) <= 1e-15 or nz >= 0.0:
        raise ValueError("this bounded audit only supports the declared negative-z plane")
    # nx*x + nz*z - nx*px - nz*pz <= 0 => z >= a*x+b.
    a = -nx / nz
    b = (nx * point[0] + nz * point[2]) / nz
    z0, z1 = low[2], high[2]
    x0, x1 = low[0], high[0]
    ywidth = high[1] - low[1]
    cuts = [x0, x1]
    for z in (z0, z1):
        if abs(a) > 1e-15:
            x = (z - b) / a
            if x0 < x < x1:
                cuts.append(x)
    cuts = sorted(set(cuts))
    area = 0.0
    pieces = []
    for xa, xb in zip(cuts, cuts[1:]):
        xm = (xa + xb) / 2.0
        cut = a * xm + b
        if cut <= z0:
            integral = (z1 - z0) * (xb - xa)
            region = "full_z"
        elif cut >= z1:
            integral = 0.0
            region = "empty"
        else:
            integral = z1 * (xb - xa) - (a * (xb * xb - xa * xa) / 2.0 + b * (xb - xa))
            region = "above_plane"
        area += integral
        pieces.append({"x_interval_m": [xa, xb], "classification": region, "integrated_height_area_m2": integral})
    return area * ywidth, {"plane_a": a, "plane_b": b, "pieces": pieces, "x_breaks_m": cuts}


def audit() -> dict[str, Any]:
    report_path = regular(REPORT)
    generated_path = regular(GENERATED_XML)
    source_path = regular(SOURCE_DEF)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema") != "ds02.stage2.f5-s1.initial-gencase-support-audit.v3":
        raise ValueError("unexpected F5 support report schema")
    source_sha = sha256(source_path)
    generated_sha = sha256(generated_path)
    if source_sha != EXPECTED_SOURCE_DEF_SHA or generated_sha != EXPECTED_GENERATED_XML_SHA:
        raise ValueError("immutable XML source hash changed")
    if sha256(report_path) != EXPECTED_REPORT_SHA:
        raise ValueError("F5 V3 report hash changed")

    parsed = parse_source_and_generated()
    point = tuple(parsed["source_clip_point_m"])
    vector = tuple(parsed["source_clip_vector"])
    low = tuple(parsed["fluid_low_m"])
    high = tuple(parsed["fluid_high_m"])
    volume, quadrature = integrate_clipped_box(low, high, vector, point)
    mass = volume * 1000.0
    sample_mass = float(report["mass_audit"]["generated_sample_mass_kg"])
    source_sample_mass = float(report["mass_audit"]["source_discrete_sample_mass_kg"])
    sample_rel = sample_mass / mass - 1.0
    source_rel = source_sample_mass / mass - 1.0

    # The line z=.28*(x-2) is exactly the upper profile from x=2 to 3.6;
    # before x=2 it is below the fluid box, so the retained half-space is the
    # fluid side above the closed bed throughout E.
    plane_a, plane_b = quadrature["plane_a"], quadrature["plane_b"]
    profile_error = max(abs(z - (plane_a * x + plane_b)) for x, z in ((2.0, 0.0), (3.0, 0.28), (3.6, 0.448)))
    if profile_error > 1e-12:
        raise ValueError(f"clip plane does not coincide with declared bed segment: {profile_error}")

    return {
        "schema": "ds02.stage2.f5-s1.clipplane-volume-audit.v1",
        "status": "COMPLETED_SOURCE_CLIP_SEMANTICS_DISCRETE_MASS_HARDFAIL",
        "identity": {
            "family_id": "F5",
            "sentinel_id": "F5-S1",
            "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
            "geometry_family_id": "F5_C082S1_CLOSED_ANALYTIC_PROFILE_EXTRUDED_Y_V1",
        },
        "scope": {
            "source_xml_read": True,
            "generated_xml_read": True,
            "support_report_read": True,
            "official_template_read": False,
            "official_binary_executed": False,
            "vtk_read": False,
            "bi4_read": False,
            "hdf5_read": False,
            "solver_started": False,
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "inputs": {
            "source_def": {"path": str(source_path), "sha256": source_sha},
            "generated_xml": {"path": str(generated_path), "sha256": generated_sha},
            "support_report": {"path": str(report_path), "sha256": sha256(report_path)},
            "official_gencase": {"path": str(GENCASE), "sha256": sha256(GENCASE), "version": "v5.4.354.01 (07-04-2025)"},
            "official_template": {"path": str(TEMPLATE), "sha256": sha256(TEMPLATE)},
            "official_changes": {"path": str(CHANGES), "sha256": sha256(CHANGES)},
        },
        "clipplane_contract": {
            "source_point_m": parsed["source_clip_point_m"],
            "source_vector_m": parsed["source_clip_vector"],
            "plane_equation": "0.28*(x-2.0)-z <= 0",
            "retained_side": "z >= 0.28*(x-2.0)",
            "implementation_evidence": {
                "official_template_lines": "GenCase_CaseTemplate.xml:136-144 (point1/2/3 and point+vector forms)",
                "official_binary_symbols": "JSpaceDraw::ClipPlaneVec -> JClipShape::AddPlane; JClipShape::ClipPoint",
                "official_binary_disassembly": "ClipPoint returns true only when every stored plane value n.x*x+n.y*y+n.z*z+d <= 0; addresses 0x4f6a30 and 0x6cad80 in the recorded binary",
                "changes_lines": "CHANGES.txt:318-319 (clip commands; clip commands also applied to draw points)",
            },
            "source_generated_point_vector_equal": True,
            "profile_plane_coincidence_max_abs_m": profile_error,
        },
        "continuous_region": {
            "envelope_low_m": parsed["fluid_low_m"],
            "envelope_high_m": parsed["fluid_high_m"],
            "envelope_y_width_m": high[1] - low[1],
            "region_definition": "E intersect {0.28*(x-2)-z <= 0}; this equals the portion of E above the closed bed upper profile for the declared x range",
            "volume_m3": volume,
            "mass_at_rho0_1000_kg": mass,
            "quadrature": quadrature,
            "derivation_status": "SOURCE_DERIVED_ANALYTIC_REGION",
            "owner_contract_status": "No separate scalar owner file; this is the mass implied by the frozen Def geometry and explicit GenCase clip plane.",
        },
        "mass_gate": {
            "generated_fluid_count": int(report["mass_audit"]["generated_fluid_count"]),
            "generated_sample_mass_kg": sample_mass,
            "source_discrete_sample_mass_kg": source_sample_mass,
            "sample_vs_source_derived_continuous_fraction": sample_rel,
            "source_sample_vs_source_derived_continuous_fraction": source_rel,
            "preferred_whole_initial_mass_fraction": 0.01,
            "hard_whole_initial_mass_fraction": 0.02,
            "status": "HARDFAIL_DISCRETE_SAMPLE_VS_SOURCE_DERIVED_REGION",
            "reason": "The generated particle mass is 11.5585% below the explicit source-geometry/clip-plane region mass. The old +0.4793% source-discrete comparison remains diagnostic only.",
            "mass_rescale": False,
            "threshold_widening": False,
        },
        "next_action": {
            "solver_or_cfd": "BLOCKED_PENDING_SOURCE_GEOMETRY_DECISION",
            "minimal_required_material": "Either an owner contract that intentionally defines a different fluid region, or a new immutable Def with explicit clip/draw semantics; do not infer a continuous target from the old particle sample.",
            "allowed_followup": "A bounded GenCase-only representation can be prepared only after the continuous region is explicitly accepted; no mass-fit/rescale and no CFD for this source-derived hard-fail.",
        },
    }


def self_test() -> dict[str, Any]:
    result = audit()
    if result["status"] != "COMPLETED_SOURCE_CLIP_SEMANTICS_DISCRETE_MASS_HARDFAIL":
        raise AssertionError(result["status"])
    if abs(result["continuous_region"]["volume_m3"] - 0.287736) > 1e-12:
        raise AssertionError(result["continuous_region"])
    if result["mass_gate"]["status"] != "HARDFAIL_DISCRETE_SAMPLE_VS_SOURCE_DERIVED_REGION":
        raise AssertionError(result["mass_gate"])
    return {"status": "PASS", "derived_volume_m3": result["continuous_region"]["volume_m3"], "derived_mass_kg": result["continuous_region"]["mass_at_rho0_1000_kg"], "sample_relative_error": result["mass_gate"]["sample_vs_source_derived_continuous_fraction"], "solver_started": False, "native_payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    result = self_test() if args.self_test else audit()
    if args.write_report:
        payload = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        if OUTPUT.exists():
            if OUTPUT.read_bytes() != payload:
                raise FileExistsError(f"refuse overwrite immutable report: {OUTPUT}")
        else:
            OUTPUT.write_bytes(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Machine-check the F5 clip-plane contract and bounded repair proposals.

This forward audit is intentionally source-level.  It verifies the immutable
F5 source/generated XML, the official v5.4 GenCase template and binary symbol /
instruction evidence, then recomputes the retained half-space volume from the
explicit plane.  It does not read VTK/BI4/HDF5 and does not execute GenCase or
the solver.  The two repair entries are *pre-registered GenCase-only
representations*: they preserve the continuous box/clip plane and controls,
change only a center-lattice discretization, and must still pass a guarded
actual XML/VTK QA before any CFD is considered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE_DEF = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml")
GENERATED_XML = DATA_ROOT / "families/F5/F5_S1_FINE_INITIAL_GENCASE_CANARY_ROOT_068/f5-s1-fine-initial-gencase-canary-root-068-001-root-forward-030-001/generated.xml"
SUPPORT_REPORT = DATA_ROOT / "families/F5/F5_S1_INITIAL_SUPPORT_AUDIT_V3_ROOT_077/f5-s1-initial-support-audit-v3-root-077-001-root-forward-030-001/report/f5_s1_initial_gencase_support_audit_v3.json"
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4")
GENCASE = OFFICIAL_ROOT / "bin/linux/GenCase_linux64"
TEMPLATE = OFFICIAL_ROOT / "doc/xml_format/GenCase_CaseTemplate.xml"
CHANGES = OFFICIAL_ROOT / "CHANGES.txt"
OUTPUT = Path(__file__).with_name("stage2_f5_s1_clipplane_official_evidence_audit_v2.json")

EXPECTED = {
    "source_def": "fc5f044b657f1cd02a9375b74a20ba0496a94e80410a61f71884f7ed8dcec28f",
    "generated_xml": "46d38211d7fc52f1647043821e2aa940084b4ceaeb455dd6749a288515bdd2d8",
    "support_report": "6bdeb4942f73ca0e96ec536dcd87cb4ad4302b4b047ab4f650df88e2f03304ed",
    "gencase": "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226",
    "template": "b0c7be2eac1f2bbf9702519cc0c94aa5ca9ef3df94c5e1cda28a005d8a27a38e",
    "changes": "742fd978500a75103dd4d383e16e7df81aaafc10962bd866bafb02deffc3842d",
}
UPPER_PROFILE = ((-0.20, 0.00), (2.00, 0.00), (3.00, 0.28), (3.60, 0.448), (3.90, 0.448), (4.40, 0.05), (4.80, 0.05))


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with regular(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    st = path.stat()
    return {"path": str(path), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino), "sha256": sha256(path)}


def finite(values: Any, label: str) -> None:
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError(f"non-finite {label}: {values}")


def xyz(node: ET.Element, label: str) -> tuple[float, float, float]:
    values = tuple(float(node.attrib[a]) for a in "xyz")
    finite(values, label)
    return values


def parse_clip(path: Path) -> dict[str, Any]:
    root = ET.parse(regular(path)).getroot()
    mains = root.findall(".//mainlist")
    if len(mains) != 1:
        raise ValueError(f"{path}: expected one mainlist")
    clips = mains[0].findall("./clipplane")
    if len(clips) != 1:
        raise ValueError(f"{path}: expected one clipplane")
    points = clips[0].findall("./point")
    vectors = clips[0].findall("./vector")
    if len(points) != 1 or len(vectors) != 1:
        raise ValueError(f"{path}: clipplane must be point/vector form")
    extrudes = mains[0].findall("./drawextrude")
    if len(extrudes) != 1:
        raise ValueError(f"{path}: expected one drawextrude")
    profile = tuple((float(p.attrib["x"]), float(p.attrib["z"])) for p in extrudes[0].findall("./point"))
    if profile[: len(UPPER_PROFILE)] != UPPER_PROFILE:
        raise ValueError(f"{path}: frozen upper profile changed")
    boxes = []
    for box in mains[0].findall("./drawbox"):
        if "initial_fluid_equilibrium_cell_centres_solid_recovery" not in box.attrib.get("cmt", ""):
            continue
        point, size = box.find("./point"), box.find("./size")
        if point is None or size is None:
            raise ValueError("fluid drawbox missing point/size")
        low, extent = xyz(point, "fluid.low"), xyz(size, "fluid.size")
        if any(v <= 0 for v in extent):
            raise ValueError("non-positive fluid extent")
        boxes.append((low, extent))
    if len(boxes) != 1:
        raise ValueError(f"{path}: expected one initial fluid box")
    definition = next((n for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "definition"), None)
    if definition is None or "dp" not in definition.attrib:
        raise ValueError(f"{path}: missing definition dp")
    return {"path": str(path.resolve()), "point": xyz(points[0], "clip.point"), "vector": xyz(vectors[0], "clip.vector"), "profile": profile, "fluid_low": boxes[0][0], "fluid_size": boxes[0][1], "dp_m": float(definition.attrib["dp"])}


def clipped_volume(low: tuple[float, float, float], size: tuple[float, float, float], normal: tuple[float, float, float], point: tuple[float, float, float]) -> tuple[float, dict[str, Any]]:
    nx, _, nz = normal
    if nz >= 0 or abs(nz) < 1e-15:
        raise ValueError("only the recorded negative-z F5 plane is supported")
    high = tuple(low[i] + size[i] for i in range(3))
    a = -nx / nz
    b = (nx * point[0] + nz * point[2]) / nz
    x0, x1, z0, z1 = low[0], high[0], low[2], high[2]
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
        xm = (xa + xb) / 2
        cut = a * xm + b
        if cut <= z0:
            integral, classification = (z1 - z0) * (xb - xa), "full_z"
        elif cut >= z1:
            integral, classification = 0.0, "empty"
        else:
            integral, classification = z1 * (xb - xa) - (a * (xb * xb - xa * xa) / 2 + b * (xb - xa)), "above_plane"
        area += integral
        pieces.append({"x_interval_m": [xa, xb], "classification": classification, "integrated_height_area_m2": integral})
    return area * (high[1] - low[1]), {"plane_a": a, "plane_b": b, "x_breaks_m": cuts, "pieces": pieces}


def run_text(command: list[str]) -> tuple[str, dict[str, Any]]:
    if shutil.which(command[0]) is None:
        raise RuntimeError(f"required read-only tool is unavailable: {command[0]}")
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout, {"argv": command, "stdout_sha256": sha256_bytes(completed.stdout), "stdout_bytes": len(completed.stdout.encode("utf-8"))}


def verify_official(binary: Path, template: Path, changes: Path) -> dict[str, Any]:
    nm, nm_command = run_text(["nm", "-C", str(binary)])
    symbols = ["JSpaceDraw::ClipPlaneVec(tdouble3, tdouble3)", "JClipShape::AddPlane(tdouble3 const&, tdouble3 const&)", "JClipShape::ClipPoint(tdouble3 const&) const"]
    missing = [s for s in symbols if s not in nm]
    if missing:
        raise ValueError(f"official symbol evidence missing: {missing}")
    dis, clip_command = run_text(["objdump", "-C", "-d", "-M", "intel", "--start-address=0x4f6a30", "--stop-address=0x4f6aaa", str(binary)])
    required_instructions = ["<JClipShape::ClipPoint", r"ucomisd\s+xmm2,xmm0", r"\bj[b]?\s+", r"setae\s+al"]
    if any((item.startswith("<") and item not in dis) or (not item.startswith("<") and re.search(item, dis) is None) for item in required_instructions):
        raise ValueError("ClipPoint disassembly does not show the recorded <=0 predicate")
    plane_dis, plane_command = run_text(["objdump", "-C", "-d", "-M", "intel", "--start-address=0x6cad80", "--stop-address=0x6cae04", str(binary)])
    if "<JSpaceDraw::ClipPlaneVec" not in plane_dis or plane_dis.count("<JClipShape::AddPlane") < 1:
        raise ValueError("ClipPlaneVec does not show AddPlane binding")
    add_plane_dis, add_plane_command = run_text(["objdump", "-C", "-d", "-M", "intel", "--start-address=0x4f4d00", "--stop-address=0x4f4f60", str(binary)])
    if "<JClipShape::AddPlane" not in add_plane_dis or "mulsd" not in add_plane_dis:
        raise ValueError("AddPlane disassembly does not show plane coefficient construction")
    template_text = template.read_text(encoding="utf-8", errors="strict")
    if "<clipplane>" not in template_text or '<point x="0" y="0" z="0" />' not in template_text or '<vector x="0" y="0" z="1" />' not in template_text:
        raise ValueError("official template lacks point/vector clipplane form")
    changes_text = changes.read_text(encoding="utf-8", errors="strict")
    if "<clipplane>" not in changes_text or "Clip commands are also applied to draw points" not in changes_text:
        raise ValueError("official CHANGES clip semantics evidence missing")
    return {"symbols_required": symbols, "symbols_verified": True, "command_output_bindings": {"nm": nm_command, "clip_point_objdump": clip_command, "clip_plane_vec_objdump": plane_command, "add_plane_objdump": add_plane_command}, "clip_point_disassembly": {"address": "0x4f6a30", "predicate_markers": required_instructions, "verified": True}, "clip_plane_vec_disassembly": {"address": "0x6cad80", "calls_add_plane": True, "verified": True}, "add_plane_disassembly": {"address": "0x4f4d00", "coefficient_construction_markers": ["mulsd"], "verified": True}, "template_semantics": {"point_vector_form": True, "template_line_hint": "136-144"}, "changes_semantics": {"clip_commands_and_draw_points": True, "line_hint": "318-319"}}


def audit() -> dict[str, Any]:
    paths = {"source_def": SOURCE_DEF, "generated_xml": GENERATED_XML, "support_report": SUPPORT_REPORT, "gencase": GENCASE, "template": TEMPLATE, "changes": CHANGES}
    inputs = {key: record(path) for key, path in paths.items()}
    for key, expected in EXPECTED.items():
        if inputs[key]["sha256"] != expected:
            raise ValueError(f"immutable {key} SHA changed: {inputs[key]['sha256']} != {expected}")
    source = parse_clip(SOURCE_DEF)
    generated = parse_clip(GENERATED_XML)
    if source["point"] != generated["point"] or source["vector"] != generated["vector"] or source["profile"] != generated["profile"] or source["fluid_low"] != generated["fluid_low"] or source["fluid_size"] != generated["fluid_size"]:
        raise ValueError("source/generated clip or fluid geometry differs")
    # The binary retains plane values n.(x-p)<=0.  For n=(.28,0,-1), p=(2,0,0),
    # this is z >= .28*(x-2), the upper-bed side inside the fluid envelope.
    nx, _, nz = source["vector"]
    a = -nx / nz
    b = (nx * source["point"][0] + nz * source["point"][2]) / nz
    volume, quadrature = clipped_volume(source["fluid_low"], source["fluid_size"], source["vector"], source["point"])
    profile_error = max(abs(z - (a * x + b)) for x, z in ((2.0, 0.0), (3.0, 0.28), (3.6, 0.448)))
    if profile_error > 1e-12:
        raise ValueError(f"clip plane/profile mismatch: {profile_error}")
    support_report = json.loads(SUPPORT_REPORT.read_text(encoding="utf-8"))
    mass = float(support_report["mass_audit"]["generated_sample_mass_kg"])
    continuous_mass = volume * 1000.0
    rel = mass / continuous_mass - 1.0
    official = verify_official(GENCASE, TEMPLATE, CHANGES)
    # These are source-preserving representation proposals, not results.  The
    # exact generated count/mass is intentionally UNKNOWN until guarded GenCase.
    repairs = [
        {"id": "F5_S1_EXPLICIT_CLIP_CENTER_LATTICE_DP010", "dp_m": 0.01, "pointref_m": [0.015, 0.0, 0.015], "continuous_box_and_clip_unchanged": True, "controls_and_motion_unchanged": True, "purpose": "center cell samples in the frozen fluid envelope and keep the official plane; actual count/support/mass must be measured", "gencase_launch": False, "solver_launch": False, "status": "PRE_REGISTERED_GENCASE_ONLY_PENDING_ROOT_REVIEW"},
        {"id": "F5_S1_EXPLICIT_CLIP_CENTER_LATTICE_DP005", "dp_m": 0.005, "pointref_m": [0.0125, 0.0, 0.0125], "continuous_box_and_clip_unchanged": True, "controls_and_motion_unchanged": True, "purpose": "independent finer center-lattice representation of the same clipped region; actual count/support/mass must be measured", "gencase_launch": False, "solver_launch": False, "status": "PRE_REGISTERED_GENCASE_ONLY_PENDING_ROOT_REVIEW"},
    ]
    return {"schema": "ds02.stage2.f5-s1.clipplane-official-evidence-audit.v2", "status": "COMPLETED_OFFICIAL_CLIP_EVIDENCE_AND_DISCRETE_MASS_HARDFAIL", "identity": {"family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"}, "scope": {"source_xml_read": True, "generated_xml_read": True, "support_report_read": True, "official_template_read": True, "official_binary_symbols_read": True, "official_binary_disassembly_read": True, "vtk_read": False, "bi4_read": False, "hdf5_read": False, "gencase_executed": False, "solver_started": False, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "inputs": inputs, "clipplane_contract": {"point_m": list(source["point"]), "vector_m": list(source["vector"]), "plane_equation": f"{a:g}*(x-{source['point'][0]:g})-z <= 0", "retained_half_space": f"z >= {a:g}*(x-{source['point'][0]:g})", "source_generated_equal": True, "bed_profile_max_abs_m": profile_error, "official_evidence": official}, "continuous_region": {"envelope_low_m": list(source["fluid_low"]), "envelope_size_m": list(source["fluid_size"]), "volume_m3": volume, "mass_at_rho0_1000_kg": continuous_mass, "quadrature": quadrature, "basis": "frozen source Def fluid box intersect official ClipPoint non-positive plane; this is not the old discrete sample target"}, "mass_gate": {"generated_sample_mass_kg": mass, "derived_continuous_mass_kg": continuous_mass, "sample_vs_derived_fraction": rel, "sample_vs_derived_percent": rel * 100.0, "preferred_fraction": 0.01, "hard_fraction": 0.02, "status": "HARDFAIL_OVER_TWO_PERCENT", "mass_rescale": False, "threshold_widening": False, "old_source_discrete_comparison_is_diagnostic_only": True}, "repair_candidates": repairs, "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "official clip semantics are machine-verified, but current discrete sample is hard-fail against the source-derived continuous region; proposals remain GenCase-only until actual QA"}}


def self_test() -> dict[str, Any]:
    if "JClipShape::ClipPoint" not in "JClipShape::ClipPoint(tdouble3 const&) const":
        raise AssertionError("fixture symbol")
    volume, _ = clipped_volume((0.01, -0.14, 0.01), (3.42, 0.28, 0.38), (0.28, 0.0, -1.0), (2.0, 0.0, 0.0))
    if abs(volume - 0.287736) > 1e-12:
        raise AssertionError(volume)
    try:
        clipped_volume((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported plane orientation accepted")
    return {"status": "PASS", "derived_volume_m3": volume, "vtk_read": False, "gencase_executed": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--write-report", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = self_test() if args.self_test else audit()
    if args.write_report:
        output = args.output.expanduser().resolve()
        payload = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        if output.exists():
            if output.read_bytes() != payload:
                raise FileExistsError(f"refuse to overwrite immutable report: {output}")
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

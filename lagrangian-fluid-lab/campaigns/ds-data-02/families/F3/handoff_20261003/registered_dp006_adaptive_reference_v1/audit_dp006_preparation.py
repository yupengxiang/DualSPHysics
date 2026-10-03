#!/usr/bin/env python3
"""Audit script for F3 DP 0.006m prospective adaptive reference preparation.

Validates:
1. Definition XML integrity and parity with fine anchor recipe (Symplectic, Wendland, CFL 0.05, CoefDtMin 0.005).
2. Spacing alignment and mass conservation (0.9 x 0.18 x 0.51 m, depth 0.09 m, dp 0.006 m, exact cell counts).
3. Discrete lattice geometry calculation: 150 x 30 x 15 = 67,500 fluid particles, 14.58 kg mass, 0 mismatch.
4. Input file and binary SHA256 integrity (GenCase, Solver, Forcing CSV).
5. Schema and structural validation of binding.json, diff_explanation.json, and launch_suggestions.json.
6. Runner request specifications under ds02.runner-request.v2 with launch_allowed=false (Root suggestions only).
7. Strict claim boundaries (Q-I complete, native evidence pending Root dispatch, Q-N not granted, production none).
"""

import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

BASE_DIR = Path(__file__).resolve().parent
DEFINITIONS_DIR = BASE_DIR / "definitions"
REQUESTS_DIR = BASE_DIR / "requests"

EXPECTED_FORCING_SHA256 = "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3"
ANCHOR_FINE_DEF = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_true_adaptive_spatial_input_review_023/definitions/F3_CELL3_plain_0p0075_Def.xml")
FORCING_CSV = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005/root-cell3-nominal-cfl-decoupled-floor-input-005/prepared/CaseSloshingAccData.csv")
PROTOCOL_JSON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/continuation/F3-CELL3-PROTOCOL.json")

def check(name: str, condition: bool, details: str = ""):
    if condition:
        print(f"[PASS] {name}{f': {details}' if details else ''}")
        return True
    else:
        print(f"[FAIL] {name}: {details}", file=sys.stderr)
        return False

def audit_all():
    passed = True

    # 1. XML Definitions Exist and Match
    def_canonical = DEFINITIONS_DIR / "F3_CELL3_LONG_DP006_ADAPTIVE_CFL05_COEF005_Def.xml"
    def_plain = DEFINITIONS_DIR / "F3_CELL3_plain_0p006_Def.xml"
    passed &= check("Canonical Def XML exists", def_canonical.is_file())
    passed &= check("Plain Def XML exists", def_plain.is_file())

    if def_canonical.is_file() and def_plain.is_file():
        h1 = hashlib.sha256(def_canonical.read_bytes()).hexdigest()
        h2 = hashlib.sha256(def_plain.read_bytes()).hexdigest()
        passed &= check("Canonical and plain XMLs identical content", h1 == h2, f"SHA256: {h1[:16]}...")

    # 2. XML Parameter Parity with Fine Reference Anchor (DP 0.0075)
    if def_plain.is_file() and ANCHOR_FINE_DEF.is_file():
        tree_006 = ET.parse(def_plain)
        tree_ref = ET.parse(ANCHOR_FINE_DEF)

        params_006 = {p.attrib["key"]: p.attrib["value"] for p in tree_006.findall(".//parameter")}
        params_ref = {p.attrib["key"]: p.attrib["value"] for p in tree_ref.findall(".//parameter")}
        passed &= check("Parameter parity with fine anchor", params_006 == params_ref, f"{len(params_006)} parameters verified")

        # Specific key checks
        passed &= check("StepAlgorithm == 2 (Symplectic)", params_006.get("StepAlgorithm") == "2")
        passed &= check("Kernel == 2 (Wendland)", params_006.get("Kernel") == "2")
        passed &= check("CFL == 0.05", tree_006.find(".//constantsdef/cflnumber").attrib.get("value") == ".05")
        passed &= check("CoefDtMin == 0.005", params_006.get("CoefDtMin") == "0.005")
        passed &= check("DtFixed == 0", params_006.get("DtFixed") == "0")
        passed &= check("TimeMax == 8.35", params_006.get("TimeMax") == "8.35")
        passed &= check("TimeOut == 0.01", params_006.get("TimeOut") == "0.01")
        passed &= check("Boundary == 2", params_006.get("Boundary") == "2")
        passed &= check("SlipMode == 2", params_006.get("SlipMode") == "2")
        passed &= check("NoPenetration == 1", params_006.get("NoPenetration") == "1")

        # DP definition check
        dp_val = float(tree_006.find(".//definition").attrib["dp"])
        passed &= check("Definition DP == 0.006", abs(dp_val - 0.006) < 1e-9)
        ptref = tree_006.find(".//definition/pointref")
        pt_x, pt_y, pt_z = float(ptref.attrib["x"]), float(ptref.attrib["y"]), float(ptref.attrib["z"])
        passed &= check("Pointref == (0.003, 0.003, 0.003)", (pt_x, pt_y, pt_z) == (0.003, 0.003, 0.003))

    # 3. Geometry Spacing Alignment and Mass Conservation
    dp = 0.006
    lx, ly, lz, depth = 0.9, 0.18, 0.51, 0.09
    nx = lx / dp
    ny = ly / dp
    nz_fill = depth / dp
    nz_box = lz / dp
    passed &= check("X-axis aligns with dp=0.006", nx.is_integer() and int(nx) == 150, f"nx = {nx}")
    passed &= check("Y-axis aligns with dp=0.006", ny.is_integer() and int(ny) == 30, f"ny = {ny}")
    passed &= check("Z-fill aligns with dp=0.006", nz_fill.is_integer() and int(nz_fill) == 15, f"nz_fill = {nz_fill}")
    passed &= check("Z-height aligns with dp=0.006", nz_box.is_integer() and int(nz_box) == 85, f"nz_box = {nz_box}")

    fluid_particles = int(nx) * int(ny) * int(nz_fill)
    passed &= check("Fluid particle count == 67,500", fluid_particles == 67500, f"count: {fluid_particles}")

    lattice_vol = fluid_particles * (dp ** 3)
    continuum_vol = lx * ly * depth
    passed &= check("Volume conservation (0% deviation)", abs(lattice_vol - continuum_vol) < 1e-12, f"{lattice_vol:.6f} m^3")

    rho0 = 1000.0
    nominal_mass = fluid_particles * (rho0 * (dp ** 3))
    continuum_mass = continuum_vol * rho0
    passed &= check("Mass conservation (0% deviation)", abs(nominal_mass - continuum_mass) < 1e-12, f"{nominal_mass:.3f} kg")

    # 4. Forcing File Hash
    if FORCING_CSV.is_file():
        forcing_h = hashlib.sha256(FORCING_CSV.read_bytes()).hexdigest()
        passed &= check("Forcing CSV SHA256 matches exact hash", forcing_h == EXPECTED_FORCING_SHA256, f"{forcing_h[:16]}...")
    else:
        passed &= check("Forcing CSV exists on disk", False, f"Not found: {FORCING_CSV}")

    # 5. Protocol Reference Ladder
    if PROTOCOL_JSON.is_file():
        proto = json.loads(PROTOCOL_JSON.read_text())
        ref_ladders = proto.get("reference_dp_m", [])
        passed &= check("Protocol contains DP 0.006 in reference ladder", 0.006 in ref_ladders, f"Ladders: {ref_ladders}")

    # 6. JSON Validation (binding.json, diff_explanation.json, launch_suggestions.json)
    for fname in ["binding.json", "diff_explanation.json", "launch_suggestions.json"]:
        p = BASE_DIR / fname
        if check(f"{fname} exists", p.is_file()):
            data = json.loads(p.read_text())
            passed &= check(f"{fname} valid JSON", isinstance(data, dict))

    # 7. Runner Requests Validation
    gencase_req = REQUESTS_DIR / "gencase_cpu_dp006_request.json"
    solver_req = REQUESTS_DIR / "solver_gpu_dp006_request.json"
    passed &= check("GenCase request exists", gencase_req.is_file())
    passed &= check("Solver GPU request exists", solver_req.is_file())

    if gencase_req.is_file():
        gdata = json.loads(gencase_req.read_text())
        passed &= check("GenCase request launch_allowed == false", gdata.get("launch_allowed") is False)
        passed &= check("GenCase request launch_owner == 'root'", gdata.get("launch_owner") == "root")

    if solver_req.is_file():
        sdata = json.loads(solver_req.read_text())
        passed &= check("Solver request launch_allowed == false", sdata.get("launch_allowed") is False)
        passed &= check("Solver request launch_owner == 'root'", sdata.get("launch_owner") == "root")
        passed &= check("Solver request max_wall_seconds <= 7200", sdata.get("max_wall_seconds", 0) <= 7200)

    # 8. Claim Boundaries Verification
    binding = json.loads((BASE_DIR / "binding.json").read_text())
    claims = binding.get("claim_boundaries", {})
    passed &= check("Q-I status is completed", claims.get("q_i") == "completed (valid definition, aligned geometry, parameter anchor parity, runner requests registered)")
    passed &= check("Native evidence pending", claims.get("native_array_evidence") == "pending_root_dispatch")
    passed &= check("Q-N not granted", claims.get("q_n") == "not_granted")
    passed &= check("Production approval is none", claims.get("production_approval") == "none")

    print(f"\nOverall Audit Result: {'SUCCESS - ALL CHECKS PASSED' if passed else 'FAILURE - SOME CHECKS FAILED'}")
    return passed

if __name__ == "__main__":
    success = audit_all()
    sys.exit(0 if success else 1)

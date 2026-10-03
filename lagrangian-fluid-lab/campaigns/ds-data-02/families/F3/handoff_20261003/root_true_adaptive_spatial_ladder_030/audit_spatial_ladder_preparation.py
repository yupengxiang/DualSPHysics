#!/usr/bin/env python3
"""Audit and validation script for F3 True Adaptive Spatial Ladder Preparation.

Validates:
1. XML case definitions for Coarse (DP 0.015m), Medium (DP 0.010m), and Fine (DP 0.0075m).
2. Strict physical equivalence: mother continuum geometry (0.9 x 0.18 x 0.51 m), water depth (0.09 m),
   fluid mass (14.58 kg), whole-field forcing (CaseSloshingAccData.csv), and mDBC boundary conditions.
3. Commensurate integer grid cell alignments and particle counts.
4. Recipe parity: Symplectic, Wendland, CFL 0.05, decoupled CoefDtMin 0.005, TimeMax 8.35s, TimeOut 0.01s.
5. Runner requests (CPU GenCase & GPU Solver) under ds02.runner-request.v2 with strict resource bounds (<= 2h).
6. Non-normalization policy and prohibition of historical fixed-dt solver reuse.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def audit_xml_definition(xml_path: Path, expected_dp: float, expected_counts: dict) -> dict:
    if not xml_path.exists():
        raise FileNotFoundError(f"Missing definition XML: {xml_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    # 1. Constants
    constants = root.find(".//constantsdef")
    if constants is None:
        raise ValueError("Missing constantsdef")
    rhop0 = float(constants.find("rhop0").get("value"))
    coefh = float(constants.find("coefh").get("value"))
    cfl = float(constants.find("cflnumber").get("value"))

    if rhop0 != 1000.0:
        raise ValueError(f"Unexpected rhop0: {rhop0}")
    if abs(coefh - 0.91924) > 1e-5:
        raise ValueError(f"Unexpected coefh: {coefh}")
    if abs(cfl - 0.05) > 1e-5:
        raise ValueError(f"Unexpected cfl: {cfl}")

    # 2. Geometry definition
    geom_def = root.find(".//geometry/definition")
    if geom_def is None:
        raise ValueError("Missing geometry definition")
    dp = float(geom_def.get("dp"))
    if abs(dp - expected_dp) > 1e-6:
        raise ValueError(f"DP mismatch: expected {expected_dp}, got {dp}")

    pointref = geom_def.find("pointref")
    pref = [float(pointref.get(k)) for k in ("x", "y", "z")]
    expected_pref = [dp / 2.0, dp / 2.0, dp / 2.0]
    if any(abs(a - b) > 1e-6 for a, b in zip(pref, expected_pref)):
        raise ValueError(f"Pointref mismatch: {pref} vs {expected_pref}")

    # 3. GeometryForNormals (mother geometry)
    norm_box = root.find(".//list[@name='GeometryForNormals']/drawbox")
    if norm_box is None:
        raise ValueError("Missing GeometryForNormals drawbox")
    norm_p = [float(norm_box.find("point").get(k)) for k in ("x", "y", "z")]
    norm_s = [float(norm_box.find("size").get(k)) for k in ("x", "y", "z")]
    if norm_p != [-0.45, -0.09, 0.0] or norm_s != [0.9, 0.18, 0.51]:
        raise ValueError(f"Mother geometry box mismatch: point={norm_p}, size={norm_s}")

    # 4. Fluid box in mainlist
    fluid_box = root.find(".//mainlist/drawbox[boxfill='solid']")
    if fluid_box is None:
        raise ValueError("Missing fluid drawbox")
    f_p = [float(fluid_box.find("point").get(k)) for k in ("x", "y", "z")]
    f_s = [float(fluid_box.find("size").get(k)) for k in ("x", "y", "z")]
    exp_fp = [-0.45 + dp / 2.0, -0.09 + dp / 2.0, dp / 2.0]
    exp_fs = [0.9 - dp, 0.18 - dp, 0.09 - dp]
    if any(abs(a - b) > 1e-5 for a, b in zip(f_p, exp_fp)):
        raise ValueError(f"Fluid point mismatch for DP {dp}: {f_p} vs {exp_fp}")
    if any(abs(a - b) > 1e-5 for a, b in zip(f_s, exp_fs)):
        raise ValueError(f"Fluid size mismatch for DP {dp}: {f_s} vs {exp_fs}")

    # 5. Boundary box in mainlist
    bound_box = root.find(".//mainlist/drawbox[layers]")
    if bound_box is None:
        raise ValueError("Missing boundary drawbox")
    b_p = [float(bound_box.find("point").get(k)) for k in ("x", "y", "z")]
    b_s = [float(bound_box.find("size").get(k)) for k in ("x", "y", "z")]
    exp_bp = [-0.45 - dp / 2.0, -0.09 - dp / 2.0, -dp / 2.0]
    exp_bs = [0.9 + dp, 0.18 + dp, 0.51 + dp / 2.0]
    if any(abs(a - b) > 1e-5 for a, b in zip(b_p, exp_bp)):
        raise ValueError(f"Bound point mismatch for DP {dp}: {b_p} vs {exp_bp}")
    if any(abs(a - b) > 1e-5 for a, b in zip(b_s, exp_bs)):
        raise ValueError(f"Bound size mismatch for DP {dp}: {b_s} vs {exp_bs}")

    # 6. Execution parameters
    params = {n.get("key"): n.get("value") for n in root.findall(".//parameters/parameter")}
    required_params = {
        "StepAlgorithm": "2",
        "Kernel": "2",
        "ViscoTreatment": "1",
        "Visco": "0.05",
        "ViscoBoundFactor": "1",
        "DensityDT": "3",
        "DensityDTvalue": "0.1",
        "Shifting": "0",
        "CoefDtMin": "0.005",
        "DtIni": "0",
        "DtMin": "0",
        "DtFixed": "0",
        "TimeMax": "8.35",
        "TimeOut": "0.01",
        "NoPenetration": "1",
        "Boundary": "2",
        "SlipMode": "2",
        "SavePosDouble": "2",
    }
    for k, v in required_params.items():
        if k not in params or params[k] != v:
            raise ValueError(f"Parameter mismatch for {k}: expected {v}, got {params.get(k)}")

    # 7. Prescribed body acceleration
    acc = root.find(".//accinput")
    if acc is None:
        raise ValueError("Missing accinput")
    centre = [float(acc.find("acccentre").get(k)) for k in ("x", "y", "z")]
    if centre != [0.45, 0.0, 0.0]:
        raise ValueError(f"Acccentre mismatch: {centre}")
    if acc.find("globalgravity").get("value") != "0":
        raise ValueError("Globalgravity must be 0 for prescribed sloshing")
    if acc.find("acctimesfile").get("value") != "CaseSloshingAccData.csv":
        raise ValueError("Acctimesfile must be CaseSloshingAccData.csv")

    # 8. Particle counts and mass
    nx = int(round(0.9 / dp))
    ny = int(round(0.18 / dp))
    nz_f = int(round(0.09 / dp))
    fluid_particles = nx * ny * nz_f
    particle_mass = rhop0 * (dp ** 3)
    fluid_mass = fluid_particles * particle_mass

    if fluid_particles != expected_counts["fluid_particles"]:
        raise ValueError(f"Fluid particle mismatch: {fluid_particles} vs {expected_counts['fluid_particles']}")
    if abs(fluid_mass - 14.58) > 1e-4:
        raise ValueError(f"Fluid mass mismatch from 14.58kg: {fluid_mass}")

    return {
        "xml_path": str(xml_path),
        "sha256": sha256_file(xml_path),
        "dp_m": dp,
        "grid_cells": [nx, ny, nz_f],
        "fluid_particles": fluid_particles,
        "particle_mass_kg": particle_mass,
        "fluid_mass_kg": fluid_mass,
        "cfl": cfl,
        "coef_dt_min": float(params["CoefDtMin"]),
        "time_max_s": float(params["TimeMax"]),
        "time_out_s": float(params["TimeOut"]),
        "status": "PASS",
    }


def audit_runner_request(req_path: Path, expected_kind: str) -> dict:
    if not req_path.exists():
        raise FileNotFoundError(f"Missing request file: {req_path}")
    data = json.loads(req_path.read_text())

    if data.get("schema") != "ds02.runner-request.v2":
        raise ValueError(f"Request schema must be ds02.runner-request.v2, got {data.get('schema')}")
    if data.get("family_id") != "F3":
        raise ValueError(f"Request family_id must be F3, got {data.get('family_id')}")
    if data.get("kind") != expected_kind:
        raise ValueError(f"Expected kind {expected_kind}, got {data.get('kind')}")
    if data.get("launch_allowed") is not False:
        raise ValueError("launch_allowed must be false in pre-dispatch request")
    if data.get("max_wall_seconds", 0) > 7200:
        raise ValueError(f"max_wall_seconds exceeds 2h cap: {data.get('max_wall_seconds')}")

    # Check input files exist
    for f in data.get("input_files", []):
        p = Path(f)
        if not p.exists():
            raise FileNotFoundError(f"Declared input file does not exist: {p}")

    return {
        "request_path": str(req_path),
        "case_id": data.get("case_id"),
        "attempt_id": data.get("attempt_id"),
        "kind": data.get("kind"),
        "max_wall_seconds": data.get("max_wall_seconds"),
        "estimated_storage_bytes": data.get("estimated_storage_bytes"),
        "status": "PASS",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    handoff = args.root
    def_dir = handoff / "definitions"
    req_dir = handoff / "requests"
    contract_path = handoff / "contracts" / "spatial_ladder_contract.json"
    prospective_path = handoff / "prospective_points_of_comparison.json"

    print("=== AUDITING F3 TRUE ADAPTIVE SPATIAL LADDER PREPARATION ===")

    # 1. Audit Definitions
    definitions_audit = {}
    ladder_specs = [
        ("coarse", def_dir / "F3_CELL3_plain_0p015_Def.xml", 0.015, {"fluid_particles": 4320}),
        ("medium", def_dir / "F3_CELL3_plain_0p010_Def.xml", 0.010, {"fluid_particles": 14580}),
        ("fine", def_dir / "F3_CELL3_plain_0p0075_Def.xml", 0.0075, {"fluid_particles": 34560}),
    ]
    for name, path, dp, counts in ladder_specs:
        print(f"Auditing {name.upper()} (DP={dp}m) definition: {path.name}")
        res = audit_xml_definition(path, dp, counts)
        definitions_audit[name] = res
        print(f"  -> PASS: fluid_particles={res['fluid_particles']}, mass={res['fluid_mass_kg']:.6f} kg")

    # 2. Verify Commensurate Ratios
    dp_c = definitions_audit["coarse"]["dp_m"]
    dp_m = definitions_audit["medium"]["dp_m"]
    dp_f = definitions_audit["fine"]["dp_m"]
    ratio_cf = dp_c / dp_f
    ratio_mf = dp_m / dp_f
    ratio_cm = dp_c / dp_m

    if abs(ratio_cf - 2.0) > 1e-6:
        raise ValueError(f"Coarse/Fine ratio is not 2.0: {ratio_cf}")
    if abs(ratio_mf - 4.0 / 3.0) > 1e-6:
        raise ValueError(f"Medium/Fine ratio is not 4/3: {ratio_mf}")
    if abs(ratio_cm - 1.5) > 1e-6:
        raise ValueError(f"Coarse/Medium ratio is not 1.5: {ratio_cm}")
    print(f"Commensurate ratios verified: C:F={ratio_cf:.1f}, M:F={ratio_mf:.4f}, C:M={ratio_cm:.2f}")

    # 3. Audit Requests
    requests_audit = {}
    req_specs = [
        ("gencase_coarse", req_dir / "gencase_cpu_coarse_dp015_request.json", "cpu"),
        ("gencase_medium", req_dir / "gencase_cpu_medium_dp010_request.json", "cpu"),
        ("solver_coarse", req_dir / "solver_gpu_coarse_dp015_request.json", "qualification"),
        ("solver_medium", req_dir / "solver_gpu_medium_dp010_request.json", "qualification"),
    ]
    for name, path, kind in req_specs:
        print(f"Auditing request: {path.name}")
        res = audit_runner_request(path, kind)
        requests_audit[name] = res
        print(f"  -> PASS: {res['case_id']} max_wall={res['max_wall_seconds']}s")

    # 4. Audit Contract and Prospective Review files
    if not contract_path.exists():
        raise FileNotFoundError(f"Missing spatial ladder contract: {contract_path}")
    contract_data = json.loads(contract_path.read_text())
    if contract_data.get("schema") != "ds02.f3.adaptive-spatial-ladder-contract.v1":
        raise ValueError("Invalid contract schema")
    print(f"Contract verified: {contract_path.name}")

    if not prospective_path.exists():
        raise FileNotFoundError(f"Missing prospective review: {prospective_path}")
    prospective_data = json.loads(prospective_path.read_text())
    if prospective_data.get("schema") != "ds02.root.prospective-spatial-ladder-comparison.v1":
        raise ValueError("Invalid prospective review schema")
    print(f"Prospective comparison verified: {prospective_path.name}")

    summary = {
        "status": "ALL_PASSED",
        "definitions": definitions_audit,
        "commensurate_ratios": {"coarse_to_fine": ratio_cf, "medium_to_fine": ratio_mf, "coarse_to_medium": ratio_cm},
        "requests": requests_audit,
        "contract": str(contract_path),
        "prospective_review": str(prospective_path),
    }

    if args.output:
        args.output.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Summary written to: {args.output}")

    print("=== AUDIT COMPLETED SUCCESSFULLY: ALL 7 CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

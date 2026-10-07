#!/usr/bin/env python3
"""Materialize F5 Stage 8 production definitions, GenCase requests, and solver dispatch."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_f5 import (
    FAMILY_ROOT,
    FAMILY_ID,
    _write_bed_stl,
    _bed_asset_path,
    _write_motion,
    _slope_code,
    _q,
    sha256_file,
    EVENT_WINDOW_S,
    GENCASE,
    SOLVER,
)

STAGE8_CASES = [
    "F5_RUNUP_00",
    "F5_WEIR_00",
    "F5_RUNUP_01",
    "F5_WEIR_01",
    "F5_RUNUP_02",
    "F5_WEIR_02",
    "F5_RUNUP_03",
    "F5_WEIR_03",
]


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_two_phase_definition_xml(case: dict) -> str:
    dp = float(case["dp_m"])
    depth = float(case["initial_depth_m"])
    background = str(case["background"])
    motion_name = Path(str(case["motion_path"])).name
    weir = background == "weir_pair"
    crest_z = float(case.get("crest_z_m") or 0.0)
    slope_ratio = float(case.get("slope_ratio", 0.28))

    # Phase 1: Cell-centred fluid lattice geometry
    x_min, x_max = -0.90, 3.30
    y_min, y_max = -0.70, 0.70
    z_min = 0.02

    nx = int(round((x_max - x_min) / dp))
    ny = int(round((y_max - y_min) / dp))
    nz = int(math.floor((depth - 0.5 * dp) / dp)) + 1

    x0 = x_min + 0.5 * dp
    y0 = y_min + 0.5 * dp
    z0 = z_min + 0.5 * dp

    sx = (nx - 1) * dp
    sy = (ny - 1) * dp
    sz = (nz - 1) * dp

    weir_xml = ""
    if weir:
        low_y = float(case.get("notch_y0_m", 0.25))
        high_y = float(case.get("notch_y1_m", 0.50))
        base_z = float(case.get("weir_base_z_m", 0.2802))
        weir_xml = f'''
          <setmkbound mk="50" />
          <drawbox cmt="weir_left_side_segment">
            <boxfill>solid</boxfill>
            <point x="4.96" y="-0.70" z="{_q(base_z)}" />
            <size x="0.24" y="{_q(low_y + 0.70)}" z="{_q(crest_z - base_z)}" />
            <layers vdp="0,1,2" />
          </drawbox>
          <drawbox cmt="weir_right_side_segment">
            <boxfill>solid</boxfill>
            <point x="4.96" y="{_q(high_y)}" z="{_q(base_z)}" />
            <size x="0.24" y="{_q(0.70 - high_y)}" z="{_q(crest_z - base_z)}" />
            <layers vdp="0,1,2" />
          </drawbox>'''

    return f'''<?xml version="1.0" encoding="UTF-8" ?>
<!-- DS-DATA-02 F5 fresh definition; mechanism={background}; physical_case_id={case["physical_case_id"]}; resolution={case["resolution"]} -->
<!-- Repair 002 two-phase cell-centre initialization: fluid drawn first, boundaries drawn second -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <rhopgradient value="3" />
      <hswl value="0" auto="true" />
      <gamma value="7" />
      <speedsystem value="0" auto="true" />
      <coefsound value="20" />
      <speedsound value="0" auto="true" />
      <coefh value="1.5" />
      <cflnumber value="0.2" />
    </constantsdef>
    <mkconfig boundcount="230" fluidcount="9">
      <mkorientfluid mk="0" orient="Xyz" />
    </mkconfig>
    <geometry>
      <definition dp="{_q(dp)}">
        <pointref x="0" y="0" z="0" />
        <pointmin x="-1.20" y="-0.86" z="-0.25" />
        <pointmax x="11.10" y="0.86" z="1.45" />
      </definition>
      <commands>
        <mainlist>
          <setshapemode>dp | actual | bound</setshapemode>
          <setdrawmode mode="solid" />
          
          <!-- Phase 1: Fluid cell-centred volume drawn first -->
          <setmkfluid mk="0" />
          <drawbox cmt="initial_fluid_cell_centres_repair_002">
            <boxfill>solid</boxfill>
            <point x="{_q(x0)}" y="{_q(y0)}" z="{_q(z0)}" />
            <size x="{_q(sx)}" y="{_q(sy)}" z="{_q(sz)}" />
          </drawbox>

          <!-- Phase 2: Fixed and moving boundaries drawn second to strictly preserve all boundary particles -->
          <setmkbound mk="0" />
          <drawbox cmt="tank_floor">
            <boxfill>bottom</boxfill>
            <point x="-1.10" y="-0.80" z="-0.25" />
            <size x="11.90" y="1.60" z="0.25" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkbound mk="30" />
          <drawbox cmt="finite_sidewall_left">
            <boxfill>solid</boxfill>
            <point x="-1.10" y="-0.80" z="-0.25" />
            <size x="11.90" y="0.08" z="1.45" />
            <layers vdp="0,1,2" />
          </drawbox>
          <drawbox cmt="finite_sidewall_right">
            <boxfill>solid</boxfill>
            <point x="-1.10" y="0.72" z="-0.25" />
            <size x="11.90" y="0.08" z="1.45" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkbound mk="10" />
          <drawbox cmt="prescribed_piston">
            <boxfill>solid</boxfill>
            <point x="-1.08" y="-0.72" z="0" />
            <size x="0.08" y="1.44" z="1.02" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setdrawmode mode="full" />
          <setmkbound mk="40" />
          <drawfilestl file="assets/f5_continuous_bed_profile_slope_{_slope_code(slope_ratio)}.stl" />
          <shapeout file="continuous_bed" reset="true" />
          {weir_xml}
        </mainlist>
      </commands>
    </geometry>
    <motion>
      <objreal ref="10">
        <begin mov="1" start="0.00" finish="{_q(EVENT_WINDOW_S)}" />
        <mvpredef id="1" duration="{_q(EVENT_WINDOW_S)}">
          <file name="{motion_name}" fields="2" fieldtime="0" fieldx="1" />
        </mvpredef>
      </objreal>
    </motion>
  </casedef>
  <execution>
    <parameters>
      <parameter key="SavePosDouble" value="0" />
      <parameter key="StepAlgorithm" value="2" />
      <parameter key="VerletSteps" value="40" />
      <parameter key="Kernel" value="2" />
      <parameter key="ViscoTreatment" value="1" />
      <parameter key="Visco" value="0.01" />
      <parameter key="ViscoBoundFactor" value="0" />
      <parameter key="DensityDT" value="2" />
      <parameter key="DensityDTvalue" value="0.1" />
      <parameter key="Shifting" value="0" />
      <parameter key="ShiftCoef" value="-2" />
      <parameter key="ShiftTFS" value="0" />
      <parameter key="RigidAlgorithm" value="1" />
      <parameter key="FtPause" value="0.0" />
      <parameter key="CoefDtMin" value="0.05" />
      <parameter key="DtIni" value="0" />
      <parameter key="DtMin" value="0" />
      <parameter key="DtFixed" value="0" />
      <parameter key="DtFixedFile" value="NONE" />
      <parameter key="DtAllParticles" value="0" />
      <parameter key="TimeMax" value="{_q(EVENT_WINDOW_S)}" />
      <parameter key="TimeOut" value="0.02" />
      <parameter key="PartsOutMax" value="1" />
      <parameter key="RhopOutMin" value="700" />
      <parameter key="RhopOutMax" value="1300" />
      <parameter key="MinFluidStop" value="0" />
      <simulationdomain comment="Defines domain of simulation">
        <posmin x="-1.30" y="-0.95" z="-0.35" />
        <posmax x="11.20" y="0.95" z="1.55" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
'''


def materialize_stage8(family_dir: Path = FAMILY_ROOT) -> list[dict]:
    family = Path(family_dir).resolve()
    reg_path = family / "case_registry.jsonl"
    prod_defs = family / "production/definitions"
    prod_assets = prod_defs / "assets"
    requests_dir = family / "requests"

    prod_defs.mkdir(parents=True, exist_ok=True)
    prod_assets.mkdir(parents=True, exist_ok=True)
    requests_dir.mkdir(parents=True, exist_ok=True)

    gencase_bin = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"

    cases = [json.loads(line) for line in reg_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stage8_cases = [c for c in cases if c["case_id"] in STAGE8_CASES]

    materialized = []
    for c in stage8_cases:
        cid = c["case_id"]
        slope_ratio = float(c.get("slope_ratio", 0.28))
        
        # 1. Ensure bed STL exists in production assets
        bed_path = prod_assets / f"f5_continuous_bed_profile_slope_{_slope_code(slope_ratio)}.stl"
        if not bed_path.is_file():
            # Check family assets first
            source_bed = family / f"definitions/assets/f5_continuous_bed_profile_slope_{_slope_code(slope_ratio)}.stl"
            if source_bed.is_file():
                bed_path.write_bytes(source_bed.read_bytes())
            else:
                _write_bed_stl(bed_path, slope_ratio=slope_ratio)

        # 2. Write motion file
        motion_name = f"piston_{c['physical_case_id'].replace('physical_F5_', '')}_{c['control_template']}.dat"
        motion_path = prod_defs / motion_name
        motion_info = _write_motion(motion_path, scale=float(c["amplitude_scale"]), control=str(c["control_template"]))

        # 3. Write definition XML
        def_xml = prod_defs / f"{cid}_Def.xml"
        c_copy = dict(c)
        c_copy["motion_path"] = str(motion_path)
        xml_content = build_two_phase_definition_xml(c_copy)
        def_xml.write_text(xml_content, encoding="utf-8")

        # 4. Write metadata JSON
        meta_path = prod_defs / f"{cid}.metadata.json"
        metadata = dict(c)
        metadata["motion_path"] = str(motion_path)
        metadata["definition_path"] = str(def_xml)
        metadata["metadata_path"] = str(meta_path)
        metadata["definition_sha256"] = sha256_file(def_xml)
        metadata["motion_sha256"] = motion_info["sha256"]
        metadata["bed_sha256"] = sha256_file(bed_path)
        metadata["written_at_utc"] = now_str()
        metadata["initialization_rule"] = "repair_002_two_phase_cell_centre"
        meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # 5. Emit GenCase request
        gencase_req = {
            "schema": "ds02.cpu-request.v2",
            "family_id": FAMILY_ID,
            "case_id": cid,
            "attempt_id": f"{cid}_GENCASE_03",
            "kind": "cpu",
            "cpu_task_kind": "gencase",
            "command": [
                str(gencase_bin),
                str(def_xml.with_suffix("")),
                "{attempt_root}/" + cid,
                "-save:all",
            ],
            "cwd": str(prod_defs),
            "max_wall_seconds": 300,
            "cpu_threads": 4,
            "estimated_storage_bytes": 256 * 1024 * 1024,
            "input_files": [
                str(gencase_bin),
                str(def_xml),
                str(meta_path),
                str(bed_path),
                str(motion_path),
            ],
            "worktree_root": str(REPO.parent),
            "purpose": "bounded native GenCase preflight only; no solver/GPU/model",
            "physical_parent_id": c["physical_case_id"],
            "registry_kind": "production",
            "expected_checks": {
                "mechanism": c["mechanism_id"],
                "registry_kind": "production",
                "physical_parent_id": c["physical_case_id"],
                "resolution": c["resolution"],
                "expected_dimension": 3,
                "positive_fluid_required": True,
            },
        }
        req_path = requests_dir / f"{cid}-gencase.json"
        req_path.write_text(json.dumps(gencase_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        materialized.append({
            "case_id": cid,
            "definition": str(def_xml),
            "metadata": str(meta_path),
            "gencase_request": str(req_path),
        })

    print(f"[{now_str()}] Materialized {len(materialized)} Stage 8 cases for F5.")
    return materialized


def emit_stage8_solver_requests(family_dir: Path = FAMILY_ROOT) -> list[Path]:
    family = Path(family_dir).resolve()
    requests_dir = family / "requests"
    prod_defs = family / "production/definitions"
    data_f5_dir = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
    solver_bin = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"

    reg_path = family / "case_registry.jsonl"
    cases = [json.loads(line) for line in reg_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stage8_cases = [c for c in cases if c["case_id"] in STAGE8_CASES]

    solver_requests = []
    for c in stage8_cases:
        cid = c["case_id"]
        gencase_receipts = sorted((data_f5_dir / cid).glob(f"{cid}_GENCASE_*/execution-receipt.json"))
        valid_receipt = None
        for r_path in reversed(gencase_receipts):
            r_data = json.loads(r_path.read_text())
            if r_data.get("status") == "completed" and r_data.get("returncode") == 0 and r_data.get("fluid_particles", 0) > 0:
                valid_receipt = r_path
                receipt_data = r_data
                break
        if not valid_receipt:
            print(f"[{now_str()}] GenCase not ready for {cid}, skipping solver request")
            continue

        gencase_dir = valid_receipt.parent
        prefix = gencase_dir / cid
        bi4 = prefix.with_suffix(".bi4")
        xml = prefix.with_suffix(".xml")
        def_xml = prod_defs / f"{cid}_Def.xml"
        meta_json = prod_defs / f"{cid}.metadata.json"
        motion_file = list(prod_defs.glob(f"piston_{c['physical_case_id'].replace('physical_F5_', '')}_*.dat"))[0]
        bed_file = prod_defs / "assets" / f"f5_continuous_bed_profile_slope_{_slope_code(float(c.get('slope_ratio', 0.28)))}.stl"

        input_files = [
            str(valid_receipt),
            str(bi4),
            str(xml),
            str(def_xml),
            str(meta_json),
            str(motion_file),
            str(bed_file),
        ]

        input_hashes = {p: sha256_file(Path(p)) for p in input_files}
        total_parts = receipt_data["total_particles"]
        solver_req = {
            "schema": "ds02.runner-request.v2",
            "family_id": FAMILY_ID,
            "case_id": cid,
            "attempt_id": f"{cid}_QUALIFICATION_004",
            "kind": "qualification",
            "command": [
                str(solver_bin),
                str(prefix),
                "{attempt_root}/solver",
                f"-tmax:{_q(EVENT_WINDOW_S)}",
                "-tout:0.02",
            ],
            "cwd": str(gencase_dir),
            "max_wall_seconds": 1800,
            "cpu_threads": 2,
            "estimated_storage_bytes": 15 * 1024 * 1024 * 1024,
            "estimated_peak_gpu_mib": 3072,
            "gencase_bi4": str(bi4),
            "gencase_prefix": str(prefix),
            "gencase_receipt": str(valid_receipt),
            "gencase_receipt_sha256": sha256_file(valid_receipt),
            "gencase_xml": str(xml),
            "input_files": input_files,
            "input_hashes": input_hashes,
            "worktree_root": str(REPO.parent),
            "purpose": "production GPU solver run for Stage 8",
            "physical_case_id": c["physical_case_id"],
            "physical_parent_id": c["physical_case_id"],
            "paired_background_id": c["paired_background_id"],
            "registry_kind": "production",
            "total_particles": total_parts,
            "fluid_particles": receipt_data["fluid_particles"],
        }

        req_path = requests_dir / f"{cid}-solver.json"
        req_path.write_text(json.dumps(solver_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        solver_requests.append(req_path)
        print(f"[{now_str()}] Emitted solver request: {req_path}")

    return solver_requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialize", action="store_true", help="Materialize definitions and GenCase requests")
    parser.add_argument("--emit-solver", action="store_true", help="Emit solver requests for completed GenCase")
    args = parser.parse_args()

    if args.materialize:
        materialize_stage8()
    if args.emit_solver:
        emit_stage8_solver_requests()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run a bounded mDBC preflight for the SPHERIC Test 14 Float1 route.

The existing F6 Test14 definition is intentionally a DBC route.  This script
does not mutate that route and does not run the six-case campaign.  It creates
one coarse, negative-offset case in a separate case/artifact namespace, adds
the official DualSPHysics mDBC normals geometry list, and runs GenCase plus a
very short CPU solver initialization.  The output is diagnostic evidence only:
it never treats solver return code 0 as proof of complete normal data or as
physical mDBC acceptance.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

try:
    from scripts.r3_g2_f6_test14 import (
        EXTRACTED,
        EQUILIBRIUM_BASE_Z_M,
        GENCASE,
        BIN,
        fetch_external,
        definition_text,
        write_world_stl,
    )
except ModuleNotFoundError:
    from r3_g2_f6_test14 import (
        EXTRACTED,
        EQUILIBRIUM_BASE_Z_M,
        GENCASE,
        BIN,
        fetch_external,
        definition_text,
        write_world_stl,
    )


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
CASE_ROOT = CAMPAIGN / "cases" / "r3-g2-f6-mdbc-preflight"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "r3-g2-f6-mdbc-preflight"
RUN_ROOT = CAMPAIGN / "runs" / "r3-g2-f6-mdbc-preflight"
REPORT_JSON = CAMPAIGN / "r3-g2-f6-mdbc-preflight.json"
REPORT_MD = CAMPAIGN / "R3-G2-F6-MDBC-PREFLIGHT.md"
SOLVER_CPU = BIN / "DualSPHysics5.4CPU_linux64"
BI_FILE_INFO = BIN / "BIFileInfo_linux64"
CASE_ID = "R3_F6_mdbc_preflight_neg074_coarse"
CURRENT_DEFINITION = (
    CAMPAIGN / "cases" / "r3-g2-f6-test14" /
    "R3_F6_test14_float1_neg074_coarse_Def.xml"
)

SOURCE_EVIDENCE = {
    "normal_storage": {
        "path": "vendor/official/DualSPHysics_v5.4/src/source/JPartsLoad4.cpp",
        "lines": "213-219, 265-270",
        "finding": "v5.4 rejects the old _Normals.nbi4 route, allocates BoundNor only when the general BI4 contains BoundNor, and loads/checks its size against the boundary count.",
    },
    "boundary_switch": {
        "path": "vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp",
        "lines": "700-718",
        "finding": "Boundary=1 selects DBC; Boundary=2 selects mDBC and enables UseNormals, with SlipMode parsed in the same block.",
    },
    "normal_and_ghost_initialization": {
        "path": "vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp",
        "lines": "1383-1430",
        "finding": "initial normals are saved, zero normals are counted separately for fixed/moving and floating particles, each normal is doubled for a new run, and the doubled values are saved as CfgInit_NormalsGhost.vtk; missing normals warn without necessarily changing return code.",
    },
    "cpu_mdbc_kernel": {
        "path": "vendor/official/DualSPHysics_v5.4/src/source/JSphCpu_mdbc.cpp",
        "lines": "41-50, 107-138, 255-286",
        "finding": "CPU mDBC skips zero BoundNor entries and forms the ghost position as boundary position plus BoundNor before the ghost-fluid interaction.",
    },
    "official_floating_pattern": {
        "path": "vendor/official/DualSPHysics_v5.4/examples/mdbc/08_FloatingWaves/CaseFloatingWaves_Def.xml",
        "lines": "26-49, 93-97, 131",
        "finding": "official floating mDBC uses GeometryForNormals, shapeout file=hdp, a mainlist runlist, norgeometry [CaseName]_hdp_Actual.vtk, and Boundary=2.",
    },
    "official_stl_floating_pattern": {
        "path": "vendor/official/DualSPHysics_v5.4/examples/mdbc/09_FloatingDuck/CaseDuckling_Def.xml",
        "lines": "26-45, 82-88, 93-95",
        "finding": "official STL floating mDBC applies actual|bound to a floating STL in GeometryForNormals, writes hdp geometry, and enables Boundary=2 with Norgeometry.",
    },
}


def preflight_record() -> dict:
    """Return the one deliberately short and coarse test record."""
    return {
        "case_id": CASE_ID,
        "offset_name": "neg074",
        "offset_m": -0.074,
        "experiment": "Fl1-0p074.txt",
        "level": "coarse",
        "dp": 0.060,
        "gpu": None,
        # This is long enough to initialize and take a few CPU steps, but is
        # far too short to support any physical conclusion.
        "tmax": 0.08,
        "tout": 0.04,
    }


def cpu_environment() -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    # The preflight intentionally uses the CPU binary and leaves no accidental
    # CUDA device visible to a child process.
    value["CUDA_VISIBLE_DEVICES"] = ""
    return value


def run_nvidia_smi(path: Path) -> dict:
    """Capture the inventory before preparing or running any solver process."""
    command = [
        "nvidia-smi",
        "--query-gpu=index,uuid,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)
    path.write_text(proc.stdout)
    rows = []
    for line in proc.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        try:
            rows.append({
                "index": int(fields[0]),
                "uuid": fields[1],
                "memory_used_mib": int(fields[2]),
                "memory_total_mib": int(fields[3]),
                "utilization_percent": int(fields[4]),
            })
        except ValueError:
            continue
    return {
        "command": " ".join(command),
        "return_code": proc.returncode,
        "rows": rows,
        "gpu_indices_used": [],
        "gpu_uuids_used": [],
        "policy": "CPU-only; physical GPU 0-3 prohibited and no GPU was launched",
    }


def current_f6_definition(record: dict) -> str:
    """Build the unmodified DBC definition used as the switch baseline."""
    return definition_text(record)


def mdbc_definition_text(record: dict) -> str:
    """Add the v5.4 official normals path to the isolated F6 definition."""
    text = definition_text(record)
    old_stl = (
        f"../../artifacts/r3-g2-f6-test14/{record['case_id']}/generated/"
        "Float1_world.stl"
    )
    new_stl = (
        f"../../artifacts/r3-g2-f6-mdbc-preflight/{record['case_id']}/generated/"
        "Float1_world.stl"
    )
    if old_stl not in text:
        raise ValueError("base Test14 definition did not contain expected STL path")
    text = text.replace(old_stl, new_stl)

    normal_list = f'''        <list name="GeometryForNormals">
          <setactive drawpoints="0" drawshapes="1" />
          <setshapemode>actual | bound</setshapemode>
          <!-- Tank fluid is inside the cylinder, so invert its outward mesh normals. -->
          <setnormalinvert invert="true" />
          <setmkbound mk="0" />
          <drawcylinder radius="2.0" mask="2">
            <point x="0" y="0" z="0" />
            <point x="0" y="0" z="1.10" />
            <layers vdp="-0.5" />
          </drawcylinder>
          <!-- Float1 fluid is outside the closed STL surface. -->
          <setnormalinvert invert="false" />
          <setmkbound mk="10" />
          <drawfilestl file="{new_stl}" autofill="true" advanced="true" />
          <shapeout file="hdp" />
          <resetdraw />
        </list>
'''
    marker = "      <commands>\n        <mainlist>"
    if marker not in text:
        raise ValueError("base Test14 definition did not contain mainlist marker")
    text = text.replace(
        marker,
        "      <commands>\n" + normal_list +
        "        <mainlist>\n          <runlist name=\"GeometryForNormals\" />",
        1,
    )
    text = text.replace(
        '<parameter key="Boundary" value="1" />',
        '<parameter key="Boundary" value="2" />',
        1,
    )
    text = text.replace(
        '    </floatings>\n  </casedef>',
        '''    </floatings>
    <normals active="true">
      <norgeometry comment="Define initial configuration of normals before applying other configurations">
        <geometryfile file="[CaseName]_hdp_Actual.vtk" />
        <distanceh v="2.0" />
      </norgeometry>
    </normals>
  </casedef>''',
        1,
    )
    # Keep the explicit slip mode visible in the effective XML rather than
    # relying on a version-dependent default.
    text = text.replace(
        '<parameter key="Boundary" value="2" />',
        '<parameter key="Boundary" value="2" />\n'
        '      <parameter key="SlipMode" value="1" />',
        1,
    )
    return text


def xml_switch_audit(current_text: str, candidate_text: str) -> dict:
    """Check the requested/effective XML switch without running a solver."""
    current = ET.fromstring(current_text)
    candidate = ET.fromstring(candidate_text)

    def boundary(root: ET.Element) -> dict:
        item = root.find(".//parameter[@key='Boundary']")
        if item is None:
            return {"value": None, "name": "missing"}
        value = item.get("value")
        return {"value": int(value) if value is not None else None,
                "name": {"1": "DBC", "2": "mDBC"}.get(value, "unknown")}

    def command_audit(root: ET.Element) -> dict:
        commands = root.find(".//geometry/commands")
        named = commands.find("./list[@name='GeometryForNormals']") if commands is not None else None
        runlist = commands.find(".//mainlist/runlist[@name='GeometryForNormals']") if commands is not None else None
        shapeout = named.find("./shapeout[@file='hdp']") if named is not None else None
        return {
            "normals_list_present": named is not None,
            "normals_list_run_from_main": runlist is not None,
            "normals_shapeout_hdp": shapeout is not None,
            "normals_shapeout_count": len(named.findall("./shapeout")) if named is not None else 0,
            "normal_stl_present": (
                named.find("./drawfilestl") is not None if named is not None else False
            ),
        }

    def normals_audit(root: ET.Element) -> dict:
        normals = root.find(".//normals")
        norgeometry = normals.find("./norgeometry") if normals is not None else None
        geometryfile = norgeometry.find("./geometryfile") if norgeometry is not None else None
        distanceh = norgeometry.find("./distanceh") if norgeometry is not None else None
        return {
            "section_present": normals is not None,
            "active": normals.get("active") if normals is not None else None,
            "norgeometry_present": norgeometry is not None,
            "geometryfile": geometryfile.get("file") if geometryfile is not None else None,
            "distanceh": distanceh.get("v") if distanceh is not None else None,
        }

    candidate_commands = command_audit(candidate)
    candidate_normals = normals_audit(candidate)
    legal = (
        boundary(candidate)["value"] == 2 and
        candidate_commands["normals_list_present"] and
        candidate_commands["normals_list_run_from_main"] and
        candidate_commands["normals_shapeout_hdp"] and
        candidate_commands["normal_stl_present"] and
        candidate_normals["section_present"] and
        candidate_normals["active"] == "true" and
        candidate_normals["norgeometry_present"] and
        candidate_normals["geometryfile"] == "[CaseName]_hdp_Actual.vtk"
    )
    return {
        "current_f6": {
            "requested_boundary": boundary(current),
            "geometry_commands": command_audit(current),
            "normals": normals_audit(current),
            "legal_mdbc_switch": False,
            "blocker": "Boundary=1 (DBC) and no normals geometry/section",
        },
        "candidate": {
            "requested_boundary": boundary(candidate),
            "geometry_commands": candidate_commands,
            "normals": candidate_normals,
            "legal_mdbc_switch": legal,
            "blocker": None if legal else "candidate XML failed required mDBC structure checks",
        },
    }


def parse_gencase_normals(log: str) -> dict:
    nonzero = re.search(
        r"Non-zero particle normals:\s*([\d,]+)/([\d,]+)", log
    )
    zero = re.search(
        r"Final zero normals:\s*([\d,]+)/([\d,]+)\s*\(([\d.]+)%\)", log
    )
    geometry = re.search(
        r"FileShapes>\s*((?:[^\s]+_)?hdp_Actual\.vtk)\s+shapes:([\d,]+)\s+points:([\d,]+)",
        log,
    )
    return {
        "normal_computation_started": "Computing normals" in log,
        "normal_geometry_file": geometry.group(1) if geometry else None,
        "normal_geometry_shape_count": int(geometry.group(2).replace(",", "")) if geometry else None,
        "normal_geometry_point_count": int(geometry.group(3).replace(",", "")) if geometry else None,
        "nonzero_count": int(nonzero.group(1).replace(",", "")) if nonzero else None,
        "boundary_count": int(nonzero.group(2).replace(",", "")) if nonzero else None,
        "zero_count": int(zero.group(1).replace(",", "")) if zero else None,
        "zero_denominator": int(zero.group(2).replace(",", "")) if zero else None,
        "zero_percent": float(zero.group(3)) if zero else None,
        "warning_present": "boundary particles without normal data" in log,
    }


def parse_solver_normals(log: str) -> dict:
    fixed = re.search(
        r"There are\s+([\d,]+)\s+of\s+([\d,]+)\s+fixed or moving boundary particles without normal data",
        log,
    )
    floating = re.search(
        r"There are\s+([\d,]+)\s+of\s+([\d,]+)\s+floating particles without normal data",
        log,
    )
    case_float = re.search(r"^CaseNfloat=([\d,]+)", log, re.MULTILINE)
    boundary_match = re.search(r'^Boundary="([^"]+)"', log, re.MULTILINE)
    floating_zero_count = int(floating.group(1).replace(",", "")) if floating else None
    floating_count = int(floating.group(2).replace(",", "")) if floating else None
    # ConfigBoundNormals emits the floating warning iff nerrft>0. Preserve
    # that inference explicitly when the solver reached that block and a
    # floating body exists, instead of treating the absent warning as missing.
    if (
        floating is None and case_float
        and int(case_float.group(1).replace(",", "")) > 0
        and "CfgInit_NormalsGhost.vtk" in log
    ):
        floating_zero_count = 0
        floating_count = int(case_float.group(1).replace(",", ""))
    return {
        "effective_boundary": boundary_match.group(1) if boundary_match else None,
        "fixed_or_moving_zero_count": int(fixed.group(1).replace(",", "")) if fixed else None,
        "fixed_or_moving_count": int(fixed.group(2).replace(",", "")) if fixed else None,
        "floating_zero_count": floating_zero_count,
        "floating_count": floating_count,
        "normal_warning_present": fixed is not None or floating is not None,
        "ghost_path_reported": "CfgInit_NormalsGhost.vtk" in log,
        "chrono_collision_warning": "their collisions should be solved using Chrono" in log,
        "solver_finished_code_0": "Finished execution (code=0)" in log,
    }


def generated_particle_counts(prefix: Path) -> dict:
    root = ET.parse(prefix.with_suffix(".xml")).getroot()
    particles = root.find(".//particles")
    floating = root.find(".//particles/floating")
    fluid = root.find(".//particles/fluid")
    if particles is None or floating is None or fluid is None:
        raise ValueError("generated XML missing particle blocks")
    return {
        "total_particles": int(particles.get("np")),
        "boundary_particles": int(particles.get("nb")),
        "fixed_particles": int(particles.get("nbf")),
        "floating_particles": int(floating.get("count")),
        "fluid_particles": int(fluid.get("count")),
        "boundnor_array_expected": int(particles.get("nb")),
    }


def run_bifileinfo(prefix: Path, generated: Path, counts: dict) -> dict:
    """Record that GenCase stored BoundNor in the general BI4 input.

    ``-svarrays:1`` is intentionally used for this coarse case so the
    preflight can count zero vectors directly from the serialized array, not
    merely infer coverage from a solver warning.
    """
    if not BI_FILE_INFO.is_file():
        return {"available": False, "return_code": None, "boundnor_array_count": None}
    proc = subprocess.run(
        [str(BI_FILE_INFO), prefix.name + ".bi4", "-svarrays:1"],
        cwd=generated,
        env=cpu_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (generated / "bifileinfo.stdout.log").write_text(proc.stdout)
    summary = generated / (prefix.name + "_.xml")
    count = None
    nonzero = zero = fixed_zero = floating_zero = None
    if summary.is_file():
        root = ET.parse(summary).getroot()
        array = root.find(".//array_float3[@name='BoundNor']")
        count = int(array.get("count")) if array is not None else None
        if array is not None and list(array):
            values = list(array)
            nonzero = sum(
                any(float(item.get(axis, "0")) != 0.0 for axis in ("x", "y", "z"))
                for item in values
            )
            zero = len(values) - nonzero
            fixed_count = int(counts.get("fixed_particles", 0))
            fixed_zero = sum(
                not any(float(item.get(axis, "0")) != 0.0 for axis in ("x", "y", "z"))
                for item in values[:fixed_count]
            )
            floating_zero = zero - fixed_zero
    return {
        "available": True,
        "return_code": proc.returncode,
        "summary_file": str(summary),
        "boundnor_array_count": count,
        "boundnor_array_present": count is not None,
        "boundnor_nonzero_count": nonzero,
        "boundnor_zero_count": zero,
        "boundnor_fixed_zero_count": fixed_zero,
        "boundnor_floating_zero_count": floating_zero,
    }


def vtk_point_count(path: Path) -> int | None:
    if not path.is_file():
        return None
    match = re.search(br"POINTS\s+(\d+)\s+(?:float|double)\r?\n", path.read_bytes())
    return int(match.group(1)) if match else None


def run_preflight(record: dict, nvidia: dict) -> dict:
    """Materialize, generate, and execute the one CPU-only preflight."""
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    generated = ARTIFACT_ROOT / record["case_id"] / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    run_dir = RUN_ROOT / record["case_id"]
    run_dir.mkdir(parents=True, exist_ok=True)

    current_text = current_f6_definition(record)
    candidate_text = mdbc_definition_text(record)
    definition = CASE_ROOT / f"{record['case_id']}_Def.xml"
    definition.write_text(candidate_text)

    stl = generated / "Float1_world.stl"
    transform = write_world_stl(
        EXTRACTED / "Float1.STL", stl,
        EQUILIBRIUM_BASE_Z_M + record["offset_m"],
    )
    prefix = generated / record["case_id"]
    gencase_proc = subprocess.run(
        [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
        cwd=CASE_ROOT,
        env=cpu_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=180,
    )
    gencase_log = generated / "gencase.stdout.log"
    gencase_log.write_text(gencase_proc.stdout)
    gencase_normals = parse_gencase_normals(gencase_proc.stdout)
    counts = generated_particle_counts(prefix) if prefix.with_suffix(".xml").is_file() else {}
    bifileinfo = run_bifileinfo(prefix, generated, counts) if prefix.with_suffix(".bi4").is_file() else {
        "available": True, "return_code": None, "boundnor_array_count": None,
        "boundnor_array_present": False,
    }

    solver_proc = None
    solver_log = ""
    solver_timeout = False
    if gencase_proc.returncode == 0 and prefix.with_suffix(".xml").is_file():
        solver_proc = subprocess.run(
            [str(SOLVER_CPU), str(prefix), str(run_dir)],
            cwd=generated,
            env=cpu_environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=180,
        )
        solver_log = solver_proc.stdout
        (run_dir / "solver.stdout.log").write_text(solver_log)
        # DualSPHysics duplicates the complete log in Run.out; include it if
        # stdout was short so effective configuration parsing remains robust.
        run_out = run_dir / "Run.out"
        if run_out.is_file():
            solver_log += "\n" + run_out.read_text(errors="replace")
    solver_normals = parse_solver_normals(solver_log)
    ghost = {
        "boundary_normals_vtk": str(run_dir / "CfgInit_Normals.vtk"),
        "ghost_normals_vtk": str(run_dir / "CfgInit_NormalsGhost.vtk"),
        "boundary_normals_vtk_present": (run_dir / "CfgInit_Normals.vtk").is_file(),
        "ghost_normals_vtk_present": (run_dir / "CfgInit_NormalsGhost.vtk").is_file(),
        "boundary_normals_point_count": vtk_point_count(run_dir / "CfgInit_Normals.vtk"),
        "ghost_normals_point_count": vtk_point_count(run_dir / "CfgInit_NormalsGhost.vtk"),
    }
    return {
        "record": record,
        "resource_policy": nvidia,
        "requested_boundary": "mDBC",
        "effective_boundary": solver_normals["effective_boundary"],
        "commandline_boundary_override": None,
        "definition": {
            "candidate_file": str(definition),
            "current_dbc_file": str(CURRENT_DEFINITION),
            "stl_file": str(stl),
            "xml_switch": xml_switch_audit(current_text, candidate_text),
        },
        "transform": transform,
        "gencase": {
            "command": [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
            "return_code": gencase_proc.returncode,
            "log_file": str(gencase_log),
            "normal_data": gencase_normals,
            "generated_counts": counts,
            "bi_file_info": bifileinfo,
        },
        "solver": {
            "device": "CPU",
            "command": [str(SOLVER_CPU), str(prefix), str(run_dir)],
            "return_code": solver_proc.returncode if solver_proc is not None else None,
            "timeout": solver_timeout,
            "log_file": str(run_dir / "solver.stdout.log") if solver_proc is not None else None,
            "normal_data": solver_normals,
            "ghost_artifacts": ghost,
        },
        "acceptance_status": "diagnostic_only_not_physical_acceptance",
        "scientific_acceptance": "not_accepted_mdbc_preflight",
        "mdbc_claim": False,
        "source_evidence": SOURCE_EVIDENCE,
    }


def add_conclusions(report: dict) -> dict:
    gencase = report["gencase"]
    solver = report["solver"]
    gnorm = gencase["normal_data"]
    snorm = solver["normal_data"]
    zeros = gnorm.get("zero_count")
    boundary = gencase.get("generated_counts", {}).get("boundary_particles")
    direct_zero = gencase["bi_file_info"].get("boundnor_zero_count")
    normal_complete = (
        gencase["return_code"] == 0 and
        zeros == 0 and
        direct_zero == 0 and
        snorm.get("fixed_or_moving_zero_count", 0) == 0 and
        snorm.get("floating_zero_count", 0) == 0 and
        solver["ghost_artifacts"]["ghost_normals_vtk_present"] and
        solver["return_code"] == 0
    )
    blockers = [
        "This is a short coarse CPU preflight, not a Test14 physical acceptance run.",
        "No DBC-vs-mDBC trajectory or buoyancy comparison was performed.",
    ]
    if report["definition"]["xml_switch"]["current_f6"]["legal_mdbc_switch"] is False:
        blockers.append("The existing F6/Test14 XML remains DBC (Boundary=1) with no normals section.")
    if zeros not in (None, 0):
        blockers.append(f"GenCase reported {zeros} zero boundary normals; normal completeness is not established.")
    if direct_zero not in (None, 0) and direct_zero != zeros:
        blockers.append(f"Serialized BoundNor inspection found {direct_zero} zero vectors (log reported {zeros}).")
    if snorm.get("fixed_or_moving_zero_count") not in (None, 0):
        blockers.append(
            f"Solver reported {snorm['fixed_or_moving_zero_count']} fixed/moving particles without normals."
        )
    if snorm.get("floating_zero_count") not in (None, 0):
        blockers.append(
            f"Solver reported {snorm['floating_zero_count']} floating particles without normals."
        )
    if snorm.get("chrono_collision_warning"):
        blockers.append("Solver warns floating mDBC collisions should use Chrono (RigidAlgorithm=3).")
    if solver["return_code"] != 0:
        blockers.append(f"CPU solver return code was {solver['return_code']}, not 0.")
    report["normal_completeness"] = {
        "complete_for_all_boundary_particles": normal_complete,
        "gencase_zero_count": zeros,
        "gencase_boundary_count": boundary,
        "solver_fixed_or_moving_zero_count": snorm.get("fixed_or_moving_zero_count"),
        "solver_floating_zero_count": snorm.get("floating_zero_count"),
        "boundnor_array_count": gencase["bi_file_info"].get("boundnor_array_count"),
        "boundnor_direct_zero_count": direct_zero,
        "boundnor_direct_fixed_zero_count": gencase["bi_file_info"].get("boundnor_fixed_zero_count"),
        "boundnor_direct_floating_zero_count": gencase["bi_file_info"].get("boundnor_floating_zero_count"),
        "ghost_vector_artifact_present": solver["ghost_artifacts"]["ghost_normals_vtk_present"],
    }
    report["open_blockers"] = blockers
    report["conclusion"] = {
        "physical_acceptance_claim": False,
        "mdbc_claim": False,
        "preflight_result": (
            "mDBC initialization path reached; inspect normal completeness and blockers"
            if solver["return_code"] == 0 else "mDBC preflight did not complete"
        ),
        "normal_completeness": "complete" if normal_complete else "incomplete_or_unverified",
    }
    return report


def markdown_report(report: dict) -> str:
    record = report["record"]
    g = report["gencase"]
    s = report["solver"]
    gn = g["normal_data"]
    sn = s["normal_data"]
    switch = report["definition"]["xml_switch"]
    lines = [
        "# R3 G2 F6 mDBC preflight",
        "",
        "This is a diagnostic preflight only. It does not accept mDBC physics and does not replace the existing DBC Test14 route.",
        "",
        "## Result",
        "",
        f"- Case: `{record['case_id']}`; Float1 offset `{record['offset_m']:+.3f} m`; dp `{record['dp']:.3f} m`; `TimeMax={record['tmax']}` s.",
        f"- Requested boundary: **mDBC** (`Boundary=2`); effective solver boundary: **{report['effective_boundary'] or 'not observed'}**.",
        f"- GenCase return code: `{g['return_code']}`; CPU solver return code: `{s['return_code']}`.",
        f"- GenCase normals: `{gn.get('nonzero_count')}` non-zero / `{gn.get('boundary_count')}` boundary; zero `{gn.get('zero_count')}` (`{gn.get('zero_percent')}%`).",
        f"- Serialized `BoundNor` inspection: zero `{g['bi_file_info'].get('boundnor_zero_count')}`; fixed zero `{g['bi_file_info'].get('boundnor_fixed_zero_count')}`; floating zero `{g['bi_file_info'].get('boundnor_floating_zero_count')}`.",
        f"- Solver zero normals: fixed/moving `{sn.get('fixed_or_moving_zero_count')}`; floating `{sn.get('floating_zero_count')}`.",
        f"- Ghost path: `CfgInit_NormalsGhost.vtk` present = `{s['ghost_artifacts']['ghost_normals_vtk_present']}`; point count = `{s['ghost_artifacts']['ghost_normals_point_count']}`.",
        f"- Normal completeness: **{report['normal_completeness']['complete_for_all_boundary_particles']}**.",
        "",
        "## XML legality",
        "",
        f"- Existing F6/Test14 XML: requested `{switch['current_f6']['requested_boundary']['name']}` (`Boundary={switch['current_f6']['requested_boundary']['value']}`), normals section present = `{switch['current_f6']['normals']['section_present']}`; direct mDBC switch legal = **{switch['current_f6']['legal_mdbc_switch']}**.",
        f"- Isolated candidate: requested `{switch['candidate']['requested_boundary']['name']}` (`Boundary={switch['candidate']['requested_boundary']['value']}`), normals list/runlist/hdp geometry = `{switch['candidate']['geometry_commands']['normals_list_present']}`/`{switch['candidate']['geometry_commands']['normals_list_run_from_main']}`/`{switch['candidate']['geometry_commands']['normals_shapeout_hdp']}`; legal structure = **{switch['candidate']['legal_mdbc_switch']}**.",
        "",
        "## Real v5.4 data path",
        "",
        "- GenCase emits a `BoundNor` float3 array in the general input `.bi4`; the generated XML references `[CaseName]_hdp_Actual.vtk` as the normal geometry source.",
        "- The solver loads `BoundNor`; for a new run it doubles the boundary-to-limit vector to form the boundary-to-ghost vector and writes both `CfgInit_Normals.vtk` and `CfgInit_NormalsGhost.vtk`.",
        "- A solver `Finished execution (code=0)` is not sufficient: zero-normal warnings remain a blocker for complete mDBC coverage.",
        '- The isolated candidate follows the official v5.4 floating mDBC pattern (`GeometryForNormals` → `shapeout file="hdp"` → `norgeometry` → `Boundary=2`) and uses the CPU solver, so no GPU index or UUID was used.',
        "- Source evidence is pinned to the vendored v5.4 files in the JSON report: `JPartsLoad4.cpp` (BoundNor load), `JSph.cpp` (Boundary/normal initialization), `JSphCpu_mdbc.cpp` (ghost position), and the official FloatingWaves/FloatingDuck XML examples.",
        "",
        "## Blockers / non-claims",
        "",
    ]
    lines.extend(f"- {item}" for item in report["open_blockers"])
    lines += [
        "",
        "Evidence files:",
        "",
        f"- Candidate XML: `{report['definition']['candidate_file']}`",
        f"- GenCase log: `{g['log_file']}`",
        f"- Solver log: `{s['log_file']}`",
        f"- JSON report: `{REPORT_JSON}`",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path, default=REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=REPORT_MD)
    parser.add_argument("--static-only", action="store_true",
                        help="write XML switch audit without GenCase or solver")
    args = parser.parse_args()

    # This must be the first external command in the script, before asset
    # acquisition or any solver launch, to make GPU policy auditable.
    snapshot_path = ARTIFACT_ROOT / "nvidia-smi.snapshot.txt"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    nvidia = run_nvidia_smi(snapshot_path)
    record = preflight_record()
    fetch_external()
    current_text = current_f6_definition(record)
    candidate_text = mdbc_definition_text(record)
    if args.static_only:
        report = {
            "schema_version": 1,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "resource_policy": nvidia,
            "record": record,
            "definition": {"xml_switch": xml_switch_audit(current_text, candidate_text)},
            "acceptance_status": "static_diagnostic_only",
            "scientific_acceptance": "not_accepted_mdbc_preflight",
            "mdbc_claim": False,
            "source_evidence": SOURCE_EVIDENCE,
            "open_blockers": ["No solver was run (--static-only)."],
        }
    else:
        report = run_preflight(record, nvidia)
        report["schema_version"] = 1
        report["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        report = add_conclusions(report)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, indent=2) + "\n")
    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_md.write_text(markdown_report(report) if not args.static_only else (
        "# R3 G2 F6 mDBC static preflight\n\n" +
        json.dumps(report["definition"]["xml_switch"], indent=2) + "\n"
    ))
    print(json.dumps({
        "report_json": str(args.report_json),
        "report_md": str(args.report_md),
        "gencase_return_code": report.get("gencase", {}).get("return_code"),
        "solver_return_code": report.get("solver", {}).get("return_code"),
        "effective_boundary": report.get("effective_boundary"),
        "normal_completeness": report.get("normal_completeness", {}).get("complete_for_all_boundary_particles"),
    }, indent=2))


if __name__ == "__main__":
    main()

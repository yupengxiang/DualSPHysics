#!/usr/bin/env python3
"""Build the candidate-only R3 F6 E1 fixed-body hydrostatic no-run report.

This audit intentionally does not invoke GenCase, DualSPHysics, FloatingInfo,
or any GPU solver.  It consumes the already materialised F6 Test14 DBC and
mDBC preflight evidence, checks the XML semantics needed for a fixed body, and
stops before the six-case matrix because the mDBC geometry gate is not proven.
All generated files stay in this directory.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[4]
LAB = ROOT / "lagrangian-fluid-lab"
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def parameter_map(root: ET.Element) -> dict[str, str]:
    return {
        item.get("key"): item.get("value")
        for item in root.findall(".//parameter")
        if item.get("key")
    }


def attrs(node: ET.Element | None, names: tuple[str, ...]) -> dict[str, str | None]:
    return {name: node.get(name) if node is not None else None for name in names}


def xml_audit(path: Path) -> dict:
    if not path.is_file():
        return {"path": rel(path), "exists": False}
    root = ET.parse(path).getroot()
    params = parameter_map(root)
    floating = root.find(".//floatings/floating")
    commands = root.find(".//geometry/commands")
    cylinder = commands.find(".//drawcylinder") if commands is not None else None
    fillbox = commands.find(".//fillbox") if commands is not None else None
    damping = root.find(".//dampingcylinder")
    normals = root.find(".//normals")
    norgeometry = normals.find("./norgeometry") if normals is not None else None
    normal_list = (
        commands.find("./list[@name='GeometryForNormals']")
        if commands is not None else None
    )
    runlist = (
        commands.find(".//mainlist/runlist[@name='GeometryForNormals']")
        if commands is not None else None
    )
    gauges = root.find(".//gauges")
    force_gauges = root.findall(".//gauges/force")
    return {
        "path": rel(path),
        "exists": True,
        "sha256": sha256(path),
        "boundary": {
            "value": int(params["Boundary"]) if params.get("Boundary") else None,
            "name": {"1": "DBC", "2": "mDBC"}.get(params.get("Boundary"), "unknown"),
        },
        "rigid_algorithm": params.get("RigidAlgorithm"),
        "time_max_s": float(params["TimeMax"]) if params.get("TimeMax") else None,
        "time_out_s": float(params["TimeOut"]) if params.get("TimeOut") else None,
        "damping": {
            "active": damping.get("active") if damping is not None else None,
            "limitmin_radius_m": (
                damping.find("./limitmin").get("radius")
                if damping is not None and damping.find("./limitmin") is not None else None
            ),
            "limitmax_radius_m": (
                damping.find("./limitmax").get("radius")
                if damping is not None and damping.find("./limitmax") is not None else None
            ),
        },
        "tank_geometry": {
            "radius_m": cylinder.get("radius") if cylinder is not None else None,
            "mask": cylinder.get("mask") if cylinder is not None else None,
            "height_m": (
                cylinder.find("./point[2]").get("z")
                if cylinder is not None and cylinder.find("./point[2]") is not None else None
            ),
            "fluid_fill_box": attrs(fillbox, ("x", "y", "z")),
        },
        "floating_body": {
            "section_present": floating is not None,
            "mkbound": floating.get("mkbound") if floating is not None else None,
            "massbody_kg": (
                float(floating.find("./massbody").get("value"))
                if floating is not None and floating.find("./massbody") is not None else None
            ),
            "center_m": attrs(
                floating.find("./center") if floating is not None else None,
                ("x", "y", "z"),
            ),
            "translation_dof": attrs(
                floating.find("./translationDOF") if floating is not None else None,
                ("x", "y", "z"),
            ),
            "rotation_dof": attrs(
                floating.find("./rotationDOF") if floating is not None else None,
                ("x", "y", "z"),
            ),
            "fixed_body": floating is None,
        },
        "mdbc_normals": {
            "section_present": normals is not None,
            "active": normals.get("active") if normals is not None else None,
            "norgeometry_present": norgeometry is not None,
            "geometryfile": (
                norgeometry.find("./geometryfile").get("file")
                if norgeometry is not None and norgeometry.find("./geometryfile") is not None else None
            ),
            "distanceh": (
                norgeometry.find("./distanceh").get("v")
                if norgeometry is not None and norgeometry.find("./distanceh") is not None else None
            ),
            "geometry_for_normals_list": normal_list is not None,
            "geometry_for_normals_runlist": runlist is not None,
            "geometry_for_normals_shapeout_hdp": (
                normal_list.find("./shapeout[@file='hdp']") is not None
                if normal_list is not None else False
            ),
        },
        "force_gauge": {
            "gauges_section_present": gauges is not None,
            "force_gauge_count": len(force_gauges),
            "targets": [node.find("./target").get("mkbound") for node in force_gauges if node.find("./target") is not None],
        },
    }


def gpu_preflight() -> dict:
    command = [
        "nvidia-smi", "-i", "4,5,6,7",
        "--query-gpu=index,uuid,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)
    snapshot = OUT / "gpu-preflight.txt"
    snapshot.write_text(proc.stdout)
    rows = []
    for line in proc.stdout.splitlines():
        fields = [item.strip() for item in line.split(",")]
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
        "snapshot": rel(snapshot),
        "rows": rows,
        "gpu_indices_used": [],
        "gpu_uuids_used": [],
        "allowed_gpu_indices": [4, 5, 6, 7],
        "forbidden_gpu_indices": [0, 1, 2, 3],
        "solver_launched": False,
        "policy": "no-run preflight; no CUDA solver process was started",
    }


def log_excerpt(path: Path, patterns: tuple[str, ...]) -> dict:
    item = {
        "path": rel(path),
        "exists": path.is_file(),
        "sha256": sha256(path),
        "excerpts": [],
    }
    if not path.is_file():
        return item
    lines = path.read_text(errors="replace").splitlines()
    for line in lines:
        if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in patterns):
            item["excerpts"].append(line.strip())
    return item


def find_latest_dbc_log() -> Path:
    root = CAMPAIGN / "runs" / "R3_F6_test14_float1_neg074_coarse" / "attempts"
    logs = sorted(root.glob("*.complete/process.stdout.log"))
    return logs[-1] if logs else root / "missing-process.stdout.log"


def plan_manifest() -> dict:
    nominal_base = 0.6117617850739425
    heights = (
        ("nominal", 0.0),
        ("deeper", -0.05),
        ("shallower", 0.05),
    )
    entries = []
    for height_id, delta in heights:
        for boundary in ("DBC", "mDBC"):
            entries.append({
                "case_id": f"R3_F6_E1_fixed_{height_id}_{boundary.lower()}",
                "tier": "primary",
                "height_id": height_id,
                "height_delta_from_nominal_m": delta,
                "provisional_body_base_z_m": nominal_base + delta,
                "boundary": boundary,
                "body_mode": "fixed",
                "chrono": False,
                "status": "blocked_preflight",
                "execute": False,
                "gpu": None,
                "result": None,
                "acceptance": "not_run_not_accepted",
            })
    return {
        "schema_version": 1,
        "manifest_id": "R3-F6-E1-fixed-submerged-hydrostatic",
        "execution_status": "blocked_preflight_no_run",
        "acceptance_status": "not_run_not_accepted",
        "planned_primary_case_count": len(entries),
        "executed_case_count": 0,
        "accepted_case_count": 0,
        "matrix_cap_cases": 9,
        "fine_extension": {
            "max_additional_cases": 3,
            "unlocked": False,
            "reason": "mDBC E0 normal/ghost geometry gate is not proven",
        },
        "heights": [
            {
                "height_id": height_id,
                "waterline_z_m": 0.8,
                "nominal_base_z_m": nominal_base,
                "delta_from_nominal_m": delta,
                "provisional_only": True,
            }
            for height_id, delta in heights
        ],
        "fixed_controls": {
            "gravity_m_s2": -9.81,
            "water_density_kg_m3": 1000.0,
            "water_depth_m": 0.8,
            "tank_radius_m": 2.0,
            "damping_start_radius_m": 1.4,
            "damping_end_radius_m": 2.0,
            "simulation_domain_zmax_m": 1.4,
            "chronology": "disabled/not configured; fixed body must not use Chrono",
            "boundary_method_is_only_sweep_variable": True,
        },
        "entries": entries,
    }


def write_manifest(manifest: dict) -> None:
    (OUT / "run-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def raw_summary() -> dict:
    dbc_log = find_latest_dbc_log()
    mdbc_gencase = (
        CAMPAIGN / "artifacts" / "r3-g2-f6-mdbc-preflight" /
        "R3_F6_mdbc_preflight_neg074_coarse" / "generated" / "gencase.stdout.log"
    )
    mdbc_solver = (
        CAMPAIGN / "runs" / "r3-g2-f6-mdbc-preflight" /
        "R3_F6_mdbc_preflight_neg074_coarse" / "solver.stdout.log"
    )
    zero_gencase = (
        CAMPAIGN / "artifacts" / "r3-g2-f6-mdbc-zero-normal-preflight" /
        "R3_F6_mdbc_zero_normal_baseline_baseline_combined_mask2_d2_invert" /
        "generated" / "gencase.stdout.log"
    )
    repair_gencase = (
        CAMPAIGN / "artifacts" / "r3-g2-f6-mdbc-zero-normal-preflight" /
        "R3_F6_mdbc_zero_normal_baseline_combined_tank_radius_minus030" /
        "generated" / "gencase.stdout.log"
    )
    patterns = (
        r"Boundary=",
        r"RigidAlgorithm=",
        r"CaseN(bound|p|fixed|float|fluid)=",
        r"FileShapes>",
        r"Non-zero particle normals:",
        r"Final zero normals:",
        r"without normal data",
        r"Chrono",
        r"Excluded particles",
        r"Steps of simulation",
        r"Simulation finished",
        r"Finished execution",
    )
    return {
        "schema_version": 1,
        "summary_status": "historical_reference_only_no_new_run_logs",
        "new_run_logs": [],
        "historical_logs": [
            {
                "label": "existing DBC Test14 neg074 coarse latest attempt",
                "device": "GPU 4 (historical run; not this task)",
                **log_excerpt(dbc_log, patterns),
            },
            {
                "label": "existing mDBC preflight GenCase",
                "device": "CPU",
                **log_excerpt(mdbc_gencase, patterns),
            },
            {
                "label": "existing mDBC preflight CPU solver",
                "device": "CPU",
                **log_excerpt(mdbc_solver, patterns),
            },
            {
                "label": "existing mDBC zero-normal baseline GenCase",
                "device": "CPU",
                **log_excerpt(zero_gencase, patterns),
            },
            {
                "label": "existing candidate tank-radius -0.030 m GenCase",
                "device": "CPU",
                **log_excerpt(repair_gencase, patterns),
            },
        ],
        "interpretation": (
            "The historical mDBC baseline initializes and exits code 0 but has "
            "792 fixed/moving zero normals; the radius-offset candidate removes "
            "the zeros only after changing tank normal geometry and remains a "
            "diagnostic, not a repair."
        ),
    }


def markdown(report: dict, manifest: dict, raw: dict) -> str:
    gate = report["geometry_gate"]
    inputs = report["inputs"]
    lines = [
        "# R3 F6 E1 固定浸没体静水力：no-run feasibility report",
        "",
        "> 状态：**blocked_preflight_no_run**。本目录只记录门槛审计与历史日志摘要；没有为本 E1 矩阵启动 GenCase、DualSPHysics 或 GPU 求解器。",
        ">",
        "> `acceptance_status=not_run_not_accepted`；没有任何工况可标记为 accepted。",
        "",
        "## 决策",
        "",
        "mDBC 的 E0 normals/ghost 几何门槛尚未可证，因此不执行 nominal/deeper/shallower × DBC/mDBC 的 6 个主工况，也不解锁额外的 3 个 fine 工况。固定体转换也尚未形成可复用 XML：现有 DBC 与 mDBC XML 都包含 `<floatings>`，且历史 mDBC solver 明确警告 floating collision 应使用 Chrono；这与本任务的 fixed-body、无 Chrono 约束不兼容。",
        "",
        "## 门槛审计",
        "",
        "| gate | status | evidence |",
        "|---|---|---|",
        f"| E0 外壳/质量静水一致性 | {gate['e0_outer_hull']['status']} | `Vsub={gate['e0_outer_hull']['nominal_displaced_volume_m3']:.9f} m³` vs `m/rho={gate['e0_outer_hull']['target_displaced_volume_m3']:.9f} m³`; relative error `{gate['e0_outer_hull']['relative_error_percent']:.3f}%`; predicted heave `{gate['e0_outer_hull']['predicted_heave_m']*1000:.3f} mm` |",
        f"| mDBC normal completeness | **FAIL / unproven** | baseline `792/24,335` zero `BoundNor` vectors, all 792 fixed; solver repeats `792` fixed/moving warnings |",
        f"| fixed-body semantics | **FAIL / unproven** | DBC/mDBC source XML both have `<floatings>`; no fixed-body definition or force gauge |",
        f"| Chrono isolation | **BLOCKED** | historical mDBC log warns floating mDBC collisions should use `RigidAlgorithm=3`; E1 requires Chrono disabled |",
        "",
        "The `-0.020/-0.030 m` tank-normal-radius candidates report zero serialized normals, but they change the tank normal surface from the nominal `2.0 m` tank and were only coarse CPU diagnostics. They are not an accepted geometry repair and cannot unlock E1.",
        "",
        "## Planned matrix (not executed)",
        "",
        "The manifest has six primary rows; all are `blocked_preflight`, `execute=false`, with no result. The fine extension is explicitly locked, so the maximum of nine cases is respected.",
        "",
        "| height | provisional base z [m] | boundary | body mode | status |",
        "|---|---:|---|---|---|",
    ]
    for entry in manifest["entries"]:
        lines.append(
            f"| {entry['height_id']} | {entry['provisional_body_base_z_m']:.6f} | {entry['boundary']} | fixed | `{entry['status']}` |"
        )
    lines += [
        "",
        "The height values are provisional plan labels derived from the existing static geometry equilibrium (`base_z=0.611761785 m`) and are not materialized as solver inputs while the gate is blocked.",
        "",
        "## Required measurements after unblocking",
        "",
        "Each future case must emit pressure field integrity, `Fx/Fz`, geometric displaced volume `Vsub`, and multiple tail windows (`last 0.5 s`, `last 1.0 s`, `last 2.0 s`). It must also audit fluid mass loss, body penetration/穿壁, NaN/Inf and missing fields. The proposed screening gates are:",
        "",
        "- no unexplained zero normal vectors;",
        "- tail mean `Fz` vs `rho*g*Vsub` within 5% (medium/fine within 3%);",
        "- symmetric horizontal `|mean(Fx)| <= 1% mg`;",
        "- zero mass loss and zero penetration/穿壁;",
        "- complete pressure/force/displacement fields in every tail window.",
        "",
        "Away from the equilibrium height, no `Fz=mg` requirement is imposed; the comparison is to the geometric displaced-volume prediction.",
        "",
        "## Resource policy",
        "",
        f"The only GPU preflight query was `{report['resource_policy']['command']}`. It recorded the UUIDs for indices 4–7 and did not launch a solver. `gpu_indices_used=[]`, `gpu_uuids_used=[]`; GPU 0–3 were not queried or used by this task.",
        "",
        "| index | UUID | memory used [MiB] | utilization [%] |",
        "|---:|---|---:|---:|",
    ]
    for row in report["resource_policy"]["rows"]:
        lines.append(f"| {row['index']} | `{row['uuid']}` | {row['memory_used_mib']} | {row['utilization_percent']} |")
    lines += [
        "",
        "## Reused evidence",
        "",
        "| item | path | SHA-256 |",
        "|---|---|---|",
    ]
    for item in inputs:
        lines.append(f"| {item['role']} | `{item['path']}` | `{item.get('sha256') or 'missing'}` |")
    lines += [
        "",
        "Historical raw log excerpts are in [`raw-log-summary.json`](raw-log-summary.json) and [`raw-log-summary.md`](raw-log-summary.md). The machine-readable decision is [`r3-f6-fixed-hydrostatic.json`](r3-f6-fixed-hydrostatic.json); the planned rows are [`run-manifest.json`](run-manifest.json).",
        "",
        "## Blockers before any run",
        "",
        "1. Produce a fixed-body XML that removes the floating/Chrono path while preserving tank, damping, gravity, domain, fluid and boundary controls.",
        "2. Add an explicit fixed-body force measurement path and verify pressure/force sign, units and body mk target.",
        "3. Rebuild mDBC normals with the nominal tank geometry and prove zero normals at all intended resolutions; do not use the radius-offset diagnostic as an unqualified repair.",
        "4. Re-audit the three height placements for displaced volume, wall clearance and pressure-field completeness before unlocking the six rows.",
        "",
        "No physical result, accepted result, or DBC-vs-mDBC conclusion is claimed by this report.",
        "",
    ]
    return "\n".join(lines)


def raw_markdown(raw: dict) -> str:
    lines = [
        "# R3 F6 E1 raw-log summary",
        "",
        "No new E1 logs exist: the matrix was blocked before any solver launch. The entries below are historical evidence consulted for the no-run decision.",
        "",
        "| source | device | path | SHA-256 | selected lines |",
        "|---|---|---|---|---|",
    ]
    for item in raw["historical_logs"]:
        selected = "<br>".join(f"`{line}`" for line in item["excerpts"])
        lines.append(
            f"| {item['label']} | {item['device']} | `{item['path']}` | `{item.get('sha256') or 'missing'}` | {selected or 'none'} |"
        )
    lines += [
        "",
        "The historical DBC entry used GPU 4 in its own prior campaign and is not counted in this E1 resource usage. The mDBC entries were CPU-only. E1 usage remains `[]`.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    static_report_path = CAMPAIGN / "r3-g2-f6-static-buoyancy.json"
    mdbc_report_path = CAMPAIGN / "r3-g2-f6-mdbc-preflight.json"
    zero_report_path = CAMPAIGN / "r3-g2-f6-mdbc-zero-normal-preflight.json"
    test14_report_path = CAMPAIGN / "r3-g2-f6-test14.json"
    static_report = load(static_report_path)
    mdbc_report = load(mdbc_report_path)
    zero_report = load(zero_report_path)
    test14_report = load(test14_report_path)
    baseline = next(
        item for item in zero_report["results"]
        if item["record"]["variant_id"] == "baseline_combined_mask2_d2_invert"
    )
    repair_variants = {}
    for name in ("combined_tank_radius_minus020", "combined_tank_radius_minus030"):
        repair_variants[name] = next(
            item for item in zero_report["results"]
            if item["record"]["variant_id"] == name
        )

    dbc_xml_dir = CAMPAIGN / "cases" / "r3-g2-f6-test14"
    inputs = []
    for path in sorted(dbc_xml_dir.glob("*.xml")):
        inputs.append({"role": "existing DBC Test14 XML", "path": rel(path), "sha256": sha256(path)})
    for role, path in (
        ("existing mDBC preflight XML", CAMPAIGN / "cases/r3-g2-f6-mdbc-preflight/R3_F6_mdbc_preflight_neg074_coarse_Def.xml"),
        ("mDBC zero-normal baseline XML", CAMPAIGN / "cases/r3-g2-f6-mdbc-zero-normal-preflight/R3_F6_mdbc_zero_normal_baseline_baseline_combined_mask2_d2_invert_Def.xml"),
        ("mDBC radius-offset diagnostic XML", CAMPAIGN / "cases/r3-g2-f6-mdbc-zero-normal-preflight/R3_F6_mdbc_zero_normal_baseline_combined_tank_radius_minus030_Def.xml"),
        ("official Float1 STL", CAMPAIGN / "artifacts/w05/external/test14/Float1.STL"),
        ("transformed Float1 STL, existing neg074", CAMPAIGN / "artifacts/r3-g2-f6-mdbc-preflight/R3_F6_mdbc_preflight_neg074_coarse/generated/Float1_world.stl"),
        ("static buoyancy report", static_report_path),
        ("existing DBC Test14 report", test14_report_path),
        ("existing mDBC preflight report", mdbc_report_path),
        ("existing mDBC zero-normal report", zero_report_path),
        ("GPU inventory contract", CAMPAIGN / "w00-inventory.json"),
    ):
        inputs.append({"role": role, "path": rel(path), "sha256": sha256(path)})

    xml_audits = {
        "dbc_neg074_coarse": xml_audit(dbc_xml_dir / "R3_F6_test14_float1_neg074_coarse_Def.xml"),
        "mdbc_preflight_neg074_coarse": xml_audit(
            CAMPAIGN / "cases/r3-g2-f6-mdbc-preflight/R3_F6_mdbc_preflight_neg074_coarse_Def.xml"
        ),
        "mdbc_zero_normal_baseline": xml_audit(
            CAMPAIGN / "cases/r3-g2-f6-mdbc-zero-normal-preflight/R3_F6_mdbc_zero_normal_baseline_baseline_combined_mask2_d2_invert_Def.xml"
        ),
        "mdbc_radius_minus030_diagnostic": xml_audit(
            CAMPAIGN / "cases/r3-g2-f6-mdbc-zero-normal-preflight/R3_F6_mdbc_zero_normal_baseline_combined_tank_radius_minus030_Def.xml"
        ),
    }
    resource = gpu_preflight()
    manifest = plan_manifest()
    write_manifest(manifest)
    raw = raw_summary()
    (OUT / "raw-log-summary.json").write_text(json.dumps(raw, indent=2) + "\n")
    (OUT / "raw-log-summary.md").write_text(raw_markdown(raw))

    static_model = static_report["static_model"]
    relative_error_percent = static_model["nominal_relative_volume_error"] * 100.0
    report = {
        "schema_version": 1,
        "report_id": "R3-F6-E1-fixed-submerged-hydrostatic",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "execution_status": "blocked_preflight_no_run",
        "acceptance_status": "not_run_not_accepted",
        "scientific_acceptance": "not_accepted",
        "physical_result": None,
        "resource_policy": resource,
        "scope": {
            "family": "F6",
            "experiment": "E1 fixed submerged-body hydrostatic closure",
            "body_mode_requested": "fixed rigid body",
            "boundary_methods": ["DBC", "mDBC"],
            "heights": ["nominal", "deeper", "shallower"],
            "primary_case_count": 6,
            "fine_extension_max_case_count": 3,
            "matrix_cap_case_count": 9,
            "chronology": "Chrono disabled; no Chrono/rigid coupling variable may enter the sweep",
        },
        "geometry_gate": {
            "overall_status": "blocked_unproven",
            "e0_outer_hull": {
                "status": "provisionally_near_pass_geometry_mass_only",
                "source_report": rel(static_report_path),
                "nominal_displaced_volume_m3": static_model["nominal_displaced_volume_m3"],
                "target_displaced_volume_m3": static_model["target_displaced_volume_m3"],
                "relative_error_percent": relative_error_percent,
                "predicted_heave_m": static_model["predicted_equilibrium"]["predicted_heave_from_reference_m"],
                "caveat": "This is an outer-hull/mass diagnostic, not proof of a fixed-body mDBC geometry gate.",
            },
            "mdbc_normals": {
                "status": "fail",
                "source_report": rel(zero_report_path),
                "baseline_variant": baseline["record"]["variant_id"],
                "gencase_zero_count": baseline["gencase"]["normal_data"]["zero_count"],
                "gencase_boundary_count": baseline["gencase"]["normal_data"]["boundary_count"],
                "boundnor_zero_count": baseline["gencase"]["boundnor"]["boundnor_zero_count"],
                "boundnor_fixed_zero_count": baseline["gencase"]["boundnor"]["boundnor_fixed_zero_count"],
                "boundnor_floating_zero_count": baseline["gencase"]["boundnor"]["boundnor_floating_zero_count"],
                "solver_fixed_or_moving_zero_count": baseline["solver"]["normal_data"]["fixed_or_moving_zero_count"],
                "solver_finished_code_0": baseline["solver"]["normal_data"]["solver_finished_code_0"],
                "zero_normal_rule": "must be zero unexplained normals before any physics run",
                "repair_candidates": {
                    key: {
                        "tank_radius_m": item["record"]["tank_radius_m"],
                        "boundnor_zero_count": item["gencase"]["boundnor"]["boundnor_zero_count"],
                        "normal_geometry_changed": True,
                        "physical_acceptance": False,
                    }
                    for key, item in repair_variants.items()
                },
            },
            "fixed_body_setup": {
                "status": "unproven_blocked",
                "existing_dbc_fixed_body_definition": xml_audits["dbc_neg074_coarse"]["floating_body"]["fixed_body"],
                "existing_mdbc_fixed_body_definition": xml_audits["mdbc_preflight_neg074_coarse"]["floating_body"]["fixed_body"],
                "existing_dbc_floatings_section": xml_audits["dbc_neg074_coarse"]["floating_body"]["section_present"],
                "existing_mdbc_floatings_section": xml_audits["mdbc_preflight_neg074_coarse"]["floating_body"]["section_present"],
                "existing_mdbc_rigid_algorithm": xml_audits["mdbc_preflight_neg074_coarse"]["rigid_algorithm"],
                "mdbc_chrono_warning_in_historical_solver": baseline["solver"]["normal_data"]["chrono_collision_warning"],
                "fixed_body_force_gauge_present_in_source": xml_audits["dbc_neg074_coarse"]["force_gauge"]["force_gauge_count"] > 0,
                "required_action": "materialize a fixed-body XML and explicit force-gauge target before running",
            },
        },
        "xml_audit": xml_audits,
        "source_reports": {
            "test14": {
                "path": rel(test14_report_path),
                "scientific_acceptance": test14_report.get("scientific_acceptance"),
                "execution_status": test14_report.get("execution_status"),
                "boundary": test14_report.get("numerical_configuration", {}).get("boundary"),
                "open_blockers": test14_report.get("open_blockers", []),
            },
            "mdbc_preflight": {
                "path": rel(mdbc_report_path),
                "acceptance_status": mdbc_report.get("acceptance_status"),
                "scientific_acceptance": mdbc_report.get("scientific_acceptance"),
                "normal_completeness": mdbc_report.get("normal_completeness"),
                "open_blockers": mdbc_report.get("open_blockers", []),
            },
        },
        "inputs": inputs,
        "run_manifest": "run-manifest.json",
        "raw_log_summary": "raw-log-summary.json",
        "planned_observables": {
            "pressure_field": {"status": "not_collected", "required": True},
            "vertical_force_Fz_N": {"status": "not_collected", "required": True},
            "horizontal_force_Fx_N": {"status": "not_collected", "required": True},
            "displaced_volume_Vsub_m3": {"status": "not_collected", "required": True},
            "tail_windows_s": [0.5, 1.0, 2.0],
            "mass_loss": {"status": "not_collected", "required": True},
            "penetration_or_through_wall": {"status": "not_collected", "required": True},
            "field_completeness": {"status": "not_collected", "required": True},
        },
        "acceptance_gates": [
            {
                "id": "normal_completeness",
                "criterion": "zero unexplained normal vectors in every boundary particle at every executed resolution",
                "status": "blocked_preflight",
            },
            {
                "id": "hydrostatic_vertical_force",
                "criterion": "each tail-window mean Fz agrees with rho*g*Vsub within 5%; medium/fine within 3%",
                "status": "not_evaluable_no_run",
            },
            {
                "id": "horizontal_symmetry",
                "criterion": "abs(mean Fx) <= 1% of mg",
                "status": "not_evaluable_no_run",
            },
            {
                "id": "integrity",
                "criterion": "zero mass loss/penetration and complete pressure/force fields",
                "status": "not_evaluable_no_run",
            },
            {
                "id": "equilibrium_interpretation",
                "criterion": "do not require Fz=mg away from nominal equilibrium; compare against geometric Vsub",
                "status": "protocol_defined",
            },
        ],
        "matrix": manifest,
        "raw_logs": raw,
        "blockers": [
            "mDBC baseline has 792 fixed/moving zero BoundNor vectors; normal completeness is not proven.",
            "Zero-normal radius-offset candidates change nominal tank geometry and are diagnostic-only.",
            "No fixed-body DBC or mDBC XML exists in the inspected inputs; both existing XMLs use <floatings>.",
            "Historical mDBC solver warns floating collisions should use Chrono, which is disallowed for this fixed-body E1.",
            "No explicit fixed-body force gauge is present in the existing F6 XMLs.",
            "Therefore no primary or fine solver case was started and no GPU was used.",
        ],
        "conclusion": {
            "decision": "no_run_feasibility_report",
            "reason": "E0 mDBC geometry gate and fixed-body measurement semantics are unproven",
            "physical_acceptance_claim": False,
            "accepted_cases": [],
            "gpu_indices_used": [],
            "next_unlock_conditions": [
                "prove complete mDBC normals/ghost geometry without changing nominal tank semantics",
                "materialize fixed-body XML with Chrono absent",
                "add and audit fixed-body pressure/force measurement path",
                "re-audit nominal/deeper/shallower volume and wall-clearance controls",
            ],
        },
    }
    (OUT / "r3-f6-fixed-hydrostatic.json").write_text(json.dumps(report, indent=2) + "\n")
    (OUT / "r3-f6-fixed-hydrostatic.md").write_text(markdown(report, manifest, raw))
    print(json.dumps({
        "report": rel(OUT / "r3-f6-fixed-hydrostatic.json"),
        "status": report["execution_status"],
        "gpu_indices_used": report["resource_policy"]["gpu_indices_used"],
        "primary_cases": manifest["planned_primary_case_count"],
        "executed_cases": manifest["executed_case_count"],
    }, indent=2))


if __name__ == "__main__":
    main()

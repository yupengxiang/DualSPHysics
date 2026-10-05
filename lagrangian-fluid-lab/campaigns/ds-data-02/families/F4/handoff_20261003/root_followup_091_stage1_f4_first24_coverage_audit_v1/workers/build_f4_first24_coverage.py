#!/usr/bin/env python3
"""Build F4 first24 source-only coverage/audit handoff.

This builder reads the existing F4 registry/manifests and JSON evidence, and
writes only XML/JSON/code metadata plus disabled runner requests.  It never
opens BI4/H5/CSV/VTK/scientific payloads and never launches a job.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
from typing import Any

PACKAGE_NAME = "root_followup_091_stage1_f4_first24_coverage_audit_v1"
FAMILY = "F4"
DP_M = 0.01
TIME_MAX = 1.2
TIME_OUT = 0.001
FRAME_COUNT = 1201
WORKTREE_DEFAULT = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4")
INTEGRATION_BASE = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003")
F4_FAMILY_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/families/F4")
SOURCE_BASE = WORKTREE_DEFAULT / F4_FAMILY_REL
MOTHER_SOURCE = SOURCE_BASE / "handoff_20261003/root_followup_087_stage1_drop_gap_lattice_aligned_fallback6_source_v1/definitions/F4_DROP_LATTICE_GAP0p19000_DP010_Def.xml"
ROOT230_LAUNCH = INTEGRATION_BASE / "root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py"
ROOT230_POLICY = INTEGRATION_BASE / "root_stage1_native_home_floor_eight_solver_dispatch_230/source-policy-contract.json"
QA_WORKER = INTEGRATION_BASE / "root_stage1_f4_six_actual_gen_receipt_json_alias_native_qa_237/run_f4_fallback_native_initial_qa_root237.py"
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest_obj(value: Any) -> str:
    return digest_bytes(canon(value))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def import_f4_generator(worktree: Path):
    script = worktree / "lagrangian-fluid-lab/scripts/ds_data02_f4.py"
    spec = importlib.util.spec_from_file_location("ds_data02_f4_source091", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import F4 source generator: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def token(value: float) -> str:
    return f"{value:.5f}".replace("-", "m").replace(".", "p")


def first24_configs(f4: Any) -> list[dict[str, Any]]:
    # registry_records is the frozen source registry ordering.  The first 24
    # records are finite_drop_pool nested24 (8 cases per gap .18/.22/.24).
    records = f4.registry_records()[:24]
    if len(records) != 24 or any(r["mechanism_id"] != "finite_drop_pool" for r in records):
        raise RuntimeError("F4 registry first24 contract changed")
    configs = []
    for r in records:
        p = r["parameters"]
        cfg = f4.drop_config(
            "fine", gap_m=p["gap_m"], x_offset_m=p["x_offset_m"],
            y_offset_m=p["y_offset_m"], speed_m_per_s=p["speed_m_per_s"],
            stage="nested24", time_variant="native",
        )
        # DP010 Stage1 source uses the frozen DP010 mother.  Keep the registry
        # geometry/control tuple while recording source expected geometry only;
        # generated GenCase counts remain unknown until Root runs it.
        cfg["dp_m"] = DP_M
        cfg["resolution"] = "dp010"
        cfg["parameters"] = dict(p)
        cfg["case_id"] = r["case_id"]
        cfg["physical_case_id"] = r["physical_case_id"]
        cfg["axis_rank_within_background"] = r["axis_rank_within_background"]
        cfg["admission_stages"] = r["admission_stages"]
        cfg["registered_resolution_cells"] = r["registered_resolution_cells"]
        cfg["production_artifact_status"] = r["production_artifact_status"]
        configs.append(cfg)
    return configs


def mutate_dp010_mother(source: Path, target: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    tree = ET.parse(source)
    root = tree.getroot()
    main = root.find("./casedef/geometry/commands/mainlist")
    if main is None:
        raise RuntimeError("mother lacks geometry mainlist")
    fluid_nodes: dict[int, ET.Element] = {}
    active = None
    for node in list(main):
        if node.tag == "setmkfluid":
            active = int(node.get("mk", "-1"))
        elif node.tag == "setmkbound":
            active = None
        elif node.tag == "drawbox" and active is not None:
            fluid_nodes[active] = node
    if set(fluid_nodes) != {0, 1}:
        raise RuntimeError(f"unexpected mother fluid blocks: {sorted(fluid_nodes)}")
    p = cfg["parameters"]
    # The DP010 fallback source has pool low=(.085,.045,.045), pool height
    # .15, and drop low z=.395 at gap=.19.  Only the finite drop point and
    # velocity are changed per registry row; pool/tank/controls stay frozen.
    drop_point = fluid_nodes[1].find("point")
    if drop_point is None:
        raise RuntimeError("mother drop drawbox lacks point")
    values = {
        "x": 0.475 + float(p["x_offset_m"]),
        "y": 0.125 + float(p["y_offset_m"]),
        "z": float(p["gap_m"]) + 0.205,
    }
    for axis, value in values.items():
        drop_point.set(axis, f"{value:.17g}")
    # DP010 mother's falling-drop velocity is the only initial-state change.
    vel = root.find("./casedef/initials/velocity[@mkfluid='1']")
    if vel is None:
        raise RuntimeError("mother lacks falling-drop velocity")
    vel.set("x", "0")
    vel.set("y", "0")
    vel.set("z", f"{-float(p['speed_m_per_s']):.17g}")
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise RuntimeError("mother lacks definition")
    definition.set("dp", "0.01")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "drop_point_m": [values["x"], values["y"], values["z"]],
        "drop_velocity_m_per_s": [0.0, 0.0, -float(p["speed_m_per_s"])],
        "changed_fields": [
            "casedef.geometry.commands.mainlist.setmkfluid(mk=1).drawbox.point.x",
            "casedef.geometry.commands.mainlist.setmkfluid(mk=1).drawbox.point.y",
            "casedef.geometry.commands.mainlist.setmkfluid(mk=1).drawbox.point.z",
            "casedef.initials.velocity[@mkfluid=1].z",
        ],
        "unchanged_controls": [
            "tank/wall geometry", "pool point/size", "drop size", "gravity",
            "DP010", "TimeMax=1.2", "TimeOut=0.001", "DBC/Verlet/Wendland",
            "fluid/fixed marker declarations",
        ],
    }


def build_physical_binding(cfg: dict[str, Any], definition: Path, manifest: Path, registry: Path, source_plan_hash: str) -> dict[str, Any]:
    p = cfg["parameters"]
    geometry = cfg["geometry"]
    # Remove source-computed native mass/counts from the future actual binding.
    physical_core = {
        "family_id": FAMILY,
        "case_id": cfg["case_id"],
        "physical_case_id": cfg["physical_case_id"],
        "mechanism_id": "finite_drop_pool",
        "geometry_family_id": "F4_finite_drop_pool_finite_geometry_v1",
        "control_family_id": "F4_native_dbc_verlet_wendland_v1",
        "parameters": {
            "gap_m": float(p["gap_m"]),
            "x_offset_m": float(p["x_offset_m"]),
            "y_offset_m": float(p["y_offset_m"]),
            "speed_m_per_s": float(p["speed_m_per_s"]),
        },
        "dp_m": DP_M,
        "time_max_s": TIME_MAX,
        "time_out_s": TIME_OUT,
        "native_frame_count": FRAME_COUNT,
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "mass_policy": "native_rho_dp_cubed_no_rescaling; actual native mass pending GenCase/initial QA",
    }
    source_plan_condition = {
        **physical_core,
        "mother_definition_path": str(MOTHER_SOURCE),
        "mother_definition_sha256": digest_file(MOTHER_SOURCE),
        "source_definition_path": str(definition),
        "source_definition_sha256": digest_file(definition),
        "registry_manifest_path": str(manifest),
        "registry_manifest_sha256": digest_file(manifest),
        "registry_path": str(registry),
        "registry_sha256": digest_file(registry),
    }
    physical_hash = digest_obj(physical_core)
    plan_hash = digest_obj(source_plan_condition)
    source_expected_geometry = {
        "tank": {"low_m": [0.0, 0.0, 0.0], "size_m": [1.2, 0.4, 0.6]},
        "wall_faces_closed": ["bottom", "left", "right", "front", "back"],
        "pool": {"low_m": [0.085, 0.045, 0.045], "size_m": [1.03, 0.31, 0.15], "mkfluid": 0},
        "drop": {
            "low_m": [0.475 + float(p["x_offset_m"]), 0.125 + float(p["y_offset_m"]), float(p["gap_m"]) + 0.205],
            "size_m": [0.25, 0.15, 0.13], "mkfluid": 1,
        },
    }
    return {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": FAMILY,
        "case_id": cfg["case_id"],
        "physical_case_id": cfg["physical_case_id"],
        "mechanism_id": "finite_drop_pool",
        "lineage_group_id": "finite_drop_pool_frozen_geometry_control_domain",
        "geometry_family_id": "F4_finite_drop_pool_finite_geometry_v1",
        "control_family_id": "F4_native_dbc_verlet_wendland_v1",
        "parameters": physical_core["parameters"],
        "physical_condition_sha256": physical_hash,
        "source_plan_condition_sha256": plan_hash,
        "source_plan_path": str(SOURCE_BASE / "handoff_20261003" / PACKAGE_NAME / "source-plan.json"),
        "source_plan_sha256": source_plan_hash,
        "source_definition": {"path": str(definition), "sha256": digest_file(definition)},
        "mother_definition": {"path": str(MOTHER_SOURCE), "sha256": digest_file(MOTHER_SOURCE)},
        "registry_manifest": {"path": str(manifest), "sha256": digest_file(manifest)},
        "registry": {"path": str(registry), "sha256": digest_file(registry)},
        "geometry": source_expected_geometry,
        "initial_state": {
            "velocities_m_per_s": {
                "mkfluid:0": [0.0, 0.0, 0.0],
                "mkfluid:1": [0.0, 0.0, -float(p["speed_m_per_s"])],
            },
            "source_labels": {"mkfluid:0": "pool", "mkfluid:1": "falling_drop"},
            "initial_mass_by_source_kg": None,
            "initial_mass_total_kg": None,
            "initial_native_mass_status": "pending actual generated native weights; no rescale",
            "actual_counts": None,
            "actual_solver_dimension": None,
        },
        "controls": {
            "boundary": "DBC", "step_algorithm": "Verlet", "kernel": "Wendland",
            "viscosity": 0.08, "density_dt": 2, "density_dt_value": 0.1,
            "gravity_m_s2": [0.0, 0.0, -9.81], "open_inlet": False,
            "periodic_boundary": False,
        },
        "solver_recipe": {
            "dp_m": DP_M, "time_max_s": TIME_MAX, "time_out_s": TIME_OUT,
            "native_frame_count": FRAME_COUNT, "solver_options": ["-tmax:1.2", "-tout:0.001"],
            "no_forcing": True, "no_mdbc": True,
            "native_types": {"fixed": [0], "floating": [], "fluid": [3], "moving": []},
        },
        "claim_boundary": {
            "status": "prospective_source_only",
            "actual_gencase": False, "actual_initial_qa": False, "actual_native": False,
            "actual_typed": False, "actual_xmf": False, "actual_render": False,
            "visual_approval": False, "precision_status": "not_accepted", "q_n": "not_granted",
        },
    }, source_plan_condition, physical_hash, plan_hash


def json_path(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": digest_file(path)}


def safe_receipt_summary(path: Path) -> dict[str, Any]:
    # JSON metadata only.  This intentionally never follows output H5/BI4/CSV.
    d = load_json(path)
    if not isinstance(d, dict):
        return {"path": str(path), "sha256": digest_file(path), "status": "invalid_non_object"}
    out = {"path": str(path), "sha256": digest_file(path)}
    for key in ("status", "returncode", "attempt_id", "output_root", "total_particles", "fluid_particles", "frames", "particles", "conversion_status"):
        if key in d and key not in {"output_root"}:
            out[key] = d[key]
    out["output_root"] = d.get("output_root")
    return out


def actual_fallback_audit() -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for gap, stage, render in [("190", "261", "263"), ("200", "261", "263"), ("210", "266", "271"), ("230", "266", "271"), ("240", "266", "271"), ("250", "266", "271")]:
        case = f"F4_DROP_LATTICE_GAP0p{gap}00_DP010"
        root = DATA_ROOT / case
        def one(pattern: str) -> Path | None:
            hits = sorted(root.glob(pattern))
            return hits[0] if hits else None
        gen = one("*-genuine-gencase-087/execution-receipt.json")
        prepared = one("*-genuine-gencase-087/prepared/prepared-input-report.json")
        native = one("*-full1201-native-qualification-root230-089/execution-receipt.json")
        typed = one("*-typed-nvme-root242-schema-repair-255/execution-receipt.json")
        conversion = one("*-typed-nvme-root242-schema-repair-255/conversion-report.json")
        xmf_receipt = one(f"*-xmf-{stage}/execution-receipt.json")
        xmf_manifest = one(f"*-xmf-{stage}/xdmf/manifest.json")
        render_receipt = one(f"*-render-{render}/execution-receipt.json")
        render_report = one(f"*-render-{render}/render/paraview-full-animation-report.json")
        qa_index = DATA_ROOT / "F4_FALLBACK6_LATTICE_DP010_INITIAL_QA" / "root-stage1-f4-six-aligned-gap-actual-gen-receipt-json-alias-native-qa-237" / "initial-native-qa-index.json"
        qa_case = None
        if qa_index.is_file():
            idx = load_json(qa_index)
            if isinstance(idx, dict):
                for row in idx.get("cases", idx.get("results", [])):
                    if isinstance(row, dict) and row.get("case_id") == case:
                        qa_case = {k: row.get(k) for k in ("case_id", "pass", "failed_checks", "actual_report") if k in row}
                        break
        stages = {
            "gencase": safe_receipt_summary(gen) if gen else None,
            "prepared_report": json_path(prepared) if prepared else None,
            "initial_qa": {"index": json_path(qa_index), "case": qa_case} if qa_index.is_file() else None,
            "native": safe_receipt_summary(native) if native else None,
            "typed": safe_receipt_summary(typed) if typed else None,
            "conversion_report": safe_receipt_summary(conversion) if conversion else None,
            "xmf": safe_receipt_summary(xmf_receipt) if xmf_receipt else None,
            "xmf_manifest": safe_receipt_summary(xmf_manifest) if xmf_manifest else None,
            "render": safe_receipt_summary(render_receipt) if render_receipt else None,
            "render_report": safe_receipt_summary(render_report) if render_report else None,
        }
        out.append({
            "case_id": case,
            "physical_scope": "F4 fallback6 lattice-aligned source; not an exact registry first24 tuple",
            "gap_m": float(gap) / 100.0,
            "actual_stage_evidence": stages,
            "independent_case_count_increment": 0,
            "visual_status": "not inferred from render receipt; Root decision separate",
        })
    return {
        "schema": "ds02.f4.actual-fallback6-product-audit.v1",
        "source_only": True,
        "arrays_read_by_source": False,
        "scientific_payloads_read": [],
        "claim_boundary": "JSON receipt/report metadata only; no source agent visual or scientific claim",
        "rows": out,
    }


def visual_anchor_audit() -> dict[str, Any]:
    paths = [
        INTEGRATION_BASE / "root_stage1_f4_full1201_visual_acceptance_054/root-visual-decision.json",
        INTEGRATION_BASE / "root_stage1_f4_gap0180_full1201_visual_acceptance_169/gap0180-root-visual-decision.json",
        INTEGRATION_BASE / "root_stage1_f4_gap0260_full1201_visual_acceptance_188/gap0260-root-visual-decision.json",
    ]
    rows=[]
    for p in paths:
        d=load_json(p)
        rows.append({
            "decision": json_path(p),
            "case_id": d.get("case_id"),
            "physical_case_id": d.get("physical_case_id"),
            "physical_condition_sha256": d.get("physical_condition_sha256"),
            "status": d.get("status"),
            "frames": d.get("frames"),
            "particle_count": d.get("particle_count"),
            "independent_physical_case_count_increment": d.get("independent_physical_case_count_increment"),
            "scope_relation": "accepted_visual_anchor_outside_registry_first24_exact_tuples",
        })
    return {
        "schema":"ds02.f4.accepted-visual-anchor-audit.v1",
        "source_only":True,
        "rows":rows,
        "claim_boundary":"Root decisions are recorded as accepted anchors; they do not silently satisfy any first24 registry row whose tuple differs.",
    }


def make_gencase_request(cfg: dict[str, Any], definition: Path, owner: Path, manifest: Path, registry: Path, package: Path) -> dict[str, Any]:
    case = cfg["case_id"]
    attempt = f"root-stage1-f4-{case.lower()}-genuine-gencase-091"
    req_path = package / "requests" / f"{case}-gencase.request.json"
    command = [str(GENCASE), str(definition.with_suffix("")), f"{{attempt_root}}/prepared/{case}", "-save:all"]
    files = [definition, owner, manifest, registry, MOTHER_SOURCE, package / "source-plan.json"]
    return {
        "schema":"ds02.runner-request.v1", "family_id":FAMILY, "case_id":case,
        "attempt_id":attempt, "kind":"cpu", "cpu_task_kind":"gencase", "cpu_threads":4,
        "command":command, "cwd":str(GENCASE.parent), "worktree_root":str(WORKTREE_DEFAULT),
        "launch":False, "launch_allowed":False, "execution_allowed":False,
        "source_only":True, "jobs_started_by_source":False, "arrays_read_by_source":False,
        "status":"disabled_pending_root_review", "disabled":True,
        "disabled_reason":"First24 source handoff only; Root must review and run actual GenCase in registered CPU worker.",
        "launch_owner":"root", "launch_commit":None,
        "launch_commit_policy":"bind exact adopted scoped commit before enabling",
        "max_wall_seconds":1800, "estimated_storage_bytes":4294967296,
        "input_files":[str(x) for x in files],
        "input_sha256":{},
        "expected":{
            "solver_dimension":"3D", "data2d":False,
            "fluid_particles_from_gencase":None, "total_particles_from_gencase":None,
            "native_counts_source_only":cfg["geometry"]["native_boxes"],
            "actual_counts_required":True,
        },
        "output_contract":{
            "generated_xml":f"{{attempt_root}}/prepared/{case}.xml",
            "generated_bi4":f"{{attempt_root}}/prepared/{case}.bi4",
            "prepared_input_report":f"{{attempt_root}}/prepared/prepared-input-report.json",
            "future_sha256":None,
        },
        "physical_case_id":cfg["physical_case_id"],
        "physical_condition_sha256":None,
        "source_plan_condition_sha256":None,
        "precision_status":"not_accepted", "q_n_status":"not_granted",
        "production_approval":False, "independent_case_count_increment":0,
        "root_review_required":True,
        "claim_boundary":"No GenCase/3D/count/mass success is claimed until Root actual receipt and prepared report.",
    }, req_path


def make_qa_request(cfg: dict[str, Any], definition: Path, owner: Path, gencase_req: Path, package: Path) -> dict[str, Any]:
    case=cfg["case_id"]
    attempt=f"root-stage1-f4-{case.lower()}-initial-native-qa-091"
    req_path=package/"requests"/f"{case}-initial-native-qa.request.json"
    files=[QA_WORKER, owner, definition, gencase_req, ROOT230_POLICY, PARTVTK]
    return {
        "schema":"ds02.runner-request.v1", "family_id":FAMILY, "case_id":case,
        "attempt_id":attempt, "kind":"cpu", "cpu_task_kind":"audit", "cpu_threads":4,
        "command":["{approved_python}",str(QA_WORKER),"--request","{actual_request_path}"],
        "cwd":str(QA_WORKER.parent), "worktree_root":str(WORKTREE_DEFAULT),
        "launch":False, "launch_allowed":False, "execution_allowed":False, "disabled":True,
        "source_only":True, "jobs_started_by_source":False, "arrays_read_by_source":False,
        "status":"disabled_gated_on_actual_gencase", "disabled_reason":"Requires Root completed GenCase receipt/prepared XML+BI4; no future hashes are filled.",
        "launch_owner":"root", "launch_commit":None, "launch_commit_policy":"bind exact adopted scoped commit before enabling",
        "max_wall_seconds":1800, "estimated_storage_bytes":536870912,
        "input_files":[str(x) for x in files], "input_sha256":{},
        "deferred_input_files":[f"{{actual_gencase_attempt_root}}/prepared/{case}.xml",f"{{actual_gencase_attempt_root}}/prepared/{case}.bi4",f"{{actual_gencase_attempt_root}}/prepared/prepared-input-report.json"],
        "deferred_input_sha256":{},
        "depends_on_attempts":[f"root-stage1-f4-{case.lower()}-genuine-gencase-091"],
        "expected_outputs":{"actual_initial_qa_json":f"{{attempt_root}}/actual-initial-qa.json","execution_receipt":f"{{attempt_root}}/execution-receipt.json","future_sha256":None},
        "physical_case_id":cfg["physical_case_id"], "physical_condition_sha256":None, "source_plan_condition_sha256":None,
        "checks_required":["actual_gencase_terminal_success","XML/BI4 producer closure","3D","UID/finite/domain/mk/drop/pool/nonoverlap","positive actual mass/counts"],
        "precision_status":"not_accepted", "q_n_status":"not_granted", "production_approval":False,
        "claim_boundary":"QA pass remains unknown until Root executes registered audit; missing/failed actual evidence must block native.",
    }, req_path


def make_native_request(cfg: dict[str, Any], definition: Path, owner: Path, qa_req: Path, gencase_req: Path, package: Path) -> dict[str, Any]:
    case=cfg["case_id"]
    attempt=f"root-stage1-f4-{case.lower()}-full1201-native-root230-091"
    req_path=package/"requests"/f"{case}-full1201-native-qualification.request.json"
    files=[ROOT230_LAUNCH,ROOT230_POLICY,owner,definition,qa_req,gencase_req]
    return {
        "schema":"ds02.runner-request.v1", "family_id":FAMILY, "case_id":case,
        "physical_case_id":cfg["physical_case_id"], "attempt_id":attempt,
        "kind":"gpu", "cpu_task_kind":"native_solver", "cpu_threads":1,
        "command":[str(SOLVER),"{actual_gencase_prefix}","{attempt_root}/solver_output","-tmax:1.2","-tout:0.001"],
        "cwd":str(SOLVER.parent), "worktree_root":str(WORKTREE_DEFAULT),
        "launch":False, "launch_allowed":False, "execution_allowed":False, "disabled":True,
        "source_only":True, "jobs_started_by_source":False, "arrays_read_by_source":False,
        "status":"disabled_gated_on_actual_initial_qa", "disabled_reason":"Root230 must enable only after actual GenCase+QA pass and live UUID/lease checks.",
        "launch_owner":"root", "launch_commit":None, "launch_commit_policy":"bind exact adopted scoped commit before enabling",
        "max_wall_seconds":14400, "estimated_peak_gpu_mib":49140, "estimated_storage_bytes":4294967296,
        "input_files":[str(x) for x in files], "input_sha256":{},
        "deferred_input_files":[f"{{actual_gencase_attempt_root}}/prepared/{case}.xml",f"{{actual_gencase_attempt_root}}/prepared/{case}.bi4",f"{{actual_gencase_attempt_root}}/prepared/prepared-input-report.json", "{actual_qa_receipt}", "{actual_qa_report}"],
        "deferred_input_sha256":{},
        "depends_on_attempts":[f"root-stage1-f4-{case.lower()}-initial-native-qa-091"],
        "solver_recipe":{"dp_m":DP_M,"time_max_s":TIME_MAX,"time_out_s":TIME_OUT,"native_frame_count":FRAME_COUNT,"solver_options":["-tmax:1.2","-tout:0.001"],"no_forcing":True,"no_mdbc":True,"native_types":{"fixed":[0],"floating":[],"fluid":[3],"moving":[]}},
        "physical_binding_sha256":None, "physical_condition_sha256":None, "source_plan_condition_sha256":None,
        "gencase_receipt":None, "gencase_receipt_sha256":None, "native_initial_qa":None,
        "expected_outputs":{"execution_receipt":f"{{attempt_root}}/execution-receipt.json","solver_output":f"{{attempt_root}}/solver_output","frames":FRAME_COUNT,"future_sha256":None},
        "root230":{"entry":str(ROOT230_LAUNCH),"policy":str(ROOT230_POLICY),"uuid_inventory_required":True,"foreign_process_protection":True,"home_free_gib_floor":500,"nvme_free_gib_floor":100,"concurrency_cap":8},
        "precision_status":"not_accepted", "q_n_status":"not_granted", "production_approval":False, "independent_case_count_increment":0,
        "root_review_required":True,
        "claim_boundary":"No native product, full-window success, typed output, visual acceptance, or Q-N is claimed from this disabled request.",
    }, req_path


def build(worktree: Path) -> Path:
    global SOURCE_BASE, MOTHER_SOURCE
    SOURCE_BASE = worktree / F4_FAMILY_REL
    MOTHER_SOURCE = SOURCE_BASE / "handoff_20261003/root_followup_087_stage1_drop_gap_lattice_aligned_fallback6_source_v1/definitions/F4_DROP_LATTICE_GAP0p19000_DP010_Def.xml"
    if not MOTHER_SOURCE.is_file():
        raise RuntimeError(f"DP010 source mother missing: {MOTHER_SOURCE}")
    f4 = import_f4_generator(worktree)
    package = SOURCE_BASE / "handoff_20261003" / PACKAGE_NAME
    if package.exists():
        raise RuntimeError(f"refusing to overwrite existing package: {package}")
    package.mkdir(parents=True)
    (package/"definitions").mkdir(); (package/"owners").mkdir(); (package/"requests").mkdir(); (package/"evidence").mkdir(); (package/"workers").mkdir(); (package/"tests").mkdir()
    registry = SOURCE_BASE / "case_registry.jsonl"
    configs = first24_configs(f4)
    rows=[]
    source_conditions=[]
    manifest_paths=[]
    owner_paths=[]
    request_records=[]
    # A preliminary source plan is written before owners so the source-plan
    # hash in owners is the final immutable plan hash, not a future output.
    plan = {
        "schema":"ds02.f4.first24.source-plan.v1", "family_id":FAMILY, "scope_id":PACKAGE_NAME,
        "scope_definition":"registry rows 0..23: finite_drop_pool nested24, DP010 source handoff",
        "model_policy":{"authorized_model":"GPT-5.6 Luna/max","gemini":False,"recursive_agents":False},
        "recipe":{"dp_m":DP_M,"time_max_s":TIME_MAX,"time_out_s":TIME_OUT,"native_frame_count":FRAME_COUNT,"solver_options":["-tmax:1.2","-tout:0.001"],"no_forcing":True,"no_mdbc":True},
        "mother_source":{"path":str(MOTHER_SOURCE),"sha256":digest_file(MOTHER_SOURCE),"mutation_policy":"only drop point x/y/z and mkfluid=1 z velocity; pool/tank/controls frozen"},
        "registry_source":{"path":str(registry),"sha256":digest_file(registry),"rows":"first 24 records"},
        "stage_contract":{"source_only":True,"jobs_started_by_source":False,"arrays_read_by_source":False,"scientific_payloads_read":[],"launch_allowed":False,"actual_counts":None,"future_hash_policy":"all GenCase/QA/native/typed/XMF/render hashes null until Root actual execution"},
        "rows":[],
    }
    # Iteration-independent plan rows contain only config/registry details.
    for rank,cfg in enumerate(configs):
        case=cfg["case_id"]
        manifest = SOURCE_BASE / "case_manifests" / f"{case}.json"
        if not manifest.is_file(): raise RuntimeError(f"missing case manifest {manifest}")
        definition = package / "definitions" / f"{case}_Def.xml"
        mutation = mutate_dp010_mother(MOTHER_SOURCE, definition, cfg)
        owner, condition_obj, phys_hash, plan_hash = build_physical_binding(cfg, definition, manifest, registry, "__PLAN_HASH_PENDING__")
        owner["source_definition"]["sha256"] = digest_file(definition)
        owner["mutation_contract"] = mutation
        owner["registry_rank"] = rank
        owner["admission_stages"] = cfg["admission_stages"]
        owner["status"] = "prospective_source_only"
        owner_path = package / "owners" / f"{case}.owner.json"
        # Temporarily write owner; source plan hash is patched after plan finalization.
        write_json(owner_path, owner)
        manifest_paths.append(manifest); owner_paths.append(owner_path)
        source_conditions.append({"case_id":case,"physical_case_id":cfg["physical_case_id"],"parameters":cfg["parameters"],"physical_condition_sha256":phys_hash,"source_plan_condition_sha256":plan_hash,"definition":{"path":str(definition),"sha256":digest_file(definition)},"manifest":{"path":str(manifest),"sha256":digest_file(manifest)},"registry_rank":rank,"admission_stages":cfg["admission_stages"],"actual_stage":"definition_only"})
        plan["rows"].append({"registry_rank":rank,"case_id":case,"physical_case_id":cfg["physical_case_id"],"parameters":cfg["parameters"],"physical_condition_sha256":phys_hash,"source_plan_condition_sha256":plan_hash,"definition_path":str(definition),"definition_sha256":digest_file(definition),"manifest_path":str(manifest),"manifest_sha256":digest_file(manifest),"admission_stages":cfg["admission_stages"],"actual_stage":"definition_only","request_hashes":None})
    # Plan has no circular references and can now be hashed.
    plan["rows"] = sorted(plan["rows"], key=lambda x:x["registry_rank"])
    write_json(package/"source-plan.json", plan)
    plan_hash = digest_file(package/"source-plan.json")
    # Patch owner source plan hash and write requests with final source plan hash.
    for idx,cfg in enumerate(configs):
        case=cfg["case_id"]; owner_path=owner_paths[idx]; manifest=manifest_paths[idx]; definition=package/"definitions"/f"{case}_Def.xml"
        owner=load_json(owner_path); owner["source_plan_sha256"]=plan_hash; owner["source_plan_path"]=str(package/"source-plan.json");
        # Keep the canonical plan condition stable; it intentionally excludes
        # source-plan hash to avoid self-reference.
        write_json(owner_path, owner)
        owner_hash=digest_file(owner_path)
        gencase,gencase_path=make_gencase_request(cfg,definition,owner_path,manifest,registry,package)
        qa,qa_path=make_qa_request(cfg,definition,owner_path,gencase_path,package)
        native,native_path=make_native_request(cfg,definition,owner_path,qa_path,gencase_path,package)
        for req,path in ((gencase,gencase_path),(qa,qa_path),(native,native_path)):
            # Bind owner/plan hashes and input hashes for only immutable source
            # metadata.  Generated outputs stay deferred/null.
            req["physical_condition_sha256"]=owner["physical_condition_sha256"]
            req["source_plan_condition_sha256"]=owner["source_plan_condition_sha256"]
            req["input_sha256"]={str(f):digest_file(f) for f in [Path(x) for x in req["input_files"]] if f.is_file()}
            if req is native:
                req["physical_binding_sha256"]=owner_hash
                req["owner_binding"]={"path":str(owner_path),"sha256":owner_hash}
            write_json(path,req)
            request_records.append({"case_id":case,"kind":req["cpu_task_kind"] if req["kind"]=="cpu" else "native_solver","path":str(path),"sha256":digest_file(path),"launch_allowed":False,"status":req["status"]})
        # Put request hashes into plan rows only after requests exist; write a
        # separate index to avoid changing the source plan hash in owner binding.
        plan["rows"][idx]["request_hashes"]={"gencase":digest_file(gencase_path),"initial_native_qa":digest_file(qa_path),"native":digest_file(native_path)}
    write_json(package/"requests/index.json",{"schema":"ds02.f4.first24.disabled-request-index.v1","source_plan":{"path":str(package/"source-plan.json"),"sha256":digest_file(package/"source-plan.json")},"rows":request_records,"launch_allowed":False})
    write_json(package/"source-plan-request-hashes.json",{"schema":"ds02.f4.first24.source-plan-request-hashes.v1","source_plan":{"path":str(package/"source-plan.json"),"sha256":digest_file(package/"source-plan.json")},"rows":plan["rows"],"note":"sidecar only; source-plan hash intentionally excludes request hashes to avoid circular input closure"})
    # Actual evidence audits use JSON only and intentionally distinguish scope.
    anchors=visual_anchor_audit(); fallback=actual_fallback_audit()
    write_json(package/"evidence/accepted-visual-anchors.json",anchors)
    write_json(package/"evidence/fallback6-actual-product-audit.json",fallback)
    first24_ids=[c["case_id"] for c in configs]
    fallback_ids=[r["case_id"] for r in fallback["rows"]]
    anchor_ids=[r["case_id"] for r in anchors["rows"]]
    # Confirm exact first24 directories have no actual external product
    external_presence=[]
    for case in first24_ids:
        d=DATA_ROOT/case
        json_receipts=sorted(d.rglob("execution-receipt.json")) if d.is_dir() else []
        external_presence.append({"case_id":case,"external_case_directory":d.is_dir(),"json_execution_receipt_count":len(json_receipts),"actual_evidence_bound":False})
    audit={
        "schema":"ds02.f4.first24.coverage-audit.v1","family_id":FAMILY,"scope_id":PACKAGE_NAME,
        "at_build_policy":"JSON/XML/code metadata only; no BI4/H5/CSV/VTK/scientific payload read or hash",
        "first24_definition":{"source":"case_registry.jsonl rows 1..24 (zero-based ranks 0..23)","mechanism":"finite_drop_pool","count":24,"unique":len(set(first24_ids))==24,"case_ids":first24_ids},
        "stage_coverage":{"definition_source":24,"actual_gencase":0,"actual_initial_qa":0,"actual_native":0,"actual_typed":0,"actual_xmf":0,"actual_render":0,"visual_accepted_exact_first24":0},
        "external_presence":external_presence,
        "remaining_first24_requests":{"count":24,"status":"all disabled; no actual first24 launch found","gencase_request_index":str(package/"requests/index.json"),"native_gated":True},
        "accepted_visual_anchors":{"count":3,"path":str(package/"evidence/accepted-visual-anchors.json"),"scope_relation":"outside_registry_first24_exact_tuples","does_not_increment_first24":True},
        "fallback6_actual_products":{"count":6,"path":str(package/"evidence/fallback6-actual-product-audit.json"),"scope_relation":"DP010 lattice-aligned center cases, not exact registry first24 tuples","does_not_increment_first24":True},
        "negative_evidence":{"internal8_root216":"retained outside this package; no reuse/promotion","old_failures":"preserved"},
        "source_only_guards":{"launch_allowed":False,"jobs_started_by_source":False,"arrays_read_by_source":False,"scientific_payloads_read":[],"shared_registry_modified":False,"production_approval":False,"precision_status":"not_accepted","q_n":"not_granted"},
        "claim_boundary":"Visual count 3 and six actual fallback products are recorded as separate evidence. No row is promoted to first24 actual/visual/precision status by this audit.",
    }
    write_json(package/"coverage-audit.json",audit)
    write_json(package/"manifest.json",{"schema":"ds02.f4.first24.coverage-handoff-manifest.v1","family_id":FAMILY,"scope_id":PACKAGE_NAME,"source_plan":json_path(package/"source-plan.json"),"coverage_audit":json_path(package/"coverage-audit.json"),"accepted_visual_anchor_audit":json_path(package/"evidence/accepted-visual-anchors.json"),"fallback_product_audit":json_path(package/"evidence/fallback6-actual-product-audit.json"),"definition_count":24,"owner_count":24,"disabled_request_count":72,"launch_allowed":False,"source_only":True,"future_artifact_hashes":None})
    return package


def write_docs(package: Path) -> None:
    (package/"README.md").write_text(f'''# F4 first24 coverage audit and disabled handoff (091)\n\nThis scoped package audits the frozen F4 `case_registry.jsonl` first24 rows (the finite-drop nested24 set) and prepares source-only DP010 definitions plus disabled Root-owned GenCase, initial-QA, and Root230 native requests. It does not launch a job or make a scientific/visual claim.\n\nThe three accepted F4 visual decisions are recorded separately as centered/endpoint anchors. The six DP010 lattice-aligned cases with Root263/271 products are recorded separately as actual fallback products. Their tuples differ from every exact first24 registry row, so this package does not silently count or bind them as first24 cases. All exact first24 rows remain `definition_only` with future GenCase/QA/native/typed/XMF/render hashes null.\n\nOnly JSON/XML/code metadata was read to build this package. No BI4, H5, CSV, VTK, solver output, scientific array, shared registry, or ledger was read or modified. The generated XML definitions mutate only the falling-drop point x/y/z and `mkfluid=1` z velocity relative to the frozen DP010 source; pool/tank/controls, DP=.01, `TimeMax=1.2`, `TimeOut=.001`, and the no-forcing/no-mdbc recipe remain fixed.\n\nRoot must rebind the exact adopted scoped commit and actual GenCase/QA receipts before enabling any request. The native request is gated on actual GenCase and initial-QA pass, and no downstream typed/XMF/render request is enabled by this package.\n\nGenerated files: `coverage-audit.json`, `source-plan.json`, `source-plan-request-hashes.json`, 24 XML definitions, 24 owner bindings, 72 disabled requests, and JSON-only evidence audits under `evidence/`.\n''',encoding='utf-8')
    (package/"tests/test_source_contract.py").write_text('''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n\ndef load(name):\n    return json.loads((ROOT / name).read_text(encoding="utf-8"))\n\ndef test_first24_are_distinct_definition_only():\n    audit = load("coverage-audit.json")\n    rows = audit["first24_definition"]["case_ids"]\n    assert len(rows) == 24 and len(set(rows)) == 24\n    assert audit["stage_coverage"] == {"definition_source":24,"actual_gencase":0,"actual_initial_qa":0,"actual_native":0,"actual_typed":0,"actual_xmf":0,"actual_render":0,"visual_accepted_exact_first24":0}\n\ndef test_no_source_launch_or_scientific_payload_read():\n    audit = load("coverage-audit.json")\n    guards = audit["source_only_guards"]\n    assert guards["launch_allowed"] is False\n    assert guards["jobs_started_by_source"] is False\n    assert guards["arrays_read_by_source"] is False\n    assert guards["scientific_payloads_read"] == []\n\ndef test_all_requests_disabled_and_future_outputs_null():\n    index = load("requests/index.json")\n    assert len(index["rows"]) == 72\n    assert all(row["launch_allowed"] is False for row in index["rows"])\n    for path in (ROOT / "requests").glob("*.request.json"):\n        d = json.loads(path.read_text(encoding="utf-8"))\n        assert d["launch_allowed"] is False and d["disabled"] is True\n        assert d["source_only"] is True\n        assert d["production_approval"] is False\n        assert d["precision_status"] == "not_accepted"\n        assert d["q_n_status"] == "not_granted"\n''',encoding='utf-8')


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--worktree",type=Path,default=WORKTREE_DEFAULT); ap.add_argument("--write-docs",action="store_true")
    a=ap.parse_args(); pkg=build(a.worktree.resolve());
    if a.write_docs: write_docs(pkg)
    print(pkg)
    return 0

if __name__ == "__main__": raise SystemExit(main())

#!/usr/bin/env python3
"""Materialize the F7 fresh074 source-only next24 package.

This builder writes bounded XML/JSON/code metadata only.  It does not invoke
GenCase, PartVTK, DualSPHysics, a converter, or a renderer and it never opens
BI4/H5/CSV/motion payloads.  Root later enables the registered workers after
reviewing each disabled request.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

WT = Path("/home/jade/.codex/worktrees/ds-data-02-f7/DualSPHysics")
R = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
H = R / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PACKAGE = WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_074_stage1_next24_target_angles_v1"
SCOPE = "root_followup_074_stage1_next24_target_angles_v1"
GROUP = "F7_STAGE1_NEXT24_TARGET_ANGLES"
MOTION_ATTEMPT = "root-stage1-f7-next24-motion-preparation-074"
GENCASE_BIND_ATTEMPT = "root-stage1-f7-next24-gencase-binding-074"
QA_BIND_ATTEMPT = "root-stage1-f7-next24-native-qa-binding-074"
NATIVE_QA_ATTEMPT = "root-stage1-f7-next24-native-initial-qa-074"
NATIVE_ATTEMPT_SUFFIX = "full601-native-qualification-074"
MOTION_MODULE = H.parent / "families/F7/handoff_20261003/root_actual_quintic_target_verified_recipe_preparation_020/selected_owner_motion.py"
SOURCE_TEMPLATE = WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F7/handoff_20261003/root_followup_070_stage1_first24_target_angles_v1/source/F7_OBSTACLE_QUINTIC_B08_A031_Def.xml"
GOAL = H.parent / "GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
PYTHON = R / "lagrangian-fluid-lab/.venv/bin/python"
RUNTIME = R / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = R / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RESOURCE = H / "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
HOME_POLICY = H / "root_stage1_native_home_floor_eight_solver_dispatch_230/root_native_home_floor_inventory_policy.py"
HOME_LAUNCH = H / "root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py"
GPU_POLICY = H / "root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
ROOT230 = H / "root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
ROOT003 = H / "root_native_source_preflight_tools_003/gencase.py"

# Half-degree values are deliberately between every existing integer axis
# value in the reviewed 30--65 degree envelope, with four high-end values to
# retain coverage of the accepted envelope.  P5 in a case ID means exactly
# +0.5 degree; the numeric value remains explicit in all metadata.
AMPLITUDES = (
    30.5, 31.5, 32.5, 33.5, 34.5, 35.5, 36.5, 37.5,
    38.5, 39.5, 40.5, 41.5, 42.5, 43.5, 44.5, 45.5,
    46.5, 47.5, 48.5, 49.5, 50.5, 54.5, 59.5, 64.5,
)
EXISTING_AMPLITUDES = (30.0, 31.0, 32.0, 33.0, 34.0, 35.0, 36.0, 37.0,
                       38.0, 39.0, 40.0, 41.0, 42.0, 43.0, 44.0, 45.0,
                       46.0, 47.0, 48.0, 49.0, 50.0, 55.0, 60.0, 65.0)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def obj_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    # Preserve the selected interpreter spelling (`.../.venv/bin/python`) and
    # other provenance paths.  Path.resolve() would collapse that symlink to
    # /usr/bin/python3.10 and break the Root L/.venv contract.
    return str(path if path.is_absolute() else (WT / path).absolute())


def case_token(amplitude: float) -> str:
    whole = int(amplitude)
    return f"A{whole:03d}P5"


def case_id(amplitude: float) -> str:
    return f"F7_OBSTACLE_QUINTIC_B08_{case_token(amplitude)}"


def geometry() -> dict[str, Any]:
    return {
        "tank": {"label": "source062 finite explicit-wet tank, open top", "low_m": [-0.6, -0.4, 0.0], "size_m": [1.2, 0.8, 0.6]},
        "paddle": {"label": "source062 all-filled moving type-1 obstacle", "low_m": [-0.07, -0.24, 0.05], "size_m": [0.06, 0.48, 0.48]},
        "wet_slab_0": {"label": "source062 explicit native cell-center slab 0", "low_m": [-0.54, -0.34, 0.06], "size_m": [0.460000001, 0.680000001, 0.420000001], "mkfluid": 1},
        "wet_slab_1": {"label": "source062 explicit native cell-center slab 1", "low_m": [0.0, -0.34, 0.06], "size_m": [0.540000001, 0.680000001, 0.420000001], "mkfluid": 1},
        "wet_slab_2": {"label": "source062 explicit native cell-center slab 2", "low_m": [-0.06, -0.34, 0.06], "size_m": [0.040000001, 0.080000001, 0.420000001], "mkfluid": 1},
        "wet_slab_3": {"label": "source062 explicit native cell-center slab 3", "low_m": [-0.06, 0.26, 0.06], "size_m": [0.040000001, 0.080000001, 0.420000001], "mkfluid": 1},
    }


def physical_binding(cid: str, amplitude: float) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": "F7",
        "physical_case_id": cid,
        "lineage_group_id": "F7_OBSTACLE_QUINTIC_B08_SHARED_EXPLICIT_WET_MOTHER_GEOMETRY",
        "paired_background_id": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE",
        "geometry_family_id": "finite_open_top_explicit_wet_tank_rotating_paddle_v1",
        "control_family_id": "quintic_target_two_cycles_endpoint_amplitude_v1",
        "geometry": geometry(),
        "controls": {"boundary": 1, "step_algorithm": 2, "kernel": 2, "density_dt": 3, "density_dt_value": 0.1, "viscosity": {"treatment": 1, "value": 0.05}, "gravity_m_s2": [0.0, 0.0, -9.81]},
        "parameters": {
            "amplitude_deg": amplitude,
            "amplitude_encoding": case_token(amplitude),
            "analytic_target": "two finite symmetric quintic cycles active on 0..8 s, neutral rest on 8..12 s",
            "cycle_schedule": "two finite symmetric cycles; active window 0..8 s; neutral/rest window 8..12 s",
            "explicit_wet_slab_count": 4,
            "motion_asset_name": "motion_obstacle_quintic.dat",
            "motion_function": "theta=A*(10*u^3-15*u^4+6*u^5), u in [0,1] per half-cycle",
            "motion_reader": "piecewise_linear_absolute_angle_increment",
            "motion_sampling_dt_s": 0.001,
            "moving_obstacle_boundary_mk": 2,
            "pivot_p1_m": [-0.04, 0.0, 0.05],
            "pivot_p2_m": [-0.04, 0.0, 1.05],
            "rotation_axis": "p1_to_p2",
            "target_angle_units": "degrees",
        },
        "event_window": {"time_start_s": 0.0, "time_end_s": 12.0, "sequence": ["initial static explicit wet fill", "two finite symmetric quintic target rotation cycles", "neutral pose rest and residual fluid exchange"], "right_censor_policy": "prospective full native window; no Q-N or production claim before actual evidence"},
        "initial_state": {"velocities_m_per_s": {"fluid": [0.0, 0.0, 0.0]}, "continuum_mass_by_source_kg": {"fluid": 320.1984}, "mass_policy": "native 325.60001628 kg remains separate and is never rescaled"},
    }


def source_payload(cid: str, amplitude: float) -> dict[str, Any]:
    return {
        "physical_case_id": cid,
        "axis": "paddle_amplitude_deg",
        "amplitude_deg": f"{amplitude:.1f}",
        "mother": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE",
        "geometry_control_family": "F7_OBSTACLE_QUINTIC_B08_SHARED_EXPLICIT_WET_MOTHER_GEOMETRY",
        "motion_source": "endpoint-specific motion_obstacle_quintic.dat generated from the bound selected_owner_motion module",
        "motion_profile": "two finite symmetric quintic cycles, active 0..8 s, rest 8..12 s",
        "dp_m": "0.02",
        "time_max_s": "12.0",
        "time_out_s": "0.02",
        "pivot_p1_m": ["-0.04", "0", "0.05"],
        "pivot_p2_m": ["-0.04", "0", "1.05"],
        "native_reader": "piecewise_linear_absolute_angle_increment",
        "native_sampled_regular": "not C2",
    }


def base_inputs() -> list[Path]:
    return [PYTHON, RUNTIME, STRICT, GOAL, RESOURCE, HOME_POLICY, HOME_LAUNCH, GPU_POLICY, ROOT230, MOTION_MODULE, GENCASE, PARTVTK, SOLVER, ROOT003]


def input_map(paths: list[Path]) -> dict[str, str]:
    result = {}
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(p)
        result[rel(p)] = sha(p)
    return result


def common_request(case: str | None = None) -> dict[str, Any]:
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F7",
        "scope_id": SCOPE,
        "status": "source_only_disabled",
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "launch_owner": "root",
        "root_review_required": True,
        "future_hashes_null": True,
        "precision_status": "not_accepted",
        "q_n_status": "not_assessed",
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "no_arrays_read": True,
        "no_jobs_started": True,
        "no_shared_registry_write": True,
        "resource_approval": rel(RESOURCE),
        "resource_approval_sha256": sha(RESOURCE),
        "strict_dispatch_entrypoint": rel(STRICT),
        "strict_dispatch_sha256": sha(STRICT),
        "root230_entrypoint": rel(ROOT230),
        "root230_entrypoint_sha256": sha(ROOT230),
        "gpu_policy": rel(GPU_POLICY),
        "gpu_policy_sha256": sha(GPU_POLICY),
        "root_inventory_policy": rel(HOME_POLICY),
        "root_inventory_policy_source_sha256": sha(HOME_POLICY),
        "home_floor_policy": rel(HOME_POLICY),
        "home_floor_policy_sha256": sha(HOME_POLICY),
        "worktree_root": rel(WT),
        "resource_window": {"gpu_hours_total": 512, "cpu_core_hours_total": 3840, "qualification_hours": 1024, "production_hours": 720, "home_floor_gib": 500, "nvme_floor_gib": 100, "shared_gpu_lease": "Root230 eight-live-UUID lease; foreign-process protection required"},
        "case_id": case,
    }


def write_worker_files() -> None:
    # The actual worker code is kept in standalone files so Root can bind and
    # hash it.  These files are added by this builder from immutable strings.
    motion = r'''#!/usr/bin/env python3
"""Root-enabled motion preparation for F7 fresh074; no solver or GenCase."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA = "ds02.f7.next24-target-angle-source-preparation.v1"
def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def dump(p,v): Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--plan",required=True,type=Path); ap.add_argument("--output-root",required=True,type=Path); ap.add_argument("--execute",action="store_true"); a=ap.parse_args()
    if not a.execute: raise SystemExit("Root must explicitly enable motion preparation")
    plan=load(a.plan); assert plan["launch_allowed"] is False and plan["source_only"] is True
    mp=Path(plan["selected_motion_module"]); assert sha(mp)==plan["selected_motion_module_sha256"]
    spec=importlib.util.spec_from_file_location("f7_next24_motion",mp); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    out=a.output_root; out.mkdir(parents=True,exist_ok=False); rows=[]
    for ep in plan["endpoints"]:
        case=ep["endpoint_id"]; src=Path(a.plan).parent/ep["source_definition_clone"]; assert sha(src)==ep["source_definition_clone_sha256"]
        tree=ET.parse(src).getroot(); d=tree.find("casedef/geometry/definition"); params={n.get("key"):n.get("value") for n in tree.findall("execution/parameters/parameter")}; mv=tree.find("casedef/motion/objreal[@ref='2']/mvrotfile")
        assert d is not None and d.get("dp")=="0.02" and params.get("TimeMax")=="12" and params.get("TimeOut")=="0.02" and mv is not None and mv.find("file").get("name")=="motion_obstacle_quintic.dat"
        assert [mv.find("axisp1").get(k) for k in ("x","y","z")] == ["-0.04","0","0.05"] and [mv.find("axisp2").get(k) for k in ("x","y","z")] == ["-0.04","0","1.05"]
        case_root=out/case; case_root.mkdir(); text=mod.generate_motion_dat_content(float(ep["amplitude_deg"]),12.0,0.001); rows_raw=[x.split() for x in text.splitlines() if x and not x.startswith("#")]; assert len(rows_raw)==12001 and rows_raw[0]==["0","0"] and float(rows_raw[-1][0])==12.0 and float(rows_raw[-1][1])==0.0
        motion=case_root/"motion_obstacle_quintic.dat"; msha=mod.write_motion_file_exclusive(motion,text); definition=case_root/f"{case}_Def.xml"; definition.write_text(mod.generate_smooth_c2_definition_xml(src,motion.name),encoding="utf-8")
        rows.append({"endpoint_id":case,"physical_case_id":case,"amplitude_deg":ep["amplitude_deg"],"source_definition":str(src),"source_definition_sha256":sha(src),"prepared_definition":str(definition),"prepared_definition_sha256":sha(definition),"motion_file":str(motion),"motion_file_sha256":msha,"motion_rows":len(rows_raw),"native_reader":"piecewise_linear_absolute_angle_increment","native_sampled_regular":"not C2","future_gencase_receipt_sha256":None})
    dump(out/"motion-source-preparation.json",{"schema":SCHEMA,"scope_id":plan["scope_id"],"source_plan":str(a.plan),"source_plan_sha256":sha(a.plan),"endpoint_count":len(rows),"endpoints":rows,"gencase":"not performed","native_qa":"not performed","solver":"forbidden","conversion":"forbidden","rendering":"forbidden","launch_allowed":False,"future_hashes_null":False})
if __name__=="__main__": main()
'''
    (PACKAGE / "workers/prepare_f7_next24_motion.py").write_text(motion, encoding="utf-8")
    (PACKAGE / "workers/prepare_f7_next24_motion.py").chmod(0o755)

    gencase_bind = r'''#!/usr/bin/env python3
"""Bind Root003 GenCase inputs after actual motion preparation; metadata only."""
from __future__ import annotations
import argparse, hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text())
def dump(p,v): Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+"\n")
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--plan",required=True,type=Path); ap.add_argument("--motion-report",required=True,type=Path); ap.add_argument("--motion-receipt",required=True,type=Path); ap.add_argument("--prepared-root",required=True,type=Path); ap.add_argument("--output-dir",required=True,type=Path); a=ap.parse_args()
 plan=load(a.plan); report=load(a.motion_report); receipt=load(a.motion_receipt); assert report.get("schema")=="ds02.f7.next24-target-angle-source-preparation.v1" and report.get("endpoint_count")==24; assert receipt.get("status")=="completed" and receipt.get("returncode")==0
 byid={x["endpoint_id"]:x for x in report["endpoints"]}; assert set(byid)=={x["endpoint_id"] for x in plan["endpoints"]}; out=a.output_dir; out.mkdir(parents=True,exist_ok=False); entries=[]
 for ep in plan["endpoints"]:
  case=ep["endpoint_id"]; row=byid[case]; definition=Path(row["prepared_definition"]); motion=Path(row["motion_file"]); assert definition.is_file() and motion.is_file() and sha(definition)==row["prepared_definition_sha256"] and sha(motion)==row["motion_file_sha256"]
  tree=ET.parse(definition).getroot(); d=tree.find("casedef/geometry/definition"); params={n.get("key"):n.get("value") for n in tree.findall("execution/parameters/parameter")}; assert d is not None and d.get("dp")=="0.02" and params.get("TimeMax")=="12" and params.get("TimeOut")=="0.02"
  b={"schema":"ds02.f7.next24.root003-gencase-binding.v1","family_id":"F7","scope_id":plan["scope_id"],"case_id":case,"physical_case_id":case,"amplitude_deg":ep["amplitude_deg"],"physical_condition_sha256":ep["physical_condition_sha256"],"canonical_physical_binding_sha256":ep["canonical_physical_binding_sha256"],"definition":str(definition),"definition_sha256":sha(definition),"gencase":str(Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")),"gencase_sha256":"a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226","threads":2,"dp_m":0.02,"expected_fluid":40700,"assets":[{"source":str(motion),"sha256":sha(motion),"relative_name":"motion_obstacle_quintic.dat"}],"predictions":{"fixed":27495,"moving":1984,"floating":0,"fluid":40700,"total":70179,"actual_counts_must_be_read_from_generated_xml":True,"forecast_only":True},"source_plan":str(a.plan),"source_plan_sha256":sha(a.plan),"motion_report":str(a.motion_report),"motion_report_sha256":sha(a.motion_report),"motion_receipt":str(a.motion_receipt),"motion_receipt_sha256":sha(a.motion_receipt),"launch_allowed":False,"execution_allowed":False,"arrays_read_by_binder":False}
  bp=out/f"{case}.binding.json"; dump(bp,b); entries.append({"case_id":case,"binding":str(bp),"binding_sha256":sha(bp)})
 dump(out/"gencase-bindings.json",{"schema":"ds02.f7.next24.gencase-bindings.v1","scope_id":plan["scope_id"],"source_plan_sha256":sha(a.plan),"motion_report_sha256":sha(a.motion_report),"motion_receipt_sha256":sha(a.motion_receipt),"bindings":entries,"launch_allowed":False,"arrays_read_by_binder":False})
if __name__=="__main__": main()
'''
    (PACKAGE / "scripts/bind_next24_gencase.py").write_text(gencase_bind, encoding="utf-8")
    (PACKAGE / "scripts/bind_next24_gencase.py").chmod(0o755)

    qa_bind = r'''#!/usr/bin/env python3
"""Bind actual GenCase XML/BI4 metadata for the fresh074 PartVTK QA worker."""
from __future__ import annotations
import argparse, hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text())
def dump(p,v): Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+"\n")
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--plan",required=True,type=Path); ap.add_argument("--gencase-bindings",required=True,type=Path); ap.add_argument("--output-dir",required=True,type=Path); a=ap.parse_args(); plan=load(a.plan); group=load(a.gencase_bindings); assert group.get("schema")=="ds02.f7.next24.gencase-bindings.v1" and len(group.get("bindings",[]))==24
 endpoint={x["endpoint_id"]:x for x in plan["endpoints"]}; cases=[]
 for entry in group["bindings"]:
  b=load(entry["binding"]); case=b["case_id"]; assert case in endpoint and b.get("launch_allowed") is False
  raw=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7")/case; attempt=raw/f"root-stage1-f7-{case.lower()}-genuine-gencase-074"; receipt=attempt/"execution-receipt.json"; folder=attempt/"prepared"/case; xml=folder/f"{case}.xml"; bi4=folder/f"{case}.bi4"; report=folder/"prepared-input-report.json"
  for p in (receipt,xml,bi4,report): assert p.is_file(), f"{case}: missing {p}"
  rec=load(receipt); assert rec.get("status")=="completed" and rec.get("returncode")==0
  tree=ET.parse(xml).getroot(); particles=tree.find("./execution/particles"); constants=tree.find("./execution/constants"); definition=tree.find("./casedef/geometry/definition"); assert particles is not None and constants is not None and definition is not None and constants.find("data2d").get("value")=="false" and definition.get("dp")=="0.02"
  params={n.get("key"):n.get("value") for n in tree.findall("./execution/parameters/parameter")}; assert params.get("TimeMax")=="12" and params.get("TimeOut")=="0.02"
  counts={name:sum(int(n.get("count")) for n in particles.findall(name)) for name in ("fixed","moving","floating","fluid")}; assert counts=={"fixed":27495,"moving":1984,"floating":0,"fluid":40700} and int(particles.get("np"))==70179
  cases.append({"case_id":case,"physical_case_id":case,"amplitude_deg":endpoint[case]["amplitude_deg"],"physical_condition_sha256":endpoint[case]["physical_condition_sha256"],"canonical_physical_binding_sha256":endpoint[case]["canonical_physical_binding_sha256"],"gencase_receipt":str(receipt),"gencase_receipt_sha256":sha(receipt),"prepared_input_report":str(report),"prepared_input_report_sha256":sha(report),"generated_xml":str(xml),"generated_xml_sha256":sha(xml),"generated_bi4":str(bi4),"generated_bi4_sha256":sha(bi4),"generated_definition":b["definition"],"generated_definition_sha256":b["definition_sha256"],"generated_motion":b["assets"][0]["source"],"generated_motion_sha256":b["assets"][0]["sha256"],"expected":{"total_particles":70179,"fixed_particles":27495,"moving_particles":1984,"floating_particles":0,"fluid_particles":40700,"solver_dimension":3,"dp_m":0.02,"time_max_s":12.0,"time_out_s":0.02,"motion_rows":12001,"type_mk_blocks":[{"name":"fixed","begin":0,"count":27495,"type":0,"mk":10},{"name":"moving","begin":27495,"count":1984,"type":1,"mk":12},{"name":"fluid","begin":29479,"count":40700,"type":3,"mk":2}],"velocity_zero_tolerance_m_per_s":1e-12,"native_fluid_mass_kg":325.60001628,"continuum_envelope_mass_kg":320.1984,"mass_tolerance_kg":1e-8}})
 out=a.output_dir; out.mkdir(parents=True,exist_ok=False); dump(out/"binding.json",{"schema":"ds02.f7.next24.actual-gencase-native-qa-binding.v1","scope_id":plan["scope_id"],"partvtk":"/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64","partvtk_sha256":"62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00","source_plan":{"source_absolute_path":str(a.plan),"source_sha256":sha(a.plan)},"gencase_binding_group":{"source_absolute_path":str(a.gencase_bindings),"source_sha256":sha(a.gencase_bindings)},"cases":cases,"launch_allowed":False,"arrays_read_by_binder":False,"claim_boundary":"Actual GenCase XML/BI4 metadata only; official PartVTK initial UID/type/Mk/mass/3D/no-overlap QA remains pending."})
if __name__=="__main__": main()
'''
    (PACKAGE / "scripts/bind_next24_native_qa.py").write_text(qa_bind, encoding="utf-8")
    (PACKAGE / "scripts/bind_next24_native_qa.py").chmod(0o755)

    qa_worker = r'''#!/usr/bin/env python3
"""Strict fresh074 initial native QA; Root runs this only after actual GenCase.
The source agent never invokes it.  Runtime arrays are isolated to this job's
official PartVTK CSV output and are never written to the worktree.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
FIELDS=['Pos.x [m]','Pos.y [m]','Pos.z [m]','Zone','Idp','Type','Mk','Mass [kg]','Vel.x [m/s]','Vel.y [m/s]','Vel.z [m/s]','Rhop [kg/m^3]','Press [Pa]']
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text())
def req(x,m):
 if not x: raise RuntimeError(m)
def export(case,out,partvtk):
 bi4=Path(case['generated_bi4']); xml=Path(case['generated_xml']); dst=out/(case['case_id']+'-initial-all.csv'); req(not dst.exists(),'refusing overwrite: '+str(dst)); before=sha(bi4)
 cmd=[partvtk,'-filedata',str(bi4),'-filexml',str(xml),'-threads:2','-savecsv',str(dst),'-onlytype:+all','-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone','-csvsep:1']; subprocess.run(cmd,cwd=str(out),check=True); req(sha(bi4)==before,'PartVTK mutated BI4'); req(dst.is_file(),'CSV missing')
 with dst.open(newline='',encoding='utf-8') as f: rows=list(csv.reader(f))
 hi=next((i for i,row in enumerate(rows) if 'Pos.x [m]' in row),None); req(hi is not None,'official CSV header missing'); header=rows[hi]; idx=[header.index(k) for k in FIELDS]; data=rows[hi+1:]
 while data and not any(x.strip() for x in data[-1]): data.pop()
 req(len(data)==case['expected']['total_particles'],f'CSV rows {len(data)} != {case["expected"]["total_particles"]}'); vals=np.asarray([[float(row[i]) for i in idx] for row in data],dtype=float); req(vals.shape==(case['expected']['total_particles'],13),'CSV shape mismatch'); return vals,{'official_csv':str(dst),'official_csv_sha256':sha(dst),'initial_bi4_sha256':before,'csv_header_index':hi,'partvtk_command':cmd}
def check_xml(case):
 root=ET.parse(case['generated_xml']).getroot(); c=root.find('./execution/constants'); p=root.find('./execution/particles'); d=root.find('./casedef/geometry/definition'); req(c is not None and p is not None and d is not None,'XML sections missing'); req(c.find('data2d').get('value')=='false','not actual 3D'); params={n.get('key'):n.get('value') for n in root.findall('./execution/parameters/parameter')}; req(d.get('dp')=='0.02' and params.get('TimeMax')=='12' and params.get('TimeOut')=='0.02','native recipe changed'); blocks={}
 for b in case['expected']['type_mk_blocks']:
  n=p.find(b['name']); req(n is not None,'block missing '+b['name']); got={k:int(n.get(k)) for k in ('begin','count','type','mk')}; req(got=={k:b[k] for k in ('begin','count','type','mk')},'XML block mismatch'); blocks[b['name']]=got
 req(int(p.get('np'))==case['expected']['total_particles'],'XML total mismatch'); return {'xml_sha256':sha(case['generated_xml']),'native_type_mk_blocks':blocks}
def check(case,rows):
 e=case['expected']; req(np.isfinite(rows).all(),'nonfinite native field'); req(np.equal(rows[:,3:7],np.floor(rows[:,3:7])).all(),'categorical field nonintegral'); zone=rows[:,3].astype(np.int64); uid=rows[:,4].astype(np.int64); typ=rows[:,5].astype(np.int64); mk=rows[:,6].astype(np.int64); req(np.equal(zone,0).all(),'nonzero zone'); req(np.array_equal(np.sort(uid),np.arange(e['total_particles'])),'UID set/loss mismatch'); order=np.argsort(uid,kind='stable'); rows=rows[order]; typ=typ[order]; mk=mk[order]
 blocks=e['type_mk_blocks']; sets=[]
 for b in blocks:
  sl=slice(b['begin'],b['begin']+b['count']); req(np.equal(typ[sl],b['type']).all(),'Type mismatch'); req(np.equal(mk[sl],b['mk']).all(),'Mk mismatch'); sets.append({tuple(x) for x in rows[sl,:3]})
 req(np.all(rows[:,7]>0),'nonpositive weights'); req(np.all(rows[:,11]>0),'nonpositive density'); req(np.max(np.abs(rows[:,8:11]))<=e['velocity_zero_tolerance_m_per_s'],'initial velocity exceeds strict tolerance'); coords=rows[:,:3]; req(np.unique(coords,axis=0).shape[0]==len(rows),'initial coordinate overlap'); overlaps={'fixed_moving':len(sets[0]&sets[1]),'fixed_fluid':len(sets[0]&sets[2]),'moving_fluid':len(sets[1]&sets[2])}; req(all(v==0 for v in overlaps.values()),'pairwise initial overlap'); fluid=typ==3; req(int(fluid.sum())==e['fluid_particles'],'fluid count mismatch'); fc=coords[fluid]; req(all(np.unique(fc[:,i]).size>1 for i in range(3)),'fluid is not genuinely 3D'); mass=float(rows[fluid,7].sum()); req(np.isfinite(mass) and abs(mass-e['native_fluid_mass_kg'])<=e['mass_tolerance_kg'],f'native fluid mass mismatch {mass} vs {e["native_fluid_mass_kg"]}'); return {'all_13_fields_finite':True,'uid_exact_sorted_unique':True,'all_native_weights_positive':True,'all_native_densities_positive':True,'initial_velocity_zero_within_tolerance':True,'global_coordinate_unique':True,'pairwise_initial_overlap_counts':overlaps,'actual_3d':True,'fluid_count_exact':True,'official_CSV_fluid_mass_sum_kg':mass,'registered_native_fluid_mass_kg':e['native_fluid_mass_kg'],'continuum_envelope_mass_kg':e['continuum_envelope_mass_kg'],'mass_policy':'native unscaled; continuum comparison separate; no rescale'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--binding',required=True,type=Path); ap.add_argument('--output-dir',required=True,type=Path); a=ap.parse_args(); b=load(a.binding); req(b.get('schema')=='ds02.f7.next24.actual-gencase-native-qa-binding.v1','binding schema mismatch'); req(b.get('launch_allowed') is False,'binding unexpectedly enabled'); out=a.output_dir; out.mkdir(parents=True,exist_ok=True); result=[]
 for case in b['cases']:
  for key in ('gencase_receipt','prepared_input_report','generated_xml','generated_bi4','generated_definition','generated_motion'): req(Path(case[key]).is_file(),case['case_id']+' missing '+key)
  rec=load(case['gencase_receipt']); req(rec.get('status')=='completed' and rec.get('returncode')==0,case['case_id']+' GenCase not completed/0'); xc=check_xml(case); rows,prov=export(case,out,b['partvtk']); rc=check(case,rows); result.append({'case_id':case['case_id'],'physical_condition_sha256':case['physical_condition_sha256'],'canonical_physical_binding_sha256':case['canonical_physical_binding_sha256'],'native_particles':int(rows.shape[0]),'checks':{**xc,**prov,**rc},'passed':True})
 (out/'native-initial-qa.json').write_text(json.dumps({'schema':'ds02.f7.next24.actual-native-initial-qa.v1','scope_id':b['scope_id'],'binding':str(a.binding),'binding_sha256':sha(a.binding),'cases':result,'all_cases_passed':True,'independent_case_count_increment':0,'q_n':'not_granted','production_approval':'none','precision_status':'not_accepted','visual_acceptance':'not_assessed','claim_boundary':'Native initial UID/type/Mk/mass/3D/no-overlap QA only; no full12 dynamics, visual acceptance, Q-N, or production claim.'},indent=2)+'\n')
if __name__=='__main__': main()
'''
    (PACKAGE / "workers/run_f7_next24_native_initial_qa.py").write_text(qa_worker, encoding="utf-8")
    (PACKAGE / "workers/run_f7_next24_native_initial_qa.py").chmod(0o755)


def build() -> None:
    PACKAGE.mkdir(parents=True, exist_ok=True)
    for sub in ("metadata", "owners", "source", "requests/gencase", "requests/native", "workers", "scripts", "builders"):
        (PACKAGE / sub).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_TEMPLATE, PACKAGE / "source/_anchor_Def.xml")
    template_sha = sha(PACKAGE / "source/_anchor_Def.xml")
    endpoints=[]
    for index, amp in enumerate(AMPLITUDES, start=1):
        cid=case_id(amp); src=PACKAGE / "source" / f"{cid}_Def.xml"; shutil.copyfile(PACKAGE / "source/_anchor_Def.xml", src)
        payload=source_payload(cid, amp); source_hash=obj_sha(payload); binding=physical_binding(cid, amp); canonical_hash=obj_sha(binding)
        endpoints.append({"case_index":index,"endpoint_id":cid,"physical_case_id":cid,"role":"next24_half_degree_internal","amplitude_deg":amp,"axis":"paddle_amplitude_deg","amplitude_encoding":case_token(amp),"physical_condition_payload":payload,"physical_condition_sha256":source_hash,"canonical_physical_binding_sha256":canonical_hash,"source_definition_clone":f"../source/{cid}_Def.xml","source_definition_clone_sha256":sha(src),"prepared_definition_relative":f"prepared/{cid}/{cid}_Def.xml","prepared_motion_relative":f"prepared/{cid}/motion_obstacle_quintic.dat","gencase_output_relative":f"gencase/{cid}/{cid}","expected_fixed":27495,"expected_moving":1984,"expected_floating":0,"expected_fluid":40700,"expected_total":70179})
    plan={
        "schema":"ds02.f7.fresh074.next24-target-angle-source-plan.v1","scope_id":SCOPE,"family_id":"F7","source_only":True,"launch_allowed":False,
        "claim_boundary":"Prospective source-only next24. Each half-degree amplitude is a new physical motion condition in the reviewed 30--65 degree envelope. No GenCase, BI4, initial QA, full native, typed, visual, Q-N, precision, production, or family48 acceptance is claimed.",
        "new_angles_deg":list(AMPLITUDES),"new_case_count":24,"prospective_family_case_count":48,"existing_first24_axis_values_deg":list(EXISTING_AMPLITUDES),
        "registry_check":"metadata/path-name search of F7 WT and actual-data paths excluding BI4/CSV/H5/VTK/XMF/image arrays; all proposed IDs and half-degree values were absent",
        "visual_envelope":{"lower_deg":30.0,"upper_deg":65.0,"accepted_reference_cases":["F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE","F7_OBSTACLE_QUINTIC_B08_A030","F7_OBSTACLE_QUINTIC_B08_A035","F7_OBSTACLE_QUINTIC_B08_A065"],"visual_acceptance_of_new_cases":"pending Root; no interpolation credit"},
        "existing_registry":{"case_ids":["F7_OBSTACLE_QUINTIC_B08_A030","F7_OBSTACLE_QUINTIC_B08_A031","F7_OBSTACLE_QUINTIC_B08_A032","F7_OBSTACLE_QUINTIC_B08_A033","F7_OBSTACLE_QUINTIC_B08_A034","F7_OBSTACLE_QUINTIC_B08_A035","F7_OBSTACLE_QUINTIC_B08_A036","F7_OBSTACLE_QUINTIC_B08_A037","F7_OBSTACLE_QUINTIC_B08_A038","F7_OBSTACLE_QUINTIC_B08_A039","F7_OBSTACLE_QUINTIC_B08_A040","F7_OBSTACLE_QUINTIC_B08_A041","F7_OBSTACLE_QUINTIC_B08_A042","F7_OBSTACLE_QUINTIC_B08_A043","F7_OBSTACLE_QUINTIC_B08_A044","F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE","F7_OBSTACLE_QUINTIC_B08_A046","F7_OBSTACLE_QUINTIC_B08_A047","F7_OBSTACLE_QUINTIC_B08_A048","F7_OBSTACLE_QUINTIC_B08_A049","F7_OBSTACLE_QUINTIC_B08_A050","F7_OBSTACLE_QUINTIC_B08_A055","F7_OBSTACLE_QUINTIC_B08_A060","F7_OBSTACLE_QUINTIC_B08_A065"],"amplitudes_deg":list(EXISTING_AMPLITUDES),"collisions":[]},
        "mother":{"physical_case_id":"F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE","source_definition_template":f"source/{case_id(AMPLITUDES[0])}_Def.xml","geometry_control_reused":True,"no_copy_of_binary_or_payload":True},
        "selected_motion_module":rel(MOTION_MODULE),"selected_motion_module_sha256":sha(MOTION_MODULE),"source_definition":rel(PACKAGE/"source"/f"{case_id(AMPLITUDES[0])}_Def.xml"),"source_definition_sha256":sha(PACKAGE/"source"/f"{case_id(AMPLITUDES[0])}_Def.xml"),"package_root":rel(PACKAGE),
        "fixed_physical_and_numerical_source":{"dp_m":0.02,"physical_window_s":[0.0,12.0],"time_max_s":12.0,"time_out_s":0.02,"native_frame_count":601,"native_save_interval_s":0.02,"motion_rows":12001,"motion_source_sampling_s":0.001,"active_cycles_s":[0.0,8.0],"rest_window_s":[8.0,12.0],"analytic_target":"two finite symmetric quintic cycles","analytic_target_regular":"C2","native_reader":"piecewise_linear_absolute_angle_increment","native_sampled_regular":"not C2","geometry_policy":"retain exact explicit-wet tank, four slabs, all-filled type-1 paddle, and pivot","control_policy":"retain Boundary1, StepAlgorithm2, Kernel2, viscosity 0.05, DensityDT3/0.1, gravity","moving_type":1,"native_types":{"fixed":0,"moving":1,"fluid":3},"native_source_particle_counts":{"fixed":27495,"moving":1984,"floating":0,"fluid":40700,"total":70179},"native_fluid_mass_kg":325.60001628,"continuum_envelope_mass_kg":320.1984,"mass_policy":"native unscaled; continuum comparison separate; no rescale","pivot_axis":{"p1_m":[-0.04,0.0,0.05],"p2_m":[-0.04,0.0,1.05]}},
        "endpoints":endpoints,
        "execution":{"motion_preparation_attempt":MOTION_ATTEMPT,"gencase_binding_attempt":GENCASE_BIND_ATTEMPT,"native_initial_qa_binding_attempt":QA_BIND_ATTEMPT,"native_initial_qa_attempt":NATIVE_QA_ATTEMPT,"native_case_attempt_suffix":NATIVE_ATTEMPT_SUFFIX,"root_launch_owner":"root","root230_entrypoint":rel(ROOT230),"root230_entrypoint_sha256":sha(ROOT230),"gpu_lease":"Root230 shared eight-live-UUID policy; never claim a static UUID; protect foreign processes","home_floor_gib":500,"resource_window":{"gpu_hours_total":512,"cpu_core_hours_total":3840,"qualification_hours":1024,"production_hours":720},"no_shared_ledger_edit":True},
        "model_policy":"gpt-5.6-luna/max; no Gemini; no recursive delegation","no_arrays":True,"no_jobs":True,"no_shared_registry_write":True,"precision_status":"not_accepted","q_n_status":"not_assessed","production_approval":"none","future_hashes_null":True,
    }
    plan_path=PACKAGE/"metadata/next24-plan.json"; write_json(plan_path,plan); plan_sha=sha(plan_path)
    for ep in endpoints:
        cid=ep["endpoint_id"]; amp=ep["amplitude_deg"]; binding=physical_binding(cid,amp); owner={"schema":"ds02.f7.next24-target-angle-owner.v1","family_id":"F7","scope_id":SCOPE,"case_id":cid,"physical_case_id":cid,"condition_id":f"{cid}_FRESH074_CANONICAL_V1","physical_condition_sha256":ep["physical_condition_sha256"],"canonical_physical_binding_sha256":ep["canonical_physical_binding_sha256"],"condition_hash_semantics":{"converter_hash_scope":"sha256(canonical JSON of this owner physical_binding.v1 only)","declared_source_hash":ep["physical_condition_sha256"],"declared_source_hash_scope":"fresh074 source plan physical_condition_payload", "source_plan_sha256":plan_sha,"source_and_canonical_hashes_are_distinct":True,"equality_claim":"none"},"physical_binding":binding,"source":{"source_plan":str(plan_path),"source_plan_sha256":plan_sha,"source_definition":rel(PACKAGE/"source"/f"{cid}_Def.xml"),"source_definition_sha256":ep["source_definition_clone_sha256"],"selected_motion_module":rel(MOTION_MODULE),"selected_motion_module_sha256":sha(MOTION_MODULE)},"native_recipe_expected":{"dp_m":0.02,"time_max_s":12.0,"time_out_s":0.02,"native_frame_count":601,"motion_rows":12001,"native_particle_counts":{"fixed":27495,"moving_type1":1984,"floating":0,"fluid_type3":40700,"total":70179},"native_fluid_mass_kg":325.60001628,"continuum_envelope_mass_kg":320.1984,"mass_policy":"native remains unscaled; continuum comparison separate; no rescale"},"planned_execution":{"motion_preparation_attempt":MOTION_ATTEMPT,"gencase_binding_attempt":GENCASE_BIND_ATTEMPT,"native_initial_qa_binding_attempt":QA_BIND_ATTEMPT,"native_initial_qa_attempt":NATIVE_QA_ATTEMPT,"solver_attempt":f"root-stage1-f7-{cid.lower()}-{NATIVE_ATTEMPT_SUFFIX}"},"claims":{"genuine_gencase":False,"actual_native_initial_qa":False,"full_native_solver":False,"visual_acceptance":"not_assessed","q_n":"not_granted","production_approval":"none","numerical_precision":"not_accepted"},"launch_allowed":False,"status":"source_only_disabled_pending_root_chain"}; write_json(PACKAGE/"owners"/f"{cid}.owner.json",owner)
    write_worker_files()
    # Requests use only bounded source/code inputs.  Future data products are
    # recorded as null under future_input_sha256 and are never hashed here.
    source_inputs=base_inputs()+[plan_path,PYTHON]
    source_inputs += [PACKAGE/"workers/prepare_f7_next24_motion.py",PACKAGE/"scripts/bind_next24_gencase.py",PACKAGE/"scripts/bind_next24_native_qa.py",PACKAGE/"workers/run_f7_next24_native_initial_qa.py"]
    for ep in endpoints:
        source_inputs += [PACKAGE/"source"/f"{ep['endpoint_id']}_Def.xml", PACKAGE/"owners"/f"{ep['endpoint_id']}.owner.json"]
    source_inputs=list(dict.fromkeys(source_inputs)); imap=input_map(source_inputs)
    motion_req=common_request(GROUP); motion_req.update({"attempt_id":MOTION_ATTEMPT,"kind":"cpu","cpu_task_kind":"audit","cpu_threads":2,"max_wall_seconds":3600,"estimated_storage_bytes":268435456,"cwd":rel(R/"lagrangian-fluid-lab"),"command":[rel(PYTHON),rel(PACKAGE/"workers/prepare_f7_next24_motion.py"),"--plan",rel(plan_path),"--output-root","{attempt_root}/prepared","--execute"],"input_files":list(imap),"input_sha256":imap,"physical_case_ids":[e["endpoint_id"] for e in endpoints],"output_contract":{"execution_receipt":"{attempt_root}/execution-receipt.json","prepared_root":"{attempt_root}/prepared","report":"{attempt_root}/prepared/motion-source-preparation.json","per_case_definition":"{attempt_root}/prepared/<case>/<case>_Def.xml","per_case_motion":"{attempt_root}/prepared/<case>/motion_obstacle_quintic.dat"},"disabled_reason":"Root review required; this worker writes only endpoint motion/Definition assets and performs no GenCase/BI4/PartVTK/solver."})
    write_json(PACKAGE/"requests/motion-preparation-request.json",motion_req)
    bind_req=common_request(GROUP); bind_req.update({"attempt_id":GENCASE_BIND_ATTEMPT,"kind":"cpu","cpu_task_kind":"audit","cpu_threads":2,"max_wall_seconds":1800,"estimated_storage_bytes":67108864,"cwd":rel(R/"lagrangian-fluid-lab"),"command":[rel(PYTHON),rel(PACKAGE/"scripts/bind_next24_gencase.py"),"--plan",rel(plan_path),"--motion-report",str(DATA/"families/F7"/GROUP/f"{MOTION_ATTEMPT}/prepared/motion-source-preparation.json"),"--motion-receipt",str(DATA/"families/F7"/GROUP/f"{MOTION_ATTEMPT}/execution-receipt.json"),"--prepared-root",str(DATA/"families/F7"/GROUP/f"{MOTION_ATTEMPT}/prepared"),"--output-dir","{attempt_root}/bindings"],"input_files":list(imap),"input_sha256":imap,"future_input_files":[str(DATA/"families/F7"/GROUP/f"{MOTION_ATTEMPT}/prepared/motion-source-preparation.json"),str(DATA/"families/F7"/GROUP/f"{MOTION_ATTEMPT}/execution-receipt.json")],"future_input_sha256":{str(DATA/"families/F7"/GROUP/f"{MOTION_ATTEMPT}/prepared/motion-source-preparation.json"):None,str(DATA/"families/F7"/GROUP/f"{MOTION_ATTEMPT}/execution-receipt.json"):None},"depends_on_attempt":MOTION_ATTEMPT,"physical_case_ids":[e["endpoint_id"] for e in endpoints],"output_contract":{"bindings_root":"{attempt_root}/bindings","binding_group":"{attempt_root}/bindings/gencase-bindings.json"},"disabled_reason":"Enable only after actual motion preparation receipt/report completed/0; binder then reads bounded JSON/XML and opaque generated asset hashes."})
    write_json(PACKAGE/"requests/gencase-binding-request.json",bind_req)
    qa_bind_req=common_request(GROUP); qa_bind_req.update({"attempt_id":QA_BIND_ATTEMPT,"kind":"cpu","cpu_task_kind":"audit","cpu_threads":2,"max_wall_seconds":7200,"estimated_storage_bytes":85899345920,"cwd":rel(R/"lagrangian-fluid-lab"),"command":[rel(PYTHON),rel(PACKAGE/"scripts/bind_next24_native_qa.py"),"--plan",rel(plan_path),"--gencase-bindings",str(DATA/"families/F7"/GROUP/f"{GENCASE_BIND_ATTEMPT}/bindings/gencase-bindings.json"),"--output-dir","{attempt_root}/binding"],"input_files":list(imap),"input_sha256":imap,"future_input_files":[str(DATA/"families/F7"/GROUP/f"{GENCASE_BIND_ATTEMPT}/bindings/gencase-bindings.json")],"future_input_sha256":{str(DATA/"families/F7"/GROUP/f"{GENCASE_BIND_ATTEMPT}/bindings/gencase-bindings.json"):None},"depends_on_attempt":GENCASE_BIND_ATTEMPT,"partvtk":rel(PARTVTK),"partvtk_sha256":sha(PARTVTK),"physical_case_ids":[e["endpoint_id"] for e in endpoints],"output_contract":{"binding":"{attempt_root}/binding/binding.json"},"disabled_reason":"Enable only after all 24 actual GenCase receipts/XML/BI4 metadata are completed/0 and counts/dimension are reviewed; this stage still only binds metadata and never runs PartVTK."})
    write_json(PACKAGE/"requests/native-initial-qa-request.json",qa_bind_req)
    # Registered aggregate PartVTK initial-QA execution.  The binder above
    # only verifies bounded XML/report metadata; this separate disabled CPU
    # request is the sole future owner of official CSV/NumPy reads.
    qa_binding_path=str(DATA/"families/F7"/GROUP/f"{QA_BIND_ATTEMPT}/binding/binding.json")
    qa_input_paths=[PYTHON,RUNTIME,STRICT,RESOURCE,HOME_POLICY,GPU_POLICY,PARTVTK,plan_path,PACKAGE/"workers/run_f7_next24_native_initial_qa.py",PACKAGE/"scripts/bind_next24_native_qa.py"]
    qa_imap=input_map(qa_input_paths)
    qa_future=[qa_binding_path]
    for ep in endpoints:
        cid=ep["endpoint_id"]; g=DATA/"families/F7"/cid/f"root-stage1-f7-{cid.lower()}-genuine-gencase-074"; p=g/"prepared"/cid
        qa_future += [str(g/"execution-receipt.json"),str(p/f"{cid}.xml"),str(p/f"{cid}.bi4"),str(p/"prepared-input-report.json")]
    qa_future=list(dict.fromkeys(qa_future))
    qa_exec_req=common_request(GROUP); qa_exec_req.update({"attempt_id":NATIVE_QA_ATTEMPT,"kind":"cpu","cpu_task_kind":"audit","cpu_threads":2,"max_wall_seconds":7200,"estimated_storage_bytes":96636764160,"cwd":rel(R/"lagrangian-fluid-lab"),"command":[rel(PYTHON),rel(PACKAGE/"workers/run_f7_next24_native_initial_qa.py"),"--binding",qa_binding_path,"--output-dir","{attempt_root}/initial-qa"],"input_files":list(qa_imap),"input_sha256":qa_imap,"future_input_files":qa_future,"future_input_sha256":{p:None for p in qa_future},"depends_on_attempts":[MOTION_ATTEMPT,GENCASE_BIND_ATTEMPT,QA_BIND_ATTEMPT],"partvtk":rel(PARTVTK),"partvtk_sha256":sha(PARTVTK),"physical_case_ids":[e["endpoint_id"] for e in endpoints],"output_contract":{"execution_receipt":"{attempt_root}/execution-receipt.json","per_case_csv":"{attempt_root}/initial-qa/<case>-initial-all.csv","report":"{attempt_root}/initial-qa/native-initial-qa.json"},"disabled_reason":"Enable only after the metadata binder is completed/0 and all actual GenCase receipts/XML/BI4 reports are bound. This is the only request that invokes official PartVTK and reads isolated CSV/NumPy arrays; the source agent does not run it."})
    write_json(PACKAGE/"requests/native-initial-qa-execution-request.json",qa_exec_req)
    # Registered per-case genuine GenCase requests (Root003 only).
    for ep in endpoints:
        cid=ep["endpoint_id"]; bpath=str(DATA/"families/F7"/GROUP/f"{GENCASE_BIND_ATTEMPT}"/"bindings"/f"{cid}.binding.json")
        req=common_request(cid); req.update({"attempt_id":f"root-stage1-f7-{cid.lower()}-genuine-gencase-074","kind":"cpu","cpu_task_kind":"gencase","cpu_threads":2,"max_wall_seconds":1800,"estimated_storage_bytes":1073741824,"cwd":rel(R/"lagrangian-fluid-lab"),"command":[rel(PYTHON),rel(ROOT003),"--binding",bpath,"--output-dir","{attempt_root}/prepared"],"input_files":[rel(PYTHON),rel(ROOT003),rel(GENCASE),rel(RUNTIME),rel(STRICT),rel(RESOURCE),rel(HOME_POLICY),rel(GPU_POLICY),rel(plan_path),rel(PACKAGE/"scripts/bind_next24_gencase.py")],"input_sha256":input_map([PYTHON,ROOT003,GENCASE,RUNTIME,STRICT,RESOURCE,HOME_POLICY,GPU_POLICY,plan_path,PACKAGE/"scripts/bind_next24_gencase.py"]),"future_input_files":[bpath],"future_input_sha256":{bpath:None},"depends_on_attempt":GENCASE_BIND_ATTEMPT,"case_id":cid,"physical_case_id":cid,"physical_condition_sha256":ep["physical_condition_sha256"],"canonical_physical_binding_sha256":ep["canonical_physical_binding_sha256"],"source_plan_sha256":plan_sha,"threads":2,"expected_counts":{"fixed":27495,"moving":1984,"floating":0,"fluid":40700,"total":70179,"dimension":3},"output_contract":{"generated_xml":"{attempt_root}/prepared/{case}/{case}.xml","generated_bi4":"{attempt_root}/prepared/{case}/{case}.bi4","receipt":"{attempt_root}/execution-receipt.json","prepared_input_report":"{attempt_root}/prepared/{case}/prepared-input-report.json"},"disabled_reason":"Root enables only after motion preparation and gencase-binding completed/0; strict Root003 must preserve the generated XML/BI4 and actual counts."})
        # The expression above intentionally avoids including any payload; fix
        # the generated map in a simple, explicit pass for readability.
        req["input_sha256"]=input_map([PYTHON,ROOT003,GENCASE,RUNTIME,STRICT,RESOURCE,HOME_POLICY,GPU_POLICY,plan_path,PACKAGE/"scripts/bind_next24_gencase.py"])
        write_json(PACKAGE/"requests/gencase"/f"{cid}.request.json",req)
    # Registered per-case native qualification requests.  They remain fully
    # disabled and list future actual binding/report paths as null hashes.
    for ep in endpoints:
        cid=ep["endpoint_id"]; owner=PACKAGE/"owners"/f"{cid}.owner.json"; source=PACKAGE/"source"/f"{cid}_Def.xml"; owner_sha=sha(owner); source_sha=sha(source)
        gencase_attempt=DATA/"families/F7"/cid/f"root-stage1-f7-{cid.lower()}-genuine-gencase-074"; native_attempt=DATA/"families/F7"/cid/f"root-stage1-f7-{cid.lower()}-{NATIVE_ATTEMPT_SUFFIX}"
        req=common_request(cid); req.update({"attempt_id":f"root-stage1-f7-{cid.lower()}-{NATIVE_ATTEMPT_SUFFIX}","kind":"qualification","cpu_task_kind":"solver","cpu_threads":4,"max_wall_seconds":14400,"estimated_peak_gpu_mib":4096,"estimated_storage_bytes":17179869184,"command":[rel(SOLVER),str(gencase_attempt/"prepared"/cid/cid),"{attempt_root}/solver_output","-tmax:12","-tout:0.02"],"cwd":str(gencase_attempt/"prepared"),"input_files":[rel(SOLVER),rel(RUNTIME),rel(STRICT),rel(HOME_POLICY),rel(GPU_POLICY),rel(RESOURCE),rel(ROOT230),rel(plan_path),rel(owner),rel(source),rel(PACKAGE/"workers/run_f7_next24_native_initial_qa.py"),rel(PACKAGE/"scripts/bind_next24_native_qa.py")],"input_sha256":input_map([SOLVER,RUNTIME,STRICT,HOME_POLICY,GPU_POLICY,RESOURCE,ROOT230,plan_path,owner,source,PACKAGE/"workers/run_f7_next24_native_initial_qa.py",PACKAGE/"scripts/bind_next24_native_qa.py"]),"future_input_files":[str(gencase_attempt/"execution-receipt.json"),str(gencase_attempt/"prepared"/cid/f"{cid}.xml"),str(gencase_attempt/"prepared"/cid/f"{cid}_Def.xml"),str(gencase_attempt/"prepared"/cid/f"{cid}.bi4"),str(gencase_attempt/"prepared"/cid/"motion_obstacle_quintic.dat"),str(gencase_attempt/"prepared"/cid/"prepared-input-report.json"),str(DATA/"families/F7"/GROUP/f"{QA_BIND_ATTEMPT}"/"binding/binding.json"),str(DATA/"families/F7"/GROUP/f"{NATIVE_QA_ATTEMPT}"/"execution-receipt.json"),str(DATA/"families/F7"/GROUP/f"{NATIVE_QA_ATTEMPT}"/"initial-qa/native-initial-qa.json")],"future_input_sha256":{str(gencase_attempt/"execution-receipt.json"):None,str(gencase_attempt/"prepared"/cid/f"{cid}.xml"):None,str(gencase_attempt/"prepared"/cid/f"{cid}_Def.xml"):None,str(gencase_attempt/"prepared"/cid/f"{cid}.bi4"):None,str(gencase_attempt/"prepared"/cid/"motion_obstacle_quintic.dat"):None,str(gencase_attempt/"prepared"/cid/"prepared-input-report.json"):None,str(DATA/"families/F7"/GROUP/f"{QA_BIND_ATTEMPT}"/"binding/binding.json"):None,str(DATA/"families/F7"/GROUP/f"{NATIVE_QA_ATTEMPT}"/"execution-receipt.json"):None,str(DATA/"families/F7"/GROUP/f"{NATIVE_QA_ATTEMPT}"/"initial-qa/native-initial-qa.json"):None},"depends_on_attempts":[MOTION_ATTEMPT,GENCASE_BIND_ATTEMPT,QA_BIND_ATTEMPT,NATIVE_QA_ATTEMPT],"case_id":cid,"physical_case_id":cid,"physical_condition_sha256":ep["physical_condition_sha256"],"canonical_physical_binding_sha256":ep["canonical_physical_binding_sha256"],"source_plan_sha256":plan_sha,"gencase_prefix":str(gencase_attempt/"prepared"/cid/cid),"gencase_receipt":str(gencase_attempt/"execution-receipt.json"),"gencase_receipt_sha256":None,"initial_qa_binding":qa_binding_path,"initial_qa_binding_sha256":None,"initial_typed_qa":str(DATA/"families/F7"/GROUP/f"{NATIVE_QA_ATTEMPT}"/"initial-qa/native-initial-qa.json"),"initial_typed_qa_receipt":str(DATA/"families/F7"/GROUP/f"{NATIVE_QA_ATTEMPT}"/"execution-receipt.json"),"initial_typed_qa_report_sha256":None,"initial_typed_qa_receipt_sha256":None,"owner_metadata":str(owner),"owner_metadata_sha256":owner_sha,"source_definition":str(source),"source_definition_sha256":source_sha,"expected_counts":{"fixed":27495,"moving":1984,"floating":0,"fluid":40700,"total":70179,"dimension":3},"solver_recipe":{"time_max_s":12.0,"time_out_s":0.02,"native_frame_count":601,"dp_m":0.02,"motion_rows":12001,"native_reader":"piecewise_linear_absolute_angle_increment","native_fluid_mass_kg":325.60001628,"continuum_envelope_mass_kg":320.1984,"mass_policy":"native unscaled; continuum comparison separate; no rescale"},"condition_hash_semantics":{"canonical_owner_binding_sha256":ep["canonical_physical_binding_sha256"],"physical_condition_sha256":ep["physical_condition_sha256"],"source_plan_sha256":plan_sha,"source_and_canonical_hashes_are_distinct":True},"output_contract":{"execution_receipt":"{attempt_root}/execution-receipt.json","solver_output":"{attempt_root}/solver_output","time_window_s":[0.0,12.0],"frames":601,"save_interval_s":0.02,"future_trajectory_sha256":None,"future_typed_sha256":None,"future_xmf_sha256":None,"future_render_sha256":None},"disabled_reason":"Root230 may enable only after actual motion/GenCase/XML/BI4/initial native QA receipts and reports are reviewed. No Q-N/precision/visual/production claim is created by this request."})
        write_json(PACKAGE/"requests/native"/f"{cid}.full601-native-qualification-request.json",req)
    # Remove the private anchor from the committed source set after all case
    # clones have been materialized; every clone remains directly auditable.
    (PACKAGE/"source/_anchor_Def.xml").unlink()
    registry={"schema":"ds02.f7.fresh074.registry-check.v1","checked_scope":[rel(WT/"lagrangian-fluid-lab/campaigns/ds-data-02/families/F7"),str(DATA/"families/F7")],"method":"metadata/path-name search excluding BI4/CSV/H5/VTK/XMF/image arrays","existing_case_ids":plan["existing_registry"]["case_ids"],"existing_amplitudes_deg":list(EXISTING_AMPLITUDES),"proposed_case_ids":[e["endpoint_id"] for e in endpoints],"proposed_amplitudes_deg":list(AMPLITUDES),"collision_count":0,"collisions":[],"envelope_deg":[30.0,65.0],"result":"all 24 proposed half-degree IDs and physical tuples are absent from the checked registry and actual-data metadata"}; write_json(PACKAGE/"metadata/registry-check.json",registry)
    manifest={"schema":"ds02.f7.fresh074.next24-target-angle-source-manifest.v1","family_id":"F7","scope_id":SCOPE,"new_case_count":24,"new_cases":[e["endpoint_id"] for e in endpoints],"new_angles_deg":list(AMPLITUDES),"existing_first24_count":24,"prospective_family_count":48,"prospective_only":True,"fixed_recipe":plan["fixed_physical_and_numerical_source"],"mass_policy":{"native_fluid_mass_kg":325.60001628,"continuum_envelope_mass_kg":320.1984,"rescale":False},"launch_allowed":False,"future_hashes_null":True,"no_arrays_read":True,"no_jobs_started":True,"no_shared_registry_write":True,"production_approval":"none","q_n":"not_assessed","numerical_precision":"not_accepted","root230_policy":{"entrypoint":rel(ROOT230),"entrypoint_sha256":sha(ROOT230),"gpu_lease":"shared eight-live-UUID; foreign protection","home_floor_gib":500,"budget":{"gpu_hours":512,"cpu_core_hours":3840,"qualification_hours":1024,"production_hours":720}},"source_plan":str(plan_path),"source_plan_sha256":plan_sha}; write_json(PACKAGE/"manifest.json",manifest)
    write_json(PACKAGE/"metadata/source-review.json",{"schema":"ds02.f7.fresh074.source-review.v1","scope_id":SCOPE,"family_id":"F7","model":"gpt-5.6-luna/max","source_plan":str(plan_path),"source_plan_sha256":plan_sha,"selected_motion_module":rel(MOTION_MODULE),"selected_motion_module_sha256":sha(MOTION_MODULE),"geometry_control_source":"fresh070/source062 explicit wet mother; four slabs, all-filled moving type-1 paddle, fixed pivots","recipe":"DP .02, 12 s, .02 output, 601 native frames, two finite symmetric quintic cycles then rest","amplitude_axis":{"existing_integer_values_deg":list(EXISTING_AMPLITUDES),"new_half_degree_values_deg":list(AMPLITUDES),"id_encoding":"A<whole 3 digits>P5 means whole+0.5 degrees"},"hash_semantics":"source-plan condition SHA and canonical physical-binding SHA are distinct; no equality claim","mass_semantics":"native fluid mass 325.60001628 kg and continuum envelope 320.1984 kg remain separate; no normalization/rescale","status":"source_only_disabled","arrays_read":False,"jobs_started":False,"shared_registry_write":False,"visual_acceptance":"pending Root per case","q_n":"not_granted","precision":"not_accepted"})
    write_json(PACKAGE/"metadata/source-validation-report.json",{"schema":"ds02.f7.fresh074.source-validation-report.v1","scope_id":SCOPE,"all_passed":True,"case_count":24,"unique_case_ids":True,"unique_amplitudes":True,"registry_collision_count":0,"xml_sources_parseable":True,"xml_recipe_preserved":True,"future_hashes_null":True,"arrays_read":False,"jobs_started":False,"shared_registry_write":False,"source_only":True,"validation_note":"Static source/JSON/XML validation only; no GenCase, BI4, PartVTK, solver, conversion, renderer, numerical precision, Q-N, visual or production claim."})
    (PACKAGE/"README.md").write_text("""# F7 fresh074 — prospective next24 target-angle source\n\nThis package registers 24 new physical motion conditions at distinct half-degree target amplitudes in the reviewed 30–65° envelope. IDs encode the half-degree explicitly (`A030P5` = 30.5°). Existing first24 conditions, accepted decisions, and the mother geometry remain historical references; no existing case is rerun or counted again.\n\nEvery case keeps the verified explicit-wet mother: DP 0.02, four wet slabs, all-filled moving type-1 paddle, pivots `(-0.04,0,0.05)` to `(-0.04,0,1.05)`, Boundary 1, StepAlgorithm 2, Kernel 2, viscosity 0.05, DensityDT 3/0.1, gravity, two finite symmetric quintic cycles on 0–8 s, rest on 8–12 s, native save interval 0.02 and 601 frames. The native reader is piecewise-linear; C2 applies only to the analytic source, and numerical precision is not certified. Native 325.60001628 kg and continuum 320.1984 kg are retained separately without rescaling.\n\n`requests/` contains disabled Root230-compatible motion preparation, GenCase binding and per-case GenCase, bounded native-QA binding, the separate official PartVTK initial-QA execution request, and full601 native qualification requests. The qualification requests carry the required future GenCase receipt and initial-QA report paths but leave all hashes null until Root binds actual completed evidence. This source package performed no scientific array reads, no hashes of BI4/CSV/H5/motion payloads, no jobs, and no shared-registry or ledger writes.\n""",encoding="utf-8")


if __name__ == "__main__":
    build()
    print(PACKAGE)

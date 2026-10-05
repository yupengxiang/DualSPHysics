#!/usr/bin/env python3
"""Static source validator for fresh090; never opens scientific payloads."""
from __future__ import annotations
import argparse, ast, hashlib, json, subprocess, xml.etree.ElementTree as ET
from pathlib import Path
SCIENCE={".bi4",".h5",".hdf5",".csv",".vtk",".npy",".npz",".dat"}
CASES=['F1_STAGE1_ECC_H110_DP010_VX015', 'F1_STAGE1_ECC_H120_DP010_VX010', 'F1_STAGE1_ECC_H120_DP010_VX020', 'F1_STAGE1_ECC_H130_DP010_VX015', 'F1_STAGE1_ECC_H140_DP010_VX010', 'F1_STAGE1_ECC_H140_DP010_VX020', 'F1_STAGE1_ECC_H160_DP010_VX010', 'F1_STAGE1_ECC_H160_DP010_VX020', 'F1_STAGE1_ECC_H170_DP010_VX015', 'F1_STAGE1_ECC_H180_DP010_VX010', 'F1_STAGE1_ECC_H180_DP010_VX020', 'F1_STAGE1_ECC_H190_DP010_VX015', 'F1_STAGE1_DUAL_H220_DP020_VX015', 'F1_STAGE1_DUAL_H240_DP020_VX015', 'F1_STAGE1_DUAL_H240_DP020_VX020', 'F1_STAGE1_DUAL_H260_DP020_VX015', 'F1_STAGE1_DUAL_H280_DP020_VX010', 'F1_STAGE1_DUAL_H280_DP020_VX015', 'F1_STAGE1_DUAL_H280_DP020_VX020', 'F1_STAGE1_DUAL_H300_DP020_VX015', 'F1_STAGE1_DUAL_H320_DP020_VX010', 'F1_STAGE1_DUAL_H320_DP020_VX015', 'F1_STAGE1_DUAL_H320_DP020_VX020', 'F1_STAGE1_DUAL_H340_DP020_VX015']
F1=Path("/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics")
INTEGRATION=Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
PYTHON=INTEGRATION/"lagrangian-fluid-lab/.venv/bin/python"
CONVERTER=INTEGRATION/"lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
def fail(m): raise SystemExit("fresh090 validation failed: "+m)
def ensure(x,m):
    if not x: fail(m)
def load(p):
    try:return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception as e:fail(f"invalid JSON {p}: {e}")
def sha(p):
    p=Path(p); ensure(p.suffix.lower() not in SCIENCE,f"scientific payload hash {p}"); h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
    return h.hexdigest()
def canonical(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def static_inputs(obj, label):
    files=obj.get("input_files",[]); hashes=obj.get("input_sha256",{})
    ensure(set(files)==set(hashes),f"{label}: input_files/input_sha256 closure differs")
    for raw,digest in hashes.items():
        p=Path(raw); ensure(p.is_file(),f"{label}: missing input {p}"); ensure(p.suffix.lower() not in SCIENCE,f"{label}: scientific immediate input {p}"); ensure(sha(p)==digest,f"{label}: input SHA drift {p}")
    ensure(not any(Path(x).suffix.lower() in SCIENCE for x in files),f"{label}: scientific immediate input")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,default=Path(__file__).resolve().parent.parent); ap.add_argument("--output",type=Path); a=ap.parse_args(); pkg=a.package.resolve()
    ensure(pkg.name=="root_followup_090_f1_first24_to48_source_expansion_v1", "wrong package")
    for p in pkg.rglob("*"):
        if p.is_file(): ensure(p.suffix.lower() not in SCIENCE,f"scientific file in package {p}")
    ensure(len(CASES)==24 and len(set(CASES))==24,"case count/uniqueness")
    tuple_rows=[]; rows=[]
    for case in CASES:
        ownerp=pkg/"owners"/(case+".owner.json"); planp=pkg/"source-plans"/(case+".json"); defp=pkg/"definitions"/(case+"_Def.xml")
        ensure(ownerp.is_file() and planp.is_file() and defp.is_file(),f"missing source {case}")
        owner=load(ownerp); plan=load(planp); root=ET.parse(defp).getroot(); bind=owner["physical_binding"]
        expected={"schema","family_id","physical_case_id","mechanism_id","geometry_family_id","control_family_id","geometry","initial_state","controls","gravity_m_s2","density_kg_m3","parameters","event_window"}
        ensure(set(bind)<=expected|{"lineage_group_id","periodic_boundary","mass_policy"},f"{case}: physical binding has unclassified fields")
        ensure(canonical(bind)==owner["physical_condition_sha256"]==owner["canonical_physical_binding_sha256"],f"{case}: physical hash drift")
        scope_code="import json,sys; sys.path.insert(0,%r); import ds_data02_direct_convert as c; o=json.load(open(%r)); print(json.dumps(c._physical_condition_scope(o),sort_keys=True,separators=(',',':')))" % (str(CONVERTER.parent),str(ownerp))
        subprocess.run([str(PYTHON),"-c",scope_code],check=True,capture_output=True,text=True)
        dp=float(root.find("./casedef/geometry/definition").get("dp")); draw=root.find(".//drawbox[@cmt='v1 fallback controlled fluid cell centres']/size"); vel=root.find("./casedef/initials/velocity");
        ensure(draw is not None and vel is not None,f"{case}: XML mutation missing"); ensure(abs(float(draw.get("z"))-(float(bind["parameters"]["fluid_depth_m"])-dp))<1e-10,f"{case}: XML fluid z drift"); ensure(abs(float(vel.get("x"))-float(bind["initial_state"]["velocities_m_per_s"]["fluid"][0]))<1e-10,f"{case}: XML velocity drift")
        params={x.get("key"):x.get("value") for x in root.findall("./execution/parameters/parameter")}; frames=161 if case.startswith("F1_STAGE1_ECC") else 401; tmax=1.6 if frames==161 else 4.0; ensure(params.get("TimeOut")=="0.01" and float(params.get("TimeMax"))==tmax,f"{case}: time recipe drift")
        tuple_rows.append((bind["mechanism_id"],bind["parameters"]["fluid_depth_m"],tuple(bind["initial_state"]["velocities_m_per_s"]["fluid"])))
        for rel in [f"requests/{case}.gencase.request.json",f"requests/{case}.initial-qa.request.json",f"requests/{case}.full-native-qualification.request.json",f"requests/{case}.native-frame0-qa.request.json",f"typed/requests/{case}.full-native-typed-nvme.request.json",f"xmf/requests/{case}.root090-xmf.request.json",f"render/requests/{case}.root090-render.request.json"]:
            req=load(pkg/rel); static_inputs(req,rel); ensure(req.get("launch_allowed") is False and req.get("execution_allowed") is False and req.get("source_only") is True,f"{case}: enabled request {rel}"); ensure(req.get("future_input_sha256") is None,f"{case}: future input hash filled {rel}")
        for rel in [f"gencase-bindings/{case}.json",f"gencase-initial-qa-bindings/{case}.json",f"native-frame0-qa-bindings/{case}.json",f"typed/bindings/{case}.json",f"typed/bindings/{case}.owner.json",f"xmf/bindings/{case}.legacy-aware-binding.json",f"render/bindings/{case}.native023-render-binding.json"]:
            x=load(pkg/rel); ensure(x.get("source_only") is True and x.get("execution_allowed") is False and x.get("launch_allowed") is False,f"{case}: enabled binding {rel}");
            if rel.startswith("gencase-initial-qa-bindings/"):
                c=x["cases"][0]; ensure({"prefix","actual_particle_counts","actual_total_particles","gencase_receipt","partvtk","generated_xml","prepared_input_report"}.issubset(set(c)|set(x)),f"{case}: GenCase QA worker contract missing required path/count keys")
        rows.append({"case_id":case,"physical_condition_sha256":owner["physical_condition_sha256"],"source_plan_sha256":sha(planp),"definition_sha256":sha(defp),"expected_native_frames":frames,"expected_particles":None,"future_hashes_null":True})
    ensure(len(set(tuple_rows))==24,"physical tuples are duplicated")
    xmfworker=pkg/"workers/export_xmf_particle_axis_corrected.py"; ensure(xmfworker.is_file(),"corrected XMF worker missing"); text=xmfworker.read_text(encoding="utf-8"); ensure("shape[1:]" in text and "shape[2:]" not in text,"XMF worker vector axis repair missing")
    result={"schema":"ds02.f1.fresh090.static-source-validation.v1","fresh_id":"fresh090","case_count":24,"rows":rows,"physical_tuples_distinct":True,"converter_scope_preflight":"real _physical_condition_scope invoked per owner","arrays_read":False,"arrays_hashed":False,"jobs_launched":False,"shared_state_modified":False,"visual_acceptance_granted":False,"q_n":"not_assessed","production_approval":"none","status":"passed"}
    if a.output:a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2,sort_keys=True))
if __name__=="__main__":main()

#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,re,xml.etree.ElementTree as ET
from pathlib import Path
HERE=Path(__file__).resolve().parent
ARRAY_SUFFIXES={".bi4",".h5",".hdf5",".csv",".npy",".npz"}
def sha(p):
    p=Path(p)
    if p.suffix.lower() in ARRAY_SUFFIXES: raise RuntimeError("array-bearing path: "+str(p))
    h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
    return h.hexdigest()
def load(p):
    x=json.loads(Path(p).read_text(encoding="utf-8"))
    if not isinstance(x,dict):raise RuntimeError("JSON object required: "+str(p))
    return x
def canon(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def csha(x):return hashlib.sha256(canon(x).encode()).hexdigest()
def req(x,m):
    if not x:raise RuntimeError(m)
def closure(d,label):
    files=set(d.get("input_files",[])); hashes=set(d.get("input_sha256",{}))
    req(files==hashes,label+": input closure")
    for raw in files:
        p=Path(raw); req(p.suffix.lower() not in ARRAY_SUFFIXES,label+": array input")
        req(p.is_file(),label+": missing "+str(p)); req(d["input_sha256"][raw]==sha(p),label+": stale "+str(p))
def disabled(d,label):
    req(d.get("source_only") is True,label+": source-only"); req(d.get("launch_allowed") is False and d.get("execution_allowed") is False,label+": enabled")
    req(d.get("future_input_sha256") is None,label+": future input hash")
    req(d.get("future_outputs",{}).get("sha256") is None,label+": future output hash")
    for k,v in d.items():
        if k.endswith("_receipt_sha256") or k.endswith("_report_sha256") or k.endswith("_xml_sha256") or k.endswith("_bi4_sha256"):req(v is None,label+": future digest "+k)
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--write",action="store_true");a=ap.parse_args()
    audit=load(HERE/"metadata/existing-first24-audit.json"); reg=load(HERE/"metadata/candidate-registry.json")
    req(audit["existing_source_native_distinct_count"]==16,"existing count"); req(audit["checkpoint_accepted_f1"]==13,"checkpoint accepted")
    req(len(audit["existing_mother_conditions"])==8 and len(audit["existing_completed_vx_conditions"])==8,"mother/VX counts")
    old=audit["existing_mother_conditions"]+audit["existing_completed_vx_conditions"]; req(len({x["physical_condition_sha256"] for x in old})==16,"old hash collision")
    cases=reg["cases"]; req(len(cases)==8 and len({x["physical_condition_sha256"] for x in cases})==8,"candidate count/hash")
    req(not ({x["case_id"] for x in cases}&{x["case_id"] for x in old}),"case collision")
    checked=[]
    for row in cases:
        case=row["case_id"]; definition=Path(row["definition"]); owner=Path(row["owner"]); plan=Path(row["source_plan"])
        req(definition.is_file() and owner.is_file() and plan.is_file(),case+": source missing")
        text=definition.read_text(encoding="utf-8"); ET.fromstring(text); pos=text.find('cmt="v1 fallback controlled fluid cell centres"'); req(pos>=0,case+": selector")
        m=re.search(r'<size\b[^>]*\bz="([^"]+)"',text[pos:pos+800]); req(m and abs(float(m.group(1))-row["xml_fluid_drawbox_size_z_m"])<1e-12,case+": target z")
        req(abs(row["xml_fluid_drawbox_size_z_m"]/row["dp_m"]-round(row["xml_fluid_drawbox_size_z_m"]/row["dp_m"]))<1e-9,case+": grid")
        od=load(owner); sp=load(plan); req(od["physical_condition_sha256"]==csha(od["physical_binding"]),case+": physical hash"); req(od["source_plan_condition_sha256"]==csha(sp),case+": plan hash")
        req(od["expected_total_particles"] is None and od["expected_fluid_particles"] is None and od["expected_native_mass_kg"] is None,case+": prediction")
        req(sha(definition)==od["source_definition_sha256"],case+": definition hash")
        for suffix in (".gencase.request.json",".initial-qa.request.json",".full-native-qualification.request.json"):
            d=load(HERE/"requests"/(case+suffix)); disabled(d,case+suffix); closure(d,case+suffix); req(d["independent_case_count_increment"]==0,case+": increment")
        gb=load(HERE/"gencase-bindings"/(case+".json")); req(gb["expected_total"] is None and gb["expected_fluid"] is None,case+": binding prediction")
        qb=load(HERE/"qa-bindings"/(case+".json")); req(qb["cases"][0]["expected_velocity_m_per_s"]==row["velocity_m_per_s"],case+": velocity")
        checked.append({"case_id":case,"definition_sha256":sha(definition),"physical_condition_sha256":row["physical_condition_sha256"],"all_requests_disabled":True})
    result={"schema":"ds02.f1.fresh084-source-validation.v1","passed":True,"family_id":"F1","fresh_id":"fresh084","existing_distinct_count":16,"new_candidate_count":8,"target_first24_distinct_count":24,"candidate_cases":checked,"first_two_executable_gencase_requests":[str(HERE/"requests"/(cases[0]["case_id"]+".gencase.request.json")),str(HERE/"requests"/(cases[1]["case_id"]+".gencase.request.json"))],"source_only":True,"launch_allowed":False,"execution_allowed":False,"gencase_launched":False,"native_solver_launched":False,"initial_qa_launched":False,"raw_arrays_read":False,"raw_arrays_hashed":False,"shared_registry_or_ledger_modified":False,"independent_case_count_increment":0,"q_n":"not_assessed","production_approval":"none"}
    if a.write:(HERE/"metadata/static-validation.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2,sort_keys=True))
if __name__=="__main__":main()

#!/usr/bin/env python3
from __future__ import annotations
import ast, hashlib, json, math
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
CASES=json.loads((ROOT/"manifest.json").read_text())["cases"]

def load(p):
    v=json.loads(Path(p).read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise AssertionError(f"object required: {p}")
    return v

def sha(p):
    p=Path(p)
    if p.suffix.lower() in {".bi4",".h5",".csv"}: raise AssertionError(f"raw array hash forbidden: {p}")
    h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def require(c,m):
    if not c: raise AssertionError(m)

def path_in(p, xs): return str(Path(p)) in {str(Path(x)) for x in xs}

manifest=load(ROOT/"manifest.json")
require(manifest["source_only"] is True and manifest["execution_allowed"] is False and manifest["launch_allowed"] is False,"manifest enables execution")
require(len(CASES)==8 and manifest["actual_native_receipts_verified"]==8,"case count")
worker=ROOT/"native_initial_vx_frame0_audit.py"
worker_sha=sha(worker)
require(worker_sha==manifest["worker_sha256"],"worker SHA")
text=worker.read_text(encoding="utf-8")
for token in ["--binding","--output-dir","Part_0000.bi4","-dirdata","-first:0","-last:0","-savecsv","-onlytype:+all","-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone"]:
    require(token in text,f"worker missing token {token}")
ast.parse(text)
metadata=load(ROOT/"metadata/actual-root164-native-bindings.json")
require(len(metadata["cases"])==8 and metadata["raw_arrays_read"] is False and metadata["raw_bi4_bytes_read"] is False and metadata["raw_bi4_hashes_recomputed"] is False,"metadata raw policy")
for case in CASES:
    b=load(ROOT/f"native-vx-bindings/{case}.json")
    require(b["source_only"] is True and b["execution_allowed"] is False and b["launch_allowed"] is False,"binding enabled")
    require(b["q_n"]=="not_assessed" and b["production_approval"]=="none" and b["independent_case_count_increment"]==0,"binding gate")
    c=b["cases"][0]
    require(c["case_id"]==case,"case id")
    actual=b["actual_gencase"]
    for k, path in {"gencase_receipt":actual["receipt"], "gencase_report":actual["report"], "generated_xml":actual["generated_xml"], "source_definition":c["source_definition"], "native_solver_receipt":c["native_solver_receipt"]}.items():
        require(Path(path).is_file(),f"{case} missing {k}")
    gen=Path(c["generated_xml"]); require(sha(gen)==c["generated_xml_sha256"],f"{case} generated XML SHA")
    root=ET.parse(gen).getroot(); data2d=root.find("./execution/constants/data2d"); require(data2d is not None and str(data2d.get("value","")).lower()=="false",f"{case} not 3D")
    src=Path(c["source_definition"]); require(sha(src)==c["source_definition_sha256"],f"{case} source Def SHA")
    vs=ET.parse(src).getroot().findall(".//initials/velocity"); require(len(vs)==1 and vs[0].get("mkfluid")=="0",f"{case} source velocity")
    want=tuple(float(x) for x in c["expected_velocity_m_per_s"]); got=tuple(float(vs[0].get(a,"nan")) for a in ("x","y","z")); require(got==want,f"{case} XML VX declaration")
    receipt=Path(b["native_receipt_provenance"]["receipt"]); rd=load(receipt); require(rd.get("status")=="completed" and rd.get("returncode")==0,f"{case} native receipt")
    rsha=sha(receipt); require(rsha==b["native_receipt_sha256"] and rsha==c["native_solver_receipt_sha256"],f"{case} native receipt SHA")
    frame=Path(b["native_receipt_provenance"]["frame0_bi4"]); require(frame.is_file(),f"{case} frame0 missing"); require(b["future_native"]["frame0_bi4_sha256"] is None and b["future_native"]["audit_report_sha256"] is None,"future hash populated")
    req=load(ROOT/f"requests/{case}.native-frame0-vx-qa.request.json")
    require(req["source_only"] is True and req["execution_allowed"] is False and req["launch_allowed"] is False,"request enabled")
    require(req["root_review_required"] is True and req["independent_case_count_increment"]==0 and req["q_n"]=="not_assessed","request gate")
    require(req["native_solver_receipt"]==str(receipt) and req["native_solver_receipt_sha256"]==rsha,"request native binding")
    files=req["input_files"]; hashes=req["input_sha256"]
    require(set(files)==set(hashes),f"{case} input set closure")
    for name in files:
        p=Path(name); require(p.is_file(),f"{case} missing input {p}"); require(p.suffix.lower() not in {".bi4",".h5",".csv"},f"{case} raw input listed"); require(sha(p)==hashes[name],f"{case} input SHA {p}")
    for p in [ROOT/f"native-vx-bindings/{case}.json", worker, ROOT/f"source-plans/{case}.json", ROOT/f"source/definitions/{case}_Def.xml", ROOT/f"source/owners/{case}.owner.json", ROOT/"provenance/root-source-review.json", ROOT/"metadata/actual-root164-native-bindings.json", receipt, Path(actual["receipt"]), Path(actual["report"]), Path(actual["generated_xml"])]:
        require(path_in(p,files),f"{case} input omission {p}")
    require(str(frame) in req["future_input_files"],f"{case} frame0 future input omission")
    require(req["future_input_sha256"] is None and req["native_frame0_bi4_sha256"] is None and req["future_outputs"]["sha256"] is None,"{case} future SHA")
    require("root_stage1_f1_eight_actual_gen_fullnative_qualification_164" not in " ".join(files+[str(x) for x in req["command"]]),f"{case} consumed Root164 active path")
    require("/tmp" not in " ".join(files+[str(x) for x in req["command"]]),f"{case} temporary active path")
print(json.dumps({"ok":True,"package":str(ROOT),"cases":len(CASES),"native_receipts_completed_zero":8,"raw_arrays_read":False,"future_frame0_hashes":None},indent=2))

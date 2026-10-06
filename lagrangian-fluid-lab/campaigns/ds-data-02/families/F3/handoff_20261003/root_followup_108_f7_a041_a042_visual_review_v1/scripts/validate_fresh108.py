#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, sys

ROOT=Path(__file__).resolve().parents[1]
META=ROOT/"metadata/fresh108-visual-review.json"
REPORT=ROOT/"metadata/fresh108-validator-report.json"
FORBIDDEN_SUFFIXES={".bi4",".h5",".csv",".dat",".vtk",".npy",".npz"}
SAFE_SUFFIXES={".json",".xml",".xmf",".png",".py",".md"}

def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def ref(r, errors):
    p=Path(r["path"]); s=r.get("sha256")
    if p.suffix.lower() in FORBIDDEN_SUFFIXES: errors.append(f"forbidden reference: {p}")
    if p.suffix.lower() not in SAFE_SUFFIXES: errors.append(f"unapproved reference suffix: {p}")
    if not p.exists(): errors.append(f"missing: {p}"); return
    if s and sha(p)!=s: errors.append(f"sha mismatch: {p}")

def main():
    errors=[]; warnings=[]; m=json.loads(META.read_text())
    assert m["schema"]=="ds02.f3.fresh108.f7.visual-review-handoff.v1"
    if m.get("no_jobs_started") is not True or m.get("no_science_payload_read_or_hashed") is not True: errors.append("source-only boundary missing")
    sb=m["selection_boundary"]
    for p,s in [(sb["root792_frontier_path"],sb["root792_frontier_sha256"]),(sb["checkpoint115_path"],sb["checkpoint115_sha256"]),(sb["root894_review_path"],sb["root894_review_sha256"])]:
        ref({"path":p,"sha256":s},errors)
    if any(sb["checkpoint115_integer_case_matches"].values()): errors.append("integer target appears accepted in checkpoint115")
    if sb["root894_has_integer_target_match"]: errors.append("integer target appears in Root894")
    if len(m.get("cases",[]))!=2: errors.append("case count")
    for c in m["cases"]:
        if c["case_id"] not in {"F7_OBSTACLE_QUINTIC_B08_A041","F7_OBSTACLE_QUINTIC_B08_A042"}: errors.append("wrong case")
        if c["qualification_boundary"]["case_credit_granted"] or c["qualification_boundary"]["independent_case_count_increment"]!=0: errors.append(f"credit boundary {c['case_id']}")
        if c["qualification_boundary"]["precision_status"]!="not_accepted": errors.append(f"precision boundary {c['case_id']}")
        sp=c["source_inputs"]["source_plan"]
        if sp["historical_length"]!=63 or sp["actual_length"]!=64 or sp["historical_equals_actual"]: errors.append(f"source plan digest provenance {c['case_id']}")
        if sp["sha256_actual_file"]!=sha(Path(sp["path"])): errors.append(f"source plan sha {c['case_id']}")
        if c["scope_separation"]["canonical_physical_binding_sha256"]==c["scope_separation"]["source_declared_condition_sha256"]: errors.append(f"scope collapse {c['case_id']}")
        chain=c["producer_chain"]
        for key,val in chain.items():
            if isinstance(val,dict) and "path" in val: ref(val,errors)
            elif isinstance(val,dict) and "execution_receipt" in val: ref(val["execution_receipt"],errors)
        e=c["render_evidence"]
        if e["inventory"]!={"contact_sheet_count":26,"event_keyframe_count":10,"saved_frame_count":601}: errors.append(f"inventory {c['case_id']}")
        for r in e["contact_sheets"]+e["event_keyframes"]: ref(r,errors)
        for r in e["all_saved_frame_pngs"]:
            p=Path(r["path"]);
            if not p.exists(): errors.append(f"missing saved frame {p}")
            if p.suffix.lower() in FORBIDDEN_SUFFIXES: errors.append(f"forbidden saved frame {p}")
        if not e["reviewed_all_contact_sheets"] or not e["reviewed_all_event_keyframes"]: errors.append(f"review completeness {c['case_id']}")
        rr=e["render_receipt"]
        if rr["status"]!="completed" or rr["returncode"]!=0: errors.append(f"render receipt {c['case_id']}")
        if e["render_report"]["frames"]!=601 or not e["render_report"]["all_frames_rendered"]: errors.append(f"render report {c['case_id']}")
    for p in [ROOT/"README.md",ROOT/"metadata/fresh108-visual-review.json"]:
        if not p.exists(): errors.append(f"package missing {p}")
    out={"schema":"ds02.f3.fresh108.validator-report.v1","valid":not errors,"errors":errors,"warnings":warnings,"cases_checked":len(m.get("cases",[])),"source_only":True,"science_payloads_opened":False}
    REPORT.write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(out,indent=2))
    return 1 if errors else 0
if __name__=="__main__": raise SystemExit(main())
